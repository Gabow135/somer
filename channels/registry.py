"""Registry de channel plugins — portado de OpenClaw registry + suites.

Gestiona el registro, descubrimiento, ciclo de vida, monitoreo de salud
y agrupación (suites) de todos los plugins de canal.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import (
    Any,
    Callable,
    Coroutine,
    Dict,
    FrozenSet,
    List,
    Optional,
    Set,
    Tuple,
)

from channels.plugin import (
    ChannelHealthStatus,
    ChannelPlugin,
    ConnectionState,
)
from shared.types import ChannelType

logger = logging.getLogger(__name__)

# ── Tipos auxiliares ──────────────────────────────────────────

LifecycleCallback = Callable[[ChannelPlugin], Coroutine[Any, Any, None]]


# ── Aliases / normalización (portado de OpenClaw CHAT_CHANNEL_ALIASES) ──

CHANNEL_ALIASES: Dict[str, str] = {
    "tg": "telegram",
    "tgram": "telegram",
    "dc": "discord",
    "wa": "whatsapp",
    "wapp": "whatsapp",
    "sig": "signal",
    "gchat": "googlechat",
    "google-chat": "googlechat",
    "teams": "msteams",
    "ms-teams": "msteams",
    "microsoft-teams": "msteams",
    "internet-relay-chat": "irc",
    "mm": "mattermost",
    "web": "webchat",
}


def normalize_channel_id(raw: Optional[str]) -> Optional[str]:
    """Normaliza un identificador de canal a su forma canónica.

    Resuelve aliases (ej. 'tg' → 'telegram', 'wa' → 'whatsapp')
    y verifica que sea un ChannelType válido o un plugin registrado.

    Args:
        raw: Identificador crudo del canal.

    Returns:
        Identificador normalizado o None si no es válido.
    """
    if not raw:
        return None
    normalized = raw.strip().lower()
    if not normalized:
        return None

    # Resolver alias
    resolved = CHANNEL_ALIASES.get(normalized, normalized)

    # Verificar si es un ChannelType válido
    try:
        ChannelType(resolved)
        return resolved
    except ValueError:
        pass

    # Podría ser un plugin externo no enumerado
    return resolved


# ── Channel Suite (agrupación de canales) ─────────────────────


class ChannelSuite:
    """Agrupación lógica de canales — portado de OpenClaw suites.

    Permite agrupar canales para operaciones en lote: iniciar/detener
    un subconjunto de canales, monitoreo conjunto, etc.

    Ejemplo: una suite "production" con Telegram + Discord,
    una suite "dev" con CLI + Webchat.
    """

    def __init__(
        self,
        suite_id: str,
        name: str,
        description: str = "",
        channel_ids: Optional[List[str]] = None,
    ) -> None:
        self.id = suite_id
        self.name = name
        self.description = description
        self._channel_ids: Set[str] = set(channel_ids or [])

    def add(self, channel_id: str) -> None:
        """Agrega un canal a la suite."""
        self._channel_ids.add(channel_id)

    def remove(self, channel_id: str) -> None:
        """Remueve un canal de la suite."""
        self._channel_ids.discard(channel_id)

    def contains(self, channel_id: str) -> bool:
        """Verifica si un canal pertenece a la suite."""
        return channel_id in self._channel_ids

    @property
    def channel_ids(self) -> FrozenSet[str]:
        """IDs de canales en la suite (inmutable)."""
        return frozenset(self._channel_ids)

    @property
    def size(self) -> int:
        return len(self._channel_ids)

    def __repr__(self) -> str:
        return (
            f"<ChannelSuite id={self.id!r} name={self.name!r} "
            f"channels={sorted(self._channel_ids)}>"
        )


# ── Health Monitor ────────────────────────────────────────────


class HealthMonitor:
    """Monitor de salud de canales con health-checks periódicos.

    Inspirado en el heartbeat/status system de OpenClaw. Ejecuta
    health checks periódicos y notifica cambios de estado.
    """

    def __init__(
        self,
        registry: ChannelRegistry,
        interval_seconds: float = 30.0,
    ) -> None:
        self._registry = registry
        self._interval = interval_seconds
        self._task: Optional[asyncio.Task[None]] = None
        self._last_results: Dict[str, ChannelHealthStatus] = {}
        self._on_unhealthy: Optional[
            Callable[[str, ChannelHealthStatus], Coroutine[Any, Any, None]]
        ] = None
        self._on_recovered: Optional[
            Callable[[str, ChannelHealthStatus], Coroutine[Any, Any, None]]
        ] = None

    def on_unhealthy(
        self,
        callback: Callable[[str, ChannelHealthStatus], Coroutine[Any, Any, None]],
    ) -> None:
        """Registra callback para cuando un canal se pone no-saludable."""
        self._on_unhealthy = callback

    def on_recovered(
        self,
        callback: Callable[[str, ChannelHealthStatus], Coroutine[Any, Any, None]],
    ) -> None:
        """Registra callback para cuando un canal se recupera."""
        self._on_recovered = callback

    async def start(self) -> None:
        """Inicia el monitor de salud periódico."""
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop(), name="channel-health-monitor")
        logger.info("Health monitor iniciado (intervalo: %.1fs)", self._interval)

    async def stop(self) -> None:
        """Detiene el monitor de salud."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("Health monitor detenido")

    async def check_all(self) -> Dict[str, ChannelHealthStatus]:
        """Ejecuta health check en todos los plugins registrados.

        Returns:
            Diccionario plugin_id → ChannelHealthStatus.
        """
        results: Dict[str, ChannelHealthStatus] = {}
        for plugin in self._registry.list_plugins():
            try:
                is_healthy = await plugin.health_check()
                status = plugin.health_status()
            except Exception as exc:
                status = ChannelHealthStatus(
                    connected=False,
                    running=plugin.is_running,
                    last_error=str(exc),
                    connection_state=ConnectionState.ERROR,
                )
                is_healthy = False

            results[plugin.id] = status

            # Detectar cambios de estado
            prev = self._last_results.get(plugin.id)
            if prev is not None:
                was_healthy = prev.connected and prev.running
                if was_healthy and not is_healthy and self._on_unhealthy:
                    try:
                        await self._on_unhealthy(plugin.id, status)
                    except Exception:
                        logger.exception(
                            "Error en callback on_unhealthy para %s", plugin.id
                        )
                elif not was_healthy and is_healthy and self._on_recovered:
                    try:
                        await self._on_recovered(plugin.id, status)
                    except Exception:
                        logger.exception(
                            "Error en callback on_recovered para %s", plugin.id
                        )

        self._last_results = results
        return results

    async def check_one(self, plugin_id: str) -> Optional[ChannelHealthStatus]:
        """Ejecuta health check en un solo plugin.

        Args:
            plugin_id: ID del plugin a verificar.

        Returns:
            ChannelHealthStatus o None si el plugin no existe.
        """
        plugin = self._registry.get(plugin_id)
        if not plugin:
            return None
        try:
            await plugin.health_check()
            return plugin.health_status()
        except Exception as exc:
            return ChannelHealthStatus(
                connected=False,
                running=plugin.is_running,
                last_error=str(exc),
                connection_state=ConnectionState.ERROR,
            )

    async def _loop(self) -> None:
        """Loop principal del monitor."""
        while True:
            try:
                await asyncio.sleep(self._interval)
                await self.check_all()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error en health check loop")


# ── Channel Registry ──────────────────────────────────────────


class ChannelRegistry:
    """Registro central de plugins de canal — portado de OpenClaw registry.

    Funcionalidades (inspiradas en OpenClaw):
      - Registro/desregistro de plugins con metadata
      - Búsqueda por tipo, ID, alias o capabilities
      - Gestión del ciclo de vida (start/stop/restart individual o global)
      - Tracking de canales en ejecución vs detenidos
      - Gestión de suites (agrupaciones de canales)
      - Monitor de salud integrado
      - Callbacks de ciclo de vida (on_start, on_stop, on_error)
    """

    def __init__(self) -> None:
        self._plugins: Dict[str, ChannelPlugin] = {}
        self._suites: Dict[str, ChannelSuite] = {}

        # Callbacks de ciclo de vida
        self._on_start_callbacks: List[LifecycleCallback] = []
        self._on_stop_callbacks: List[LifecycleCallback] = []
        self._on_error_callbacks: List[
            Callable[[ChannelPlugin, Exception], Coroutine[Any, Any, None]]
        ] = []

        # Timestamps de actividad
        self._registered_at: Dict[str, float] = {}
        self._started_at: Dict[str, float] = {}
        self._stopped_at: Dict[str, float] = {}

    # ── Registro ──────────────────────────────────────────────

    def register(self, plugin: ChannelPlugin) -> None:
        """Registra un plugin de canal.

        Si ya existe un plugin con el mismo ID, se reemplaza.

        Args:
            plugin: Instancia del plugin a registrar.
        """
        if plugin.id in self._plugins:
            logger.warning(
                "Canal %s ya registrado, reemplazando", plugin.id
            )
        self._plugins[plugin.id] = plugin
        self._registered_at[plugin.id] = time.time()
        logger.debug("Canal registrado: %s (%s)", plugin.id, plugin.meta.name)

    def unregister(self, plugin_id: str) -> Optional[ChannelPlugin]:
        """Desregistra un plugin de canal.

        Si el plugin estaba corriendo, NO lo detiene — el caller
        debe llamar stop() primero.

        Args:
            plugin_id: ID del plugin a desregistrar.

        Returns:
            El plugin removido o None si no existía.
        """
        plugin = self._plugins.pop(plugin_id, None)
        if plugin:
            self._registered_at.pop(plugin_id, None)
            self._started_at.pop(plugin_id, None)
            self._stopped_at.pop(plugin_id, None)
            # Remover de todas las suites
            for suite in self._suites.values():
                suite.remove(plugin_id)
            logger.debug("Canal desregistrado: %s", plugin_id)
        return plugin

    # ── Búsqueda ──────────────────────────────────────────────

    def get(self, plugin_id: str) -> Optional[ChannelPlugin]:
        """Obtiene un plugin por su ID exacto.

        Args:
            plugin_id: ID del plugin.

        Returns:
            El plugin o None si no existe.
        """
        return self._plugins.get(plugin_id)

    def get_by_alias(self, alias: str) -> Optional[ChannelPlugin]:
        """Obtiene un plugin por alias o ID normalizado.

        Args:
            alias: Alias o ID crudo del canal.

        Returns:
            El plugin o None si no se puede resolver.
        """
        normalized = normalize_channel_id(alias)
        if not normalized:
            return None
        # Buscar por ID directo
        plugin = self._plugins.get(normalized)
        if plugin:
            return plugin
        # Buscar en aliases declarados por los plugins
        for p in self._plugins.values():
            if normalized in p.aliases:
                return p
        return None

    def get_by_type(self, channel_type: ChannelType) -> Optional[ChannelPlugin]:
        """Obtiene el primer plugin que coincida con un ChannelType.

        Args:
            channel_type: Tipo de canal a buscar.

        Returns:
            El primer plugin que matchea o None.
        """
        for plugin in self._plugins.values():
            if plugin.channel_type == channel_type:
                return plugin
            if plugin.id == channel_type.value:
                return plugin
        return None

    def find_by_capability(self, capability: str) -> List[ChannelPlugin]:
        """Busca plugins que soporten una capability específica.

        Args:
            capability: Nombre de la capability (ej. 'supports_threads',
                        'supports_media', 'supports_reactions').

        Returns:
            Lista de plugins que soportan la capability.
        """
        result: List[ChannelPlugin] = []
        for plugin in self._plugins.values():
            if hasattr(plugin.capabilities, capability):
                if getattr(plugin.capabilities, capability, False):
                    result.append(plugin)
        return result

    # ── Listados ──────────────────────────────────────────────

    def list_plugins(self) -> List[ChannelPlugin]:
        """Lista todos los plugins registrados."""
        return list(self._plugins.values())

    def list_running(self) -> List[ChannelPlugin]:
        """Lista plugins en ejecución."""
        return [p for p in self._plugins.values() if p.is_running]

    def list_stopped(self) -> List[ChannelPlugin]:
        """Lista plugins detenidos."""
        return [p for p in self._plugins.values() if not p.is_running]

    def list_connected(self) -> List[ChannelPlugin]:
        """Lista plugins conectados."""
        return [
            p for p in self._plugins.values()
            if p.connection_state == ConnectionState.CONNECTED
        ]

    def list_errored(self) -> List[ChannelPlugin]:
        """Lista plugins en estado de error."""
        return [
            p for p in self._plugins.values()
            if p.connection_state == ConnectionState.ERROR
        ]

    def list_ids(self) -> List[str]:
        """Lista los IDs de todos los plugins registrados."""
        return list(self._plugins.keys())

    @property
    def plugin_count(self) -> int:
        """Número total de plugins registrados."""
        return len(self._plugins)

    @property
    def running_count(self) -> int:
        """Número de plugins en ejecución."""
        return sum(1 for p in self._plugins.values() if p.is_running)

    # ── Ciclo de vida global ──────────────────────────────────

    async def start_all(self) -> int:
        """Inicia todos los plugins registrados.

        Returns:
            Número de plugins iniciados exitosamente.
        """
        started = 0
        for plugin in self._plugins.values():
            try:
                await plugin.start()
                self._started_at[plugin.id] = time.time()
                started += 1
                await self._fire_on_start(plugin)
            except Exception as exc:
                logger.exception("Error iniciando canal %s", plugin.id)
                await self._fire_on_error(plugin, exc)
        return started

    async def stop_all(self) -> int:
        """Detiene todos los plugins en ejecución.

        Returns:
            Número de plugins detenidos exitosamente.
        """
        stopped = 0
        for plugin in self._plugins.values():
            if not plugin.is_running:
                continue
            try:
                await plugin.stop()
                self._stopped_at[plugin.id] = time.time()
                stopped += 1
                await self._fire_on_stop(plugin)
            except Exception as exc:
                logger.exception("Error deteniendo canal %s", plugin.id)
                await self._fire_on_error(plugin, exc)
        return stopped

    async def restart_all(self) -> int:
        """Reinicia todos los plugins en ejecución.

        Returns:
            Número de plugins reiniciados exitosamente.
        """
        restarted = 0
        for plugin in list(self._plugins.values()):
            if not plugin.is_running:
                continue
            try:
                await plugin.restart()
                self._started_at[plugin.id] = time.time()
                restarted += 1
            except Exception as exc:
                logger.exception("Error reiniciando canal %s", plugin.id)
                await self._fire_on_error(plugin, exc)
        return restarted

    # ── Ciclo de vida individual ──────────────────────────────

    async def start_plugin(self, plugin_id: str) -> bool:
        """Inicia un plugin específico.

        Args:
            plugin_id: ID del plugin a iniciar.

        Returns:
            True si se inició exitosamente.
        """
        plugin = self._plugins.get(plugin_id)
        if not plugin:
            logger.warning("Canal %s no encontrado para iniciar", plugin_id)
            return False
        try:
            await plugin.start()
            self._started_at[plugin_id] = time.time()
            await self._fire_on_start(plugin)
            return True
        except Exception as exc:
            logger.exception("Error iniciando canal %s", plugin_id)
            await self._fire_on_error(plugin, exc)
            return False

    async def stop_plugin(self, plugin_id: str) -> bool:
        """Detiene un plugin específico.

        Args:
            plugin_id: ID del plugin a detener.

        Returns:
            True si se detuvo exitosamente.
        """
        plugin = self._plugins.get(plugin_id)
        if not plugin:
            logger.warning("Canal %s no encontrado para detener", plugin_id)
            return False
        try:
            await plugin.stop()
            self._stopped_at[plugin_id] = time.time()
            await self._fire_on_stop(plugin)
            return True
        except Exception as exc:
            logger.exception("Error deteniendo canal %s", plugin_id)
            await self._fire_on_error(plugin, exc)
            return False

    async def restart_plugin(self, plugin_id: str) -> bool:
        """Reinicia un plugin específico (stop + start).

        Args:
            plugin_id: ID del plugin a reiniciar.

        Returns:
            True si se reinició exitosamente.
        """
        plugin = self._plugins.get(plugin_id)
        if not plugin:
            logger.warning("Canal %s no encontrado para reiniciar", plugin_id)
            return False
        try:
            await plugin.restart()
            self._started_at[plugin_id] = time.time()
            return True
        except Exception as exc:
            logger.exception("Error reiniciando canal %s", plugin_id)
            await self._fire_on_error(plugin, exc)
            return False

    # ── Suites (agrupación) ───────────────────────────────────

    def create_suite(
        self,
        suite_id: str,
        name: str,
        description: str = "",
        channel_ids: Optional[List[str]] = None,
    ) -> ChannelSuite:
        """Crea una nueva suite de canales.

        Args:
            suite_id: Identificador único de la suite.
            name: Nombre descriptivo.
            description: Descripción de la suite.
            channel_ids: IDs iniciales de canales para la suite.

        Returns:
            La suite creada.
        """
        suite = ChannelSuite(suite_id, name, description, channel_ids)
        self._suites[suite_id] = suite
        logger.debug("Suite creada: %s (%s)", suite_id, name)
        return suite

    def get_suite(self, suite_id: str) -> Optional[ChannelSuite]:
        """Obtiene una suite por su ID."""
        return self._suites.get(suite_id)

    def delete_suite(self, suite_id: str) -> bool:
        """Elimina una suite.

        Returns:
            True si la suite existía y fue eliminada.
        """
        return self._suites.pop(suite_id, None) is not None

    def list_suites(self) -> List[ChannelSuite]:
        """Lista todas las suites."""
        return list(self._suites.values())

    def get_suite_plugins(self, suite_id: str) -> List[ChannelPlugin]:
        """Obtiene los plugins que pertenecen a una suite.

        Args:
            suite_id: ID de la suite.

        Returns:
            Lista de plugins en la suite (solo los que están registrados).
        """
        suite = self._suites.get(suite_id)
        if not suite:
            return []
        return [
            self._plugins[cid]
            for cid in suite.channel_ids
            if cid in self._plugins
        ]

    async def start_suite(self, suite_id: str) -> int:
        """Inicia todos los plugins de una suite.

        Returns:
            Número de plugins iniciados.
        """
        plugins = self.get_suite_plugins(suite_id)
        started = 0
        for plugin in plugins:
            try:
                await plugin.start()
                self._started_at[plugin.id] = time.time()
                started += 1
                await self._fire_on_start(plugin)
            except Exception as exc:
                logger.exception(
                    "Error iniciando canal %s (suite %s)", plugin.id, suite_id
                )
                await self._fire_on_error(plugin, exc)
        return started

    async def stop_suite(self, suite_id: str) -> int:
        """Detiene todos los plugins de una suite.

        Returns:
            Número de plugins detenidos.
        """
        plugins = self.get_suite_plugins(suite_id)
        stopped = 0
        for plugin in plugins:
            if not plugin.is_running:
                continue
            try:
                await plugin.stop()
                self._stopped_at[plugin.id] = time.time()
                stopped += 1
                await self._fire_on_stop(plugin)
            except Exception as exc:
                logger.exception(
                    "Error deteniendo canal %s (suite %s)", plugin.id, suite_id
                )
                await self._fire_on_error(plugin, exc)
        return stopped

    # ── Health monitoring ─────────────────────────────────────

    def create_health_monitor(
        self,
        interval_seconds: float = 30.0,
    ) -> HealthMonitor:
        """Crea un monitor de salud asociado a este registry.

        Args:
            interval_seconds: Intervalo entre health checks.

        Returns:
            Instancia de HealthMonitor.
        """
        return HealthMonitor(self, interval_seconds)

    async def get_health_summary(self) -> Dict[str, Any]:
        """Obtiene un resumen de salud de todos los canales.

        Returns:
            Diccionario con resumen de salud global y por canal.
        """
        statuses: Dict[str, Dict[str, Any]] = {}
        for plugin in self._plugins.values():
            status = plugin.health_status()
            statuses[plugin.id] = {
                "running": status.running,
                "connected": status.connected,
                "connection_state": status.connection_state.value,
                "last_error": status.last_error,
                "last_connected_at": status.last_connected_at,
                "last_message_at": status.last_message_at,
                "reconnect_attempts": status.reconnect_attempts,
            }

        total = len(self._plugins)
        running = sum(1 for s in statuses.values() if s["running"])
        connected = sum(1 for s in statuses.values() if s["connected"])
        errored = sum(
            1 for s in statuses.values()
            if s["connection_state"] == ConnectionState.ERROR.value
        )

        return {
            "total": total,
            "running": running,
            "connected": connected,
            "errored": errored,
            "channels": statuses,
        }

    # ── Lifecycle callbacks ───────────────────────────────────

    def on_start(self, callback: LifecycleCallback) -> None:
        """Registra callback ejecutado después de iniciar un plugin."""
        self._on_start_callbacks.append(callback)

    def on_stop(self, callback: LifecycleCallback) -> None:
        """Registra callback ejecutado después de detener un plugin."""
        self._on_stop_callbacks.append(callback)

    def on_error(
        self,
        callback: Callable[
            [ChannelPlugin, Exception], Coroutine[Any, Any, None]
        ],
    ) -> None:
        """Registra callback ejecutado cuando un plugin falla."""
        self._on_error_callbacks.append(callback)

    async def _fire_on_start(self, plugin: ChannelPlugin) -> None:
        for cb in self._on_start_callbacks:
            try:
                await cb(plugin)
            except Exception:
                logger.exception("Error en on_start callback para %s", plugin.id)

    async def _fire_on_stop(self, plugin: ChannelPlugin) -> None:
        for cb in self._on_stop_callbacks:
            try:
                await cb(plugin)
            except Exception:
                logger.exception("Error en on_stop callback para %s", plugin.id)

    async def _fire_on_error(
        self,
        plugin: ChannelPlugin,
        exc: Exception,
    ) -> None:
        for cb in self._on_error_callbacks:
            try:
                await cb(plugin, exc)
            except Exception:
                logger.exception(
                    "Error en on_error callback para %s", plugin.id
                )

    # ── Información / debug ───────────────────────────────────

    def describe(self) -> Dict[str, Any]:
        """Retorna descripción completa del registry para debug/CLI.

        Returns:
            Diccionario con toda la información del registry.
        """
        plugins_info = []
        for pid, plugin in self._plugins.items():
            plugins_info.append({
                "id": pid,
                "name": plugin.meta.name,
                "running": plugin.is_running,
                "connection_state": plugin.connection_state.value,
                "channel_type": (
                    plugin.channel_type.value if plugin.channel_type else None
                ),
                "delivery_mode": plugin.delivery_mode.value,
                "registered_at": self._registered_at.get(pid),
                "started_at": self._started_at.get(pid),
                "stopped_at": self._stopped_at.get(pid),
                "capabilities": {
                    "threads": plugin.capabilities.supports_threads,
                    "reactions": plugin.capabilities.supports_reactions,
                    "media": plugin.capabilities.supports_media,
                    "editing": plugin.capabilities.supports_editing,
                    "deletion": plugin.capabilities.supports_deletion,
                    "max_msg_len": plugin.capabilities.max_message_length,
                },
            })

        suites_info = []
        for suite in self._suites.values():
            suites_info.append({
                "id": suite.id,
                "name": suite.name,
                "description": suite.description,
                "channel_ids": sorted(suite.channel_ids),
            })

        return {
            "total_plugins": len(self._plugins),
            "running": self.running_count,
            "plugins": plugins_info,
            "suites": suites_info,
        }

    def __repr__(self) -> str:
        return (
            f"<ChannelRegistry plugins={self.plugin_count} "
            f"running={self.running_count} "
            f"suites={len(self._suites)}>"
        )
