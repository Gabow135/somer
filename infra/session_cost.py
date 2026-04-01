"""Seguimiento de costos y uso de sesiones — SOMER.

Portado de OpenClaw: session-cost-usage.ts, provider-usage.ts.

Rastrea el uso de tokens y costo estimado por sesión,
proveedor y ventana de tiempo.
"""

from __future__ import annotations

import logging
import time
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TokenUsage:
    """Uso de tokens de una llamada o acumulado."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    total_tokens: int = 0

    def add(self, other: TokenUsage) -> None:
        """Suma otro TokenUsage a este."""
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.cache_write_tokens += other.cache_write_tokens
        self.total_tokens += other.total_tokens


@dataclass
class SessionCostEntry:
    """Entrada de costo por sesión."""

    session_id: str
    session_key: Optional[str] = None
    provider: str = ""
    model: str = ""
    usage: TokenUsage = field(default_factory=TokenUsage)
    cost_usd: float = 0.0
    call_count: int = 0
    first_call_at: float = 0.0
    last_call_at: float = 0.0
    duration_ms_total: float = 0.0


@dataclass
class UsageWindow:
    """Ventana de uso de un proveedor."""

    label: str
    used_percent: float = 0.0
    reset_at: Optional[float] = None  # Timestamp de reinicio


@dataclass
class ProviderUsageSnapshot:
    """Snapshot de uso de un proveedor."""

    provider: str
    display_name: str
    windows: List[UsageWindow] = field(default_factory=list)
    plan: Optional[str] = None
    error: Optional[str] = None


@dataclass
class UsageSummary:
    """Resumen de uso de todos los proveedores."""

    updated_at: float = 0.0
    providers: List[ProviderUsageSnapshot] = field(default_factory=list)


class SessionCostTracker:
    """Rastreador de costos por sesión.

    Acumula uso de tokens y costo estimado por sesión,
    permitiendo consultar totales y generar reportes.
    """

    def __init__(self) -> None:
        self._entries: Dict[str, SessionCostEntry] = {}
        self._lock = threading.Lock()

    def record_usage(
        self,
        session_id: str,
        provider: str,
        model: str,
        usage: TokenUsage,
        cost_usd: float = 0.0,
        duration_ms: float = 0.0,
        session_key: Optional[str] = None,
    ) -> None:
        """Registra uso de tokens para una sesión.

        Args:
            session_id: ID de la sesión.
            provider: Proveedor usado.
            model: Modelo usado.
            usage: Uso de tokens de esta llamada.
            cost_usd: Costo estimado en USD.
            duration_ms: Duración de la llamada en ms.
            session_key: Session key opcional.
        """
        now = time.time()
        with self._lock:
            entry = self._entries.get(session_id)
            if entry is None:
                entry = SessionCostEntry(
                    session_id=session_id,
                    session_key=session_key,
                    provider=provider,
                    model=model,
                    first_call_at=now,
                )
                self._entries[session_id] = entry

            entry.usage.add(usage)
            entry.cost_usd += cost_usd
            entry.call_count += 1
            entry.last_call_at = now
            entry.duration_ms_total += duration_ms
            entry.provider = provider
            entry.model = model
            if session_key:
                entry.session_key = session_key

    def get_session_cost(self, session_id: str) -> Optional[SessionCostEntry]:
        """Obtiene el costo acumulado de una sesión.

        Args:
            session_id: ID de la sesión.

        Returns:
            Entrada de costo o None si no existe.
        """
        return self._entries.get(session_id)

    def get_all_sessions(self) -> Dict[str, SessionCostEntry]:
        """Retorna todas las sesiones con su costo."""
        return dict(self._entries)

    @property
    def total_cost_usd(self) -> float:
        """Costo total acumulado de todas las sesiones."""
        return sum(e.cost_usd for e in self._entries.values())

    @property
    def total_tokens(self) -> int:
        """Total de tokens usados en todas las sesiones."""
        return sum(e.usage.total_tokens for e in self._entries.values())

    def summary_lines(self) -> List[str]:
        """Genera líneas de resumen de costos.

        Returns:
            Lista de strings con el resumen.
        """
        if not self._entries:
            return ["Sin uso registrado."]

        lines = [f"Sesiones: {len(self._entries)}"]
        lines.append(f"Costo total: ${self.total_cost_usd:.4f} USD")
        lines.append(f"Tokens totales: {self.total_tokens:,}")

        # Top 5 sesiones por costo
        sorted_entries = sorted(
            self._entries.values(),
            key=lambda e: e.cost_usd,
            reverse=True,
        )[:5]

        if sorted_entries:
            lines.append("Top sesiones por costo:")
            for entry in sorted_entries:
                key_label = entry.session_key or entry.session_id[:12]
                lines.append(
                    f"  {key_label}: ${entry.cost_usd:.4f} "
                    f"({entry.usage.total_tokens:,} tokens, "
                    f"{entry.call_count} llamadas)"
                )

        return lines

    def reset(self) -> None:
        """Reinicia todos los registros (para tests)."""
        with self._lock:
            self._entries.clear()


# ── Utilidades de formato de uso ────────────────────────────


def clamp_percent(value: float) -> float:
    """Limita un valor entre 0 y 100."""
    if not isinstance(value, (int, float)) or value != value:  # NaN check
        return 0.0
    return max(0.0, min(100.0, value))


def format_reset_remaining(
    target_ms: Optional[float] = None,
    now: Optional[float] = None,
) -> Optional[str]:
    """Formatea el tiempo restante hasta un reset.

    Args:
        target_ms: Timestamp del reset en milisegundos.
        now: Timestamp actual (default: time.time() * 1000).

    Returns:
        String formateado o None.
    """
    if target_ms is None:
        return None

    base = now if now is not None else time.time() * 1000
    diff_ms = target_ms - base

    if diff_ms <= 0:
        return "ahora"

    diff_mins = int(diff_ms / 60000)
    if diff_mins < 60:
        return f"{diff_mins}m"

    hours = diff_mins // 60
    mins = diff_mins % 60
    if hours < 24:
        return f"{hours}h {mins}m" if mins > 0 else f"{hours}h"

    days = hours // 24
    if days < 7:
        return f"{days}d {hours % 24}h"

    from datetime import datetime
    dt = datetime.fromtimestamp(target_ms / 1000)
    return dt.strftime("%b %d")


def format_usage_report(summary: UsageSummary) -> List[str]:
    """Formatea un reporte de uso de proveedores.

    Args:
        summary: Resumen de uso.

    Returns:
        Lista de líneas del reporte.
    """
    if not summary.providers:
        return ["Uso: no hay datos de uso disponibles."]

    lines = ["Uso:"]
    for entry in summary.providers:
        plan_suffix = f" ({entry.plan})" if entry.plan else ""
        if entry.error:
            lines.append(f"  {entry.display_name}{plan_suffix}: {entry.error}")
            continue
        if not entry.windows:
            lines.append(f"  {entry.display_name}{plan_suffix}: sin datos")
            continue
        lines.append(f"  {entry.display_name}{plan_suffix}")
        for window in entry.windows:
            remaining = clamp_percent(100 - window.used_percent)
            reset = format_reset_remaining(
                window.reset_at * 1000 if window.reset_at else None
            )
            reset_suffix = f" - reinicia {reset}" if reset else ""
            lines.append(
                f"    {window.label}: {remaining:.0f}% disponible{reset_suffix}"
            )

    return lines


def estimate_cost(
    input_tokens: int,
    output_tokens: int,
    cost_per_input: float,
    cost_per_output: float,
) -> float:
    """Estima el costo de una llamada LLM.

    Args:
        input_tokens: Tokens de entrada.
        output_tokens: Tokens de salida.
        cost_per_input: Costo por token de entrada.
        cost_per_output: Costo por token de salida.

    Returns:
        Costo estimado en USD.
    """
    return (input_tokens * cost_per_input) + (output_tokens * cost_per_output)


def estimate_cost_from_model(
    input_tokens: int,
    output_tokens: int,
    model_cost: Any,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """Estima el costo de una llamada LLM usando ModelCostConfig completo.

    Los costos en ModelCostConfig están en USD por millón de tokens.
    Esta función convierte automáticamente a costo real.

    Args:
        input_tokens: Tokens de entrada (sin cache).
        output_tokens: Tokens de salida.
        model_cost: ModelCostConfig con campos input, output, cache_read, cache_write.
        cache_read_tokens: Tokens leídos de cache.
        cache_write_tokens: Tokens escritos a cache.

    Returns:
        Costo estimado en USD.
    """
    per_million = 1_000_000.0
    cost_input = getattr(model_cost, "input", 0.0) or 0.0
    cost_output = getattr(model_cost, "output", 0.0) or 0.0
    cost_cache_read = getattr(model_cost, "cache_read", 0.0) or 0.0
    cost_cache_write = getattr(model_cost, "cache_write", 0.0) or 0.0

    return (
        (input_tokens * cost_input / per_million)
        + (output_tokens * cost_output / per_million)
        + (cache_read_tokens * cost_cache_read / per_million)
        + (cache_write_tokens * cost_cache_write / per_million)
    )


# ── Singleton global ────────────────────────────────────────

_global_tracker: Optional[SessionCostTracker] = None


def get_cost_tracker() -> SessionCostTracker:
    """Obtiene el rastreador de costos global."""
    global _global_tracker
    if _global_tracker is None:
        _global_tracker = SessionCostTracker()
    return _global_tracker


def reset_cost_tracker() -> None:
    """Reinicia el rastreador global (para tests)."""
    global _global_tracker
    _global_tracker = None
