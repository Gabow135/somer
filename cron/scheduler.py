"""Cron scheduler — tareas programadas para acciones de agentes.

Portado y extendido desde OpenClaw ``service/timer.ts``.
Soporta: expresiones cron clásicas (5 campos), strings especiales (@daily...),
timezone, jitter, overlap prevention, retry con backoff exponencial,
alertas de fallo, concurrencia controlada e historial de ejecución.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set

from cron.parser import matches_cron, next_cron_datetime, parse_cron_expression
from shared.errors import (
    CronConcurrencyError,
    CronError,
    CronExpressionError,
    CronJobNotFoundError,
    CronJobTimeoutError,
    CronRetryExhaustedError,
)

logger = logging.getLogger(__name__)

# ── Type alias ──────────────────────────────────────────────
CronAction = Callable[[], Coroutine[Any, Any, Any]]


# ── Constantes (portadas de OpenClaw timer.ts) ──────────────
MIN_REFIRE_GAP_SECS = 2.0
MAX_TIMER_DELAY_SECS = 60.0
DEFAULT_MISSED_JOB_STAGGER_SECS = 5.0
DEFAULT_MAX_MISSED_JOBS_PER_RESTART = 5
DEFAULT_FAILURE_ALERT_AFTER = 2
DEFAULT_FAILURE_ALERT_COOLDOWN_SECS = 3600.0  # 1 hora
DEFAULT_JOB_TIMEOUT_SECS = 600.0  # 10 minutos
DEFAULT_MAX_CONCURRENT_JOBS = 1

# Backoff exponencial (segundos) indexado por errores consecutivos
DEFAULT_BACKOFF_SCHEDULE_SECS: List[float] = [
    30.0,     # 1er error  → 30 s
    60.0,     # 2do error  → 1 min
    300.0,    # 3er error  → 5 min
    900.0,    # 4to error  → 15 min
    3600.0,   # 5to+ error → 60 min
]

DEFAULT_MAX_TRANSIENT_RETRIES = 3

# Patrones de errores transitorios (portados de timer.ts)
_TRANSIENT_PATTERNS = {
    "rate_limit": r"(?i)(rate[_ ]limit|too many requests|429|resource has been exhausted)",
    "overloaded": r"(?i)(\b529\b|overloaded|high demand|capacity exceeded)",
    "network": r"(?i)(network|econnreset|econnrefused|fetch failed|socket|connectionerror)",
    "timeout": r"(?i)(timeout|etimedout|timed?\s*out)",
    "server_error": r"\b5\d{2}\b",
}


# ── Enums ───────────────────────────────────────────────────
class CronRunStatus(str, Enum):
    """Estado de ejecución de un job cron."""
    OK = "ok"
    ERROR = "error"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"


class CronScheduleKind(str, Enum):
    """Tipo de schedule de un job cron."""
    CRON = "cron"        # Expresión cron clásica
    EVERY = "every"      # Cada N segundos
    AT = "at"            # Una sola vez en un timestamp


# ── Dataclasses ─────────────────────────────────────────────
@dataclass
class CronJobState:
    """Estado mutable de un job cron (portado de OpenClaw CronJobState)."""

    next_run_at: Optional[float] = None        # timestamp epoch secs
    running_at: Optional[float] = None          # timestamp epoch secs si corriendo
    last_run_at: Optional[float] = None         # timestamp del último run
    last_run_status: Optional[CronRunStatus] = None
    last_error: Optional[str] = None
    last_duration_secs: Optional[float] = None
    consecutive_errors: int = 0
    last_failure_alert_at: Optional[float] = None
    schedule_error_count: int = 0


@dataclass
class CronRunLogEntry:
    """Entrada de historial de ejecución de un job cron."""

    ts: float                               # timestamp epoch secs
    job_id: str
    status: CronRunStatus
    error: Optional[str] = None
    summary: Optional[str] = None
    duration_secs: Optional[float] = None
    next_run_at: Optional[float] = None


@dataclass
class CronFailureAlertConfig:
    """Configuración de alertas de fallo para un job cron."""

    after: int = DEFAULT_FAILURE_ALERT_AFTER
    cooldown_secs: float = DEFAULT_FAILURE_ALERT_COOLDOWN_SECS
    callback: Optional[Callable[[str, str, int], Coroutine[Any, Any, None]]] = None


@dataclass
class CronRetryConfig:
    """Configuración de reintentos para un job cron."""

    max_attempts: int = DEFAULT_MAX_TRANSIENT_RETRIES
    backoff_schedule_secs: List[float] = field(
        default_factory=lambda: list(DEFAULT_BACKOFF_SCHEDULE_SECS[:3])
    )
    retry_on: Optional[List[str]] = None  # claves de _TRANSIENT_PATTERNS


@dataclass
class CronJob:
    """Definición de un trabajo cron.

    Preserva la API original y agrega campos portados de OpenClaw.
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = ""
    expression: str = "* * * * *"
    description: str = ""
    action: Optional[CronAction] = None
    enabled: bool = True
    timezone: Optional[str] = None
    jitter_secs: float = 0.0
    overlap_policy: str = "skip"   # "skip" | "allow" | "queue"
    timeout_secs: Optional[float] = None
    delete_after_run: bool = False
    schedule_kind: CronScheduleKind = CronScheduleKind.CRON
    every_secs: Optional[float] = None
    at_timestamp: Optional[float] = None
    stagger_ms: int = 0

    # Estado mutable
    state: CronJobState = field(default_factory=CronJobState)

    # Configuraciones opcionales
    retry_config: Optional[CronRetryConfig] = None
    failure_alert: Optional[CronFailureAlertConfig] = None

    # Legacy compat
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    run_count: int = 0
    error_count: int = 0

    def __post_init__(self) -> None:
        """Valida la expresión al crear."""
        if self.schedule_kind == CronScheduleKind.CRON:
            parse_cron_expression(self.expression)
        if not self.name:
            self.name = self.description or self.id


def _error_backoff_secs(
    consecutive_errors: int,
    schedule: Optional[List[float]] = None,
) -> float:
    """Calcula el backoff exponencial dado el número de errores consecutivos.

    Portado de ``errorBackoffMs`` en OpenClaw ``timer.ts``.
    """
    sched = schedule or DEFAULT_BACKOFF_SCHEDULE_SECS
    idx = min(consecutive_errors - 1, len(sched) - 1)
    return sched[max(0, idx)]


def _is_transient_error(error: str, retry_on: Optional[List[str]] = None) -> bool:
    """Detecta si un error es transitorio basado en patrones regex.

    Portado de ``isTransientCronError`` en OpenClaw ``timer.ts``.
    """
    import re
    if not error:
        return False
    keys = retry_on if retry_on else list(_TRANSIENT_PATTERNS.keys())
    for key in keys:
        pattern = _TRANSIENT_PATTERNS.get(key)
        if pattern and re.search(pattern, error):
            return True
    return False


def _resolve_stable_stagger_offset(job_id: str, stagger_ms: int) -> float:
    """Genera un offset estable basado en hash del job_id.

    Portado de ``resolveStableCronOffsetMs`` en OpenClaw ``jobs.ts``.
    """
    if stagger_ms <= 1:
        return 0.0
    digest = hashlib.sha256(job_id.encode()).digest()
    offset_ms = int.from_bytes(digest[:4], "big") % stagger_ms
    return offset_ms / 1000.0


# ── Scheduler principal ────────────────────────────────────
class CronScheduler:
    """Scheduler de tareas cron basado en asyncio.

    Portado y extendido desde OpenClaw ``CronService`` + ``timer.ts``.
    Soporta jitter, overlap prevention, timezone, retry con backoff,
    alertas de fallo, concurrencia controlada e historial de ejecución.

    Uso::

        scheduler = CronScheduler()
        scheduler.add("*/5 * * * *", my_action, "Cada 5 minutos")
        await scheduler.start()
        # ... el scheduler corre en background ...
        await scheduler.stop()
    """

    def __init__(
        self,
        tick_interval: float = 30.0,
        max_concurrent_jobs: int = DEFAULT_MAX_CONCURRENT_JOBS,
        on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
        failure_alert_callback: Optional[
            Callable[[str, str, int], Coroutine[Any, Any, None]]
        ] = None,
    ) -> None:
        self._jobs: Dict[str, CronJob] = {}
        self._task: Optional[asyncio.Task[None]] = None
        self._running = False
        self._tick_interval = tick_interval
        self._max_concurrent = max(1, max_concurrent_jobs)
        self._active_jobs: Set[str] = set()
        self._run_queue: asyncio.Queue[str] = asyncio.Queue()
        self._history: List[CronRunLogEntry] = []
        self._max_history = 2000
        self._on_event = on_event
        self._failure_alert_callback = failure_alert_callback
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(self._max_concurrent)

    # ── API pública: gestión de jobs ────────────────────────

    def add(
        self,
        expression: str,
        action: CronAction,
        description: str = "",
        *,
        job_id: Optional[str] = None,
        name: Optional[str] = None,
        enabled: bool = True,
        timezone: Optional[str] = None,
        jitter_secs: float = 0.0,
        overlap_policy: str = "skip",
        timeout_secs: Optional[float] = None,
        delete_after_run: bool = False,
        schedule_kind: CronScheduleKind = CronScheduleKind.CRON,
        every_secs: Optional[float] = None,
        at_timestamp: Optional[float] = None,
        stagger_ms: int = 0,
        retry_config: Optional[CronRetryConfig] = None,
        failure_alert: Optional[CronFailureAlertConfig] = None,
    ) -> str:
        """Agrega un job al scheduler. Retorna el ID del job.

        Args:
            expression: Expresión cron (5 campos) o string especial (@daily...).
            action: Coroutine a ejecutar.
            description: Descripción del job.
            job_id: ID personalizado (auto-generado si no se provee).
            name: Nombre del job (usa description si no se provee).
            enabled: Si el job está habilitado.
            timezone: Timezone IANA para la evaluación (ej: 'America/Mexico_City').
            jitter_secs: Jitter aleatorio máximo en segundos.
            overlap_policy: Política de overlap: 'skip', 'allow', 'queue'.
            timeout_secs: Timeout por ejecución en segundos.
            delete_after_run: Eliminar el job después de ejecutar exitosamente.
            schedule_kind: Tipo de schedule (CRON, EVERY, AT).
            every_secs: Intervalo en segundos para schedule_kind=EVERY.
            at_timestamp: Timestamp epoch para schedule_kind=AT.
            stagger_ms: Ventana de stagger en milisegundos para evitar thundering herd.
            retry_config: Configuración de reintentos.
            failure_alert: Configuración de alertas de fallo.

        Returns:
            ID del job creado.
        """
        jid = job_id or uuid.uuid4().hex[:12]
        job = CronJob(
            id=jid,
            name=name or description or jid,
            expression=expression,
            description=description,
            action=action,
            enabled=enabled,
            timezone=timezone,
            jitter_secs=jitter_secs,
            overlap_policy=overlap_policy,
            timeout_secs=timeout_secs,
            delete_after_run=delete_after_run,
            schedule_kind=schedule_kind,
            every_secs=every_secs,
            at_timestamp=at_timestamp,
            stagger_ms=stagger_ms,
            retry_config=retry_config,
            failure_alert=failure_alert,
        )
        if job.id in self._jobs:
            raise CronError(f"Ya existe un job con ID '{job.id}'")

        # Calcular próxima ejecución
        now = time.time()
        job.state.next_run_at = self._compute_next_run(job, now)

        self._jobs[job.id] = job
        self._emit_event(job_id=job.id, action="added", next_run_at=job.state.next_run_at)
        logger.info(
            "Job '%s' (%s) agregado: %s", job.id, job.name, expression
        )
        return job.id

    def remove(self, job_id: str) -> bool:
        """Remueve un job por ID. Retorna True si existía."""
        removed = self._jobs.pop(job_id, None)
        if removed:
            self._active_jobs.discard(job_id)
            self._emit_event(job_id=job_id, action="removed")
            logger.info("Job '%s' removido", job_id)
        return removed is not None

    def enable(self, job_id: str) -> None:
        """Habilita un job (resume)."""
        job = self._get_job_or_raise(job_id)
        job.enabled = True
        now = time.time()
        job.state.next_run_at = self._compute_next_run(job, now)
        self._emit_event(
            job_id=job_id, action="updated", next_run_at=job.state.next_run_at
        )

    def disable(self, job_id: str) -> None:
        """Deshabilita un job (pause)."""
        job = self._get_job_or_raise(job_id)
        job.enabled = False
        job.state.next_run_at = None
        self._emit_event(job_id=job_id, action="updated")

    def pause(self, job_id: str) -> None:
        """Alias de disable — pausa un job."""
        self.disable(job_id)

    def resume(self, job_id: str) -> None:
        """Alias de enable — reanuda un job pausado."""
        self.enable(job_id)

    def list_jobs(self) -> List[CronJob]:
        """Lista todos los jobs registrados."""
        return list(self._jobs.values())

    def list_enabled_jobs(self) -> List[CronJob]:
        """Lista solo jobs habilitados, ordenados por próxima ejecución."""
        enabled = [j for j in self._jobs.values() if j.enabled]
        enabled.sort(key=lambda j: j.state.next_run_at or float("inf"))
        return enabled

    def get_job(self, job_id: str) -> Optional[CronJob]:
        """Obtiene un job por ID."""
        return self._jobs.get(job_id)

    def update_job(
        self,
        job_id: str,
        *,
        expression: Optional[str] = None,
        description: Optional[str] = None,
        name: Optional[str] = None,
        enabled: Optional[bool] = None,
        timezone: Optional[str] = None,
        jitter_secs: Optional[float] = None,
        overlap_policy: Optional[str] = None,
        timeout_secs: Optional[float] = None,
        action: Optional[CronAction] = None,
        retry_config: Optional[CronRetryConfig] = None,
        failure_alert: Optional[CronFailureAlertConfig] = None,
    ) -> CronJob:
        """Actualiza propiedades de un job existente.

        Solo modifica los campos que se pasan explícitamente.
        Retorna el job actualizado.
        """
        job = self._get_job_or_raise(job_id)
        schedule_changed = False

        if expression is not None:
            parse_cron_expression(expression)
            job.expression = expression
            schedule_changed = True
        if description is not None:
            job.description = description
        if name is not None:
            job.name = name
        if enabled is not None:
            job.enabled = enabled
            schedule_changed = True
        if timezone is not None:
            job.timezone = timezone
            schedule_changed = True
        if jitter_secs is not None:
            job.jitter_secs = jitter_secs
        if overlap_policy is not None:
            job.overlap_policy = overlap_policy
        if timeout_secs is not None:
            job.timeout_secs = timeout_secs
        if action is not None:
            job.action = action
        if retry_config is not None:
            job.retry_config = retry_config
        if failure_alert is not None:
            job.failure_alert = failure_alert

        if schedule_changed:
            now = time.time()
            if job.enabled:
                job.state.next_run_at = self._compute_next_run(job, now)
            else:
                job.state.next_run_at = None
                job.state.running_at = None

        self._emit_event(
            job_id=job_id, action="updated", next_run_at=job.state.next_run_at
        )
        return job

    # ── API pública: ejecución manual ───────────────────────

    async def run_now(self, job_id: str, *, force: bool = False) -> CronRunStatus:
        """Ejecuta un job inmediatamente.

        Args:
            job_id: ID del job a ejecutar.
            force: Si True, ignora overlap_policy y estado habilitado.

        Returns:
            Estado del resultado de la ejecución.
        """
        job = self._get_job_or_raise(job_id)
        if not force and not job.enabled:
            return CronRunStatus.SKIPPED
        if not force and job.state.running_at is not None:
            if job.overlap_policy == "skip":
                return CronRunStatus.SKIPPED
        return await self._execute_job(job)

    # ── API pública: historial ──────────────────────────────

    def get_history(
        self,
        *,
        job_id: Optional[str] = None,
        status: Optional[CronRunStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[CronRunLogEntry]:
        """Obtiene historial de ejecución con filtros opcionales.

        Args:
            job_id: Filtrar por ID de job.
            status: Filtrar por estado.
            limit: Cantidad máxima de entradas.
            offset: Offset para paginación.

        Returns:
            Lista de entradas de historial.
        """
        entries = self._history
        if job_id:
            entries = [e for e in entries if e.job_id == job_id]
        if status:
            entries = [e for e in entries if e.status == status]
        # Más recientes primero
        entries = sorted(entries, key=lambda e: e.ts, reverse=True)
        return entries[offset:offset + limit]

    def get_job_stats(self, job_id: str) -> Dict[str, Any]:
        """Obtiene estadísticas de un job.

        Returns:
            Dict con conteos de éxito/error/total, duración promedio, etc.
        """
        job = self._get_job_or_raise(job_id)
        entries = [e for e in self._history if e.job_id == job_id]
        ok_count = sum(1 for e in entries if e.status == CronRunStatus.OK)
        error_count = sum(1 for e in entries if e.status == CronRunStatus.ERROR)
        timeout_count = sum(1 for e in entries if e.status == CronRunStatus.TIMEOUT)
        durations = [e.duration_secs for e in entries if e.duration_secs is not None]
        avg_duration = sum(durations) / len(durations) if durations else 0.0
        return {
            "job_id": job_id,
            "name": job.name,
            "enabled": job.enabled,
            "total_runs": len(entries),
            "ok_count": ok_count,
            "error_count": error_count,
            "timeout_count": timeout_count,
            "consecutive_errors": job.state.consecutive_errors,
            "avg_duration_secs": round(avg_duration, 3),
            "last_run_at": job.state.last_run_at,
            "last_run_status": job.state.last_run_status.value if job.state.last_run_status else None,
            "next_run_at": job.state.next_run_at,
        }

    # ── API pública: status ─────────────────────────────────

    def status(self) -> Dict[str, Any]:
        """Retorna estado general del scheduler."""
        enabled_jobs = [j for j in self._jobs.values() if j.enabled]
        next_runs = [
            j.state.next_run_at for j in enabled_jobs
            if j.state.next_run_at is not None
        ]
        return {
            "running": self._running,
            "total_jobs": len(self._jobs),
            "enabled_jobs": len(enabled_jobs),
            "active_jobs": len(self._active_jobs),
            "next_wake_at": min(next_runs) if next_runs else None,
            "max_concurrent": self._max_concurrent,
            "history_entries": len(self._history),
        }

    # ── Lifecycle ───────────────────────────────────────────

    async def start(self) -> None:
        """Inicia el scheduler en background."""
        if self._running:
            logger.warning("Scheduler ya está corriendo")
            return
        self._running = True

        # Limpiar marcadores de running_at obsoletos (restart recovery)
        for job in self._jobs.values():
            if job.state.running_at is not None:
                logger.warning(
                    "Limpiando marcador running_at obsoleto en job '%s'", job.id
                )
                job.state.running_at = None

        # Recalcular próximas ejecuciones
        now = time.time()
        for job in self._jobs.values():
            if job.enabled and job.state.next_run_at is None:
                job.state.next_run_at = self._compute_next_run(job, now)

        self._task = asyncio.create_task(self._tick())
        logger.info(
            "CronScheduler iniciado (tick=%.1fs, max_concurrent=%d, jobs=%d)",
            self._tick_interval,
            self._max_concurrent,
            len(self._jobs),
        )

    async def stop(self) -> None:
        """Detiene el scheduler."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("CronScheduler detenido")

    @property
    def is_running(self) -> bool:
        """Indica si el scheduler está corriendo."""
        return self._running

    @property
    def active_job_count(self) -> int:
        """Número de jobs actualmente en ejecución."""
        return len(self._active_jobs)

    @property
    def max_concurrent_jobs(self) -> int:
        """Límite de concurrencia configurado."""
        return self._max_concurrent

    @max_concurrent_jobs.setter
    def max_concurrent_jobs(self, value: int) -> None:
        """Actualiza el límite de concurrencia."""
        self._max_concurrent = max(1, value)
        self._semaphore = asyncio.Semaphore(self._max_concurrent)

    # ── Loop principal ──────────────────────────────────────

    async def _tick(self) -> None:
        """Loop principal — verifica jobs cada tick_interval segundos.

        Portado de ``onTimer`` en OpenClaw ``timer.ts``.
        Incluye detección de cambio de minuto para evitar ejecuciones dobles.
        """
        last_check_minute: Optional[int] = None

        while self._running:
            try:
                now_ts = time.time()
                now = datetime.fromtimestamp(now_ts)
                current_minute = now.minute + now.hour * 60 + now.day * 1440

                # Solo evaluar si cambió el minuto (evitar ejecuciones dobles)
                if current_minute != last_check_minute:
                    last_check_minute = current_minute
                    await self._evaluate_jobs(now_ts)

                await asyncio.sleep(self._tick_interval)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error en tick del scheduler")
                await asyncio.sleep(self._tick_interval)

    async def _evaluate_jobs(self, now_ts: float) -> None:
        """Evalúa y ejecuta todos los jobs que coinciden con el momento actual.

        Portado de ``onTimer`` + ``collectRunnableJobs`` en OpenClaw.
        Incluye concurrencia controlada via semáforo.
        """
        due_jobs = self._collect_runnable_jobs(now_ts)
        if not due_jobs:
            return

        # Limitar concurrencia
        concurrency = min(self._max_concurrent, len(due_jobs))
        tasks: List[asyncio.Task[None]] = []

        for job in due_jobs[:concurrency]:
            task = asyncio.create_task(self._run_due_job(job))
            tasks.append(task)

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _collect_runnable_jobs(self, now_ts: float) -> List[CronJob]:
        """Recolecta jobs que deben ejecutarse ahora.

        Portado de ``collectRunnableJobs`` en OpenClaw ``timer.ts``.
        """
        runnable: List[CronJob] = []
        for job in self._jobs.values():
            if not job.enabled or job.action is None:
                continue
            if job.state.running_at is not None:
                if job.overlap_policy == "skip":
                    continue
            if job.state.next_run_at is not None and now_ts >= job.state.next_run_at:
                runnable.append(job)
                continue
            # Fallback: evaluar expresión cron directamente
            if job.schedule_kind == CronScheduleKind.CRON:
                try:
                    now_dt = datetime.fromtimestamp(now_ts)
                    if job.timezone:
                        try:
                            from zoneinfo import ZoneInfo
                            now_dt = datetime.fromtimestamp(
                                now_ts, tz=ZoneInfo(job.timezone)
                            )
                        except (ImportError, KeyError):
                            pass
                    if matches_cron(job.expression, now_dt):
                        if job.state.next_run_at is None:
                            runnable.append(job)
                except CronExpressionError:
                    logger.warning(
                        "Expresión cron inválida en job '%s': %s",
                        job.id, job.expression,
                    )
        return runnable

    async def _run_due_job(self, job: CronJob) -> None:
        """Ejecuta un job due con semáforo de concurrencia."""
        async with self._semaphore:
            await self._execute_job(job)

    # ── Ejecución de job ────────────────────────────────────

    async def _execute_job(self, job: CronJob) -> CronRunStatus:
        """Ejecuta un job con timeout, retry, tracking y alertas.

        Portado de ``executeJob`` + ``applyJobResult`` en OpenClaw.
        """
        if job.action is None:
            return CronRunStatus.SKIPPED

        # Marcar como corriendo
        started_at = time.time()
        job.state.running_at = started_at
        job.state.last_error = None
        self._active_jobs.add(job.id)
        self._emit_event(job_id=job.id, action="started", run_at=started_at)

        status = CronRunStatus.OK
        error_text: Optional[str] = None
        summary: Optional[str] = None

        try:
            # Aplicar jitter
            if job.jitter_secs > 0:
                jitter = random.uniform(0, job.jitter_secs)
                await asyncio.sleep(jitter)

            # Ejecutar con timeout
            timeout = job.timeout_secs or DEFAULT_JOB_TIMEOUT_SECS
            try:
                result = await asyncio.wait_for(job.action(), timeout=timeout)
                if isinstance(result, str):
                    summary = result
            except asyncio.TimeoutError:
                status = CronRunStatus.TIMEOUT
                error_text = f"Job '{job.name}' excedió timeout de {timeout}s"
                logger.warning(error_text)
            except Exception as exc:
                status = CronRunStatus.ERROR
                error_text = str(exc)
                logger.exception("Error al ejecutar job '%s'", job.id)

        except asyncio.CancelledError:
            status = CronRunStatus.ERROR
            error_text = "Job cancelado"
        finally:
            ended_at = time.time()
            duration = ended_at - started_at

            # Actualizar estado del job
            await self._apply_job_result(
                job, status, error_text, started_at, ended_at
            )

            # Registrar en historial
            self._record_history(job, status, error_text, summary, duration, ended_at)

            # Limpiar running
            job.state.running_at = None
            self._active_jobs.discard(job.id)

            # Legacy compat
            job.last_run = datetime.fromtimestamp(started_at)
            job.run_count += 1
            if status != CronRunStatus.OK:
                job.error_count += 1

            # Emit finished
            self._emit_event(
                job_id=job.id,
                action="finished",
                status=status.value,
                error=error_text,
                summary=summary,
                duration_secs=round(duration, 3),
                next_run_at=job.state.next_run_at,
            )

            # Delete-after-run para jobs one-shot
            if (
                job.delete_after_run
                and job.schedule_kind == CronScheduleKind.AT
                and status == CronRunStatus.OK
            ):
                self._jobs.pop(job.id, None)
                self._emit_event(job_id=job.id, action="removed")

        return status

    async def _apply_job_result(
        self,
        job: CronJob,
        status: CronRunStatus,
        error: Optional[str],
        started_at: float,
        ended_at: float,
    ) -> None:
        """Aplica el resultado de una ejecución al estado del job.

        Portado de ``applyJobResult`` en OpenClaw ``timer.ts``.
        Maneja errores consecutivos, backoff exponencial, one-shot disable,
        y cálculo de next_run_at.
        """
        job.state.last_run_at = started_at
        job.state.last_run_status = status
        job.state.last_error = error
        job.state.last_duration_secs = max(0, ended_at - started_at)

        if status in (CronRunStatus.ERROR, CronRunStatus.TIMEOUT):
            job.state.consecutive_errors += 1
            await self._check_failure_alert(job, error)

            # Backoff y retry para one-shot jobs
            if job.schedule_kind == CronScheduleKind.AT:
                retry_cfg = job.retry_config or CronRetryConfig()
                is_transient = _is_transient_error(
                    error or "", retry_cfg.retry_on
                )
                if is_transient and job.state.consecutive_errors <= retry_cfg.max_attempts:
                    backoff = _error_backoff_secs(
                        job.state.consecutive_errors, retry_cfg.backoff_schedule_secs
                    )
                    job.state.next_run_at = ended_at + backoff
                    logger.info(
                        "Programando reintento para job one-shot '%s' "
                        "(errores=%d, backoff=%.1fs)",
                        job.id, job.state.consecutive_errors, backoff,
                    )
                else:
                    job.enabled = False
                    job.state.next_run_at = None
                    logger.warning(
                        "Deshabilitando job one-shot '%s' tras error: %s",
                        job.id, "max reintentos" if is_transient else "error permanente",
                    )
            else:
                # Jobs recurrentes: aplicar backoff exponencial
                backoff = _error_backoff_secs(
                    job.state.consecutive_errors
                )
                normal_next = self._compute_next_run(job, ended_at)
                backoff_next = ended_at + backoff
                if normal_next is not None:
                    job.state.next_run_at = max(normal_next, backoff_next)
                else:
                    job.state.next_run_at = backoff_next
                logger.info(
                    "Aplicando backoff a job '%s' (errores=%d, backoff=%.1fs)",
                    job.id, job.state.consecutive_errors, backoff,
                )
        else:
            # Éxito: resetear errores
            job.state.consecutive_errors = 0
            job.state.last_failure_alert_at = None

            if job.schedule_kind == CronScheduleKind.AT:
                if status == CronRunStatus.OK or status == CronRunStatus.SKIPPED:
                    job.enabled = False
                    job.state.next_run_at = None
            elif job.enabled:
                next_run = self._compute_next_run(job, ended_at)
                # Safety net: evitar refire inmediato
                if (
                    job.schedule_kind == CronScheduleKind.CRON
                    and next_run is not None
                ):
                    min_next = ended_at + MIN_REFIRE_GAP_SECS
                    next_run = max(next_run, min_next)
                job.state.next_run_at = next_run
            else:
                job.state.next_run_at = None

    async def _check_failure_alert(
        self, job: CronJob, error: Optional[str]
    ) -> None:
        """Emite alerta de fallo si se cumplen las condiciones.

        Portado de ``emitFailureAlert`` en OpenClaw ``timer.ts``.
        """
        alert_cfg = job.failure_alert
        # Determinar callback: prioridad al del job, luego al global
        callback = None
        if alert_cfg and alert_cfg.callback:
            callback = alert_cfg.callback
        elif self._failure_alert_callback:
            callback = self._failure_alert_callback

        if callback is None:
            return

        after = alert_cfg.after if alert_cfg else DEFAULT_FAILURE_ALERT_AFTER
        cooldown = (
            alert_cfg.cooldown_secs
            if alert_cfg
            else DEFAULT_FAILURE_ALERT_COOLDOWN_SECS
        )

        if job.state.consecutive_errors < after:
            return

        # Cooldown check
        now = time.time()
        if job.state.last_failure_alert_at is not None:
            if now - job.state.last_failure_alert_at < cooldown:
                return

        job.state.last_failure_alert_at = now

        safe_error = (error or "error desconocido")[:200]
        alert_text = (
            f'Job cron "{job.name}" falló {job.state.consecutive_errors} veces.\n'
            f"Último error: {safe_error}"
        )

        await self._safe_fire_alert(
            callback, job.id, alert_text, job.state.consecutive_errors
        )

    async def _safe_fire_alert(
        self,
        callback: Callable[[str, str, int], Coroutine[Any, Any, None]],
        job_id: str,
        text: str,
        count: int,
    ) -> None:
        """Ejecuta callback de alerta de forma segura."""
        try:
            await callback(job_id, text, count)
        except Exception:
            logger.exception("Error al enviar alerta de fallo para job '%s'", job_id)

    # ── Cálculo de próxima ejecución ────────────────────────

    def _compute_next_run(self, job: CronJob, now_ts: float) -> Optional[float]:
        """Calcula la próxima ejecución para un job.

        Portado de ``computeJobNextRunAtMs`` en OpenClaw ``jobs.ts``.
        """
        if not job.enabled:
            return None

        if job.schedule_kind == CronScheduleKind.EVERY:
            every = job.every_secs
            if every is None or every <= 0:
                return None
            # Si ya corrió, calcular desde el último run
            if job.state.last_run_at is not None:
                next_from_last = job.state.last_run_at + every
                if next_from_last > now_ts:
                    return next_from_last
            # Calcular desde anchor (creación)
            return now_ts + every

        if job.schedule_kind == CronScheduleKind.AT:
            at = job.at_timestamp
            if at is None:
                return None
            if job.state.last_run_status == CronRunStatus.OK:
                return None
            return at if at > now_ts else at

        # CRON expression
        try:
            now_dt = datetime.fromtimestamp(now_ts)
            tz_info = None
            if job.timezone:
                try:
                    from zoneinfo import ZoneInfo
                    tz_info = ZoneInfo(job.timezone)
                    now_dt = datetime.fromtimestamp(now_ts, tz=tz_info)
                except (ImportError, KeyError):
                    pass

            next_dt = next_cron_datetime(job.expression, now_dt)
            if next_dt is None:
                return None

            next_ts = next_dt.timestamp()

            # Aplicar stagger
            if job.stagger_ms > 0:
                offset = _resolve_stable_stagger_offset(job.id, job.stagger_ms)
                next_ts += offset

            return next_ts
        except CronExpressionError:
            logger.warning(
                "Error al calcular próxima ejecución para job '%s': expresión '%s'",
                job.id, job.expression,
            )
            return None

    # ── Historial ───────────────────────────────────────────

    def _record_history(
        self,
        job: CronJob,
        status: CronRunStatus,
        error: Optional[str],
        summary: Optional[str],
        duration: float,
        ended_at: float,
    ) -> None:
        """Registra una ejecución en el historial."""
        entry = CronRunLogEntry(
            ts=ended_at,
            job_id=job.id,
            status=status,
            error=error,
            summary=summary,
            duration_secs=round(duration, 3),
            next_run_at=job.state.next_run_at,
        )
        self._history.append(entry)

        # Pruning: mantener máximo _max_history entradas
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

    def clear_history(self, *, job_id: Optional[str] = None) -> int:
        """Limpia el historial. Retorna cantidad de entradas eliminadas.

        Args:
            job_id: Si se provee, solo limpia historial de ese job.
        """
        if job_id:
            before = len(self._history)
            self._history = [e for e in self._history if e.job_id != job_id]
            return before - len(self._history)
        else:
            count = len(self._history)
            self._history.clear()
            return count

    # ── Eventos ─────────────────────────────────────────────

    def _emit_event(self, **kwargs: Any) -> None:
        """Emite un evento del scheduler."""
        if self._on_event:
            try:
                self._on_event(kwargs)
            except Exception:
                pass  # Ignorar errores en handlers de eventos

    # ── Helpers ─────────────────────────────────────────────

    def _get_job_or_raise(self, job_id: str) -> CronJob:
        """Obtiene un job o lanza CronJobNotFoundError."""
        job = self._jobs.get(job_id)
        if job is None:
            raise CronJobNotFoundError(f"Job '{job_id}' no encontrado")
        return job
