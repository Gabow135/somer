"""Plugin lifecycle — gestión de estados del ciclo de vida de plugins.

Portado desde OpenClaw. Gestiona las transiciones de estado:
discovered → init → ready → running → stopped → error
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Coroutine, Dict, List, Optional

from plugins.types import PluginState, ResourceLimits
from shared.errors import SomerError

logger = logging.getLogger(__name__)


class PluginLifecycleError(SomerError):
    """Error en el ciclo de vida de un plugin."""


# ── Transiciones válidas ─────────────────────────────────────

VALID_TRANSITIONS: Dict[PluginState, List[PluginState]] = {
    PluginState.DISCOVERED: [
        PluginState.VALIDATING,
        PluginState.DISABLED,
        PluginState.ERROR,
    ],
    PluginState.VALIDATING: [
        PluginState.INIT,
        PluginState.ERROR,
    ],
    PluginState.INIT: [
        PluginState.READY,
        PluginState.ERROR,
    ],
    PluginState.READY: [
        PluginState.RUNNING,
        PluginState.STOPPED,
        PluginState.ERROR,
    ],
    PluginState.RUNNING: [
        PluginState.STOPPING,
        PluginState.ERROR,
    ],
    PluginState.STOPPING: [
        PluginState.STOPPED,
        PluginState.ERROR,
    ],
    PluginState.STOPPED: [
        PluginState.INIT,
        PluginState.DISABLED,
    ],
    PluginState.ERROR: [
        PluginState.INIT,
        PluginState.DISABLED,
    ],
    PluginState.DISABLED: [
        PluginState.DISCOVERED,
    ],
}


def is_valid_transition(from_state: PluginState, to_state: PluginState) -> bool:
    """Verifica si una transición de estado es válida.

    Args:
        from_state: Estado actual.
        to_state: Estado destino.

    Returns:
        True si la transición es válida.
    """
    allowed = VALID_TRANSITIONS.get(from_state, [])
    return to_state in allowed


# ── Callbacks del ciclo de vida ──────────────────────────────

LifecycleCallback = Callable[[str, PluginState, PluginState], Coroutine[Any, Any, None]]


class PluginLifecycleManager:
    """Gestor del ciclo de vida de plugins.

    Controla las transiciones de estado, emite eventos de lifecycle,
    y aplica timeouts/resource limits durante las transiciones.

    Uso::

        manager = PluginLifecycleManager()
        await manager.transition("my-plugin", PluginState.INIT)
        await manager.transition("my-plugin", PluginState.READY)
        await manager.transition("my-plugin", PluginState.RUNNING)
        state = manager.get_state("my-plugin")
    """

    def __init__(self) -> None:
        self._states: Dict[str, PluginState] = {}
        self._timestamps: Dict[str, float] = {}
        self._errors: Dict[str, str] = {}
        self._callbacks: List[LifecycleCallback] = []
        self._resource_limits: Dict[str, ResourceLimits] = {}
        self._lock = asyncio.Lock()

    def register_plugin(
        self,
        plugin_id: str,
        initial_state: PluginState = PluginState.DISCOVERED,
        resource_limits: Optional[ResourceLimits] = None,
    ) -> None:
        """Registra un plugin con su estado inicial.

        Args:
            plugin_id: ID del plugin.
            initial_state: Estado inicial.
            resource_limits: Límites de recursos opcionales.
        """
        self._states[plugin_id] = initial_state
        self._timestamps[plugin_id] = time.time()
        if resource_limits is not None:
            self._resource_limits[plugin_id] = resource_limits
        logger.debug(
            "Plugin '%s' registrado con estado %s",
            plugin_id, initial_state.value,
        )

    def unregister_plugin(self, plugin_id: str) -> None:
        """Desregistra un plugin del lifecycle manager.

        Args:
            plugin_id: ID del plugin a desregistrar.
        """
        self._states.pop(plugin_id, None)
        self._timestamps.pop(plugin_id, None)
        self._errors.pop(plugin_id, None)
        self._resource_limits.pop(plugin_id, None)

    async def transition(
        self,
        plugin_id: str,
        to_state: PluginState,
        error: Optional[str] = None,
    ) -> None:
        """Transiciona un plugin a un nuevo estado.

        Args:
            plugin_id: ID del plugin.
            to_state: Estado destino.
            error: Mensaje de error si la transición es a ERROR.

        Raises:
            PluginLifecycleError: Si la transición no es válida
                o el plugin no está registrado.
        """
        async with self._lock:
            current = self._states.get(plugin_id)
            if current is None:
                raise PluginLifecycleError(
                    f"Plugin '{plugin_id}' no está registrado en el lifecycle manager"
                )

            if not is_valid_transition(current, to_state):
                raise PluginLifecycleError(
                    f"Transición inválida para '{plugin_id}': "
                    f"{current.value} → {to_state.value}"
                )

            old_state = current
            self._states[plugin_id] = to_state
            self._timestamps[plugin_id] = time.time()

            if to_state == PluginState.ERROR and error:
                self._errors[plugin_id] = error
            elif to_state != PluginState.ERROR:
                self._errors.pop(plugin_id, None)

            logger.info(
                "Plugin '%s': %s → %s%s",
                plugin_id, old_state.value, to_state.value,
                f" (error: {error})" if error else "",
            )

        # Notificar callbacks fuera del lock
        for callback in self._callbacks:
            try:
                await callback(plugin_id, old_state, to_state)
            except Exception:
                logger.exception(
                    "Error en callback de lifecycle para '%s'", plugin_id
                )

    def get_state(self, plugin_id: str) -> Optional[PluginState]:
        """Obtiene el estado actual de un plugin.

        Args:
            plugin_id: ID del plugin.

        Returns:
            Estado actual o None si no está registrado.
        """
        return self._states.get(plugin_id)

    def get_error(self, plugin_id: str) -> Optional[str]:
        """Obtiene el último error de un plugin.

        Args:
            plugin_id: ID del plugin.

        Returns:
            Mensaje de error o None.
        """
        return self._errors.get(plugin_id)

    def get_timestamp(self, plugin_id: str) -> Optional[float]:
        """Obtiene el timestamp de la última transición.

        Args:
            plugin_id: ID del plugin.

        Returns:
            Timestamp o None.
        """
        return self._timestamps.get(plugin_id)

    def get_resource_limits(self, plugin_id: str) -> Optional[ResourceLimits]:
        """Obtiene los límites de recursos de un plugin.

        Args:
            plugin_id: ID del plugin.

        Returns:
            ResourceLimits o None.
        """
        return self._resource_limits.get(plugin_id)

    def on_transition(self, callback: LifecycleCallback) -> None:
        """Registra un callback para transiciones de estado.

        Args:
            callback: Función async(plugin_id, old_state, new_state).
        """
        self._callbacks.append(callback)

    def list_plugins(
        self,
        state: Optional[PluginState] = None,
    ) -> Dict[str, PluginState]:
        """Lista plugins y sus estados.

        Args:
            state: Filtrar por estado específico.

        Returns:
            Dict de plugin_id → estado.
        """
        if state is None:
            return dict(self._states)
        return {
            pid: s for pid, s in self._states.items()
            if s == state
        }

    def is_running(self, plugin_id: str) -> bool:
        """Verifica si un plugin está en estado RUNNING.

        Args:
            plugin_id: ID del plugin.

        Returns:
            True si está running.
        """
        return self._states.get(plugin_id) == PluginState.RUNNING

    def is_healthy(self, plugin_id: str) -> bool:
        """Verifica si un plugin está en un estado saludable.

        Args:
            plugin_id: ID del plugin.

        Returns:
            True si está en READY o RUNNING.
        """
        state = self._states.get(plugin_id)
        return state in (PluginState.READY, PluginState.RUNNING)

    async def stop_all(self) -> Dict[str, bool]:
        """Detiene todos los plugins que están running.

        Returns:
            Dict de plugin_id → éxito.
        """
        results: Dict[str, bool] = {}
        running = [
            pid for pid, s in self._states.items()
            if s == PluginState.RUNNING
        ]
        for plugin_id in running:
            try:
                await self.transition(plugin_id, PluginState.STOPPING)
                await self.transition(plugin_id, PluginState.STOPPED)
                results[plugin_id] = True
            except PluginLifecycleError as exc:
                logger.error(
                    "Error al detener plugin '%s': %s", plugin_id, exc
                )
                results[plugin_id] = False
        return results

    def get_summary(self) -> Dict[str, int]:
        """Obtiene un resumen de conteos por estado.

        Returns:
            Dict de estado → conteo.
        """
        summary: Dict[str, int] = {}
        for state in self._states.values():
            key = state.value
            summary[key] = summary.get(key, 0) + 1
        return summary
