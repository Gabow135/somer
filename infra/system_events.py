"""Bus de eventos del sistema — pub/sub interno para SOMER.

Portado de OpenClaw: agent-events.ts, diagnostic-events.ts.

Proporciona un bus de eventos global para comunicación interna
entre componentes sin acoplamiento directo.
"""

from __future__ import annotations

import logging
import time
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# ── Tipos de flujo de eventos ───────────────────────────────
EventStream = str  # "lifecycle" | "tool" | "assistant" | "error" | custom


@dataclass
class EventPayload:
    """Payload de un evento del sistema."""

    run_id: str
    seq: int
    stream: EventStream
    ts: float
    data: Dict[str, Any]
    session_key: Optional[str] = None


@dataclass
class RunContext:
    """Contexto de una ejecución de agente."""

    session_key: Optional[str] = None
    verbose_level: Optional[int] = None
    is_heartbeat: bool = False
    is_control_ui_visible: bool = True


# ── Tipos de eventos de diagnóstico ────────────────────────

DiagnosticSessionState = str  # "idle" | "processing" | "waiting"


@dataclass
class DiagnosticEvent:
    """Evento de diagnóstico del sistema."""

    type: str
    seq: int = 0
    ts: float = 0.0
    data: Dict[str, Any] = field(default_factory=dict)


# ── Estado global del bus de eventos ────────────────────────

EventListener = Callable[[EventPayload], None]
DiagnosticListener = Callable[[DiagnosticEvent], None]


class _EventBusState:
    """Estado global del bus de eventos de agentes."""

    def __init__(self) -> None:
        self.seq_by_run: Dict[str, int] = {}
        self.listeners: Set[EventListener] = set()
        self.run_context_by_id: Dict[str, RunContext] = {}
        self._lock = threading.Lock()

    def reset(self) -> None:
        """Reinicia el estado completo (para tests)."""
        with self._lock:
            self.seq_by_run.clear()
            self.listeners.clear()
            self.run_context_by_id.clear()


class _DiagnosticBusState:
    """Estado global del bus de eventos de diagnóstico."""

    def __init__(self) -> None:
        self.seq: int = 0
        self.listeners: Set[DiagnosticListener] = set()
        self.dispatch_depth: int = 0
        self._lock = threading.Lock()

    def reset(self) -> None:
        """Reinicia el estado completo (para tests)."""
        with self._lock:
            self.seq = 0
            self.listeners.clear()
            self.dispatch_depth = 0


# Singletons
_agent_state = _EventBusState()
_diagnostic_state = _DiagnosticBusState()


# ── API de eventos de agente ────────────────────────────────


def register_run_context(run_id: str, context: RunContext) -> None:
    """Registra o actualiza el contexto de una ejecución de agente."""
    if not run_id:
        return

    with _agent_state._lock:
        existing = _agent_state.run_context_by_id.get(run_id)
        if existing is None:
            _agent_state.run_context_by_id[run_id] = RunContext(
                session_key=context.session_key,
                verbose_level=context.verbose_level,
                is_heartbeat=context.is_heartbeat,
                is_control_ui_visible=context.is_control_ui_visible,
            )
            return

        if context.session_key and existing.session_key != context.session_key:
            existing.session_key = context.session_key
        if context.verbose_level is not None and existing.verbose_level != context.verbose_level:
            existing.verbose_level = context.verbose_level
        if existing.is_control_ui_visible != context.is_control_ui_visible:
            existing.is_control_ui_visible = context.is_control_ui_visible
        if existing.is_heartbeat != context.is_heartbeat:
            existing.is_heartbeat = context.is_heartbeat


def get_run_context(run_id: str) -> Optional[RunContext]:
    """Obtiene el contexto de una ejecución de agente."""
    return _agent_state.run_context_by_id.get(run_id)


def clear_run_context(run_id: str) -> None:
    """Elimina el contexto de una ejecución de agente."""
    _agent_state.run_context_by_id.pop(run_id, None)


def emit_agent_event(
    run_id: str,
    stream: EventStream,
    data: Dict[str, Any],
    session_key: Optional[str] = None,
) -> None:
    """Emite un evento de agente a todos los listeners registrados.

    Enriquece el evento con seq y timestamp automáticamente.
    """
    with _agent_state._lock:
        next_seq = _agent_state.seq_by_run.get(run_id, 0) + 1
        _agent_state.seq_by_run[run_id] = next_seq
        context = _agent_state.run_context_by_id.get(run_id)
        is_visible = context.is_control_ui_visible if context else True

        event_session_key = session_key.strip() if session_key and session_key.strip() else None
        resolved_session_key = (
            (event_session_key or (context.session_key if context else None))
            if is_visible
            else None
        )

        payload = EventPayload(
            run_id=run_id,
            seq=next_seq,
            stream=stream,
            ts=time.time(),
            data=data,
            session_key=resolved_session_key,
        )
        listeners = list(_agent_state.listeners)

    for listener in listeners:
        try:
            listener(payload)
        except Exception:
            logger.debug("Error en listener de evento de agente", exc_info=True)


def on_agent_event(listener: EventListener) -> Callable[[], None]:
    """Registra un listener para eventos de agente.

    Returns:
        Función para desregistrar el listener.
    """
    _agent_state.listeners.add(listener)

    def unsubscribe() -> None:
        _agent_state.listeners.discard(listener)

    return unsubscribe


def reset_agent_events() -> None:
    """Reinicia el estado del bus de eventos de agente (para tests)."""
    _agent_state.reset()


# ── API de eventos de diagnóstico ───────────────────────────

MAX_DISPATCH_DEPTH = 100


def emit_diagnostic_event(
    event_type: str,
    data: Optional[Dict[str, Any]] = None,
) -> None:
    """Emite un evento de diagnóstico a todos los listeners registrados.

    Incluye protección contra recursión infinita.
    """
    with _diagnostic_state._lock:
        if _diagnostic_state.dispatch_depth > MAX_DISPATCH_DEPTH:
            logger.error(
                "Guardia de recursión activada en diagnostic events "
                "(depth=%d, type=%s)",
                _diagnostic_state.dispatch_depth,
                event_type,
            )
            return

        _diagnostic_state.seq += 1
        event = DiagnosticEvent(
            type=event_type,
            seq=_diagnostic_state.seq,
            ts=time.time(),
            data=data or {},
        )
        _diagnostic_state.dispatch_depth += 1
        listeners = list(_diagnostic_state.listeners)

    try:
        for listener in listeners:
            try:
                listener(event)
            except Exception:
                logger.debug(
                    "Error en listener de diagnóstico (type=%s, seq=%d)",
                    event.type,
                    event.seq,
                    exc_info=True,
                )
    finally:
        with _diagnostic_state._lock:
            _diagnostic_state.dispatch_depth -= 1


def on_diagnostic_event(listener: DiagnosticListener) -> Callable[[], None]:
    """Registra un listener para eventos de diagnóstico.

    Returns:
        Función para desregistrar el listener.
    """
    _diagnostic_state.listeners.add(listener)

    def unsubscribe() -> None:
        _diagnostic_state.listeners.discard(listener)

    return unsubscribe


def reset_diagnostic_events() -> None:
    """Reinicia el estado del bus de diagnóstico (para tests)."""
    _diagnostic_state.reset()


# ── Flags de diagnóstico ────────────────────────────────────

DIAGNOSTICS_ENV = "SOMER_DIAGNOSTICS"


def parse_diagnostic_flags(raw: Optional[str] = None) -> List[str]:
    """Parsea flags de diagnóstico desde string o variable de entorno.

    Soporta: "1", "true", "all", "*" → todos activos.
    "0", "false", "off", "none" → ninguno activo.
    Separados por coma o espacio → flags individuales.
    """
    if not raw:
        return []
    trimmed = raw.strip()
    if not trimmed:
        return []

    lowered = trimmed.lower()
    if lowered in ("0", "false", "off", "none"):
        return []
    if lowered in ("1", "true", "all", "*"):
        return ["*"]

    import re
    flags = re.split(r"[,\s]+", trimmed)
    return _unique_flags(flags)


def _unique_flags(flags: List[str]) -> List[str]:
    """Retorna flags únicos normalizados."""
    seen: Set[str] = set()
    out: List[str] = []
    for flag in flags:
        normalized = flag.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def resolve_diagnostic_flags(
    config_flags: Optional[List[str]] = None,
    env_value: Optional[str] = None,
) -> List[str]:
    """Resuelve flags de diagnóstico combinando config + entorno."""
    import os
    cfg = config_flags or []
    env_raw = env_value if env_value is not None else os.environ.get(DIAGNOSTICS_ENV, "")
    env_flags = parse_diagnostic_flags(env_raw)
    return _unique_flags(cfg + env_flags)


def matches_diagnostic_flag(flag: str, enabled_flags: List[str]) -> bool:
    """Verifica si un flag coincide con los flags habilitados.

    Soporta wildcards: "*", "all", "prefix.*", "prefix*".
    """
    target = flag.strip().lower()
    if not target:
        return False

    for raw in enabled_flags:
        enabled = raw.strip().lower()
        if not enabled:
            continue
        if enabled in ("*", "all"):
            return True
        if enabled.endswith(".*"):
            prefix = enabled[:-2]
            if target == prefix or target.startswith(f"{prefix}."):
                return True
        elif enabled.endswith("*"):
            prefix = enabled[:-1]
            if target.startswith(prefix):
                return True
        elif enabled == target:
            return True

    return False
