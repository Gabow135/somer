"""Sistema de sub-agentes: registry, spawn, depth tracking.

Portado de OpenClaw: subagent-registry.ts, subagent-registry.types.ts,
subagent-spawn.ts, subagent-depth.ts, subagent-announce.ts.

Implementa:
- Registro global de runs de sub-agentes con ciclo de vida
- Spawn de nuevos sub-agentes con control de profundidad
- Tracking de profundidad de anidamiento
- Anuncio de resultados al padre
- Limpieza y archivado de runs

Python 3.9+ — ``from __future__ import annotations``.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set

from shared.errors import AgentError

logger = logging.getLogger(__name__)


# ── Constantes ────────────────────────────────────────────────

DEFAULT_MAX_SPAWN_DEPTH = 3
DEFAULT_MAX_CONCURRENT = 3
DEFAULT_RUN_TIMEOUT_SECS = 300
ANNOUNCE_TIMEOUT_SECS = 120
MAX_ANNOUNCE_RETRIES = 3
ARCHIVE_AFTER_SECS = 300  # 5 minutos


# ── Enums ─────────────────────────────────────────────────────


class SpawnMode(str, Enum):
    """Modo de spawn de un sub-agente.

    Portado de OpenClaw: subagent-spawn.ts → SpawnSubagentMode.
    """

    RUN = "run"  # Ejecución única, sesión eliminada al terminar
    SESSION = "session"  # Sesión persistente para follow-ups


class RunOutcome(str, Enum):
    """Resultado de un run de sub-agente.

    Portado de OpenClaw: subagent-announce.ts → SubagentRunOutcome.
    """

    COMPLETE = "complete"
    ERROR = "error"
    TIMEOUT = "timeout"
    KILLED = "killed"


class EndedReason(str, Enum):
    """Razón de finalización de un sub-agente.

    Portado de OpenClaw: subagent-lifecycle-events.ts.
    """

    COMPLETE = "complete"
    ERROR = "error"
    KILLED = "killed"
    TIMEOUT = "timeout"


# ── Tipos ─────────────────────────────────────────────────────


@dataclass
class SubagentRunRecord:
    """Registro de un run de sub-agente.

    Portado de OpenClaw: subagent-registry.types.ts → SubagentRunRecord.
    """

    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    child_session_key: str = ""
    requester_session_key: str = ""
    requester_display_key: str = ""
    task: str = ""
    cleanup: str = "delete"  # "delete" | "keep"
    label: Optional[str] = None
    model: Optional[str] = None
    spawn_mode: SpawnMode = SpawnMode.RUN
    run_timeout_secs: Optional[float] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    outcome: Optional[RunOutcome] = None
    ended_reason: Optional[EndedReason] = None
    result_text: Optional[str] = None
    depth: int = 0

    @property
    def is_active(self) -> bool:
        """True si el run está en progreso."""
        return self.ended_at is None

    @property
    def runtime_secs(self) -> float:
        """Duración del run en segundos."""
        if self.started_at is None:
            return 0.0
        end = self.ended_at or time.time()
        return end - self.started_at


@dataclass
class SpawnParams:
    """Parámetros para spawn de un sub-agente.

    Portado de OpenClaw: subagent-spawn.ts → SpawnSubagentParams.
    """

    task: str
    agent_id: Optional[str] = None
    label: Optional[str] = None
    model: Optional[str] = None
    mode: SpawnMode = SpawnMode.RUN
    cleanup: str = "delete"
    run_timeout_secs: Optional[float] = None
    expects_completion: bool = True


@dataclass
class SpawnResult:
    """Resultado del spawn de un sub-agente.

    Portado de OpenClaw: subagent-spawn.ts → SpawnSubagentResult.
    """

    status: str  # "accepted" | "forbidden" | "error"
    child_session_key: Optional[str] = None
    run_id: Optional[str] = None
    mode: Optional[SpawnMode] = None
    note: Optional[str] = None
    error: Optional[str] = None


# ── Registry de sub-agentes ───────────────────────────────────


class SubagentRegistry:
    """Registro global de sub-agentes activos.

    Portado de OpenClaw: subagent-registry.ts.
    Mantiene todos los runs de sub-agentes con su estado de ciclo de vida,
    y provee queries para monitoreo y control.
    """

    def __init__(
        self,
        max_concurrent: int = DEFAULT_MAX_CONCURRENT,
        max_depth: int = DEFAULT_MAX_SPAWN_DEPTH,
    ) -> None:
        self._runs: Dict[str, SubagentRunRecord] = {}
        self._max_concurrent = max_concurrent
        self._max_depth = max_depth
        self._lock = asyncio.Lock()

    # ── Registro ──────────────────────────────────────────────

    async def register(self, record: SubagentRunRecord) -> None:
        """Registra un nuevo run de sub-agente."""
        async with self._lock:
            self._runs[record.run_id] = record
            logger.info(
                "Sub-agente registrado: run=%s child=%s depth=%d",
                record.run_id,
                record.child_session_key,
                record.depth,
            )

    async def start(self, run_id: str) -> None:
        """Marca un run como iniciado."""
        async with self._lock:
            record = self._runs.get(run_id)
            if record:
                record.started_at = time.time()

    async def end(
        self,
        run_id: str,
        outcome: RunOutcome,
        *,
        reason: Optional[EndedReason] = None,
        result_text: Optional[str] = None,
    ) -> None:
        """Marca un run como finalizado."""
        async with self._lock:
            record = self._runs.get(run_id)
            if record:
                record.ended_at = time.time()
                record.outcome = outcome
                record.ended_reason = reason or EndedReason(outcome.value)
                if result_text is not None:
                    record.result_text = result_text[:100 * 1024]  # Cap 100KB
                logger.info(
                    "Sub-agente finalizado: run=%s outcome=%s (%.1fs)",
                    run_id,
                    outcome.value,
                    record.runtime_secs,
                )

    async def remove(self, run_id: str) -> Optional[SubagentRunRecord]:
        """Elimina un run del registro."""
        async with self._lock:
            return self._runs.pop(run_id, None)

    # ── Queries ───────────────────────────────────────────────

    def get(self, run_id: str) -> Optional[SubagentRunRecord]:
        """Obtiene un run por ID."""
        return self._runs.get(run_id)

    def active_count(self, requester_key: Optional[str] = None) -> int:
        """Cuenta runs activos, opcionalmente filtrado por requester."""
        return sum(
            1
            for r in self._runs.values()
            if r.is_active
            and (requester_key is None or r.requester_session_key == requester_key)
        )

    def active_runs(self, requester_key: Optional[str] = None) -> List[SubagentRunRecord]:
        """Lista runs activos."""
        return [
            r
            for r in self._runs.values()
            if r.is_active
            and (requester_key is None or r.requester_session_key == requester_key)
        ]

    def runs_for_child(self, child_session_key: str) -> List[SubagentRunRecord]:
        """Lista runs para una sesión child."""
        return [
            r
            for r in self._runs.values()
            if r.child_session_key == child_session_key
        ]

    def all_runs(self) -> List[SubagentRunRecord]:
        """Lista todos los runs."""
        return list(self._runs.values())

    # ── Validación de spawn ───────────────────────────────────

    def can_spawn(
        self,
        requester_key: str,
        depth: int = 0,
    ) -> Tuple[bool, Optional[str]]:
        """Verifica si se puede hacer spawn de un sub-agente.

        Returns:
            (puede_spawnar, razón_de_rechazo)
        """
        # Verificar profundidad
        if depth >= self._max_depth:
            return False, (
                f"Profundidad máxima alcanzada ({depth}/{self._max_depth})"
            )

        # Verificar concurrencia
        active = self.active_count(requester_key)
        if active >= self._max_concurrent:
            return False, (
                f"Máximo de sub-agentes concurrentes alcanzado "
                f"({active}/{self._max_concurrent})"
            )

        return True, None

    # ── Limpieza ──────────────────────────────────────────────

    async def cleanup_expired(self, max_age_secs: float = ARCHIVE_AFTER_SECS) -> int:
        """Limpia runs terminados más antiguos que max_age_secs.

        Returns:
            Número de runs eliminados.
        """
        now = time.time()
        to_remove: List[str] = []

        async with self._lock:
            for run_id, record in self._runs.items():
                if (
                    record.ended_at is not None
                    and (now - record.ended_at) > max_age_secs
                ):
                    to_remove.append(run_id)

            for run_id in to_remove:
                del self._runs[run_id]

        if to_remove:
            logger.debug("Limpiados %d runs expirados", len(to_remove))
        return len(to_remove)

    async def kill_all(
        self,
        requester_key: Optional[str] = None,
    ) -> int:
        """Finaliza forzosamente todos los runs activos.

        Returns:
            Número de runs terminados.
        """
        killed = 0
        async with self._lock:
            for record in self._runs.values():
                if not record.is_active:
                    continue
                if requester_key and record.requester_session_key != requester_key:
                    continue
                record.ended_at = time.time()
                record.outcome = RunOutcome.KILLED
                record.ended_reason = EndedReason.KILLED
                killed += 1

        if killed:
            logger.info("Terminados forzosamente %d sub-agentes", killed)
        return killed

    def status_summary(self) -> Dict[str, Any]:
        """Resumen del estado del registry."""
        active = [r for r in self._runs.values() if r.is_active]
        ended = [r for r in self._runs.values() if not r.is_active]
        return {
            "total": len(self._runs),
            "active": len(active),
            "ended": len(ended),
            "max_concurrent": self._max_concurrent,
            "max_depth": self._max_depth,
            "runs": [
                {
                    "run_id": r.run_id,
                    "task": r.task[:100],
                    "active": r.is_active,
                    "depth": r.depth,
                    "runtime_secs": round(r.runtime_secs, 1),
                    "outcome": r.outcome.value if r.outcome else None,
                }
                for r in self._runs.values()
            ],
        }


# Usamos Tuple importado de typing para Python 3.9
from typing import Tuple


# ── Depth tracking ────────────────────────────────────────────


def get_spawn_depth(
    session_key: str,
    depth_store: Optional[Dict[str, int]] = None,
) -> int:
    """Obtiene la profundidad de spawn de una sesión.

    Portado de OpenClaw: subagent-depth.ts → getSubagentDepthFromSessionStore.

    Args:
        session_key: Clave de sesión.
        depth_store: Almacén de profundidades por session_key.

    Returns:
        Profundidad de anidamiento (0 = raíz).
    """
    if not session_key:
        return 0

    if depth_store:
        depth = depth_store.get(session_key)
        if depth is not None:
            return depth

    # Inferir de la session key si contiene indicadores de profundidad
    # Formato: agent:<id>:subagent:<depth>:...
    parts = session_key.split(":")
    for i, part in enumerate(parts):
        if part == "subagent" and i + 1 < len(parts):
            try:
                return int(parts[i + 1])
            except ValueError:
                pass

    return 0


# ── Spawn ─────────────────────────────────────────────────────


async def spawn_subagent(
    params: SpawnParams,
    requester_session_key: str,
    registry: SubagentRegistry,
    *,
    agent_id: str = "main",
    depth: int = 0,
    depth_store: Optional[Dict[str, int]] = None,
) -> SpawnResult:
    """Spawn de un sub-agente.

    Portado de OpenClaw: subagent-spawn.ts → spawnSubagent.

    Valida profundidad y concurrencia, registra el run y genera
    la session key del child.

    Args:
        params: Parámetros de spawn.
        requester_session_key: Clave de sesión del requester.
        registry: Registro global de sub-agentes.
        agent_id: ID del agente a usar.
        depth: Profundidad actual del requester.
        depth_store: Almacén de profundidades.

    Returns:
        SpawnResult con el estado y la session key del child.
    """
    # Validar
    can, reason = registry.can_spawn(requester_session_key, depth)
    if not can:
        return SpawnResult(
            status="forbidden",
            error=reason,
        )

    # Generar IDs
    run_id = uuid.uuid4().hex[:12]
    child_depth = depth + 1
    target_agent = params.agent_id or agent_id
    child_key = f"agent:{target_agent}:subagent:{child_depth}:{run_id}"

    # Registrar
    record = SubagentRunRecord(
        run_id=run_id,
        child_session_key=child_key,
        requester_session_key=requester_session_key,
        requester_display_key=requester_session_key,
        task=params.task,
        cleanup=params.cleanup,
        label=params.label,
        model=params.model,
        spawn_mode=params.mode,
        run_timeout_secs=params.run_timeout_secs,
        depth=child_depth,
    )
    await registry.register(record)

    # Actualizar depth store
    if depth_store is not None:
        depth_store[child_key] = child_depth

    note = (
        "Auto-announce habilitado. No hacer polling, esperar evento de "
        "finalización."
    )
    if params.mode == SpawnMode.SESSION:
        note = "Sesión thread-bound activa para follow-ups."

    return SpawnResult(
        status="accepted",
        child_session_key=child_key,
        run_id=run_id,
        mode=params.mode,
        note=note,
    )


# ── Singleton global ──────────────────────────────────────────

_global_registry: Optional[SubagentRegistry] = None


def get_subagent_registry() -> SubagentRegistry:
    """Obtiene el registry global de sub-agentes.

    Crea uno si no existe.
    """
    global _global_registry
    if _global_registry is None:
        _global_registry = SubagentRegistry()
    return _global_registry


def set_subagent_registry(registry: SubagentRegistry) -> None:
    """Establece el registry global (para testing)."""
    global _global_registry
    _global_registry = registry
