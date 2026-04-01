"""Tipos core de SOMER 2.0 — Pydantic v2."""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ── Enums ────────────────────────────────────────────────────
class Role(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class ResponseType(str, Enum):
    TEXT = "text"
    CODE = "code"
    DATA = "data"
    ERROR = "error"
    CONFIG = "config"
    INFO = "info"


class SessionStatus(str, Enum):
    ACTIVE = "active"
    IDLE = "idle"
    CLOSED = "closed"
    ERROR = "error"


class ChannelType(str, Enum):
    TELEGRAM = "telegram"
    SLACK = "slack"
    DISCORD = "discord"
    WHATSAPP = "whatsapp"
    SIGNAL = "signal"
    MATRIX = "matrix"
    IRC = "irc"
    MSTEAMS = "msteams"
    GOOGLECHAT = "googlechat"
    LINE = "line"
    TWITCH = "twitch"
    MATTERMOST = "mattermost"
    NOSTR = "nostr"
    FEISHU = "feishu"
    WEBCHAT = "webchat"
    CLI = "cli"
    API = "api"


ModelApi = Literal[
    "anthropic-messages",
    "openai-completions",
    "openai-responses",
    "google-generative-ai",
    "ollama",
    "bedrock-converse-stream",
    "deepseek",
]


# ── Mensajes ─────────────────────────────────────────────────
class Message(BaseModel):
    role: Role
    content: str
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)


class ToolCall(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    tool_call_id: str
    content: str
    is_error: bool = False


# ── Agentes ──────────────────────────────────────────────────
class AgentMessage(BaseModel):
    """Mensaje en el transcript de un agente."""
    role: Role
    content: str
    tool_calls: List[ToolCall] = Field(default_factory=list)
    tool_results: List[ToolResult] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)
    provenance: Optional[InputProvenance] = None


class AgentTurn(BaseModel):
    """Un turno completo de agente (user → assistant → tool results)."""
    messages: List[AgentMessage] = Field(default_factory=list)
    token_count: int = 0
    model: Optional[str] = None


# ── Sesiones ─────────────────────────────────────────────────
class ParsedSessionKey(BaseModel):
    """Session key parseada en sus componentes.

    Portado de OpenClaw: session-key-utils.ts.
    Formato canónico: ``agent:<agentId>:<rest>``.
    """
    agent_id: str
    rest: str


class SessionTranscriptUpdate(BaseModel):
    """Evento de actualización de transcript de sesión.

    Portado de OpenClaw: transcript-events.ts.
    """
    session_file: str
    session_key: Optional[str] = None
    message: Optional[Any] = None
    message_id: Optional[str] = None


class ChatType(str, Enum):
    """Tipo de chat/peer — portado de OpenClaw ChatType.

    Usado para clasificar el tipo de conversación en el routing.
    ``group`` y ``channel`` se tratan como equivalentes en el matching.
    """
    DIRECT = "direct"
    GROUP = "group"
    CHANNEL = "channel"
    THREAD = "thread"


class SessionChatType(str, Enum):
    """Tipo de chat derivado de la session key."""
    DIRECT = "direct"
    GROUP = "group"
    CHANNEL = "channel"
    UNKNOWN = "unknown"


class InputProvenanceKind(str, Enum):
    """Origen de un mensaje de entrada."""
    EXTERNAL_USER = "external_user"
    INTER_SESSION = "inter_session"
    INTERNAL_SYSTEM = "internal_system"


class SendPolicyDecision(str, Enum):
    """Decisión de política de envío."""
    ALLOW = "allow"
    DENY = "deny"


class InputProvenance(BaseModel):
    """Procedencia de un mensaje de entrada.

    Portado de OpenClaw: input-provenance.ts.
    Indica si el mensaje viene de un usuario externo,
    de otra sesión (inter_session) o del sistema interno.
    """
    kind: InputProvenanceKind
    origin_session_id: Optional[str] = None
    source_session_key: Optional[str] = None
    source_channel: Optional[str] = None
    source_tool: Optional[str] = None


class ModelOverrideSelection(BaseModel):
    """Selección de modelo override para una sesión.

    Portado de OpenClaw: model-overrides.ts.
    """
    provider: str
    model: str
    is_default: bool = False


class SessionInfo(BaseModel):
    session_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    session_key: Optional[str] = None
    channel: ChannelType = ChannelType.CLI
    channel_user_id: str = ""
    channel_thread_id: Optional[str] = None
    guild_id: Optional[str] = None
    team_id: Optional[str] = None
    account_id: Optional[str] = None
    status: SessionStatus = SessionStatus.ACTIVE
    chat_type: SessionChatType = SessionChatType.UNKNOWN
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # ── Model overrides (portado de OpenClaw) ───────────────
    provider_override: Optional[str] = None
    model_override: Optional[str] = None
    model: Optional[str] = None
    model_provider: Optional[str] = None
    context_tokens: Optional[int] = None

    # ── Auth profile override ───────────────────────────────
    auth_profile_override: Optional[str] = None
    auth_profile_override_source: Optional[Literal["auto", "user"]] = None
    auth_profile_override_compaction_count: Optional[int] = None

    # ── Fallback notice (se limpia al cambiar modelo) ───────
    fallback_notice_selected_model: Optional[str] = None
    fallback_notice_active_model: Optional[str] = None
    fallback_notice_reason: Optional[str] = None

    # ── Send policy ─────────────────────────────────────────
    send_policy: Optional[SendPolicyDecision] = None
    last_channel: Optional[str] = None

    # ── Input provenance ────────────────────────────────────
    last_provenance: Optional[InputProvenance] = None


# ── Providers ────────────────────────────────────────────────
class ModelCostConfig(BaseModel):
    """Costos por token de un modelo (por millón de tokens).

    Portado de OpenClaw: types.models.ts ``ModelDefinitionConfig.cost``.
    """
    input: float = 0.0
    output: float = 0.0
    cache_read: float = 0.0
    cache_write: float = 0.0


class ModelCompatConfig(BaseModel):
    """Flags de compatibilidad por modelo.

    Portado de OpenClaw: types.models.ts ``ModelCompatConfig``.
    Cada flag indica un quirk o capacidad especial del modelo.
    """
    supports_developer_role: bool = False
    requires_tool_result_name: bool = False
    requires_assistant_after_tool_result: bool = False
    requires_thinking_as_text: bool = False
    supports_usage_in_streaming: bool = True
    supports_strict_mode: bool = True
    supports_reasoning_effort: bool = False
    max_tokens_field: Optional[str] = None
    thinking_format: Optional[str] = None
    tool_schema_profile: Optional[str] = None
    supports_tools: bool = True
    native_web_search_tool: bool = False
    tool_call_arguments_encoding: Optional[str] = None
    requires_mistral_tool_ids: bool = False


class ModelDefinition(BaseModel):
    """Definición de un modelo LLM."""
    id: str
    name: str
    api: ModelApi
    provider: str
    max_input_tokens: int = 128_000
    max_output_tokens: int = 8_192
    supports_streaming: bool = True
    supports_tools: bool = True
    supports_vision: bool = False
    reasoning: bool = False
    input_modalities: List[str] = Field(default_factory=lambda: ["text"])
    cost: ModelCostConfig = Field(default_factory=ModelCostConfig)
    compat: ModelCompatConfig = Field(default_factory=ModelCompatConfig)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def __init__(self, **data: Any) -> None:
        # Migración legacy: cost_per_input_token / cost_per_output_token → cost
        cpit = data.pop("cost_per_input_token", None)
        cpot = data.pop("cost_per_output_token", None)
        if (cpit is not None or cpot is not None) and "cost" not in data:
            data["cost"] = ModelCostConfig(
                input=cpit or 0.0,
                output=cpot or 0.0,
            )
        super().__init__(**data)

    @property
    def cost_per_input_token(self) -> float:
        """Retrocompatibilidad: costo por token de entrada."""
        return self.cost.input

    @property
    def cost_per_output_token(self) -> float:
        """Retrocompatibilidad: costo por token de salida."""
        return self.cost.output


class ProviderConfig(BaseModel):
    """Configuración de un provider LLM."""
    id: str
    api: ModelApi
    api_key_env: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    models: List[ModelDefinition] = Field(default_factory=list)
    default_model: Optional[str] = None
    enabled: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ── Context Engine ───────────────────────────────────────────
class BootstrapResult(BaseModel):
    session_id: str
    system_prompt: str = ""
    messages: List[AgentMessage] = Field(default_factory=list)
    token_count: int = 0


class IngestResult(BaseModel):
    accepted: bool = True
    token_count: int = 0


class AssembleResult(BaseModel):
    messages: List[Dict[str, Any]] = Field(default_factory=list)
    token_count: int = 0
    truncated: bool = False


class CompactResult(BaseModel):
    compacted: bool = False
    tokens_before: int = 0
    tokens_after: int = 0
    summary: str = ""


# ── Channels ─────────────────────────────────────────────────
class ChannelMeta(BaseModel):
    id: str
    name: str
    version: str = "1.0.0"
    description: str = ""


class ChannelCapabilities(BaseModel):
    supports_threads: bool = False
    supports_reactions: bool = False
    supports_media: bool = False
    supports_editing: bool = False
    supports_deletion: bool = False
    max_message_length: int = 4096


class RoutePeer(BaseModel):
    """Peer de routing — identifica el chat/grupo/canal destino.

    Portado de OpenClaw: resolve-route.ts ``RoutePeer``.
    """
    kind: ChatType = ChatType.DIRECT
    id: str = ""


class IncomingMessage(BaseModel):
    """Mensaje entrante desde un canal."""
    channel: ChannelType
    channel_user_id: str
    channel_thread_id: Optional[str] = None
    guild_id: Optional[str] = None
    team_id: Optional[str] = None
    peer: Optional[RoutePeer] = None
    parent_peer: Optional[RoutePeer] = None
    member_role_ids: List[str] = Field(default_factory=list)
    content: str
    media: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)


class OutgoingMessage(BaseModel):
    """Mensaje saliente hacia un canal."""
    content: str
    response_type: ResponseType = ResponseType.TEXT
    media: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ── Skills ───────────────────────────────────────────────────
class SkillMeta(BaseModel):
    """Metadata de un skill (parseado de SKILL.md frontmatter)."""
    name: str
    description: str = ""
    version: str = "1.0.0"
    triggers: List[str] = Field(default_factory=list)
    required_credentials: List[str] = Field(default_factory=list)
    tools: List[Any] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    category: str = "general"
    dependencies: List[str] = Field(default_factory=list)
    enabled: bool = True
    body: str = ""


# ── Memory ───────────────────────────────────────────────────
class MemoryStatus(str, Enum):
    """Estado de una entrada de memoria."""
    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"


class MemoryCategory(str, Enum):
    """Categorías predefinidas para entradas de memoria.

    Portado de OpenClaw: categorización de archivos de memoria.
    """
    CONVERSATION = "conversation"
    KNOWLEDGE = "knowledge"
    TASK = "task"
    PREFERENCE = "preference"
    CONTEXT = "context"
    SESSION = "session"
    SYSTEM = "system"
    CUSTOM = "custom"


class MemorySource(str, Enum):
    """Origen de una entrada de memoria.

    Portado de OpenClaw: MemorySource type.
    """
    MEMORY = "memory"
    SESSIONS = "sessions"
    IMPORT = "import"
    MANUAL = "manual"


class MemoryEntry(BaseModel):
    """Entrada en el sistema de memoria.

    Portado y extendido desde OpenClaw: tipos de memoria con soporte
    para categorías, tags, importancia, archival y versionado.
    """
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    content: str
    embedding: Optional[List[float]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    session_id: Optional[str] = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    accessed_at: float = Field(default_factory=time.time)
    access_count: int = 0
    score: float = 0.0

    # ── Categorización y tags (portado de OpenClaw) ──────────
    category: MemoryCategory = MemoryCategory.KNOWLEDGE
    tags: List[str] = Field(default_factory=list)
    source: MemorySource = MemorySource.MEMORY

    # ── Importancia y ciclo de vida ──────────────────────────
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    status: MemoryStatus = MemoryStatus.ACTIVE
    archived_at: Optional[float] = None
    version: int = 1
    parent_id: Optional[str] = None
    content_hash: Optional[str] = None


class MemorySyncProgress(BaseModel):
    """Progreso de sincronización de memoria.

    Portado de OpenClaw: MemorySyncProgressUpdate.
    """
    completed: int = 0
    total: int = 0
    label: Optional[str] = None


class MemoryStats(BaseModel):
    """Estadísticas del sistema de memoria."""
    total_entries: int = 0
    active_entries: int = 0
    archived_entries: int = 0
    total_by_category: Dict[str, int] = Field(default_factory=dict)
    total_by_source: Dict[str, int] = Field(default_factory=dict)
    avg_importance: float = 0.0
    oldest_entry_at: Optional[float] = None
    newest_entry_at: Optional[float] = None
