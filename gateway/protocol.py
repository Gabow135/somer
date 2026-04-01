"""Protocolo JSON-RPC 2.0 para el Gateway — portado de OpenClaw.

Implementa el protocolo completo de comunicación WebSocket del gateway,
incluyendo frames de request/response/event, códigos de error,
modelos de batch request y registro de métodos.

Ref: OpenClaw src/gateway/protocol/schema/frames.ts,
     src/gateway/protocol/schema/error-codes.ts,
     src/gateway/protocol/index.ts,
     src/gateway/server-methods-list.ts
"""

from __future__ import annotations

import re
import time
import uuid
from enum import Enum, IntEnum
from typing import (
    Any,
    Callable,
    Coroutine,
    Dict,
    List,
    Literal,
    Optional,
    Sequence,
    Union,
)

from pydantic import BaseModel, Field, field_validator


# ── Versión del protocolo ────────────────────────────────────
PROTOCOL_VERSION = 3


# ── Códigos de error estándar JSON-RPC ───────────────────────
class JsonRpcErrorCode(IntEnum):
    """Códigos de error estándar JSON-RPC 2.0 y extensiones SOMER."""

    # Estándar JSON-RPC 2.0
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603

    # Rango reservado servidor (-32099 a -32000)
    SERVER_ERROR = -32000

    # Extensiones SOMER
    SESSION_NOT_FOUND = -32001
    PROVIDER_ERROR = -32002
    CHANNEL_ERROR = -32003
    AUTH_ERROR = -32004
    RATE_LIMIT = -32005
    AGENT_TIMEOUT = -32006
    UNAVAILABLE = -32007


# Aliases para compatibilidad con código existente
PARSE_ERROR = JsonRpcErrorCode.PARSE_ERROR
INVALID_REQUEST = JsonRpcErrorCode.INVALID_REQUEST
METHOD_NOT_FOUND = JsonRpcErrorCode.METHOD_NOT_FOUND
INVALID_PARAMS = JsonRpcErrorCode.INVALID_PARAMS
INTERNAL_ERROR = JsonRpcErrorCode.INTERNAL_ERROR
SERVER_ERROR = JsonRpcErrorCode.SERVER_ERROR
SESSION_NOT_FOUND = JsonRpcErrorCode.SESSION_NOT_FOUND
PROVIDER_ERROR = JsonRpcErrorCode.PROVIDER_ERROR
CHANNEL_ERROR = JsonRpcErrorCode.CHANNEL_ERROR
AUTH_ERROR = JsonRpcErrorCode.AUTH_ERROR
RATE_LIMIT = JsonRpcErrorCode.RATE_LIMIT
AGENT_TIMEOUT = JsonRpcErrorCode.AGENT_TIMEOUT
UNAVAILABLE = JsonRpcErrorCode.UNAVAILABLE


# ── Códigos de error de nivel aplicación (OpenClaw style) ────
class ErrorCode(str, Enum):
    """Códigos de error semánticos del gateway (portados de OpenClaw)."""

    NOT_LINKED = "NOT_LINKED"
    NOT_PAIRED = "NOT_PAIRED"
    AGENT_TIMEOUT = "AGENT_TIMEOUT"
    INVALID_REQUEST = "INVALID_REQUEST"
    UNAVAILABLE = "UNAVAILABLE"
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"
    AUTH_FAILED = "AUTH_FAILED"


class ErrorShape(BaseModel):
    """Forma estandarizada de error en respuestas del gateway.

    Portado de OpenClaw: ErrorShapeSchema en frames.ts
    """

    code: str
    message: str
    details: Optional[Any] = None
    retryable: Optional[bool] = None
    retry_after_ms: Optional[int] = Field(None, ge=0)


def error_shape(
    code: Union[ErrorCode, str],
    message: str,
    *,
    details: Optional[Any] = None,
    retryable: Optional[bool] = None,
    retry_after_ms: Optional[int] = None,
) -> ErrorShape:
    """Crea un ErrorShape de forma conveniente (equivalente a errorShape() de OpenClaw)."""
    code_val = code.value if isinstance(code, ErrorCode) else code
    return ErrorShape(
        code=code_val,
        message=message,
        details=details,
        retryable=retryable,
        retry_after_ms=retry_after_ms,
    )


# ── Frame types (OpenClaw frame protocol) ────────────────────

class FrameType(str, Enum):
    """Tipos de frame del protocolo WebSocket."""

    REQUEST = "req"
    RESPONSE = "res"
    EVENT = "event"


class RequestFrame(BaseModel):
    """Frame de petición — equivalente a RequestFrameSchema de OpenClaw.

    El cliente envía un request y espera un response con el mismo id.
    """

    type: Literal["req"] = "req"
    id: str
    method: str
    params: Optional[Any] = None

    @field_validator("id")
    @classmethod
    def _id_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("id no puede estar vacío")
        return v

    @field_validator("method")
    @classmethod
    def _method_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("method no puede estar vacío")
        return v


class ResponseFrame(BaseModel):
    """Frame de respuesta — equivalente a ResponseFrameSchema de OpenClaw."""

    type: Literal["res"] = "res"
    id: str
    ok: bool
    payload: Optional[Any] = None
    error: Optional[ErrorShape] = None

    @classmethod
    def success(
        cls, req_id: str, payload: Optional[Any] = None
    ) -> "ResponseFrame":
        """Crea un response frame exitoso."""
        return cls(id=req_id, ok=True, payload=payload)

    @classmethod
    def failure(
        cls,
        req_id: str,
        code: Union[ErrorCode, str],
        message: str,
        *,
        details: Optional[Any] = None,
        retryable: Optional[bool] = None,
        retry_after_ms: Optional[int] = None,
    ) -> "ResponseFrame":
        """Crea un response frame con error."""
        return cls(
            id=req_id,
            ok=False,
            error=error_shape(
                code,
                message,
                details=details,
                retryable=retryable,
                retry_after_ms=retry_after_ms,
            ),
        )


class StateVersion(BaseModel):
    """Versión de estado para tracking de cambios.

    Portado de OpenClaw: StateVersionSchema.
    """

    health: Optional[int] = None
    presence: Optional[int] = None
    sessions: Optional[int] = None


class EventFrame(BaseModel):
    """Frame de evento (push del servidor) — equivalente a EventFrameSchema.

    El servidor envía eventos a clientes suscritos sin solicitud previa.
    """

    type: Literal["event"] = "event"
    event: str
    payload: Optional[Any] = None
    seq: Optional[int] = Field(None, ge=0)
    state_version: Optional[StateVersion] = None

    @field_validator("event")
    @classmethod
    def _event_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("event no puede estar vacío")
        return v


# Tipo unión para frames entrantes/salientes
GatewayFrame = Union[RequestFrame, ResponseFrame, EventFrame]


# ── JSON-RPC 2.0 clásico (compatibilidad) ───────────────────

class JsonRpcRequest(BaseModel):
    """Petición JSON-RPC 2.0 (formato clásico, compatibilidad con SOMER 1.x)."""

    jsonrpc: str = "2.0"
    method: str
    params: Optional[Dict[str, Any]] = None
    id: Optional[Union[str, int]] = Field(default_factory=lambda: uuid.uuid4().hex[:8])


class JsonRpcResponse(BaseModel):
    """Respuesta JSON-RPC 2.0 (formato clásico, compatibilidad con SOMER 1.x)."""

    jsonrpc: str = "2.0"
    result: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None
    id: Optional[Union[str, int]] = None

    @classmethod
    def success(cls, result: Any, req_id: Optional[Union[str, int]] = None) -> "JsonRpcResponse":
        """Crea una respuesta exitosa."""
        return cls(result=result, id=req_id)

    @classmethod
    def error_response(
        cls,
        code: int,
        message: str,
        data: Optional[Any] = None,
        req_id: Optional[Union[str, int]] = None,
    ) -> "JsonRpcResponse":
        """Crea una respuesta de error."""
        error: Dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        return cls(error=error, id=req_id)


class JsonRpcNotification(BaseModel):
    """Notificación JSON-RPC 2.0 (sin id, no espera respuesta)."""

    jsonrpc: str = "2.0"
    method: str
    params: Optional[Dict[str, Any]] = None


class JsonRpcBatchRequest(BaseModel):
    """Batch de peticiones JSON-RPC 2.0.

    Permite enviar múltiples requests en un solo mensaje WebSocket.
    """

    requests: List[JsonRpcRequest]

    @field_validator("requests")
    @classmethod
    def _non_empty(cls, v: List[JsonRpcRequest]) -> List[JsonRpcRequest]:
        if not v:
            raise ValueError("Un batch debe contener al menos una petición")
        return v


class JsonRpcBatchResponse(BaseModel):
    """Batch de respuestas JSON-RPC 2.0."""

    responses: List[JsonRpcResponse]


# ── Modelos de conexión (hello handshake) ────────────────────

class ClientInfo(BaseModel):
    """Información del cliente al conectarse.

    Portado de OpenClaw: ConnectParams.client
    """

    id: str
    display_name: Optional[str] = None
    version: str
    platform: str
    device_family: Optional[str] = None
    model_identifier: Optional[str] = None
    mode: str = "default"
    instance_id: Optional[str] = None


class ConnectAuthParams(BaseModel):
    """Parámetros de autenticación en la conexión."""

    token: Optional[str] = None
    bootstrap_token: Optional[str] = None
    device_token: Optional[str] = None
    password: Optional[str] = None


class ConnectParams(BaseModel):
    """Parámetros de conexión — equivalente a ConnectParamsSchema de OpenClaw."""

    min_protocol: int = Field(ge=1, default=1)
    max_protocol: int = Field(ge=1, default=PROTOCOL_VERSION)
    client: ClientInfo
    caps: List[str] = Field(default_factory=list)
    commands: Optional[List[str]] = None
    permissions: Optional[Dict[str, bool]] = None
    role: Optional[str] = None
    scopes: Optional[List[str]] = None
    auth: Optional[ConnectAuthParams] = None
    locale: Optional[str] = None
    user_agent: Optional[str] = None


class HelloOk(BaseModel):
    """Respuesta de handshake exitoso — equivalente a HelloOkSchema.

    Se envía al cliente tras autenticación y negociación de protocolo.
    """

    type: Literal["hello-ok"] = "hello-ok"
    protocol: int = PROTOCOL_VERSION
    server: Dict[str, str] = Field(default_factory=dict)
    features: Dict[str, List[str]] = Field(default_factory=dict)
    snapshot: Optional[Dict[str, Any]] = None
    policy: Dict[str, int] = Field(default_factory=lambda: {
        "max_payload": 1_048_576,       # 1 MiB
        "max_buffered_bytes": 4_194_304, # 4 MiB
        "tick_interval_ms": 30_000,      # 30 seg
    })


# ── Eventos del gateway ──────────────────────────────────────

class GatewayEvent(BaseModel):
    """Evento del gateway para pub/sub (formato SOMER)."""

    type: str
    session_id: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)
    seq: Optional[int] = None

    def to_event_frame(self) -> EventFrame:
        """Convierte a EventFrame del protocolo OpenClaw."""
        return EventFrame(
            event=self.type,
            payload={
                "session_id": self.session_id,
                **self.data,
                "ts": self.timestamp,
            },
            seq=self.seq,
        )


class TickEvent(BaseModel):
    """Evento de tick periódico del gateway (keepalive)."""

    ts: int = Field(default_factory=lambda: int(time.time() * 1000))


class ShutdownEvent(BaseModel):
    """Evento de shutdown del gateway."""

    reason: str
    restart_expected_ms: Optional[int] = Field(None, ge=0)


# ── Eventos conocidos ────────────────────────────────────────

GATEWAY_EVENTS = [
    "connect.challenge",
    "agent",
    "chat",
    "session.message",
    "session.tool",
    "sessions.changed",
    "presence",
    "tick",
    "shutdown",
    "health",
    "heartbeat",
    "channel.status",
    "provider.status",
    "update.available",
]


# ── Métodos base del gateway ────────────────────────────────

BASE_METHODS = [
    # Sistema
    "ping",
    "health",
    "status",
    "version",
    # Sesiones
    "sessions.list",
    "sessions.create",
    "sessions.send",
    "sessions.abort",
    "sessions.patch",
    "sessions.reset",
    "sessions.delete",
    "sessions.compact",
    "sessions.resolve",
    "sessions.preview",
    "sessions.usage",
    "sessions.subscribe",
    "sessions.unsubscribe",
    "sessions.messages.subscribe",
    "sessions.messages.unsubscribe",
    # Config
    "config.get",
    "config.set",
    "config.apply",
    "config.patch",
    "config.schema",
    # Agentes
    "agents.list",
    "agents.create",
    "agents.update",
    "agents.delete",
    "agents.files.list",
    "agents.files.get",
    "agents.files.set",
    "agent",
    "agent.wait",
    "agent.identity.get",
    # Modelos y skills
    "models.list",
    "skills.status",
    "skills.install",
    "skills.update",
    "tools.catalog",
    # Canales
    "channels.status",
    "channels.list",
    "channels.logout",
    # Providers
    "providers.list",
    # Envío
    "send",
    # Logs
    "logs.tail",
    # Nodos
    "node.list",
    "node.describe",
    "node.pair.request",
    "node.pair.list",
    "node.pair.approve",
    "node.pair.reject",
    "node.pair.verify",
    "node.rename",
    "node.invoke",
    "node.invoke.result",
    "node.event",
    "node.pending.drain",
    "node.pending.enqueue",
    "node.pending.pull",
    "node.pending.ack",
    # Cron
    "cron.list",
    "cron.status",
    "cron.add",
    "cron.update",
    "cron.remove",
    "cron.run",
    "cron.runs",
    # Wizard
    "wizard.start",
    "wizard.next",
    "wizard.cancel",
    "wizard.status",
    # Secretos
    "secrets.reload",
    "secrets.resolve",
    # Doctor
    "doctor.memory.status",
    # TTS
    "tts.status",
    "tts.providers",
    "tts.enable",
    "tts.disable",
    "tts.convert",
    "tts.setProvider",
    # Heartbeat
    "last-heartbeat",
    "set-heartbeats",
    "wake",
    # Uso
    "usage.status",
    "usage.cost",
    # Updates
    "update.run",
    # Chat nativo (WebChat)
    "chat.history",
    "chat.send",
    "chat.abort",
    # Gateway identity
    "gateway.identity.get",
    "system-presence",
    "system-event",
]


# ── Registro de métodos ──────────────────────────────────────

# Type alias para handlers
MethodHandler = Callable[
    [Dict[str, Any]], Coroutine[Any, Any, Any]
]


class MethodRegistry:
    """Registro centralizado de métodos RPC del gateway.

    Portado de OpenClaw: server-methods-list.ts + patrón de registro
    en server.impl.ts. Permite registrar handlers con metadata,
    validación de parámetros, y permisos.
    """

    def __init__(self) -> None:
        self._handlers: Dict[str, MethodHandler] = {}
        self._metadata: Dict[str, MethodMeta] = {}

    def register(
        self,
        name: str,
        handler: MethodHandler,
        *,
        description: Optional[str] = None,
        auth_required: bool = False,
        scopes: Optional[List[str]] = None,
    ) -> None:
        """Registra un método RPC con metadata opcional."""
        self._handlers[name] = handler
        self._metadata[name] = MethodMeta(
            name=name,
            description=description or "",
            auth_required=auth_required,
            scopes=scopes or [],
        )

    def unregister(self, name: str) -> None:
        """Desregistra un método."""
        self._handlers.pop(name, None)
        self._metadata.pop(name, None)

    def get(self, name: str) -> Optional[MethodHandler]:
        """Obtiene el handler de un método."""
        return self._handlers.get(name)

    def has(self, name: str) -> bool:
        """Verifica si un método está registrado."""
        return name in self._handlers

    def get_meta(self, name: str) -> Optional["MethodMeta"]:
        """Obtiene la metadata de un método."""
        return self._metadata.get(name)

    @property
    def names(self) -> List[str]:
        """Lista de nombres de métodos registrados."""
        return list(self._handlers.keys())

    @property
    def count(self) -> int:
        """Número de métodos registrados."""
        return len(self._handlers)

    def merge(self, other: "MethodRegistry") -> None:
        """Fusiona otro registry dentro de éste."""
        self._handlers.update(other._handlers)
        self._metadata.update(other._metadata)

    def list_methods(self) -> List["MethodMeta"]:
        """Lista toda la metadata de métodos registrados."""
        return list(self._metadata.values())


class MethodMeta(BaseModel):
    """Metadata de un método RPC registrado."""

    name: str
    description: str = ""
    auth_required: bool = False
    scopes: List[str] = Field(default_factory=list)


# ── Sesiones: modelos de parámetros para métodos ─────────────
# Portados de OpenClaw: protocol/schema/sessions.ts

class SessionsListParams(BaseModel):
    """Parámetros para sessions.list."""

    limit: Optional[int] = Field(None, ge=1)
    active_minutes: Optional[int] = Field(None, ge=1)
    include_global: Optional[bool] = None
    include_unknown: Optional[bool] = None
    include_derived_titles: Optional[bool] = None
    include_last_message: Optional[bool] = None
    label: Optional[str] = None
    spawned_by: Optional[str] = None
    agent_id: Optional[str] = None
    search: Optional[str] = None


class SessionsCreateParams(BaseModel):
    """Parámetros para sessions.create."""

    key: Optional[str] = None
    agent_id: Optional[str] = None
    label: Optional[str] = None
    model: Optional[str] = None
    parent_session_key: Optional[str] = None
    task: Optional[str] = None
    message: Optional[str] = None


class SessionsSendParams(BaseModel):
    """Parámetros para sessions.send."""

    key: str
    message: str
    thinking: Optional[str] = None
    attachments: Optional[List[Any]] = None
    timeout_ms: Optional[int] = Field(None, ge=0)
    idempotency_key: Optional[str] = None


class SessionsResolveParams(BaseModel):
    """Parámetros para sessions.resolve."""

    key: Optional[str] = None
    session_id: Optional[str] = None
    label: Optional[str] = None
    agent_id: Optional[str] = None
    spawned_by: Optional[str] = None
    include_global: Optional[bool] = None
    include_unknown: Optional[bool] = None


class SessionsPatchParams(BaseModel):
    """Parámetros para sessions.patch."""

    key: str
    label: Optional[str] = None
    model: Optional[str] = None
    thinking_level: Optional[str] = None
    verbose_level: Optional[str] = None
    reasoning_level: Optional[str] = None
    elevated_level: Optional[str] = None
    send_policy: Optional[Literal["allow", "deny"]] = None
    response_usage: Optional[Literal["on", "off", "tokens", "full"]] = None
    spawned_by: Optional[str] = None


class SessionsResetParams(BaseModel):
    """Parámetros para sessions.reset."""

    key: str
    reason: Optional[Literal["new", "reset"]] = None


class SessionsDeleteParams(BaseModel):
    """Parámetros para sessions.delete."""

    key: str
    delete_transcript: Optional[bool] = None


class SessionsAbortParams(BaseModel):
    """Parámetros para sessions.abort."""

    key: str
    run_id: Optional[str] = None


class SessionsCompactParams(BaseModel):
    """Parámetros para sessions.compact."""

    key: str
    max_lines: Optional[int] = Field(None, ge=1)


class SessionsPreviewParams(BaseModel):
    """Parámetros para sessions.preview."""

    keys: List[str]
    limit: Optional[int] = Field(None, ge=1)
    max_chars: Optional[int] = Field(None, ge=20)


class SessionsUsageParams(BaseModel):
    """Parámetros para sessions.usage."""

    key: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    mode: Optional[Literal["utc", "gateway", "specific"]] = None
    utc_offset: Optional[str] = None
    limit: Optional[int] = Field(None, ge=1)
    include_context_weight: Optional[bool] = None

    @field_validator("start_date", "end_date")
    @classmethod
    def _validate_date_format(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            raise ValueError("Formato de fecha inválido, se espera YYYY-MM-DD")
        return v

    @field_validator("utc_offset")
    @classmethod
    def _validate_utc_offset(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not re.match(
            r"^UTC[+-]\d{1,2}(?::[0-5]\d)?$", v
        ):
            raise ValueError("Formato de UTC offset inválido, se espera UTC+/-N[:MM]")
        return v


# ── Helpers de parseo ────────────────────────────────────────

def parse_gateway_frame(data: Dict[str, Any]) -> Optional[GatewayFrame]:
    """Parsea un dict como GatewayFrame, retornando None si es inválido.

    Usa el campo 'type' como discriminador (OpenClaw pattern).
    """
    frame_type = data.get("type")
    try:
        if frame_type == "req":
            return RequestFrame.model_validate(data)
        elif frame_type == "res":
            return ResponseFrame.model_validate(data)
        elif frame_type == "event":
            return EventFrame.model_validate(data)
        else:
            return None
    except Exception:
        return None


def is_batch_request(data: Any) -> bool:
    """Determina si un payload es un batch request (lista de requests)."""
    return isinstance(data, list) and len(data) > 0


def format_validation_errors(errors: Sequence[Dict[str, Any]]) -> str:
    """Formatea errores de validación Pydantic en un string legible.

    Portado de OpenClaw: formatValidationErrors() en protocol/index.ts
    """
    if not errors:
        return "error de validación desconocido"

    parts: List[str] = []
    for err in errors:
        loc = err.get("loc", [])
        msg = err.get("msg", "error de validación")
        path = ".".join(str(l) for l in loc) if loc else "raíz"
        parts.append(f"en {path}: {msg}")

    # Eliminar duplicados preservando orden
    seen = set()
    unique: List[str] = []
    for part in parts:
        normalized = part.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)

    return "; ".join(unique) if unique else "error de validación desconocido"
