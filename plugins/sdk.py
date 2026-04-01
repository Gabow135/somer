"""Plugin SDK — interfaz que reciben los plugins para registrar capacidades.

Portado desde OpenClaw types.ts (OpenClawPluginApi). Es la superficie
de API que los plugins reciben durante register/setup para registrar
tools, hooks, channels, providers, servicios, comandos y más.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Coroutine, Dict, List, Optional

from shared.types import SkillMeta

logger = logging.getLogger(__name__)

# Type aliases para handlers
ToolHandler = Callable[..., Coroutine[Any, Any, Any]]
HookCallback = Callable[..., Coroutine[Any, Any, Any]]


class PluginSDK:
    """SDK que se pasa a cada plugin durante la carga.

    Permite al plugin registrar skills, tools, hooks, channels,
    providers, servicios, comandos y gateway methods en el sistema
    de SOMER sin acceder directamente a los registries internos.

    Uso desde un plugin::

        async def setup(sdk: PluginSDK):
            sdk.register_skill(SkillMeta(name="my-skill", ...))
            sdk.register_tool("my_tool", my_handler)
            sdk.register_hook("on_message", my_hook)
            sdk.register_provider("my-provider", provider_config)
            sdk.register_channel("my-channel", channel_handler)
            sdk.register_command("status", status_handler, description="Estado")
            sdk.register_service("bg-worker", start=worker_start, stop=worker_stop)
            api_key = sdk.get_secret("MY_API_KEY")
    """

    def __init__(
        self,
        plugin_name: str,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._plugin_name = plugin_name
        self._config = config or {}
        self._skills: List[SkillMeta] = []
        self._tools: Dict[str, ToolHandler] = {}
        self._hooks: Dict[str, List[HookCallback]] = {}
        self._channels: Dict[str, Any] = {}
        self._providers: Dict[str, Any] = {}
        self._services: Dict[str, Any] = {}
        self._commands: Dict[str, Any] = {}
        self._gateway_methods: Dict[str, Any] = {}
        self._context_engines: Dict[str, Any] = {}

    @property
    def plugin_name(self) -> str:
        """Nombre del plugin."""
        return self._plugin_name

    # ── Skills ──────────────────────────────────────────────

    def register_skill(self, skill_meta: SkillMeta) -> None:
        """Registra un skill en el sistema."""
        self._skills.append(skill_meta)
        logger.info("[%s] Skill registrado: %s", self._plugin_name, skill_meta.name)

    @property
    def registered_skills(self) -> List[SkillMeta]:
        """Skills registrados por este plugin."""
        return list(self._skills)

    # ── Tools ───────────────────────────────────────────────

    def register_tool(self, name: str, handler: ToolHandler) -> None:
        """Registra una tool callable."""
        qualified = f"{self._plugin_name}.{name}"
        self._tools[qualified] = handler
        logger.info("[%s] Tool registrada: %s", self._plugin_name, qualified)

    @property
    def registered_tools(self) -> Dict[str, ToolHandler]:
        """Tools registradas por este plugin."""
        return dict(self._tools)

    # ── Hooks ───────────────────────────────────────────────

    def register_hook(self, event: str, callback: HookCallback) -> None:
        """Registra un callback para un evento del sistema.

        Eventos del ciclo de vida del sistema:
            on_message, on_session_start, on_session_end,
            on_skill_execute, on_agent_route, on_error,
            before_agent_start, llm_input, llm_output,
            before_tool_call, after_tool_call, gateway_start, gateway_stop.
        """
        if event not in self._hooks:
            self._hooks[event] = []
        self._hooks[event].append(callback)
        logger.info("[%s] Hook registrado: %s", self._plugin_name, event)

    def get_hooks(self, event: str) -> List[HookCallback]:
        """Obtiene los callbacks registrados para un evento."""
        return list(self._hooks.get(event, []))

    @property
    def registered_hooks(self) -> Dict[str, List[HookCallback]]:
        """Hooks registrados por este plugin."""
        return {k: list(v) for k, v in self._hooks.items()}

    # ── Channels ────────────────────────────────────────────

    def register_channel(self, channel_id: str, handler: Any) -> None:
        """Registra un canal de comunicación.

        Args:
            channel_id: ID del canal (e.g., 'telegram', 'discord').
            handler: Instancia del plugin de canal.
        """
        self._channels[channel_id] = handler
        logger.info("[%s] Canal registrado: %s", self._plugin_name, channel_id)

    @property
    def registered_channels(self) -> Dict[str, Any]:
        """Canales registrados por este plugin."""
        return dict(self._channels)

    # ── Providers ───────────────────────────────────────────

    def register_provider(self, provider_id: str, provider: Any) -> None:
        """Registra un provider de LLM.

        Args:
            provider_id: ID del provider (e.g., 'openai', 'anthropic').
            provider: Instancia o configuración del provider.
        """
        self._providers[provider_id] = provider
        logger.info("[%s] Provider registrado: %s", self._plugin_name, provider_id)

    @property
    def registered_providers(self) -> Dict[str, Any]:
        """Providers registrados por este plugin."""
        return dict(self._providers)

    # ── Services ────────────────────────────────────────────

    def register_service(
        self,
        service_id: str,
        start: Optional[Callable[..., Any]] = None,
        stop: Optional[Callable[..., Any]] = None,
    ) -> None:
        """Registra un servicio de fondo.

        Args:
            service_id: ID del servicio.
            start: Función para iniciar el servicio.
            stop: Función para detener el servicio.
        """
        self._services[service_id] = {"start": start, "stop": stop}
        logger.info("[%s] Servicio registrado: %s", self._plugin_name, service_id)

    @property
    def registered_services(self) -> Dict[str, Any]:
        """Servicios registrados por este plugin."""
        return dict(self._services)

    # ── Commands ────────────────────────────────────────────

    def register_command(
        self,
        name: str,
        handler: Callable[..., Any],
        description: str = "",
        accepts_args: bool = False,
        require_auth: bool = True,
    ) -> None:
        """Registra un comando que bypasea el LLM.

        Los comandos de plugin se procesan antes de los comandos
        built-in y antes de invocar al agente.

        Args:
            name: Nombre del comando (sin /).
            handler: Función handler del comando.
            description: Descripción para /help.
            accepts_args: Si acepta argumentos.
            require_auth: Si requiere autorización.
        """
        self._commands[name] = {
            "handler": handler,
            "description": description,
            "accepts_args": accepts_args,
            "require_auth": require_auth,
        }
        logger.info("[%s] Comando registrado: %s", self._plugin_name, name)

    @property
    def registered_commands(self) -> Dict[str, Any]:
        """Comandos registrados por este plugin."""
        return dict(self._commands)

    # ── Gateway Methods ─────────────────────────────────────

    def register_gateway_method(self, method: str, handler: Any) -> None:
        """Registra un método JSON-RPC en el gateway.

        Args:
            method: Nombre del método RPC.
            handler: Handler del método.
        """
        self._gateway_methods[method] = handler
        logger.info("[%s] Método gateway registrado: %s", self._plugin_name, method)

    @property
    def registered_gateway_methods(self) -> Dict[str, Any]:
        """Métodos de gateway registrados por este plugin."""
        return dict(self._gateway_methods)

    # ── Context Engines ─────────────────────────────────────

    def register_context_engine(self, engine_id: str, factory: Any) -> None:
        """Registra un motor de contexto.

        Args:
            engine_id: ID del motor de contexto.
            factory: Factory o instancia del motor.
        """
        self._context_engines[engine_id] = factory
        logger.info(
            "[%s] Context engine registrado: %s",
            self._plugin_name, engine_id,
        )

    @property
    def registered_context_engines(self) -> Dict[str, Any]:
        """Context engines registrados por este plugin."""
        return dict(self._context_engines)

    # ── Config & Secrets ────────────────────────────────────

    def get_config(self, key: str, default: Any = None) -> Any:
        """Obtiene un valor de configuración del plugin."""
        return self._config.get(key, default)

    @property
    def plugin_config(self) -> Dict[str, Any]:
        """Configuración completa del plugin."""
        return dict(self._config)

    @staticmethod
    def get_secret(name: str, default: Optional[str] = None) -> Optional[str]:
        """Obtiene un secreto del entorno.

        Busca primero como variable de entorno, luego podría
        integrarse con el sistema de secretos de SOMER.
        """
        return os.environ.get(name, default)

    # ── Utilidades ──────────────────────────────────────────

    def resolve_path(self, path: str) -> str:
        """Resuelve una ruta relativa al directorio del plugin.

        Args:
            path: Ruta a resolver.

        Returns:
            Ruta absoluta.
        """
        from pathlib import Path as PPath
        resolved = PPath(path).expanduser()
        if resolved.is_absolute():
            return str(resolved)
        return str(PPath.cwd() / resolved)
