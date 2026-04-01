"""Plugin runtime — carga, descarga y gestión del ciclo de vida de plugins.

Portado desde OpenClaw runtime.ts. Carga plugins desde manifiestos,
ejecuta entry points, gestiona el ciclo de vida completo, y ofrece
ejecución sandboxed con límites de recursos.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional

from plugins.lifecycle import PluginLifecycleManager
from plugins.manifest import PluginManifest, PluginManifestError
from plugins.registry import PluginRegistry
from plugins.sdk import PluginSDK
from plugins.types import PluginState, ResourceLimits
from shared.errors import SomerError

logger = logging.getLogger(__name__)


class PluginRuntimeError(SomerError):
    """Error en el runtime de plugins."""


@dataclass
class LoadedPlugin:
    """Plugin cargado en memoria."""

    manifest: PluginManifest
    sdk: PluginSDK
    module: Any = None
    enabled: bool = True
    state: PluginState = PluginState.READY
    error: Optional[str] = None


class PluginRuntime:
    """Runtime para carga y gestión de plugins.

    Carga plugins desde su manifest, ejecuta su entry point
    pasándoles un PluginSDK, y mantiene el registro de plugins activos.
    Integra con PluginRegistry y PluginLifecycleManager para
    gestión completa.

    Uso::

        runtime = PluginRuntime()
        manifest = load_manifest("/path/to/plugin/manifest.json")
        await runtime.load(manifest)
        plugins = runtime.list_plugins()
        await runtime.unload("my-plugin")
        await runtime.start("my-plugin")
        await runtime.stop_all()
    """

    def __init__(
        self,
        registry: Optional[PluginRegistry] = None,
        lifecycle: Optional[PluginLifecycleManager] = None,
    ) -> None:
        self._plugins: Dict[str, LoadedPlugin] = {}
        self._registry = registry
        self._lifecycle = lifecycle or PluginLifecycleManager()
        self._start_callbacks: Dict[str, Callable[..., Coroutine[Any, Any, None]]] = {}
        self._stop_callbacks: Dict[str, Callable[..., Coroutine[Any, Any, None]]] = {}

    @property
    def registry(self) -> Optional[PluginRegistry]:
        """Registry asociado al runtime."""
        return self._registry

    @property
    def lifecycle(self) -> PluginLifecycleManager:
        """Lifecycle manager del runtime."""
        return self._lifecycle

    async def load(
        self,
        manifest: PluginManifest,
        config: Optional[Dict[str, Any]] = None,
        resource_limits: Optional[ResourceLimits] = None,
    ) -> LoadedPlugin:
        """Carga un plugin desde su manifiesto.

        1. Registra el plugin en el lifecycle manager.
        2. Crea un PluginSDK para el plugin.
        3. Importa el entry_point como módulo Python.
        4. Llama a la función ``setup(sdk)`` del módulo si existe.
        5. Llama a ``register(sdk)`` si existe.
        6. Transiciona a READY.

        Args:
            manifest: Manifiesto del plugin.
            config: Configuración a pasar al SDK.
            resource_limits: Límites de recursos para sandboxing.

        Returns:
            LoadedPlugin con el estado del plugin cargado.
        """
        if manifest.name in self._plugins:
            raise PluginRuntimeError(
                f"Plugin '{manifest.name}' ya está cargado"
            )

        if manifest.source_path is None:
            raise PluginRuntimeError(
                f"Plugin '{manifest.name}' no tiene source_path"
            )

        # Registrar en lifecycle
        self._lifecycle.register_plugin(
            manifest.name,
            PluginState.DISCOVERED,
            resource_limits=resource_limits,
        )

        try:
            await self._lifecycle.transition(manifest.name, PluginState.VALIDATING)
            await self._lifecycle.transition(manifest.name, PluginState.INIT)
        except Exception as exc:
            raise PluginRuntimeError(
                f"Error en transición de lifecycle para '{manifest.name}': {exc}"
            ) from exc

        # Crear SDK
        sdk = PluginSDK(plugin_name=manifest.name, config=config)

        # Importar entry point
        entry_path = manifest.source_path / manifest.entry_point
        if not entry_path.exists():
            await self._lifecycle.transition(
                manifest.name, PluginState.ERROR,
                error=f"Entry point no encontrado: {entry_path}",
            )
            raise PluginRuntimeError(
                f"Entry point no encontrado: {entry_path}"
            )

        module_name = f"somer_plugin_{manifest.name.replace('-', '_')}"
        spec = importlib.util.spec_from_file_location(module_name, str(entry_path))
        if spec is None or spec.loader is None:
            await self._lifecycle.transition(
                manifest.name, PluginState.ERROR,
                error=f"No se pudo crear spec para {entry_path}",
            )
            raise PluginRuntimeError(
                f"No se pudo crear spec para {entry_path}"
            )

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module

        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            sys.modules.pop(module_name, None)
            await self._lifecycle.transition(
                manifest.name, PluginState.ERROR,
                error=f"Error al ejecutar {entry_path}: {exc}",
            )
            raise PluginRuntimeError(
                f"Error al ejecutar {entry_path}: {exc}"
            ) from exc

        # Llamar a setup() si existe
        setup_fn = getattr(module, "setup", None)
        if setup_fn is not None and callable(setup_fn):
            try:
                if asyncio.iscoroutinefunction(setup_fn):
                    await setup_fn(sdk)
                else:
                    setup_fn(sdk)
            except Exception as exc:
                sys.modules.pop(module_name, None)
                await self._lifecycle.transition(
                    manifest.name, PluginState.ERROR,
                    error=f"Error en setup() de '{manifest.name}': {exc}",
                )
                raise PluginRuntimeError(
                    f"Error en setup() de '{manifest.name}': {exc}"
                ) from exc

        # Llamar a register() si existe
        register_fn = getattr(module, "register", None)
        if register_fn is not None and callable(register_fn):
            try:
                if asyncio.iscoroutinefunction(register_fn):
                    await register_fn(sdk)
                else:
                    register_fn(sdk)
            except Exception as exc:
                sys.modules.pop(module_name, None)
                await self._lifecycle.transition(
                    manifest.name, PluginState.ERROR,
                    error=f"Error en register() de '{manifest.name}': {exc}",
                )
                raise PluginRuntimeError(
                    f"Error en register() de '{manifest.name}': {exc}"
                ) from exc

        # Almacenar callbacks de start/stop si existen
        start_fn = getattr(module, "start", None)
        if start_fn is not None and callable(start_fn):
            self._start_callbacks[manifest.name] = start_fn

        stop_fn = getattr(module, "stop", None)
        if stop_fn is not None and callable(stop_fn):
            self._stop_callbacks[manifest.name] = stop_fn

        # Transicionar a READY
        await self._lifecycle.transition(manifest.name, PluginState.READY)

        loaded = LoadedPlugin(
            manifest=manifest, sdk=sdk, module=module,
            state=PluginState.READY,
        )
        self._plugins[manifest.name] = loaded
        logger.info(
            "Plugin '%s' v%s cargado (%d skills, %d tools)",
            manifest.name, manifest.version,
            len(sdk.registered_skills), len(sdk.registered_tools),
        )
        return loaded

    async def start(self, name: str) -> bool:
        """Inicia un plugin cargado (transiciona a RUNNING).

        Llama a ``start()`` del módulo si existe.

        Args:
            name: Nombre del plugin.

        Returns:
            True si se inició exitosamente.
        """
        loaded = self._plugins.get(name)
        if loaded is None:
            logger.warning("Plugin '%s' no está cargado", name)
            return False

        start_fn = self._start_callbacks.get(name)
        if start_fn is not None:
            try:
                if asyncio.iscoroutinefunction(start_fn):
                    await start_fn(loaded.sdk)
                else:
                    start_fn(loaded.sdk)
            except Exception as exc:
                await self._lifecycle.transition(
                    name, PluginState.ERROR,
                    error=f"Error en start() de '{name}': {exc}",
                )
                loaded.state = PluginState.ERROR
                loaded.error = str(exc)
                return False

        await self._lifecycle.transition(name, PluginState.RUNNING)
        loaded.state = PluginState.RUNNING
        logger.info("Plugin '%s' iniciado", name)
        return True

    async def stop(self, name: str) -> bool:
        """Detiene un plugin que está running.

        Llama a ``stop()`` del módulo si existe.

        Args:
            name: Nombre del plugin.

        Returns:
            True si se detuvo exitosamente.
        """
        loaded = self._plugins.get(name)
        if loaded is None:
            return False

        if loaded.state != PluginState.RUNNING:
            return False

        await self._lifecycle.transition(name, PluginState.STOPPING)
        loaded.state = PluginState.STOPPING

        stop_fn = self._stop_callbacks.get(name)
        if stop_fn is not None:
            try:
                if asyncio.iscoroutinefunction(stop_fn):
                    await stop_fn(loaded.sdk)
                else:
                    stop_fn(loaded.sdk)
            except Exception:
                logger.exception("Error en stop() de '%s'", name)

        await self._lifecycle.transition(name, PluginState.STOPPED)
        loaded.state = PluginState.STOPPED
        logger.info("Plugin '%s' detenido", name)
        return True

    async def stop_all(self) -> Dict[str, bool]:
        """Detiene todos los plugins que están running.

        Returns:
            Dict de nombre → éxito.
        """
        results: Dict[str, bool] = {}
        running = [
            name for name, loaded in self._plugins.items()
            if loaded.state == PluginState.RUNNING
        ]
        for name in running:
            results[name] = await self.stop(name)
        return results

    async def unload(self, name: str) -> bool:
        """Descarga un plugin por nombre.

        Llama a ``teardown()`` del módulo si existe, luego limpia.
        """
        loaded = self._plugins.get(name)
        if loaded is None:
            logger.warning("Plugin '%s' no está cargado", name)
            return False

        # Detener si está running
        if loaded.state == PluginState.RUNNING:
            await self.stop(name)

        # Llamar a teardown() si existe
        if loaded.module is not None:
            teardown_fn = getattr(loaded.module, "teardown", None)
            if teardown_fn is not None and callable(teardown_fn):
                try:
                    if asyncio.iscoroutinefunction(teardown_fn):
                        await teardown_fn(loaded.sdk)
                    else:
                        teardown_fn(loaded.sdk)
                except Exception:
                    logger.exception("Error en teardown() de '%s'", name)

        # Limpiar módulo del registro
        module_name = f"somer_plugin_{name.replace('-', '_')}"
        sys.modules.pop(module_name, None)

        # Limpiar callbacks
        self._start_callbacks.pop(name, None)
        self._stop_callbacks.pop(name, None)

        # Desregistrar del lifecycle
        self._lifecycle.unregister_plugin(name)

        del self._plugins[name]
        logger.info("Plugin '%s' descargado", name)
        return True

    def list_plugins(self) -> List[LoadedPlugin]:
        """Lista todos los plugins cargados."""
        return list(self._plugins.values())

    def get_plugin(self, name: str) -> Optional[LoadedPlugin]:
        """Obtiene un plugin por nombre."""
        return self._plugins.get(name)

    @property
    def plugin_names(self) -> List[str]:
        """Nombres de plugins cargados."""
        return list(self._plugins.keys())

    def get_all_tools(self) -> Dict[str, Any]:
        """Recopila todas las tools registradas por todos los plugins."""
        tools: Dict[str, Any] = {}
        for loaded in self._plugins.values():
            tools.update(loaded.sdk.registered_tools)
        return tools

    def get_all_hooks(self, event: str) -> List[Any]:
        """Recopila todos los hooks para un evento de todos los plugins."""
        hooks: List[Any] = []
        for loaded in self._plugins.values():
            hooks.extend(loaded.sdk.get_hooks(event))
        return hooks

    def get_plugin_state(self, name: str) -> Optional[PluginState]:
        """Obtiene el estado de lifecycle de un plugin.

        Args:
            name: Nombre del plugin.

        Returns:
            PluginState o None.
        """
        return self._lifecycle.get_state(name)

    def is_running(self, name: str) -> bool:
        """Verifica si un plugin está running.

        Args:
            name: Nombre del plugin.

        Returns:
            True si está running.
        """
        loaded = self._plugins.get(name)
        return loaded is not None and loaded.state == PluginState.RUNNING

    def get_summary(self) -> Dict[str, Any]:
        """Obtiene un resumen del runtime.

        Returns:
            Dict con conteos y estadísticas.
        """
        states: Dict[str, int] = {}
        for loaded in self._plugins.values():
            key = loaded.state.value
            states[key] = states.get(key, 0) + 1

        return {
            "total_plugins": len(self._plugins),
            "states": states,
            "total_tools": sum(
                len(loaded.sdk.registered_tools)
                for loaded in self._plugins.values()
            ),
            "total_hooks": sum(
                sum(len(v) for v in loaded.sdk.registered_hooks.values())
                for loaded in self._plugins.values()
            ),
        }
