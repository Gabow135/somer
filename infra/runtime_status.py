"""Seguimiento del estado de ejecución del sistema — SOMER.

Portado de OpenClaw: runtime-status.ts.

Rastrea uptime, versiones, salud de componentes y
métricas básicas del runtime.
"""

from __future__ import annotations

import logging
import platform
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ComponentHealth(str, Enum):
    """Estado de salud de un componente."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class ComponentStatus:
    """Estado de un componente individual."""

    name: str
    health: ComponentHealth = ComponentHealth.UNKNOWN
    message: str = ""
    last_check: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RuntimeInfo:
    """Información del runtime del sistema."""

    version: str = ""
    python_version: str = ""
    platform: str = ""
    arch: str = ""
    pid: int = 0
    start_time: float = 0.0
    uptime_seconds: float = 0.0


@dataclass
class RuntimeSnapshot:
    """Snapshot completo del estado del runtime."""

    info: RuntimeInfo
    components: Dict[str, ComponentStatus] = field(default_factory=dict)
    overall_health: ComponentHealth = ComponentHealth.UNKNOWN
    checked_at: float = 0.0


class RuntimeStatusTracker:
    """Rastreador de estado del runtime de SOMER.

    Registra componentes, verifica su salud y produce
    snapshots del estado general del sistema.
    """

    def __init__(self, version: str = "") -> None:
        self._version = version
        self._start_time = time.time()
        self._components: Dict[str, ComponentStatus] = {}

    @property
    def version(self) -> str:
        """Versión del sistema."""
        return self._version

    @property
    def uptime(self) -> float:
        """Segundos desde el inicio del sistema."""
        return time.time() - self._start_time

    def register_component(self, name: str) -> None:
        """Registra un componente para rastreo de salud."""
        if name not in self._components:
            self._components[name] = ComponentStatus(name=name)
            logger.debug("Componente registrado: %s", name)

    def update_health(
        self,
        name: str,
        health: ComponentHealth,
        message: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Actualiza el estado de salud de un componente.

        Args:
            name: Nombre del componente.
            health: Estado de salud.
            message: Mensaje descriptivo opcional.
            metadata: Metadatos adicionales.
        """
        if name not in self._components:
            self.register_component(name)

        comp = self._components[name]
        comp.health = health
        comp.message = message
        comp.last_check = time.time()
        if metadata:
            comp.metadata.update(metadata)

    def get_component(self, name: str) -> Optional[ComponentStatus]:
        """Obtiene el estado de un componente."""
        return self._components.get(name)

    @property
    def components(self) -> Dict[str, ComponentStatus]:
        """Retorna todos los componentes registrados."""
        return dict(self._components)

    def compute_overall_health(self) -> ComponentHealth:
        """Calcula la salud general del sistema.

        - Si algún componente es UNHEALTHY → UNHEALTHY
        - Si alguno es DEGRADED → DEGRADED
        - Si todos son HEALTHY → HEALTHY
        - Si no hay componentes → UNKNOWN
        """
        if not self._components:
            return ComponentHealth.UNKNOWN

        statuses = [c.health for c in self._components.values()]

        if ComponentHealth.UNHEALTHY in statuses:
            return ComponentHealth.UNHEALTHY
        if ComponentHealth.DEGRADED in statuses:
            return ComponentHealth.DEGRADED
        if all(s == ComponentHealth.HEALTHY for s in statuses):
            return ComponentHealth.HEALTHY

        return ComponentHealth.UNKNOWN

    def get_runtime_info(self) -> RuntimeInfo:
        """Obtiene información del runtime."""
        import os
        return RuntimeInfo(
            version=self._version,
            python_version=platform.python_version(),
            platform=sys.platform,
            arch=platform.machine(),
            pid=os.getpid(),
            start_time=self._start_time,
            uptime_seconds=self.uptime,
        )

    def snapshot(self) -> RuntimeSnapshot:
        """Produce un snapshot completo del estado del runtime."""
        return RuntimeSnapshot(
            info=self.get_runtime_info(),
            components=dict(self._components),
            overall_health=self.compute_overall_health(),
            checked_at=time.time(),
        )

    def summary_lines(self) -> List[str]:
        """Genera líneas de resumen para display.

        Returns:
            Lista de strings con el resumen del runtime.
        """
        info = self.get_runtime_info()
        lines = [
            f"SOMER v{info.version}",
            f"  Python {info.python_version} en {info.platform} ({info.arch})",
            f"  PID: {info.pid}",
            f"  Uptime: {_format_uptime(info.uptime_seconds)}",
            f"  Salud: {self.compute_overall_health().value}",
        ]

        if self._components:
            lines.append("  Componentes:")
            for name, comp in sorted(self._components.items()):
                status = comp.health.value
                msg = f" - {comp.message}" if comp.message else ""
                lines.append(f"    {name}: {status}{msg}")

        return lines


def _format_uptime(seconds: float) -> str:
    """Formatea segundos de uptime en formato legible."""
    if seconds < 60:
        return f"{seconds:.0f}s"

    minutes = int(seconds // 60)
    if minutes < 60:
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"

    hours = minutes // 60
    mins = minutes % 60
    if hours < 24:
        return f"{hours}h {mins}m"

    days = hours // 24
    hrs = hours % 24
    return f"{days}d {hrs}h {mins}m"


# ── Singleton global ────────────────────────────────────────

_global_tracker: Optional[RuntimeStatusTracker] = None


def get_runtime_tracker(version: str = "") -> RuntimeStatusTracker:
    """Obtiene el rastreador de runtime global."""
    global _global_tracker
    if _global_tracker is None:
        _global_tracker = RuntimeStatusTracker(version=version)
    return _global_tracker


def reset_runtime_tracker() -> None:
    """Reinicia el rastreador global (para tests)."""
    global _global_tracker
    _global_tracker = None
