"""Plugin contracts — interfaces que los plugins deben implementar.

Portado desde OpenClaw contracts/. Define los contratos (protocolos)
que los plugins deben cumplir según su tipo: channel, provider,
skill, hook, context engine, etc.
"""

from __future__ import annotations

import abc
from typing import Any, Callable, Coroutine, Dict, List, Optional, Protocol, runtime_checkable


# ── Contrato base ────────────────────────────────────────────

@runtime_checkable
class PluginContract(Protocol):
    """Contrato base que todo plugin debe cumplir."""

    @property
    def id(self) -> str:
        """Identificador único del plugin."""
        ...

    @property
    def name(self) -> str:
        """Nombre legible del plugin."""
        ...

    @property
    def version(self) -> str:
        """Versión semver del plugin."""
        ...


# ── Contrato de Channel ─────────────────────────────────────

@runtime_checkable
class ChannelPluginContract(Protocol):
    """Contrato para plugins de canal de comunicación.

    Un plugin de canal conecta SOMER con una plataforma de mensajería
    (Telegram, Discord, Slack, etc.).
    """

    @property
    def channel_id(self) -> str:
        """ID del canal (e.g., 'telegram', 'discord')."""
        ...

    async def setup(self, config: Dict[str, Any]) -> None:
        """Configura el canal con la configuración dada."""
        ...

    async def start(self) -> None:
        """Inicia la escucha de mensajes del canal."""
        ...

    async def stop(self) -> None:
        """Detiene la escucha de mensajes."""
        ...

    async def send_message(
        self,
        to: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Envía un mensaje a través del canal.

        Args:
            to: Destinatario.
            content: Contenido del mensaje.
            metadata: Metadata adicional.

        Returns:
            True si el envío fue exitoso.
        """
        ...

    def on_message(
        self,
        callback: Callable[..., Coroutine[Any, Any, Any]],
    ) -> None:
        """Registra un callback para mensajes entrantes."""
        ...


# ── Contrato de Provider ────────────────────────────────────

@runtime_checkable
class ProviderPluginContract(Protocol):
    """Contrato para plugins de provider LLM.

    Un plugin de provider conecta SOMER con un servicio de inferencia
    de modelos de lenguaje.
    """

    @property
    def provider_id(self) -> str:
        """ID del provider (e.g., 'openai', 'anthropic')."""
        ...

    @property
    def label(self) -> str:
        """Etiqueta legible del provider."""
        ...

    async def complete(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Genera una completion.

        Args:
            messages: Lista de mensajes del chat.
            model: ID del modelo a usar.
            **kwargs: Parámetros adicionales.

        Returns:
            Respuesta del modelo.
        """
        ...

    async def health_check(self) -> bool:
        """Verifica conectividad con el provider.

        Returns:
            True si el provider responde correctamente.
        """
        ...


# ── Contrato de Skill ───────────────────────────────────────

@runtime_checkable
class SkillPluginContract(Protocol):
    """Contrato para plugins de skill.

    Un plugin de skill agrega capacidades ejecutables al agente.
    """

    @property
    def skill_name(self) -> str:
        """Nombre del skill."""
        ...

    @property
    def description(self) -> str:
        """Descripción del skill."""
        ...

    async def execute(
        self,
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Ejecuta el skill.

        Args:
            params: Parámetros de ejecución.
            context: Contexto de ejecución opcional.

        Returns:
            Resultado de la ejecución.
        """
        ...

    def validate_params(self, params: Dict[str, Any]) -> bool:
        """Valida los parámetros antes de ejecutar.

        Args:
            params: Parámetros a validar.

        Returns:
            True si los parámetros son válidos.
        """
        ...


# ── Contrato de Hook ─────────────────────────────────────────

@runtime_checkable
class HookPluginContract(Protocol):
    """Contrato para plugins de hook.

    Un plugin de hook se suscribe a eventos del ciclo de vida
    del sistema.
    """

    @property
    def events(self) -> List[str]:
        """Eventos a los que el hook se suscribe."""
        ...

    async def handle(
        self,
        event: str,
        data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Maneja un evento.

        Args:
            event: Nombre del evento.
            data: Datos del evento.
            context: Contexto adicional.

        Returns:
            Resultado opcional que puede modificar el flujo.
        """
        ...


# ── Contrato de Context Engine ───────────────────────────────

@runtime_checkable
class ContextEnginePluginContract(Protocol):
    """Contrato para plugins de motor de contexto.

    Un plugin de context engine gestiona cómo se construye,
    compacta y ensambla el contexto del agente.
    """

    @property
    def engine_id(self) -> str:
        """ID del motor de contexto."""
        ...

    async def bootstrap(
        self,
        config: Dict[str, Any],
    ) -> None:
        """Inicializa el motor de contexto."""
        ...

    async def ingest(
        self,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Ingesta contenido nuevo en el contexto."""
        ...

    async def assemble(
        self,
        max_tokens: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Ensambla el contexto para enviar al LLM.

        Returns:
            Lista de mensajes ensamblados.
        """
        ...

    async def compact(self) -> None:
        """Compacta el contexto para liberar espacio."""
        ...

    async def after_turn(
        self,
        messages: List[Dict[str, Any]],
    ) -> None:
        """Post-procesamiento después de un turno."""
        ...


# ── Contrato de Service ─────────────────────────────────────

@runtime_checkable
class ServicePluginContract(Protocol):
    """Contrato para plugins de servicio.

    Un plugin de servicio ejecuta un proceso de fondo continuo
    dentro de SOMER.
    """

    @property
    def service_id(self) -> str:
        """ID del servicio."""
        ...

    async def start(self, context: Dict[str, Any]) -> None:
        """Inicia el servicio."""
        ...

    async def stop(self, context: Optional[Dict[str, Any]] = None) -> None:
        """Detiene el servicio."""
        ...


# ── Contrato de Tool ────────────────────────────────────────

@runtime_checkable
class ToolPluginContract(Protocol):
    """Contrato para plugins de tool.

    Un plugin de tool registra herramientas ejecutables
    que el agente puede invocar.
    """

    @property
    def tool_name(self) -> str:
        """Nombre de la herramienta."""
        ...

    @property
    def tool_description(self) -> str:
        """Descripción de la herramienta."""
        ...

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        """JSON Schema de los parámetros."""
        ...

    async def execute(
        self,
        arguments: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Ejecuta la herramienta.

        Args:
            arguments: Argumentos de la herramienta.
            context: Contexto de ejecución.

        Returns:
            Resultado de la ejecución.
        """
        ...


# ── Validación de contratos ──────────────────────────────────

def validate_contract(
    plugin: Any,
    contract_type: type,
) -> List[str]:
    """Valida que un plugin cumple con un contrato.

    Args:
        plugin: Instancia o módulo del plugin.
        contract_type: Tipo de contrato a validar.

    Returns:
        Lista de errores de validación (vacía si cumple).
    """
    errors: List[str] = []

    if not isinstance(plugin, contract_type):
        # Verificar atributos manualmente para mensajes útiles
        for attr_name in dir(contract_type):
            if attr_name.startswith("_"):
                continue
            if not hasattr(plugin, attr_name):
                errors.append(
                    f"Plugin no implementa '{attr_name}' requerido por "
                    f"{contract_type.__name__}"
                )

    return errors


# ── Mapa de contratos por tipo ───────────────────────────────

CONTRACT_MAP: Dict[str, type] = {
    "channel": ChannelPluginContract,
    "provider": ProviderPluginContract,
    "skill": SkillPluginContract,
    "hook": HookPluginContract,
    "context_engine": ContextEnginePluginContract,
    "service": ServicePluginContract,
    "tool": ToolPluginContract,
}


def get_contract_for_kind(kind: str) -> Optional[type]:
    """Obtiene el contrato correspondiente a un tipo de plugin.

    Args:
        kind: Tipo del plugin (channel, provider, skill, etc.).

    Returns:
        Clase del contrato o None si no existe.
    """
    return CONTRACT_MAP.get(kind)
