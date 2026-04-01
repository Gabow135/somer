"""HeartbeatRunner — ejecuta turnos LLM periódicos y envía alertas.

Portado de OpenClaw: heartbeat-runner.ts, heartbeat-summary.ts,
heartbeat-visibility.ts.

Flujo cada intervalo:
  1. Verificar horario activo
  2. Leer HEARTBEAT.md (instrucciones)
  3. Ejecutar turno LLM con prompt de heartbeat
  4. Si responde HEARTBEAT_OK → nada que reportar (opcionalmente enviar ack)
  5. Si responde con contenido → entregar al canal configurado
  6. Deduplicar alertas repetidas
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

HEARTBEAT_TOKEN = "HEARTBEAT_OK"
HEARTBEAT_FILENAME = "HEARTBEAT.md"

DEFAULT_PROMPT = (
    "Lee HEARTBEAT.md si existe (contexto de workspace). "
    "Sigue las instrucciones estrictamente. "
    "No inventes tareas ni repitas cosas de conversaciones anteriores. "
    "Si no hay nada que necesite atencion, responde solo: HEARTBEAT_OK"
)

DEFAULT_HEARTBEAT_CONTENT = """\
# SOMER Heartbeat

## Instrucciones

Eres el agente de monitoreo de SOMER. En cada heartbeat:

1. **Revisa tareas cron pendientes** — si hay jobs fallidos recientes, reporta un resumen.
2. **Verifica estado del sistema** — si todo esta en orden, responde solo: HEARTBEAT_OK
3. **No inventes tareas** — solo reporta problemas reales que detectes.
4. **No repitas alertas** — si ya reportaste algo, no lo repitas a menos que cambie.

## Reglas

- Si no hay nada que reportar, responde **unicamente**: `HEARTBEAT_OK`
- Si hay un problema, describe brevemente que paso y que accion se recomienda.
- Nunca ejecutes escaneos de seguridad automaticos desde el heartbeat.
- Los escaneos de ciberseguridad solo se ejecutan cuando el usuario los solicita explicitamente.
"""

_HEARTBEAT_OK_PATTERN = re.compile(
    r"^\s*HEARTBEAT_OK\s*$", re.IGNORECASE
)


def is_heartbeat_ok(text: str) -> bool:
    """Detecta si la respuesta es solo HEARTBEAT_OK (sin contenido extra)."""
    stripped = text.strip()
    if not stripped:
        return True
    return bool(_HEARTBEAT_OK_PATTERN.match(stripped))


# ── Estadísticas de heartbeat ────────────────────────────────


@dataclass
class HeartbeatStats:
    """Estadísticas acumuladas del heartbeat runner."""

    total_runs: int = 0
    ok_count: int = 0
    alert_count: int = 0
    error_count: int = 0
    skip_quiet_count: int = 0
    skip_duplicate_count: int = 0
    skip_no_target_count: int = 0
    last_run_at: float = 0.0
    last_result: str = ""
    consecutive_errors: int = 0

    def record(self, result: str) -> None:
        """Registra el resultado de un ciclo de heartbeat."""
        self.total_runs += 1
        self.last_run_at = time.time()
        self.last_result = result

        if result == "ok":
            self.ok_count += 1
            self.consecutive_errors = 0
        elif result == "alert-sent":
            self.alert_count += 1
            self.consecutive_errors = 0
        elif result == "error":
            self.error_count += 1
            self.consecutive_errors += 1
        elif result == "skipped-quiet-hours":
            self.skip_quiet_count += 1
        elif result == "skipped-duplicate":
            self.skip_duplicate_count += 1
        elif result == "skipped-no-target":
            self.skip_no_target_count += 1


# ── Backoff para errores consecutivos ───────────────────────


def compute_error_backoff(
    consecutive_errors: int,
    base_interval: int,
    max_multiplier: int = 8,
) -> int:
    """Calcula el intervalo con backoff exponencial para errores.

    Args:
        consecutive_errors: Número de errores consecutivos.
        base_interval: Intervalo base en segundos.
        max_multiplier: Multiplicador máximo.

    Returns:
        Intervalo ajustado en segundos.
    """
    if consecutive_errors <= 0:
        return base_interval
    multiplier = min(2 ** consecutive_errors, max_multiplier)
    return base_interval * multiplier


def _parse_time_minutes(time_str: str) -> Optional[int]:
    """Parsea "HH:MM" a minutos desde medianoche."""
    match = re.match(r"^([01]\d|2[0-3]):([0-5]\d)$", time_str.strip())
    if not match:
        if time_str.strip() == "24:00":
            return 24 * 60
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


def is_within_active_hours(
    start: str,
    end: str,
    timezone: str = "UTC",
    now: Optional[datetime] = None,
) -> bool:
    """Verifica si la hora actual está dentro del horario activo."""
    start_min = _parse_time_minutes(start)
    end_min = _parse_time_minutes(end)
    if start_min is None or end_min is None:
        return True
    if start_min == end_min:
        return False

    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(timezone)
    except (ImportError, KeyError):
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo("UTC")
        except ImportError:
            return True

    current = now or datetime.now(tz)
    if current.tzinfo is None:
        current = current.replace(tzinfo=tz)
    else:
        current = current.astimezone(tz)

    current_min = current.hour * 60 + current.minute

    if end_min > start_min:
        return start_min <= current_min < end_min
    # Rango que cruza medianoche (ej: 22:00 - 06:00)
    return current_min >= start_min or current_min < end_min


class HeartbeatRunner:
    """Ejecuta turnos LLM periódicos y entrega alertas por canales.

    Inspirado en OpenClaw heartbeat-runner.ts.
    """

    def __init__(
        self,
        runner: Any,  # AgentRunner
        channel_registry: Any,  # ChannelRegistry
        config: Any,  # SomerConfig
    ):
        self._runner = runner
        self._channels = channel_registry
        self._config = config
        self._hb_config = config.heartbeat
        self._task: Optional[asyncio.Task[None]] = None
        self._running = False
        self._last_alert_text = ""
        self._last_alert_time = 0.0
        self._system_prompt = ""
        self._stats = HeartbeatStats()
        self._started_at: float = 0.0

    def update_config(self, config: Any) -> None:
        """Hot-reload de configuración."""
        self._config = config
        self._hb_config = config.heartbeat

    def set_system_prompt(self, prompt: str) -> None:
        """Establece el system prompt para los turnos de heartbeat."""
        self._system_prompt = prompt

    @property
    def stats(self) -> HeartbeatStats:
        """Estadísticas acumuladas del runner."""
        return self._stats

    def get_summary(self) -> Dict[str, Any]:
        """Retorna un resumen del estado del heartbeat.

        Returns:
            Dict con estadísticas, configuración y estado actual.
        """
        uptime = time.time() - self._started_at if self._started_at > 0 else 0
        return {
            "running": self._running,
            "enabled": self._hb_config.enabled,
            "interval_seconds": self._hb_config.every,
            "target": self._hb_config.target,
            "uptime_seconds": uptime,
            "stats": {
                "total_runs": self._stats.total_runs,
                "ok": self._stats.ok_count,
                "alerts": self._stats.alert_count,
                "errors": self._stats.error_count,
                "skipped_quiet": self._stats.skip_quiet_count,
                "skipped_duplicate": self._stats.skip_duplicate_count,
                "last_result": self._stats.last_result,
                "consecutive_errors": self._stats.consecutive_errors,
            },
        }

    async def start(self) -> None:
        """Inicia el heartbeat runner."""
        if not self._hb_config.enabled:
            logger.info("Heartbeat desactivado en config")
            return
        if self._running:
            return
        self._running = True
        self._started_at = time.time()
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "Heartbeat iniciado (cada %ds, target=%s)",
            self._hb_config.every,
            self._hb_config.target,
        )

    async def stop(self) -> None:
        """Detiene el heartbeat runner."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("Heartbeat detenido")

    async def _loop(self) -> None:
        """Loop principal — espera el intervalo y ejecuta.

        Aplica backoff exponencial cuando hay errores consecutivos.
        """
        # Esperar un poco al arranque para que todo esté listo
        await asyncio.sleep(5)

        while self._running:
            logger.info("Heartbeat: iniciando ciclo #%d", self._stats.total_runs + 1)
            try:
                result = await asyncio.wait_for(
                    self._run_once(),
                    timeout=120,  # 2 min máximo por ciclo
                )
                self._stats.record(result)
                logger.info("Heartbeat resultado: %s", result)
            except asyncio.TimeoutError:
                logger.error("Heartbeat: timeout (120s) en _run_once — posible hang del provider")
                self._stats.record("error")
            except Exception:
                logger.exception("Error en heartbeat")
                self._stats.record("error")

            if not self._running:
                break

            # Aplicar backoff si hay errores consecutivos (máximo 1h)
            interval = min(
                compute_error_backoff(
                    self._stats.consecutive_errors,
                    self._hb_config.every,
                ),
                3600,
            )
            if self._stats.consecutive_errors > 0:
                logger.warning(
                    "Heartbeat: %d errores consecutivos, próximo intento en %ds",
                    self._stats.consecutive_errors, interval,
                )
            await asyncio.sleep(interval)

    async def _run_once(self) -> str:
        """Ejecuta un ciclo de heartbeat.

        Returns:
            Status string: "ok", "alert-sent", "skipped-*", "error"
        """
        # 1. Verificar horario activo
        if self._hb_config.active_hours:
            ah = self._hb_config.active_hours
            if not is_within_active_hours(ah.start, ah.end, ah.timezone):
                return "skipped-quiet-hours"

        # 2. Leer HEARTBEAT.md
        heartbeat_content = self._read_heartbeat_file()

        # 3. Construir prompt
        prompt = self._build_prompt(heartbeat_content)

        # 4. Ejecutar turno LLM
        try:
            response_text = await self._run_llm_turn(prompt)
        except Exception as exc:
            logger.warning("Error en turno LLM de heartbeat: %s", exc)
            return "error"

        if not response_text:
            return "ok"

        # 5. Detectar HEARTBEAT_OK
        if is_heartbeat_ok(response_text):
            if self._hb_config.show_ok:
                await self._deliver(HEARTBEAT_TOKEN)
            return "ok"

        # 6. Deduplicar
        if self._is_duplicate(response_text):
            logger.debug("Heartbeat duplicado suprimido")
            return "skipped-duplicate"

        # 7. Entregar al canal
        delivered = await self._deliver(response_text)
        if delivered:
            self._last_alert_text = response_text.strip()
            self._last_alert_time = time.monotonic()
            return "alert-sent"

        return "skipped-no-target"

    def _read_heartbeat_file(self) -> str:
        """Lee HEARTBEAT.md del directorio de trabajo."""
        for candidate in [
            Path(HEARTBEAT_FILENAME),
            Path.home() / ".somer" / HEARTBEAT_FILENAME,
        ]:
            if candidate.exists():
                try:
                    content = candidate.read_text(encoding="utf-8").strip()
                    if content:
                        return content
                except Exception:
                    pass
        return ""

    def _build_prompt(self, heartbeat_content: str) -> str:
        """Construye el prompt para el turno de heartbeat."""
        base = self._hb_config.prompt or DEFAULT_PROMPT

        parts = [base]

        if heartbeat_content:
            parts.append(
                f"\n\n--- Contenido de HEARTBEAT.md ---\n{heartbeat_content}"
            )

        # Agregar timestamp para contexto temporal
        now = datetime.now()
        parts.append(f"\n\nFecha y hora actual: {now.strftime('%Y-%m-%d %H:%M:%S')}")

        return "\n".join(parts)

    async def _run_llm_turn(self, prompt: str) -> str:
        """Ejecuta un turno LLM con el prompt de heartbeat."""
        model = self._hb_config.model or self._config.default_model
        session_id = "heartbeat:main"

        logger.info("Heartbeat: ejecutando turno LLM con modelo=%s", model)

        turn = await self._runner.run(
            session_id=session_id,
            user_message=prompt,
            model=model,
            system_prompt=self._system_prompt,
        )

        # Extraer respuesta del asistente
        for msg in turn.messages:
            if msg.role.value == "assistant" and msg.content:
                logger.info(
                    "Heartbeat: respuesta LLM (%d chars): %s",
                    len(msg.content), msg.content[:150],
                )
                return msg.content

        logger.warning("Heartbeat: turno LLM sin respuesta del asistente")
        return ""

    def _is_duplicate(self, text: str) -> bool:
        """Verifica si el texto es duplicado de la última alerta."""
        if not self._last_alert_text:
            return False

        dedup_window = self._hb_config.deduplicate_hours * 3600
        elapsed = time.monotonic() - self._last_alert_time

        if elapsed > dedup_window:
            return False

        return text.strip() == self._last_alert_text

    async def _deliver(self, text: str) -> bool:
        """Entrega un mensaje al canal configurado."""
        target = self._hb_config.target
        chat_id = self._hb_config.target_chat_id

        if target == "none" or not chat_id:
            return False

        plugin = self._channels.get(target)
        if not plugin:
            logger.warning("Canal heartbeat no encontrado: %s", target)
            return False

        try:
            await plugin.send_message(chat_id, text)
            logger.info("Heartbeat entregado a %s/%s", target, chat_id)
            return True
        except Exception as exc:
            logger.warning(
                "Error entregando heartbeat a %s/%s: %s", target, chat_id, exc
            )
            return False
