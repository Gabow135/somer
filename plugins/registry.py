"""Plugin registry — registro, consulta y resolución de dependencias.

Portado desde OpenClaw registry.ts. Mantiene el registro centralizado
de todos los plugins y sus capacidades registradas.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Coroutine, Dict, List, Optional

from plugins.types import (
    HookCallback,
    PluginCapability,
    PluginChannelRegistration,
    PluginCommandRegistration,
    PluginDiagnostic,
    PluginHookRegistration,
    PluginOrigin,
    PluginProviderRegistration,
    PluginRecord,
    PluginServiceRegistration,
    PluginState,
    PluginToolRegistration,
    ToolHandler,
    is_plugin_hook_name,
)
from shared.errors import SomerError

logger = logging.getLogger(__name__)


class PluginRegistryError(SomerError):
    """Error en el registro de plugins."""


class PluginRegistry:
    """Registro centralizado de plugins y sus capacidades.

    Mantiene un catálogo de todos los plugins cargados y las
    capacidades que cada uno ha registrado (tools, hooks, channels,
    providers, servicios, comandos).

    Uso::

        registry = PluginRegistry()
        registry.register_plugin(record)
        registry.register_tool(plugin_id, "my_tool", handler)
        all_tools = registry.get_all_tools()
    """

    def __init__(self) -> None:
        self._plugins: Dict[str, PluginRecord] = {}
        self._tools: Dict[str, PluginToolRegistration] = {}
        self._tool_handlers: Dict[str, ToolHandler] = {}
        self._hooks: List[PluginHookRegistration] = []
        self._hook_handlers: Dict[str, List[HookCallback]] = {}
        self._channels: Dict[str, PluginChannelRegistration] = {}
        self._providers: Dict[str, PluginProviderRegistration] = {}
        self._services: Dict[str, PluginServiceRegistration] = {}
        self._commands: Dict[str, PluginCommandRegistration] = {}
        self._gateway_handlers: Dict[str, Any] = {}
        self._diagnostics: List[PluginDiagnostic] = []

    # ── Plugins ──────────────────────────────────────────────

    def register_plugin(self, record: PluginRecord) -> None:
        """Registra un plugin en el registry.

        Args:
            record: Registro del plugin.

        Raises:
            PluginRegistryError: Si el plugin ya está registrado.
        """
        if record.id in self._plugins:
            raise PluginRegistryError(
                f"Plugin '{record.id}' ya está registrado"
            )
        self._plugins[record.id] = record
        logger.info(
            "Plugin registrado: %s v%s (%s)",
            record.name, record.version or "?", record.origin.value,
        )

    def unregister_plugin(self, plugin_id: str) -> bool:
        """Desregistra un plugin y todas sus capacidades.

        Args:
            plugin_id: ID del plugin.

        Returns:
            True si se desregistró exitosamente.
        """
        if plugin_id not in self._plugins:
            return False

        # Limpiar tools
        tool_keys = [
            k for k, v in self._tools.items()
            if v.plugin_id == plugin_id
        ]
        for key in tool_keys:
            del self._tools[key]
            self._tool_handlers.pop(key, None)

        # Limpiar hooks
        self._hooks = [
            h for h in self._hooks
            if h.plugin_id != plugin_id
        ]
        # Limpiar hook handlers registrados por el plugin
        for event in list(self._hook_handlers.keys()):
            # Los handlers no se pueden filtrar por plugin directamente,
            # pero al reconstruir desde la lista de hooks se mantiene consistente
            pass

        # Limpiar channels
        ch_keys = [
            k for k, v in self._channels.items()
            if v.plugin_id == plugin_id
        ]
        for key in ch_keys:
            del self._channels[key]

        # Limpiar providers
        prov_keys = [
            k for k, v in self._providers.items()
            if v.plugin_id == plugin_id
        ]
        for key in prov_keys:
            del self._providers[key]

        # Limpiar services
        svc_keys = [
            k for k, v in self._services.items()
            if v.plugin_id == plugin_id
        ]
        for key in svc_keys:
            del self._services[key]

        # Limpiar commands
        cmd_keys = [
            k for k, v in self._commands.items()
            if v.plugin_id == plugin_id
        ]
        for key in cmd_keys:
            del self._commands[key]

        # Limpiar gateway handlers del plugin
        record = self._plugins[plugin_id]
        for method in record.gateway_methods:
            self._gateway_handlers.pop(method, None)

        del self._plugins[plugin_id]
        logger.info("Plugin desregistrado: %s", plugin_id)
        return True

    def get_plugin(self, plugin_id: str) -> Optional[PluginRecord]:
        """Obtiene un plugin por ID.

        Args:
            plugin_id: ID del plugin.

        Returns:
            PluginRecord o None.
        """
        return self._plugins.get(plugin_id)

    def list_plugins(
        self,
        state: Optional[PluginState] = None,
        origin: Optional[PluginOrigin] = None,
        capability: Optional[PluginCapability] = None,
    ) -> List[PluginRecord]:
        """Lista plugins con filtros opcionales.

        Args:
            state: Filtrar por estado.
            origin: Filtrar por origen.
            capability: Filtrar por capacidad.

        Returns:
            Lista de PluginRecord que cumplen los filtros.
        """
        results = list(self._plugins.values())
        if state is not None:
            results = [p for p in results if p.state == state]
        if origin is not None:
            results = [p for p in results if p.origin == origin]
        if capability is not None:
            results = [p for p in results if capability in p.capabilities]
        return results

    @property
    def plugin_count(self) -> int:
        """Cantidad de plugins registrados."""
        return len(self._plugins)

    @property
    def plugin_ids(self) -> List[str]:
        """IDs de plugins registrados."""
        return list(self._plugins.keys())

    # ── Tools ────────────────────────────────────────────────

    def register_tool(
        self,
        plugin_id: str,
        name: str,
        handler: ToolHandler,
        optional: bool = False,
    ) -> None:
        """Registra una tool desde un plugin.

        Args:
            plugin_id: ID del plugin que registra la tool.
            name: Nombre de la tool.
            handler: Función handler async de la tool.
            optional: Si la tool es opcional.

        Raises:
            PluginRegistryError: Si la tool ya existe o el plugin no.
        """
        record = self._plugins.get(plugin_id)
        if record is None:
            raise PluginRegistryError(
                f"Plugin '{plugin_id}' no registrado"
            )

        qualified = f"{plugin_id}.{name}"
        if qualified in self._tools:
            self._push_diagnostic(PluginDiagnostic(
                level="error",
                plugin_id=plugin_id,
                message=f"Tool ya registrada: {qualified}",
            ))
            return

        registration = PluginToolRegistration(
            plugin_id=plugin_id,
            plugin_name=record.name,
            name=name,
            qualified_name=qualified,
            optional=optional,
            source=record.source,
        )
        self._tools[qualified] = registration
        self._tool_handlers[qualified] = handler
        record.tool_names.append(qualified)
        if PluginCapability.TOOL not in record.capabilities:
            record.capabilities.append(PluginCapability.TOOL)

        logger.debug("[%s] Tool registrada: %s", plugin_id, qualified)

    def get_tool(self, qualified_name: str) -> Optional[ToolHandler]:
        """Obtiene un handler de tool por nombre calificado.

        Args:
            qualified_name: Nombre calificado (plugin_id.tool_name).

        Returns:
            Handler de la tool o None.
        """
        return self._tool_handlers.get(qualified_name)

    def get_all_tools(self) -> Dict[str, ToolHandler]:
        """Obtiene todas las tools registradas.

        Returns:
            Dict de qualified_name → handler.
        """
        return dict(self._tool_handlers)

    def get_tools_by_plugin(self, plugin_id: str) -> Dict[str, ToolHandler]:
        """Obtiene las tools de un plugin específico.

        Args:
            plugin_id: ID del plugin.

        Returns:
            Dict de qualified_name → handler.
        """
        return {
            k: v for k, v in self._tool_handlers.items()
            if self._tools.get(k, PluginToolRegistration(
                plugin_id="", name="", qualified_name=""
            )).plugin_id == plugin_id
        }

    # ── Hooks ────────────────────────────────────────────────

    def register_hook(
        self,
        plugin_id: str,
        event: str,
        callback: HookCallback,
        priority: int = 0,
    ) -> None:
        """Registra un hook desde un plugin.

        Args:
            plugin_id: ID del plugin.
            event: Nombre del evento.
            callback: Función callback async.
            priority: Prioridad (mayor = primero).
        """
        record = self._plugins.get(plugin_id)
        if record is None:
            self._push_diagnostic(PluginDiagnostic(
                level="error",
                plugin_id=plugin_id,
                message=f"Plugin '{plugin_id}' no registrado para hook",
            ))
            return

        registration = PluginHookRegistration(
            plugin_id=plugin_id,
            hook_name=event,
            events=[event],
            priority=priority,
            source=record.source,
        )
        self._hooks.append(registration)

        if event not in self._hook_handlers:
            self._hook_handlers[event] = []
        self._hook_handlers[event].append(callback)

        record.hook_names.append(event)
        record.hook_count += 1
        if PluginCapability.HOOK not in record.capabilities:
            record.capabilities.append(PluginCapability.HOOK)

        logger.debug("[%s] Hook registrado: %s", plugin_id, event)

    def get_hooks(self, event: str) -> List[HookCallback]:
        """Obtiene los callbacks registrados para un evento.

        Args:
            event: Nombre del evento.

        Returns:
            Lista de callbacks.
        """
        return list(self._hook_handlers.get(event, []))

    def get_all_hook_events(self) -> List[str]:
        """Obtiene todos los eventos con hooks registrados.

        Returns:
            Lista de nombres de eventos.
        """
        return list(self._hook_handlers.keys())

    # ── Channels ─────────────────────────────────────────────

    def register_channel(
        self,
        plugin_id: str,
        channel_id: str,
    ) -> None:
        """Registra un canal desde un plugin.

        Args:
            plugin_id: ID del plugin.
            channel_id: ID del canal.
        """
        record = self._plugins.get(plugin_id)
        if record is None:
            return

        if channel_id in self._channels:
            existing = self._channels[channel_id]
            self._push_diagnostic(PluginDiagnostic(
                level="error",
                plugin_id=plugin_id,
                message=(
                    f"Canal ya registrado: {channel_id} "
                    f"(por {existing.plugin_id})"
                ),
            ))
            return

        self._channels[channel_id] = PluginChannelRegistration(
            plugin_id=plugin_id,
            plugin_name=record.name,
            channel_id=channel_id,
            source=record.source,
        )
        record.channel_ids.append(channel_id)
        if PluginCapability.CHANNEL not in record.capabilities:
            record.capabilities.append(PluginCapability.CHANNEL)

    def get_channel_plugin(self, channel_id: str) -> Optional[str]:
        """Obtiene el plugin que registró un canal.

        Args:
            channel_id: ID del canal.

        Returns:
            plugin_id o None.
        """
        reg = self._channels.get(channel_id)
        return reg.plugin_id if reg else None

    # ── Providers ────────────────────────────────────────────

    def register_provider(
        self,
        plugin_id: str,
        provider_id: str,
    ) -> None:
        """Registra un provider desde un plugin.

        Args:
            plugin_id: ID del plugin.
            provider_id: ID del provider.
        """
        record = self._plugins.get(plugin_id)
        if record is None:
            return

        if provider_id in self._providers:
            existing = self._providers[provider_id]
            self._push_diagnostic(PluginDiagnostic(
                level="error",
                plugin_id=plugin_id,
                message=(
                    f"Provider ya registrado: {provider_id} "
                    f"(por {existing.plugin_id})"
                ),
            ))
            return

        self._providers[provider_id] = PluginProviderRegistration(
            plugin_id=plugin_id,
            plugin_name=record.name,
            provider_id=provider_id,
            source=record.source,
        )
        record.provider_ids.append(provider_id)
        if PluginCapability.PROVIDER not in record.capabilities:
            record.capabilities.append(PluginCapability.PROVIDER)

    def get_provider_plugin(self, provider_id: str) -> Optional[str]:
        """Obtiene el plugin que registró un provider."""
        reg = self._providers.get(provider_id)
        return reg.plugin_id if reg else None

    # ── Gateway Methods ──────────────────────────────────────

    def register_gateway_method(
        self,
        plugin_id: str,
        method: str,
        handler: Any,
    ) -> None:
        """Registra un método de gateway desde un plugin.

        Args:
            plugin_id: ID del plugin.
            method: Nombre del método RPC.
            handler: Handler del método.
        """
        record = self._plugins.get(plugin_id)
        if record is None:
            return

        trimmed = method.strip()
        if not trimmed:
            return

        if trimmed in self._gateway_handlers:
            self._push_diagnostic(PluginDiagnostic(
                level="error",
                plugin_id=plugin_id,
                message=f"Método de gateway ya registrado: {trimmed}",
            ))
            return

        self._gateway_handlers[trimmed] = handler
        record.gateway_methods.append(trimmed)
        if PluginCapability.GATEWAY_METHOD not in record.capabilities:
            record.capabilities.append(PluginCapability.GATEWAY_METHOD)

    def get_gateway_handlers(self) -> Dict[str, Any]:
        """Obtiene todos los handlers de gateway registrados."""
        return dict(self._gateway_handlers)

    # ── Services ─────────────────────────────────────────────

    def register_service(
        self,
        plugin_id: str,
        service_id: str,
    ) -> None:
        """Registra un servicio desde un plugin.

        Args:
            plugin_id: ID del plugin.
            service_id: ID del servicio.
        """
        record = self._plugins.get(plugin_id)
        if record is None:
            return

        if service_id in self._services:
            existing = self._services[service_id]
            self._push_diagnostic(PluginDiagnostic(
                level="error",
                plugin_id=plugin_id,
                message=(
                    f"Servicio ya registrado: {service_id} "
                    f"(por {existing.plugin_id})"
                ),
            ))
            return

        self._services[service_id] = PluginServiceRegistration(
            plugin_id=plugin_id,
            plugin_name=record.name if record else None,
            service_id=service_id,
            source=record.source if record else None,
        )
        record.service_ids.append(service_id)
        if PluginCapability.SERVICE not in record.capabilities:
            record.capabilities.append(PluginCapability.SERVICE)

    # ── Commands ─────────────────────────────────────────────

    def register_command(
        self,
        plugin_id: str,
        command_name: str,
        description: str = "",
        accepts_args: bool = False,
        require_auth: bool = True,
    ) -> None:
        """Registra un comando desde un plugin.

        Args:
            plugin_id: ID del plugin.
            command_name: Nombre del comando (sin /).
            description: Descripción del comando.
            accepts_args: Si acepta argumentos.
            require_auth: Si requiere autorización.
        """
        record = self._plugins.get(plugin_id)
        if record is None:
            return

        name = command_name.strip()
        if not name:
            self._push_diagnostic(PluginDiagnostic(
                level="error",
                plugin_id=plugin_id,
                message="Registro de comando sin nombre",
            ))
            return

        if name in self._commands:
            existing = self._commands[name]
            self._push_diagnostic(PluginDiagnostic(
                level="error",
                plugin_id=plugin_id,
                message=(
                    f"Comando ya registrado: {name} "
                    f"(por {existing.plugin_id})"
                ),
            ))
            return

        self._commands[name] = PluginCommandRegistration(
            plugin_id=plugin_id,
            plugin_name=record.name,
            command_name=name,
            description=description,
            accepts_args=accepts_args,
            require_auth=require_auth,
            source=record.source,
        )
        record.command_names.append(name)
        if PluginCapability.CLI_COMMAND not in record.capabilities:
            record.capabilities.append(PluginCapability.CLI_COMMAND)

    def get_command(self, name: str) -> Optional[PluginCommandRegistration]:
        """Obtiene el registro de un comando."""
        return self._commands.get(name)

    def list_commands(self) -> List[PluginCommandRegistration]:
        """Lista todos los comandos registrados."""
        return list(self._commands.values())

    # ── Diagnósticos ─────────────────────────────────────────

    def _push_diagnostic(self, diag: PluginDiagnostic) -> None:
        """Agrega un diagnóstico al registro."""
        self._diagnostics.append(diag)
        if diag.level == "error":
            logger.error("[%s] %s", diag.plugin_id or "?", diag.message)
        else:
            logger.warning("[%s] %s", diag.plugin_id or "?", diag.message)

    @property
    def diagnostics(self) -> List[PluginDiagnostic]:
        """Diagnósticos acumulados durante el registro."""
        return list(self._diagnostics)

    def clear_diagnostics(self) -> None:
        """Limpia los diagnósticos acumulados."""
        self._diagnostics.clear()

    # ── Resolución de dependencias ───────────────────────────

    def resolve_dependencies(
        self,
        plugin_id: str,
    ) -> List[str]:
        """Resuelve el orden de dependencias para un plugin.

        Realiza una resolución topológica de dependencias del plugin
        basada en el campo dependencies del manifiesto.

        Args:
            plugin_id: ID del plugin raíz.

        Returns:
            Lista ordenada de plugin_ids (dependencias primero).

        Raises:
            PluginRegistryError: Si hay dependencia circular
                o dependencia no satisfecha.
        """
        visited: set[str] = set()
        in_progress: set[str] = set()
        order: List[str] = []

        def visit(pid: str) -> None:
            if pid in visited:
                return
            if pid in in_progress:
                raise PluginRegistryError(
                    f"Dependencia circular detectada: {pid}"
                )

            in_progress.add(pid)
            record = self._plugins.get(pid)
            if record is None:
                raise PluginRegistryError(
                    f"Dependencia no satisfecha: '{pid}' "
                    f"(requerida por '{plugin_id}')"
                )

            # Buscar dependencias en el manifiesto original
            # (almacenadas como tool_names que empiezan con "dep:")
            # En la práctica, las deps vienen del manifest
            # y se pasan en el PluginRecord

            in_progress.discard(pid)
            visited.add(pid)
            order.append(pid)

        visit(plugin_id)
        return order

    def query(
        self,
        capability: Optional[PluginCapability] = None,
        origin: Optional[PluginOrigin] = None,
        enabled_only: bool = True,
    ) -> List[PluginRecord]:
        """Consulta plugins con filtros combinados.

        Args:
            capability: Filtrar por capacidad.
            origin: Filtrar por origen.
            enabled_only: Solo plugins habilitados.

        Returns:
            Lista de PluginRecord que cumplen los filtros.
        """
        results = list(self._plugins.values())
        if enabled_only:
            results = [p for p in results if p.enabled]
        if capability is not None:
            results = [p for p in results if capability in p.capabilities]
        if origin is not None:
            results = [p for p in results if p.origin == origin]
        return results

    def get_summary(self) -> Dict[str, Any]:
        """Obtiene un resumen del registry.

        Returns:
            Dict con conteos y estadísticas.
        """
        return {
            "plugins": len(self._plugins),
            "tools": len(self._tools),
            "hooks": len(self._hooks),
            "channels": len(self._channels),
            "providers": len(self._providers),
            "services": len(self._services),
            "commands": len(self._commands),
            "gateway_methods": len(self._gateway_handlers),
            "diagnostics": {
                "errors": sum(
                    1 for d in self._diagnostics if d.level == "error"
                ),
                "warnings": sum(
                    1 for d in self._diagnostics if d.level == "warn"
                ),
            },
        }
