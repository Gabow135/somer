"""Sistema de hooks internos de SOMER 2.0.

Provee un sistema extensible de eventos para el motor cognitivo,
inspirado en la arquitectura de hooks de OpenClaw. Soporta:

- Registro de handlers por tipo de evento o tipo:accion especifica
- Ejecucion con prioridad/orden de registro
- Contextos tipados para mensajes, sesiones, agente y gateway
- Mappers para transformar entre contextos canonicos y de canal
- Guard functions para validar tipos de evento
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    Sequence,
    Union,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Tipos de evento
# ============================================================================

class HookEventType(str, Enum):
    """Tipos de evento soportados por el sistema de hooks internos."""
    COMMAND = "command"
    SESSION = "session"
    AGENT = "agent"
    GATEWAY = "gateway"
    MESSAGE = "message"
    PROVIDER = "provider"
    MEMORY = "memory"
    SKILL = "skill"
    CONTEXT = "context"
    CHANNEL = "channel"


# ============================================================================
# Contextos de evento
# ============================================================================

@dataclass
class HookEvent:
    """Evento base del sistema de hooks internos.

    Cada evento tiene un tipo, una accion, una clave de sesion opcional,
    contexto adicional, timestamp y una lista de mensajes que los handlers
    pueden rellenar para enviar respuestas al usuario.
    """
    type: HookEventType
    action: str
    session_key: str = ""
    context: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    messages: List[str] = field(default_factory=list)


# ── Contextos especificos ────────────────────────────────────────

@dataclass
class AgentBootstrapContext:
    """Contexto para el evento agent:bootstrap."""
    workspace_dir: str = ""
    session_key: str = ""
    session_id: str = ""
    agent_id: str = ""
    bootstrap_files: List[str] = field(default_factory=list)
    config: Optional[Dict[str, Any]] = None


@dataclass
class GatewayStartupContext:
    """Contexto para el evento gateway:startup."""
    host: str = "127.0.0.1"
    port: int = 18789
    config: Optional[Dict[str, Any]] = None
    workspace_dir: str = ""


@dataclass
class MessageReceivedContext:
    """Contexto para el evento message:received."""
    sender: str = ""
    content: str = ""
    timestamp: Optional[float] = None
    channel_id: str = ""
    account_id: Optional[str] = None
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MessageSentContext:
    """Contexto para el evento message:sent."""
    recipient: str = ""
    content: str = ""
    success: bool = True
    error: Optional[str] = None
    channel_id: str = ""
    account_id: Optional[str] = None
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    is_group: bool = False
    group_id: Optional[str] = None


@dataclass
class MessageTranscribedContext:
    """Contexto para el evento message:transcribed."""
    sender: Optional[str] = None
    recipient: Optional[str] = None
    body: Optional[str] = None
    body_for_agent: Optional[str] = None
    transcript: str = ""
    timestamp: Optional[float] = None
    channel_id: str = ""
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    sender_id: Optional[str] = None
    sender_name: Optional[str] = None
    sender_username: Optional[str] = None
    provider: Optional[str] = None
    surface: Optional[str] = None
    media_path: Optional[str] = None
    media_type: Optional[str] = None


@dataclass
class MessagePreprocessedContext:
    """Contexto para el evento message:preprocessed."""
    sender: Optional[str] = None
    recipient: Optional[str] = None
    body: Optional[str] = None
    body_for_agent: Optional[str] = None
    transcript: Optional[str] = None
    timestamp: Optional[float] = None
    channel_id: str = ""
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    sender_id: Optional[str] = None
    sender_name: Optional[str] = None
    sender_username: Optional[str] = None
    provider: Optional[str] = None
    surface: Optional[str] = None
    media_path: Optional[str] = None
    media_type: Optional[str] = None
    is_group: bool = False
    group_id: Optional[str] = None


@dataclass
class SessionLifecycleContext:
    """Contexto para eventos session:create / session:close / session:expire."""
    session_id: str = ""
    channel: str = ""
    channel_user_id: str = ""
    channel_thread_id: Optional[str] = None
    guild_id: Optional[str] = None
    reason: Optional[str] = None


@dataclass
class ProviderSwitchContext:
    """Contexto para el evento provider:switch."""
    old_provider: str = ""
    new_provider: str = ""
    old_model: str = ""
    new_model: str = ""
    reason: Optional[str] = None


@dataclass
class ErrorContext:
    """Contexto generico para eventos de error."""
    error_type: str = ""
    error_message: str = ""
    source: str = ""
    session_key: str = ""
    recoverable: bool = True
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ContextCompactContext:
    """Contexto para el evento context:compact."""
    session_id: str = ""
    messages_before: int = 0
    messages_after: int = 0
    tokens_saved: int = 0
    strategy: str = ""


@dataclass
class SkillExecutionContext:
    """Contexto para eventos skill:execute / skill:complete / skill:error."""
    skill_name: str = ""
    session_id: str = ""
    trigger: str = ""
    duration_ms: float = 0.0
    success: bool = True
    error: Optional[str] = None


# ============================================================================
# Tipo de handler
# ============================================================================

HookHandler = Callable[[HookEvent], Awaitable[None]]
"""Handler asincrono que recibe un HookEvent."""

SyncHookHandler = Callable[[HookEvent], None]
"""Handler sincrono que recibe un HookEvent (se ejecuta en el loop)."""

AnyHookHandler = Union[HookHandler, SyncHookHandler]
"""Cualquier tipo de handler (sincrono o asincrono)."""


# ============================================================================
# Entrada de handler con prioridad
# ============================================================================

@dataclass
class _HandlerEntry:
    """Entrada interna de handler con prioridad y metadatos."""
    handler: AnyHookHandler
    priority: int = 0
    name: Optional[str] = None

    def __lt__(self, other: _HandlerEntry) -> bool:
        return self.priority < other.priority


# ============================================================================
# Registro global de hooks internos
# ============================================================================

_handlers: Dict[str, List[_HandlerEntry]] = {}


def register_internal_hook(
    event_key: str,
    handler: AnyHookHandler,
    *,
    priority: int = 0,
    name: Optional[str] = None,
) -> None:
    """Registra un handler para un tipo de evento o tipo:accion especifica.

    El ``event_key`` puede ser un tipo general (e.g. ``"message"``) o
    una combinacion tipo:accion (e.g. ``"message:received"``).
    Los handlers con prioridad mas baja se ejecutan primero (0 = default).

    Args:
        event_key: Clave del evento (tipo o tipo:accion).
        handler: Funcion asincrona o sincrona que procesa el evento.
        priority: Prioridad de ejecucion (menor = antes). Default 0.
        name: Nombre opcional para debug/logging.

    Ejemplo::

        # Escuchar todos los eventos de mensaje
        register_internal_hook("message", mi_handler_mensajes)

        # Escuchar solo mensajes recibidos
        register_internal_hook("message:received", mi_handler_recibidos)

        # Con prioridad alta (se ejecuta antes)
        register_internal_hook("message:received", mi_handler, priority=-10)
    """
    entry = _HandlerEntry(handler=handler, priority=priority, name=name)
    if event_key not in _handlers:
        _handlers[event_key] = []
    _handlers[event_key].append(entry)
    # Mantener ordenado por prioridad
    _handlers[event_key].sort()
    logger.debug(
        "Hook interno registrado: %s (prioridad=%d, nombre=%s)",
        event_key,
        priority,
        name or "<anonimo>",
    )


def unregister_internal_hook(event_key: str, handler: AnyHookHandler) -> bool:
    """Desregistra un handler especifico.

    Args:
        event_key: Clave del evento donde se registro.
        handler: La referencia al handler a remover.

    Returns:
        True si se encontro y removio, False si no existia.
    """
    entries = _handlers.get(event_key)
    if not entries:
        return False

    for i, entry in enumerate(entries):
        if entry.handler is handler:
            entries.pop(i)
            # Limpiar listas vacias
            if not entries:
                del _handlers[event_key]
            return True
    return False


def clear_internal_hooks() -> None:
    """Limpia todos los hooks registrados.

    Util para testing y reinicio del sistema.
    """
    _handlers.clear()
    logger.debug("Todos los hooks internos han sido limpiados")


def get_registered_event_keys() -> List[str]:
    """Retorna todas las claves de evento registradas.

    Util para debug e inspeccion.
    """
    return list(_handlers.keys())


def get_handler_count(event_key: str) -> int:
    """Retorna la cantidad de handlers registrados para una clave.

    Args:
        event_key: Clave del evento.
    """
    return len(_handlers.get(event_key, []))


def get_all_handlers_for_event(event: HookEvent) -> List[_HandlerEntry]:
    """Obtiene todos los handlers aplicables a un evento, en orden de prioridad.

    Combina handlers del tipo general y del tipo:accion especifica,
    ordenados por prioridad (menor primero).

    Args:
        event: El evento a evaluar.
    """
    type_key = event.type.value if isinstance(event.type, HookEventType) else str(event.type)
    specific_key = f"{type_key}:{event.action}"

    type_handlers = _handlers.get(type_key, [])
    specific_handlers = _handlers.get(specific_key, [])

    # Merge y re-sort por prioridad
    combined = list(type_handlers) + list(specific_handlers)
    combined.sort()
    return combined


# ============================================================================
# Ejecucion de hooks
# ============================================================================

async def trigger_internal_hook(event: HookEvent) -> int:
    """Dispara un evento y ejecuta todos los handlers registrados.

    Llama a todos los handlers registrados para:
    1. El tipo general del evento (e.g. ``"message"``)
    2. La combinacion tipo:accion especifica (e.g. ``"message:received"``)

    Los handlers se ejecutan en orden de prioridad (menor primero).
    Los errores se capturan y loggean sin detener la ejecucion.

    Args:
        event: El evento a disparar.

    Returns:
        Numero de handlers ejecutados exitosamente.
    """
    all_entries = get_all_handlers_for_event(event)

    if not all_entries:
        return 0

    type_key = event.type.value if isinstance(event.type, HookEventType) else str(event.type)
    executed = 0

    for entry in all_entries:
        try:
            result = entry.handler(event)
            # Soportar tanto handlers async como sync
            if hasattr(result, "__await__"):
                await result
            executed += 1
        except Exception as exc:
            handler_name = entry.name or getattr(entry.handler, "__name__", "<anonimo>")
            logger.error(
                "Error en hook interno [%s:%s] handler=%s: %s",
                type_key,
                event.action,
                handler_name,
                exc,
            )

    return executed


async def trigger_hook(
    event_type: HookEventType,
    action: str,
    session_key: str = "",
    context: Optional[Dict[str, Any]] = None,
) -> HookEvent:
    """Atajo para crear y disparar un evento en un solo paso.

    Args:
        event_type: Tipo del evento.
        action: Accion especifica.
        session_key: Clave de sesion.
        context: Contexto adicional.

    Returns:
        El HookEvent creado (con posibles mensajes agregados por handlers).
    """
    event = create_hook_event(event_type, action, session_key, context)
    await trigger_internal_hook(event)
    return event


# ============================================================================
# Factory de eventos
# ============================================================================

def create_hook_event(
    event_type: HookEventType,
    action: str,
    session_key: str = "",
    context: Optional[Dict[str, Any]] = None,
) -> HookEvent:
    """Crea un HookEvent con los campos comunes rellenados.

    Args:
        event_type: Tipo del evento.
        action: Accion dentro del tipo (e.g. 'create', 'received', 'startup').
        session_key: Clave de sesion relacionada.
        context: Contexto adicional especifico del evento.
    """
    return HookEvent(
        type=event_type,
        action=action,
        session_key=session_key,
        context=context or {},
        timestamp=time.time(),
        messages=[],
    )


# ── Factories especializadas ────────────────────────────────────

def create_agent_bootstrap_event(
    ctx: AgentBootstrapContext,
    session_key: str = "",
) -> HookEvent:
    """Crea un evento agent:bootstrap."""
    return create_hook_event(
        HookEventType.AGENT,
        "bootstrap",
        session_key=session_key,
        context={
            "workspace_dir": ctx.workspace_dir,
            "session_key": ctx.session_key,
            "session_id": ctx.session_id,
            "agent_id": ctx.agent_id,
            "bootstrap_files": ctx.bootstrap_files,
            "config": ctx.config,
        },
    )


def create_gateway_startup_event(ctx: GatewayStartupContext) -> HookEvent:
    """Crea un evento gateway:startup."""
    return create_hook_event(
        HookEventType.GATEWAY,
        "startup",
        context={
            "host": ctx.host,
            "port": ctx.port,
            "config": ctx.config,
            "workspace_dir": ctx.workspace_dir,
        },
    )


def create_message_received_event(
    ctx: MessageReceivedContext,
    session_key: str = "",
) -> HookEvent:
    """Crea un evento message:received."""
    return create_hook_event(
        HookEventType.MESSAGE,
        "received",
        session_key=session_key,
        context={
            "sender": ctx.sender,
            "content": ctx.content,
            "timestamp": ctx.timestamp,
            "channel_id": ctx.channel_id,
            "account_id": ctx.account_id,
            "conversation_id": ctx.conversation_id,
            "message_id": ctx.message_id,
            "metadata": ctx.metadata,
        },
    )


def create_message_sent_event(
    ctx: MessageSentContext,
    session_key: str = "",
) -> HookEvent:
    """Crea un evento message:sent."""
    return create_hook_event(
        HookEventType.MESSAGE,
        "sent",
        session_key=session_key,
        context={
            "recipient": ctx.recipient,
            "content": ctx.content,
            "success": ctx.success,
            "error": ctx.error,
            "channel_id": ctx.channel_id,
            "account_id": ctx.account_id,
            "conversation_id": ctx.conversation_id,
            "message_id": ctx.message_id,
            "is_group": ctx.is_group,
            "group_id": ctx.group_id,
        },
    )


def create_message_transcribed_event(
    ctx: MessageTranscribedContext,
    session_key: str = "",
) -> HookEvent:
    """Crea un evento message:transcribed."""
    return create_hook_event(
        HookEventType.MESSAGE,
        "transcribed",
        session_key=session_key,
        context={
            "sender": ctx.sender,
            "recipient": ctx.recipient,
            "body": ctx.body,
            "body_for_agent": ctx.body_for_agent,
            "transcript": ctx.transcript,
            "timestamp": ctx.timestamp,
            "channel_id": ctx.channel_id,
            "conversation_id": ctx.conversation_id,
            "message_id": ctx.message_id,
            "sender_id": ctx.sender_id,
            "sender_name": ctx.sender_name,
            "sender_username": ctx.sender_username,
            "provider": ctx.provider,
            "surface": ctx.surface,
            "media_path": ctx.media_path,
            "media_type": ctx.media_type,
        },
    )


def create_message_preprocessed_event(
    ctx: MessagePreprocessedContext,
    session_key: str = "",
) -> HookEvent:
    """Crea un evento message:preprocessed."""
    return create_hook_event(
        HookEventType.MESSAGE,
        "preprocessed",
        session_key=session_key,
        context={
            "sender": ctx.sender,
            "recipient": ctx.recipient,
            "body": ctx.body,
            "body_for_agent": ctx.body_for_agent,
            "transcript": ctx.transcript,
            "timestamp": ctx.timestamp,
            "channel_id": ctx.channel_id,
            "conversation_id": ctx.conversation_id,
            "message_id": ctx.message_id,
            "sender_id": ctx.sender_id,
            "sender_name": ctx.sender_name,
            "sender_username": ctx.sender_username,
            "provider": ctx.provider,
            "surface": ctx.surface,
            "media_path": ctx.media_path,
            "media_type": ctx.media_type,
            "is_group": ctx.is_group,
            "group_id": ctx.group_id,
        },
    )


def create_session_event(
    action: str,
    ctx: SessionLifecycleContext,
) -> HookEvent:
    """Crea un evento session:create / session:close / session:expire."""
    return create_hook_event(
        HookEventType.SESSION,
        action,
        session_key=ctx.session_id,
        context={
            "session_id": ctx.session_id,
            "channel": ctx.channel,
            "channel_user_id": ctx.channel_user_id,
            "channel_thread_id": ctx.channel_thread_id,
            "guild_id": ctx.guild_id,
            "reason": ctx.reason,
        },
    )


def create_error_event(ctx: ErrorContext) -> HookEvent:
    """Crea un evento generico de error (type depende de source)."""
    return create_hook_event(
        HookEventType.AGENT,
        "error",
        session_key=ctx.session_key,
        context={
            "error_type": ctx.error_type,
            "error_message": ctx.error_message,
            "source": ctx.source,
            "recoverable": ctx.recoverable,
            "details": ctx.details,
        },
    )


def create_provider_switch_event(
    ctx: ProviderSwitchContext,
    session_key: str = "",
) -> HookEvent:
    """Crea un evento provider:switch."""
    return create_hook_event(
        HookEventType.PROVIDER,
        "switch",
        session_key=session_key,
        context={
            "old_provider": ctx.old_provider,
            "new_provider": ctx.new_provider,
            "old_model": ctx.old_model,
            "new_model": ctx.new_model,
            "reason": ctx.reason,
        },
    )


def create_context_compact_event(
    ctx: ContextCompactContext,
    session_key: str = "",
) -> HookEvent:
    """Crea un evento context:compact."""
    return create_hook_event(
        HookEventType.CONTEXT,
        "compact",
        session_key=session_key,
        context={
            "session_id": ctx.session_id,
            "messages_before": ctx.messages_before,
            "messages_after": ctx.messages_after,
            "tokens_saved": ctx.tokens_saved,
            "strategy": ctx.strategy,
        },
    )


def create_skill_event(
    action: str,
    ctx: SkillExecutionContext,
    session_key: str = "",
) -> HookEvent:
    """Crea un evento skill:execute / skill:complete / skill:error."""
    return create_hook_event(
        HookEventType.SKILL,
        action,
        session_key=session_key,
        context={
            "skill_name": ctx.skill_name,
            "session_id": ctx.session_id,
            "trigger": ctx.trigger,
            "duration_ms": ctx.duration_ms,
            "success": ctx.success,
            "error": ctx.error,
        },
    )


# ============================================================================
# Type guards — validacion de tipo de evento
# ============================================================================

def _is_event_type_and_action(
    event: HookEvent,
    event_type: HookEventType,
    action: str,
) -> bool:
    """Verifica si el evento coincide con tipo y accion dados."""
    actual_type = event.type.value if isinstance(event.type, HookEventType) else str(event.type)
    expected_type = event_type.value if isinstance(event_type, HookEventType) else str(event_type)
    return actual_type == expected_type and event.action == action


def _get_context_str(event: HookEvent, key: str) -> Optional[str]:
    """Obtiene un campo string del contexto de un evento."""
    val = event.context.get(key)
    return val if isinstance(val, str) else None


def _has_str_field(event: HookEvent, key: str) -> bool:
    """Verifica que un campo del contexto sea string."""
    return isinstance(event.context.get(key), str)


def _has_bool_field(event: HookEvent, key: str) -> bool:
    """Verifica que un campo del contexto sea bool."""
    return isinstance(event.context.get(key), bool)


def is_agent_bootstrap_event(event: HookEvent) -> bool:
    """Verifica si el evento es un agent:bootstrap valido."""
    if not _is_event_type_and_action(event, HookEventType.AGENT, "bootstrap"):
        return False
    if not _has_str_field(event, "workspace_dir"):
        return False
    return isinstance(event.context.get("bootstrap_files"), list)


def is_gateway_startup_event(event: HookEvent) -> bool:
    """Verifica si el evento es un gateway:startup valido."""
    return _is_event_type_and_action(event, HookEventType.GATEWAY, "startup")


def is_message_received_event(event: HookEvent) -> bool:
    """Verifica si el evento es un message:received valido."""
    if not _is_event_type_and_action(event, HookEventType.MESSAGE, "received"):
        return False
    return _has_str_field(event, "sender") and _has_str_field(event, "channel_id")


def is_message_sent_event(event: HookEvent) -> bool:
    """Verifica si el evento es un message:sent valido."""
    if not _is_event_type_and_action(event, HookEventType.MESSAGE, "sent"):
        return False
    return (
        _has_str_field(event, "recipient")
        and _has_str_field(event, "channel_id")
        and _has_bool_field(event, "success")
    )


def is_message_transcribed_event(event: HookEvent) -> bool:
    """Verifica si el evento es un message:transcribed valido."""
    if not _is_event_type_and_action(event, HookEventType.MESSAGE, "transcribed"):
        return False
    return _has_str_field(event, "transcript") and _has_str_field(event, "channel_id")


def is_message_preprocessed_event(event: HookEvent) -> bool:
    """Verifica si el evento es un message:preprocessed valido."""
    if not _is_event_type_and_action(event, HookEventType.MESSAGE, "preprocessed"):
        return False
    return _has_str_field(event, "channel_id")


def is_session_event(event: HookEvent, action: Optional[str] = None) -> bool:
    """Verifica si el evento es de tipo session, opcionalmente con una accion especifica."""
    actual_type = event.type.value if isinstance(event.type, HookEventType) else str(event.type)
    if actual_type != HookEventType.SESSION.value:
        return False
    if action is not None and event.action != action:
        return False
    return True


def is_error_event(event: HookEvent) -> bool:
    """Verifica si el evento es de tipo error."""
    return _is_event_type_and_action(event, HookEventType.AGENT, "error")


def is_provider_switch_event(event: HookEvent) -> bool:
    """Verifica si el evento es un provider:switch valido."""
    if not _is_event_type_and_action(event, HookEventType.PROVIDER, "switch"):
        return False
    return _has_str_field(event, "new_provider") and _has_str_field(event, "new_model")


# ============================================================================
# Message hook mappers — transformacion de contextos
# ============================================================================

@dataclass
class CanonicalInboundContext:
    """Contexto canonico para un mensaje entrante.

    Normaliza los datos de cualquier canal a un formato comun,
    permitiendo que los hooks procesen mensajes de forma unificada.
    """
    sender: str = ""
    recipient: Optional[str] = None
    content: str = ""
    body: Optional[str] = None
    body_for_agent: Optional[str] = None
    transcript: Optional[str] = None
    timestamp: Optional[float] = None
    channel_id: str = ""
    account_id: Optional[str] = None
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    sender_id: Optional[str] = None
    sender_name: Optional[str] = None
    sender_username: Optional[str] = None
    provider: Optional[str] = None
    surface: Optional[str] = None
    thread_id: Optional[str] = None
    media_path: Optional[str] = None
    media_type: Optional[str] = None
    originating_channel: Optional[str] = None
    guild_id: Optional[str] = None
    channel_name: Optional[str] = None
    is_group: bool = False
    group_id: Optional[str] = None


@dataclass
class CanonicalSentContext:
    """Contexto canonico para un mensaje enviado."""
    recipient: str = ""
    content: str = ""
    success: bool = True
    error: Optional[str] = None
    channel_id: str = ""
    account_id: Optional[str] = None
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    is_group: bool = False
    group_id: Optional[str] = None


def _strip_channel_prefix(value: Optional[str], channel_id: str) -> Optional[str]:
    """Elimina prefijos de canal conocidos de un valor.

    Soporta prefijos genericos (channel:, chat:, user:) y
    prefijos especificos del canal.
    """
    if not value:
        return None
    generic_prefixes = ("channel:", "chat:", "user:")
    for prefix in generic_prefixes:
        if value.startswith(prefix):
            return value[len(prefix):]
    channel_prefix = f"{channel_id}:"
    if value.startswith(channel_prefix):
        return value[len(channel_prefix):]
    return value


def derive_conversation_id(canonical: CanonicalInboundContext) -> Optional[str]:
    """Deriva el ID de conversacion canonico a partir del contexto de entrada.

    Aplica logica especifica por canal (Discord, Telegram, etc.) para
    normalizar IDs de conversacion.
    """
    # Logica especifica para Discord
    if canonical.channel_id == "discord":
        raw_target = canonical.recipient or canonical.conversation_id
        raw_sender = canonical.sender
        # Extraer user ID de Discord
        sender_user_id: Optional[str] = None
        if raw_sender:
            if raw_sender.startswith("discord:user:"):
                sender_user_id = raw_sender[len("discord:user:"):]
            elif raw_sender.startswith("discord:"):
                sender_user_id = raw_sender[len("discord:"):]

        if not canonical.is_group and sender_user_id:
            return f"user:{sender_user_id}"

        if raw_target:
            if raw_target.startswith("discord:channel:"):
                return f"channel:{raw_target[len('discord:channel:'):]}"
            if raw_target.startswith("discord:user:"):
                return f"user:{raw_target[len('discord:user:'):]}"
            if raw_target.startswith("discord:"):
                return f"user:{raw_target[len('discord:'):]}"
            if raw_target.startswith("channel:") or raw_target.startswith("user:"):
                return raw_target
        return None

    # ID base (generico para todos los canales)
    base_id = _strip_channel_prefix(
        canonical.recipient or canonical.conversation_id,
        canonical.channel_id,
    )

    # Logica especifica para Telegram (soporte de topics/threads)
    if canonical.channel_id == "telegram" and base_id:
        thread_id = canonical.thread_id
        if thread_id:
            return f"{base_id}:topic:{thread_id}"

    return base_id


def derive_parent_conversation_id(
    canonical: CanonicalInboundContext,
) -> Optional[str]:
    """Deriva el ID de la conversacion padre (solo relevante en Telegram topics)."""
    if canonical.channel_id != "telegram":
        return None
    if canonical.thread_id is None:
        return None
    return _strip_channel_prefix(
        canonical.recipient or canonical.conversation_id,
        "telegram",
    )


def inbound_to_received_context(canonical: CanonicalInboundContext) -> MessageReceivedContext:
    """Convierte un contexto canonico de entrada a un MessageReceivedContext.

    Usado para disparar el hook message:received desde datos canonicos.
    """
    return MessageReceivedContext(
        sender=canonical.sender,
        content=canonical.content,
        timestamp=canonical.timestamp,
        channel_id=canonical.channel_id,
        account_id=canonical.account_id,
        conversation_id=canonical.conversation_id,
        message_id=canonical.message_id,
        metadata={
            k: v
            for k, v in {
                "recipient": canonical.recipient,
                "provider": canonical.provider,
                "surface": canonical.surface,
                "thread_id": canonical.thread_id,
                "sender_id": canonical.sender_id,
                "sender_name": canonical.sender_name,
                "sender_username": canonical.sender_username,
                "guild_id": canonical.guild_id,
                "channel_name": canonical.channel_name,
            }.items()
            if v is not None
        },
    )


def inbound_to_transcribed_context(
    canonical: CanonicalInboundContext,
) -> MessageTranscribedContext:
    """Convierte un contexto canonico a MessageTranscribedContext."""
    return MessageTranscribedContext(
        sender=canonical.sender,
        recipient=canonical.recipient,
        body=canonical.body,
        body_for_agent=canonical.body_for_agent,
        transcript=canonical.transcript or "",
        timestamp=canonical.timestamp,
        channel_id=canonical.channel_id,
        conversation_id=canonical.conversation_id,
        message_id=canonical.message_id,
        sender_id=canonical.sender_id,
        sender_name=canonical.sender_name,
        sender_username=canonical.sender_username,
        provider=canonical.provider,
        surface=canonical.surface,
        media_path=canonical.media_path,
        media_type=canonical.media_type,
    )


def inbound_to_preprocessed_context(
    canonical: CanonicalInboundContext,
) -> MessagePreprocessedContext:
    """Convierte un contexto canonico a MessagePreprocessedContext."""
    return MessagePreprocessedContext(
        sender=canonical.sender,
        recipient=canonical.recipient,
        body=canonical.body,
        body_for_agent=canonical.body_for_agent,
        transcript=canonical.transcript,
        timestamp=canonical.timestamp,
        channel_id=canonical.channel_id,
        conversation_id=canonical.conversation_id,
        message_id=canonical.message_id,
        sender_id=canonical.sender_id,
        sender_name=canonical.sender_name,
        sender_username=canonical.sender_username,
        provider=canonical.provider,
        surface=canonical.surface,
        media_path=canonical.media_path,
        media_type=canonical.media_type,
        is_group=canonical.is_group,
        group_id=canonical.group_id,
    )


def sent_to_sent_context(canonical: CanonicalSentContext) -> MessageSentContext:
    """Convierte un contexto canonico de envio a MessageSentContext."""
    return MessageSentContext(
        recipient=canonical.recipient,
        content=canonical.content,
        success=canonical.success,
        error=canonical.error,
        channel_id=canonical.channel_id,
        account_id=canonical.account_id,
        conversation_id=canonical.conversation_id or canonical.recipient,
        message_id=canonical.message_id,
        is_group=canonical.is_group,
        group_id=canonical.group_id,
    )


# ============================================================================
# Hooks built-in de SOMER
# ============================================================================

async def _builtin_log_startup(event: HookEvent) -> None:
    """Hook built-in: loggea el inicio de SOMER."""
    host = event.context.get("host", "?")
    port = event.context.get("port", "?")
    logger.info("SOMER 2.0 iniciado — gateway en %s:%s", host, port)


async def _builtin_log_shutdown(event: HookEvent) -> None:
    """Hook built-in: loggea la detencion de SOMER."""
    logger.info("SOMER 2.0 detenido")


async def _builtin_log_session_create(event: HookEvent) -> None:
    """Hook built-in: loggea la creacion de sesion."""
    sid = event.context.get("session_id", "unknown")
    channel = event.context.get("channel", "?")
    logger.info("Sesion creada: %s (canal: %s)", sid, channel)


async def _builtin_log_session_close(event: HookEvent) -> None:
    """Hook built-in: loggea el cierre de sesion."""
    sid = event.context.get("session_id", "unknown")
    reason = event.context.get("reason", "normal")
    logger.info("Sesion cerrada: %s (razon: %s)", sid, reason)


async def _builtin_log_error(event: HookEvent) -> None:
    """Hook built-in: loggea errores."""
    error_type = event.context.get("error_type", "unknown")
    error_msg = event.context.get("error_message", "sin detalle")
    source = event.context.get("source", "?")
    logger.error("Error [%s] en %s: %s", error_type, source, error_msg)


async def _builtin_log_message_received(event: HookEvent) -> None:
    """Hook built-in: loggea mensajes recibidos."""
    sender = event.context.get("sender", "?")
    channel = event.context.get("channel_id", "?")
    content_preview = (event.context.get("content", "") or "")[:80]
    logger.debug(
        "Mensaje recibido de %s via %s: %s%s",
        sender,
        channel,
        content_preview,
        "..." if len(event.context.get("content", "") or "") > 80 else "",
    )


async def _builtin_log_message_sent(event: HookEvent) -> None:
    """Hook built-in: loggea mensajes enviados."""
    recipient = event.context.get("recipient", "?")
    channel = event.context.get("channel_id", "?")
    success = event.context.get("success", True)
    if success:
        logger.debug("Mensaje enviado a %s via %s", recipient, channel)
    else:
        error = event.context.get("error", "sin detalle")
        logger.warning("Fallo envio a %s via %s: %s", recipient, channel, error)


async def _builtin_log_provider_switch(event: HookEvent) -> None:
    """Hook built-in: loggea cambios de provider."""
    old_p = event.context.get("old_provider", "?")
    new_p = event.context.get("new_provider", "?")
    old_m = event.context.get("old_model", "?")
    new_m = event.context.get("new_model", "?")
    reason = event.context.get("reason", "")
    logger.info(
        "Provider switch: %s/%s -> %s/%s%s",
        old_p,
        old_m,
        new_p,
        new_m,
        f" ({reason})" if reason else "",
    )


# ── Tabla de hooks built-in ──────────────────────────────────────

_BUILTIN_HOOKS: List[tuple] = [
    # (event_key, handler, priority, name)
    ("gateway:startup", _builtin_log_startup, 100, "builtin:log_startup"),
    ("gateway:shutdown", _builtin_log_shutdown, 100, "builtin:log_shutdown"),
    ("session:create", _builtin_log_session_create, 100, "builtin:log_session_create"),
    ("session:close", _builtin_log_session_close, 100, "builtin:log_session_close"),
    ("agent:error", _builtin_log_error, 100, "builtin:log_error"),
    ("message:received", _builtin_log_message_received, 100, "builtin:log_message_received"),
    ("message:sent", _builtin_log_message_sent, 100, "builtin:log_message_sent"),
    ("provider:switch", _builtin_log_provider_switch, 100, "builtin:log_provider_switch"),
]


def install_builtin_hooks() -> int:
    """Registra todos los hooks built-in de SOMER.

    Los hooks built-in tienen prioridad alta (100) para ejecutarse despues
    de hooks de usuario (prioridad 0 por default).

    Returns:
        Numero de hooks instalados.
    """
    installed = 0
    for event_key, handler, priority, name in _BUILTIN_HOOKS:
        register_internal_hook(event_key, handler, priority=priority, name=name)
        installed += 1
    logger.debug("Instalados %d hooks built-in", installed)
    return installed


def uninstall_builtin_hooks() -> int:
    """Desregistra todos los hooks built-in.

    Returns:
        Numero de hooks removidos.
    """
    removed = 0
    for event_key, handler, _, _ in _BUILTIN_HOOKS:
        if unregister_internal_hook(event_key, handler):
            removed += 1
    return removed
