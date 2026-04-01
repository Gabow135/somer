"""Plugin types — sistema completo de tipos para plugins de SOMER.

Portado desde OpenClaw types.ts. Define capacidades, permisos,
estados de ciclo de vida, formatos y hooks de plugins.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field


# ── Enums de Plugin ──────────────────────────────────────────

class PluginState(str, Enum):
    """Estados del ciclo de vida de un plugin."""
    DISCOVERED = "discovered"
    VALIDATING = "validating"
    INIT = "init"
    READY = "ready"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"
    DISABLED = "disabled"


class PluginOrigin(str, Enum):
    """Origen del plugin — de dónde fue descubierto."""
    BUNDLED = "bundled"
    GLOBAL = "global"
    WORKSPACE = "workspace"
    CONFIG = "config"
    LOCAL = "local"
    PIP = "pip"
    GIT = "git"


class PluginFormat(str, Enum):
    """Formato del paquete de plugin."""
    SOMER = "somer"
    PYTHON_PACKAGE = "python_package"
    DIRECTORY = "directory"
    SINGLE_FILE = "single_file"


class PluginKind(str, Enum):
    """Tipo funcional del plugin."""
    PROVIDER = "provider"
    CHANNEL = "channel"
    SKILL = "skill"
    HOOK = "hook"
    CONTEXT_ENGINE = "context_engine"
    MEMORY = "memory"
    TOOL = "tool"
    GENERAL = "general"


class PluginCapability(str, Enum):
    """Capacidades que un plugin puede ofrecer."""
    PROVIDER = "provider"
    CHANNEL = "channel"
    SKILL = "skill"
    HOOK = "hook"
    TOOL = "tool"
    CONTEXT_ENGINE = "context_engine"
    MEMORY = "memory"
    GATEWAY_METHOD = "gateway_method"
    CLI_COMMAND = "cli_command"
    SERVICE = "service"
    WEB_SEARCH = "web_search"
    TTS = "tts"
    MEDIA = "media"


class PluginPermission(str, Enum):
    """Permisos que un plugin puede solicitar."""
    READ_CONFIG = "read_config"
    WRITE_CONFIG = "write_config"
    READ_SECRETS = "read_secrets"
    NETWORK = "network"
    FILESYSTEM = "filesystem"
    SUBPROCESS = "subprocess"
    REGISTER_HOOKS = "register_hooks"
    REGISTER_TOOLS = "register_tools"
    REGISTER_PROVIDERS = "register_providers"
    REGISTER_CHANNELS = "register_channels"
    REGISTER_SKILLS = "register_skills"
    REGISTER_GATEWAY_METHODS = "register_gateway_methods"


# ── Hook Names ───────────────────────────────────────────────

PluginHookName = Literal[
    "before_model_resolve",
    "before_prompt_build",
    "before_agent_start",
    "llm_input",
    "llm_output",
    "agent_end",
    "before_compaction",
    "after_compaction",
    "before_reset",
    "inbound_claim",
    "message_received",
    "message_sending",
    "message_sent",
    "before_tool_call",
    "after_tool_call",
    "session_start",
    "session_end",
    "gateway_start",
    "gateway_stop",
]

PLUGIN_HOOK_NAMES: List[str] = [
    "before_model_resolve",
    "before_prompt_build",
    "before_agent_start",
    "llm_input",
    "llm_output",
    "agent_end",
    "before_compaction",
    "after_compaction",
    "before_reset",
    "inbound_claim",
    "message_received",
    "message_sending",
    "message_sent",
    "before_tool_call",
    "after_tool_call",
    "session_start",
    "session_end",
    "gateway_start",
    "gateway_stop",
]

_PLUGIN_HOOK_NAME_SET = frozenset(PLUGIN_HOOK_NAMES)


def is_plugin_hook_name(name: str) -> bool:
    """Verifica si un nombre es un hook de plugin válido."""
    return name in _PLUGIN_HOOK_NAME_SET


# ── Tipo aliases ─────────────────────────────────────────────

ToolHandler = Callable[..., Coroutine[Any, Any, Any]]
HookCallback = Callable[..., Coroutine[Any, Any, Any]]
PluginRegistrationMode = Literal["full", "setup_only", "setup_runtime"]


# ── Modelos de configuración ─────────────────────────────────

class PluginConfigUiHint(BaseModel):
    """Hint de UI para un campo de configuración de plugin."""
    label: Optional[str] = None
    help: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    advanced: bool = False
    sensitive: bool = False
    placeholder: Optional[str] = None


class PluginConfigValidation(BaseModel):
    """Resultado de validación de configuración de plugin."""
    ok: bool
    value: Optional[Any] = None
    errors: List[str] = Field(default_factory=list)


class PluginConfigSchema(BaseModel):
    """Esquema de configuración de un plugin."""
    json_schema: Optional[Dict[str, Any]] = None
    ui_hints: Dict[str, PluginConfigUiHint] = Field(default_factory=dict)

    def validate_value(self, value: Any) -> PluginConfigValidation:
        """Valida un valor contra el esquema."""
        # Validación básica — se puede extender con jsonschema
        if self.json_schema is None:
            return PluginConfigValidation(ok=True, value=value)

        if not isinstance(value, dict):
            return PluginConfigValidation(
                ok=False,
                errors=["El valor de configuración debe ser un diccionario"]
            )
        return PluginConfigValidation(ok=True, value=value)


# ── Modelos de diagnóstico ───────────────────────────────────

class PluginDiagnostic(BaseModel):
    """Diagnóstico generado durante la carga de un plugin."""
    level: Literal["warn", "error"] = "warn"
    message: str
    plugin_id: Optional[str] = None
    source: Optional[str] = None


# ── Modelos de registro ──────────────────────────────────────

class PluginToolRegistration(BaseModel):
    """Registro de una tool provista por un plugin."""
    plugin_id: str
    plugin_name: Optional[str] = None
    name: str
    qualified_name: str
    optional: bool = False
    source: Optional[str] = None


class PluginHookRegistration(BaseModel):
    """Registro de un hook provisto por un plugin."""
    plugin_id: str
    hook_name: str
    events: List[str] = Field(default_factory=list)
    priority: int = 0
    source: Optional[str] = None


class PluginChannelRegistration(BaseModel):
    """Registro de un canal provisto por un plugin."""
    plugin_id: str
    plugin_name: Optional[str] = None
    channel_id: str
    source: Optional[str] = None


class PluginProviderRegistration(BaseModel):
    """Registro de un provider provisto por un plugin."""
    plugin_id: str
    plugin_name: Optional[str] = None
    provider_id: str
    source: Optional[str] = None


class PluginServiceRegistration(BaseModel):
    """Registro de un servicio provisto por un plugin."""
    plugin_id: str
    plugin_name: Optional[str] = None
    service_id: str
    source: Optional[str] = None


class PluginCommandRegistration(BaseModel):
    """Registro de un comando provisto por un plugin."""
    plugin_id: str
    plugin_name: Optional[str] = None
    command_name: str
    description: str = ""
    accepts_args: bool = False
    require_auth: bool = True
    source: Optional[str] = None


# ── Modelo de registro del plugin completo ───────────────────

class PluginRecord(BaseModel):
    """Registro completo de un plugin en el sistema."""
    id: str
    name: str
    version: Optional[str] = None
    description: Optional[str] = None
    format: PluginFormat = PluginFormat.SOMER
    kind: Optional[PluginKind] = None
    source: str = ""
    root_dir: Optional[str] = None
    origin: PluginOrigin = PluginOrigin.LOCAL
    enabled: bool = True
    state: PluginState = PluginState.DISCOVERED
    error: Optional[str] = None
    capabilities: List[PluginCapability] = Field(default_factory=list)
    permissions: List[PluginPermission] = Field(default_factory=list)

    # Ids registrados
    tool_names: List[str] = Field(default_factory=list)
    hook_names: List[str] = Field(default_factory=list)
    channel_ids: List[str] = Field(default_factory=list)
    provider_ids: List[str] = Field(default_factory=list)
    gateway_methods: List[str] = Field(default_factory=list)
    cli_commands: List[str] = Field(default_factory=list)
    service_ids: List[str] = Field(default_factory=list)
    command_names: List[str] = Field(default_factory=list)

    # Conteos
    hook_count: int = 0
    http_route_count: int = 0

    # Esquema
    has_config_schema: bool = False
    config_ui_hints: Optional[Dict[str, PluginConfigUiHint]] = None
    config_json_schema: Optional[Dict[str, Any]] = None


# ── Contextos de hooks ───────────────────────────────────────

class PluginHookAgentContext(BaseModel):
    """Contexto de agente compartido entre hooks."""
    agent_id: Optional[str] = None
    session_key: Optional[str] = None
    session_id: Optional[str] = None
    workspace_dir: Optional[str] = None
    trigger: Optional[str] = None
    channel_id: Optional[str] = None


class PluginHookMessageContext(BaseModel):
    """Contexto de mensaje para hooks."""
    channel_id: str
    account_id: Optional[str] = None
    conversation_id: Optional[str] = None


class PluginHookToolContext(BaseModel):
    """Contexto de herramienta para hooks."""
    agent_id: Optional[str] = None
    session_key: Optional[str] = None
    session_id: Optional[str] = None
    run_id: Optional[str] = None
    tool_name: str = ""
    tool_call_id: Optional[str] = None


class PluginHookSessionContext(BaseModel):
    """Contexto de sesión para hooks."""
    agent_id: Optional[str] = None
    session_id: str = ""
    session_key: Optional[str] = None


class PluginHookGatewayContext(BaseModel):
    """Contexto de gateway para hooks."""
    port: Optional[int] = None


# ── Límites de recursos ─────────────────────────────────────

class ResourceLimits(BaseModel):
    """Límites de recursos para la ejecución sandboxed de un plugin."""
    max_memory_mb: int = 256
    max_cpu_seconds: int = 30
    max_open_files: int = 100
    max_network_connections: int = 10
    timeout_seconds: int = 60
    allow_network: bool = True
    allow_filesystem: bool = False
    allow_subprocess: bool = False
