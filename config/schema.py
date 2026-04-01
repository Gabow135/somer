"""Esquema de configuración SOMER 2.0 — Pydantic v2 models.

Portado y adaptado de OpenClaw (TypeScript) a Python 3.9+.
Cubre: providers, modelos, sesiones, canales, hooks, plugins,
cron, tts, web_search, memory, media, seguridad, gateway, etc.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator

from shared.types import ModelApi, ModelCompatConfig, ModelCostConfig


# ════════════════════════════════════════════════════════════════
# Providers & Modelos
# ════════════════════════════════════════════════════════════════

class ProviderAuthConfig(BaseModel):
    """Configuración de autenticación para un provider."""
    api_key_env: Optional[str] = None
    api_key_file: Optional[str] = None
    api_key: Optional[str] = None  # Solo para testing, nunca en config
    base_url: Optional[str] = None
    region: Optional[str] = None
    auth_mode: Optional[Literal["api-key", "aws-sdk", "oauth", "token"]] = None
    auth_header: Optional[bool] = None
    headers: Dict[str, str] = Field(default_factory=dict)


class ModelConfig(BaseModel):
    """Configuración de un modelo específico.

    Portado de OpenClaw: types.models.ts ``ModelDefinitionConfig``.
    """
    id: str
    name: Optional[str] = None
    provider: str = ""
    api: Optional[ModelApi] = "anthropic-messages"
    max_input_tokens: int = 128_000
    max_output_tokens: int = 8_192
    context_window: int = 128_000
    supports_streaming: bool = True
    supports_tools: bool = True
    supports_vision: bool = False
    reasoning: bool = False
    input_modalities: List[str] = Field(default_factory=lambda: ["text"])
    cost: ModelCostConfig = Field(default_factory=ModelCostConfig)
    headers: Dict[str, str] = Field(default_factory=dict)
    compat: ModelCompatConfig = Field(default_factory=ModelCompatConfig)


class ProviderSettings(BaseModel):
    """Configuración de un provider LLM.

    Portado de OpenClaw: types.models.ts ``ModelProviderConfig``.
    """
    enabled: bool = True
    auth: ProviderAuthConfig = Field(default_factory=ProviderAuthConfig)
    models: List[ModelConfig] = Field(default_factory=list)
    default_model: Optional[str] = None
    cooldown_secs: float = 60.0
    max_retries: int = 3
    api: Optional[ModelApi] = None
    inject_num_ctx: bool = False


class BedrockDiscoveryConfig(BaseModel):
    """Descubrimiento automático de modelos en Amazon Bedrock.

    Portado de OpenClaw: types.models.ts ``BedrockDiscoveryConfig``.
    """
    enabled: bool = False
    region: Optional[str] = None
    provider_filter: List[str] = Field(default_factory=list)
    refresh_interval: int = 3600
    default_context_window: int = 128_000
    default_max_tokens: int = 8_192


class ModelsConfig(BaseModel):
    """Configuración global de modelos y providers.

    Portado de OpenClaw: types.models.ts ``ModelsConfig``.
    """
    mode: Literal["merge", "replace"] = "merge"
    providers: Dict[str, ProviderSettings] = Field(default_factory=dict)
    bedrock_discovery: Optional[BedrockDiscoveryConfig] = None


# ════════════════════════════════════════════════════════════════
# Gateway
# ════════════════════════════════════════════════════════════════

class GatewayTlsConfig(BaseModel):
    """Configuración TLS para el gateway.

    Portado de OpenClaw: types.gateway.ts ``GatewayTlsConfig``.
    """
    enabled: bool = False
    auto_generate: bool = True
    cert_path: Optional[str] = None
    key_path: Optional[str] = None
    ca_path: Optional[str] = None


class GatewayAuthRateLimitConfig(BaseModel):
    """Rate limiting para intentos de autenticación fallidos.

    Portado de OpenClaw: types.gateway.ts ``GatewayAuthRateLimitConfig``.
    """
    max_attempts: int = 10
    window_ms: int = 60_000
    lockout_ms: int = 300_000
    exempt_loopback: bool = True


class GatewayAuthConfig(BaseModel):
    """Configuración de autenticación del gateway.

    Portado de OpenClaw: types.gateway.ts ``GatewayAuthConfig``.
    """
    mode: Literal["none", "token", "password"] = "none"
    token: Optional[str] = None
    password: Optional[str] = None
    rate_limit: GatewayAuthRateLimitConfig = Field(
        default_factory=GatewayAuthRateLimitConfig
    )


class GatewayReloadConfig(BaseModel):
    """Configuración de recarga del gateway ante cambios de config.

    Portado de OpenClaw: types.gateway.ts ``GatewayReloadConfig``.
    """
    mode: Literal["off", "restart", "hot", "hybrid"] = "hybrid"
    debounce_ms: int = 300
    deferral_timeout_ms: int = 300_000


class GatewayHttpEndpointsConfig(BaseModel):
    """Endpoints HTTP del gateway.

    Portado de OpenClaw: types.gateway.ts.
    """
    chat_completions_enabled: bool = False
    responses_enabled: bool = False
    max_body_bytes: int = 20_000_000


class GatewayConfig(BaseModel):
    """Configuración del gateway WebSocket.

    Portado de OpenClaw: types.gateway.ts ``GatewayConfig``.
    """
    host: str = "127.0.0.1"
    port: int = 18789
    bind: Literal["auto", "lan", "loopback", "custom"] = "loopback"
    custom_bind_host: Optional[str] = None
    ping_interval: float = 30.0
    ping_timeout: float = 10.0
    tls: GatewayTlsConfig = Field(default_factory=GatewayTlsConfig)
    auth: GatewayAuthConfig = Field(default_factory=GatewayAuthConfig)
    reload: GatewayReloadConfig = Field(default_factory=GatewayReloadConfig)
    http: Optional[GatewayHttpEndpointsConfig] = None
    trusted_proxies: List[str] = Field(default_factory=list)
    channel_health_check_minutes: int = 5
    channel_stale_event_threshold_minutes: int = 30
    channel_max_restarts_per_hour: int = 10


# ════════════════════════════════════════════════════════════════
# Canales
# ════════════════════════════════════════════════════════════════

class ChannelHealthMonitorConfig(BaseModel):
    """Monitor de salud para un canal.

    Portado de OpenClaw: types.channels.ts ``ChannelHealthMonitorConfig``.
    """
    enabled: Optional[bool] = None


class ChannelConfig(BaseModel):
    """Configuración de un canal.

    Portado de OpenClaw: types.channels.ts ``ExtensionChannelConfig``.
    """
    enabled: bool = False
    plugin: str = ""  # Ruta al plugin
    allow_from: Union[str, List[str], None] = None
    dm_policy: Optional[Literal["pairing", "allowlist", "open", "disabled"]] = None
    group_policy: Optional[Literal["open", "disabled", "allowlist"]] = None
    health_monitor: Optional[ChannelHealthMonitorConfig] = None
    config: Dict[str, Any] = Field(default_factory=dict)


class ChannelDefaultsConfig(BaseModel):
    """Configuración por defecto para todos los canales.

    Portado de OpenClaw: types.channels.ts ``ChannelDefaultsConfig``.
    """
    group_policy: Optional[Literal["open", "disabled", "allowlist"]] = None


class ChannelsConfig(BaseModel):
    """Configuración de canales con defaults y canales individuales.

    Portado de OpenClaw: types.channels.ts ``ChannelsConfig``.
    Contiene defaults globales y un diccionario de canales configurados.
    """
    defaults: ChannelDefaultsConfig = Field(default_factory=ChannelDefaultsConfig)
    entries: Dict[str, ChannelConfig] = Field(default_factory=dict)


# ════════════════════════════════════════════════════════════════
# Memoria
# ════════════════════════════════════════════════════════════════

class MemoryConfig(BaseModel):
    """Configuración del sistema de memoria.

    Portado de OpenClaw: types.memory.ts ``MemoryConfig``.
    """
    enabled: bool = True
    backend: Literal["sqlite", "builtin"] = "sqlite"
    database_path: Optional[str] = None
    embedding_provider: str = "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    embedding_fallback_provider: Optional[str] = None
    embedding_api_key: Optional[str] = None
    embedding_base_url: Optional[str] = None
    max_results: int = 20
    temporal_decay_days: int = 30
    citations: Optional[Literal["auto", "on", "off"]] = None
    # Búsqueda
    bm25_weight: float = 0.3
    vector_weight: float = 0.7
    mmr_enabled: bool = False
    mmr_lambda: float = 0.7
    min_score: float = 0.0
    # Temporal decay
    temporal_decay_enabled: bool = True
    evergreen_categories: List[str] = Field(default_factory=lambda: ["system"])


# ════════════════════════════════════════════════════════════════
# Agents & Routing
# ════════════════════════════════════════════════════════════════

class AgentIdentityConfig(BaseModel):
    """Identidad visual de un agente.

    Portado de OpenClaw: types.base.ts ``IdentityConfig``.
    """
    name: Optional[str] = None
    theme: Optional[str] = None
    emoji: Optional[str] = None
    avatar: Optional[str] = None


class AgentSandboxConfig(BaseModel):
    """Configuración de sandbox para un agente.

    Portado de OpenClaw: types.sandbox.ts.
    """
    enabled: bool = False
    image: Optional[str] = None
    container_prefix: Optional[str] = None
    workdir: str = "/workspace"
    network: Optional[str] = None
    env: Dict[str, str] = Field(default_factory=dict)


class AgentCompactionConfig(BaseModel):
    """Configuración de compactación de contexto para un agente.

    Portado de OpenClaw: defaults.ts ``applyCompactionDefaults``.
    """
    mode: Literal["safeguard", "aggressive", "off"] = "safeguard"
    threshold_ratio: float = 0.85


class AgentHeartbeatConfig(BaseModel):
    """Configuración de heartbeat por agente.

    Portado de OpenClaw: types.agent-defaults.ts.
    """
    every: Optional[str] = None
    target: Optional[str] = None
    target_chat_id: Optional[str] = None
    prompt: Optional[str] = None
    model: Optional[str] = None
    show_ok: bool = False


class AgentSubagentsConfig(BaseModel):
    """Configuración de sub-agentes.

    Portado de OpenClaw: types.agents.ts.
    """
    allow_agents: List[str] = Field(default_factory=list)
    model: Optional[str] = None
    max_concurrent: int = 3


class ModelAliasEntry(BaseModel):
    """Entrada de alias de modelo.

    Portado de OpenClaw: types.agent-defaults.ts ``ModelAliasEntry``.
    Permite mapear nombres cortos (e.g. 'fast', 'smart') a modelos reales.
    """
    alias: Optional[str] = None


class AgentDefaultsConfig(BaseModel):
    """Configuración por defecto para agentes.

    Portado de OpenClaw: types.agent-defaults.ts ``AgentDefaultsConfig``.
    """
    model: Optional[str] = None
    max_concurrent: int = 5
    compaction: AgentCompactionConfig = Field(
        default_factory=AgentCompactionConfig
    )
    heartbeat: AgentHeartbeatConfig = Field(
        default_factory=AgentHeartbeatConfig
    )
    subagents: AgentSubagentsConfig = Field(
        default_factory=AgentSubagentsConfig
    )
    models: Dict[str, Any] = Field(default_factory=dict)
    context_pruning_mode: Optional[Literal["cache-ttl", "off"]] = None
    context_pruning_ttl: Optional[str] = None


class AgentDefinition(BaseModel):
    """Definición de un agente en la configuración.

    Portado de OpenClaw: types.agents.ts ``AgentConfig``.
    """
    id: str
    name: Optional[str] = None
    model: Optional[str] = None
    system_prompt: Optional[str] = None
    workspace: Optional[str] = None
    agent_dir: Optional[str] = None
    enabled: bool = True
    skills: Optional[List[str]] = None
    identity: Optional[AgentIdentityConfig] = None
    heartbeat: Optional[AgentHeartbeatConfig] = None
    sandbox: Optional[AgentSandboxConfig] = None
    subagents: Optional[AgentSubagentsConfig] = None
    human_delay_mode: Optional[Literal["off", "natural", "custom"]] = None
    human_delay_min_ms: int = 800
    human_delay_max_ms: int = 2500
    params: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BindingPeerMatch(BaseModel):
    """Criterio de peer para un binding de routing."""
    kind: Optional[str] = None
    id: Optional[str] = None


class BindingMatchConfig(BaseModel):
    """Criterios de coincidencia para un binding de routing.

    Portado de OpenClaw: types.agents.ts ``AgentBindingMatch``.
    """
    channel: Optional[str] = None
    account_id: Optional[str] = None
    peer: Optional[BindingPeerMatch] = None
    guild_id: Optional[str] = None
    team_id: Optional[str] = None
    roles: Optional[List[str]] = None


class AgentRouteBinding(BaseModel):
    """Vinculación agente ↔ ruta.

    Portado de OpenClaw: types.agents.ts ``AgentRouteBinding``.
    Define qué agente maneja mensajes que coincidan con ``match``.
    """
    agent_id: str
    match: BindingMatchConfig = Field(default_factory=BindingMatchConfig)
    comment: Optional[str] = None


class DelegationConfig(BaseModel):
    """Configuración de delegación automática de tareas.

    Cuando ``orchestrator_mode`` está activo, el agente principal
    NO escribe código directamente — delega a agentes especializados.
    """
    orchestrator_mode: bool = True
    coding_agent: str = "claude-code"
    coding_agent_cmd: str = "claude --permission-mode bypassPermissions --print"
    coding_agent_model: Optional[str] = None
    default_workdir: Optional[str] = None
    timeout_secs: int = 600
    auto_branch: bool = False
    max_concurrent: int = 3


class AgentsConfig(BaseModel):
    """Configuración de agentes.

    Portado de OpenClaw: types.agents.ts ``AgentsConfig``.
    """
    default: str = "main"
    defaults: AgentDefaultsConfig = Field(default_factory=AgentDefaultsConfig)
    list: List[AgentDefinition] = Field(default_factory=list)
    delegation: DelegationConfig = Field(default_factory=DelegationConfig)


# ════════════════════════════════════════════════════════════════
# Sesiones
# ════════════════════════════════════════════════════════════════

class SendPolicyRuleMatch(BaseModel):
    """Criterios de coincidencia para una regla de send policy."""
    channel: Optional[str] = None
    chat_type: Optional[str] = None
    key_prefix: Optional[str] = None
    raw_key_prefix: Optional[str] = None


class SendPolicyRule(BaseModel):
    """Regla individual de send policy."""
    action: Literal["allow", "deny"] = "allow"
    match: SendPolicyRuleMatch = Field(default_factory=SendPolicyRuleMatch)


class SendPolicyConfig(BaseModel):
    """Configuración de política de envío.

    Portado de OpenClaw: types.base.ts ``SessionSendPolicyConfig``.
    Permite controlar qué sesiones pueden enviar mensajes
    basándose en canal, tipo de chat y prefijos de key.
    """
    default: Literal["allow", "deny"] = "allow"
    rules: List[SendPolicyRule] = Field(default_factory=list)


class SessionResetConfig(BaseModel):
    """Configuración de reseteo de sesiones.

    Portado de OpenClaw: types.base.ts ``SessionResetConfig``.
    """
    mode: Literal["daily", "idle"] = "idle"
    at_hour: Optional[int] = None
    idle_minutes: Optional[int] = None

    @model_validator(mode="after")
    def _validate_at_hour(self) -> SessionResetConfig:
        if self.at_hour is not None and not (0 <= self.at_hour <= 23):
            raise ValueError("at_hour debe estar entre 0 y 23")
        return self


class SessionResetByTypeConfig(BaseModel):
    """Reseteo de sesiones por tipo de chat.

    Portado de OpenClaw: types.base.ts ``SessionResetByTypeConfig``.
    """
    direct: Optional[SessionResetConfig] = None
    group: Optional[SessionResetConfig] = None
    thread: Optional[SessionResetConfig] = None


class SessionThreadBindingsConfig(BaseModel):
    """Configuración de thread-bound session routing.

    Portado de OpenClaw: types.base.ts ``SessionThreadBindingsConfig``.
    """
    enabled: bool = False
    idle_hours: int = 24
    max_age_hours: int = 0


class SessionMaintenanceConfig(BaseModel):
    """Mantenimiento automático de sesiones.

    Portado de OpenClaw: types.base.ts ``SessionMaintenanceConfig``.
    """
    mode: Literal["enforce", "warn"] = "warn"
    prune_after: str = "30d"
    max_entries: int = 500
    rotate_bytes: int = 10_000_000
    reset_archive_retention: Optional[str] = None
    max_disk_bytes: Optional[int] = None


class SessionConfig(BaseModel):
    """Configuración de sesiones.

    Portado de OpenClaw: types.base.ts ``SessionConfig``.
    """
    idle_timeout_secs: int = 3600
    max_turns: int = 200
    persist: bool = True
    storage_dir: Optional[str] = None
    scope: Literal["per-sender", "global"] = "per-sender"
    dm_scope: Literal[
        "main", "per-peer", "per-channel-peer", "per-account-channel-peer"
    ] = "main"
    identity_links: Dict[str, List[str]] = Field(default_factory=dict)
    reset_triggers: List[str] = Field(default_factory=list)
    reset: Optional[SessionResetConfig] = None
    reset_by_type: Optional[SessionResetByTypeConfig] = None
    reset_by_channel: Dict[str, SessionResetConfig] = Field(default_factory=dict)
    typing_mode: Literal["never", "instant", "thinking", "message"] = "never"
    typing_interval_secs: int = 5
    parent_fork_max_tokens: int = 0
    main_key: str = "main"
    send_policy: Optional[SendPolicyConfig] = None
    thread_bindings: Optional[SessionThreadBindingsConfig] = None
    maintenance: Optional[SessionMaintenanceConfig] = None
    agent_to_agent_max_turns: int = 5


# ════════════════════════════════════════════════════════════════
# Context Engine
# ════════════════════════════════════════════════════════════════

class ContextEngineConfig(BaseModel):
    """Configuración del context engine."""
    compact_threshold_ratio: float = 0.85
    max_context_tokens: int = 128_000
    max_output_tokens: int = 8_192


# ════════════════════════════════════════════════════════════════
# Seguridad
# ════════════════════════════════════════════════════════════════

class SecurityConfig(BaseModel):
    """Configuración de seguridad."""
    audit_on_start: bool = True
    block_dangerous_skills: bool = True
    allowed_hosts: List[str] = Field(default_factory=list)


# ════════════════════════════════════════════════════════════════
# Auth Profiles
# ════════════════════════════════════════════════════════════════

class AuthProfileConfig(BaseModel):
    """Perfil de autenticación para un provider.

    Portado de OpenClaw: types.auth.ts ``AuthProfileConfig``.
    """
    provider: str
    mode: Literal["api_key", "oauth", "token"] = "api_key"
    email: Optional[str] = None


class AuthCooldownsConfig(BaseModel):
    """Configuración de cooldowns de autenticación.

    Portado de OpenClaw: types.auth.ts ``AuthConfig.cooldowns``.
    """
    billing_backoff_hours: float = 5.0
    billing_backoff_hours_by_provider: Dict[str, float] = Field(default_factory=dict)
    billing_max_hours: float = 24.0
    failure_window_hours: float = 24.0


class AuthConfig(BaseModel):
    """Configuración de autenticación multi-perfil.

    Portado de OpenClaw: types.auth.ts ``AuthConfig``.
    """
    profiles: Dict[str, AuthProfileConfig] = Field(default_factory=dict)
    order: Dict[str, List[str]] = Field(default_factory=dict)
    cooldowns: AuthCooldownsConfig = Field(default_factory=AuthCooldownsConfig)


# ════════════════════════════════════════════════════════════════
# Heartbeat
# ════════════════════════════════════════════════════════════════

class ActiveHoursConfig(BaseModel):
    """Horario activo para el heartbeat (timezone-aware)."""
    start: str = "08:00"
    end: str = "22:00"
    timezone: str = "UTC"


class HeartbeatConfig(BaseModel):
    """Configuración del heartbeat periódico.

    Portado de OpenClaw: heartbeat-runner.ts, heartbeat-summary.ts.
    Ejecuta turnos LLM periódicos y envía alertas por canales.
    """
    enabled: bool = False
    every: int = 1800  # segundos (default 30 min)
    target: str = "none"  # canal destino: "none", "telegram", "discord", etc.
    target_chat_id: str = ""  # chat_id/channel_id donde enviar
    prompt: Optional[str] = None  # prompt personalizado (default lee HEARTBEAT.md)
    model: Optional[str] = None  # override de modelo (usar uno barato)
    active_hours: Optional[ActiveHoursConfig] = None
    show_ok: bool = False  # enviar HEARTBEAT_OK al canal
    deduplicate_hours: int = 24  # suprimir alertas duplicadas dentro de N horas


# ════════════════════════════════════════════════════════════════
# Hooks
# ════════════════════════════════════════════════════════════════

class HookMappingConfig(BaseModel):
    """Configuración de un mapping de hook externo.

    Portado de OpenClaw: types.hooks.ts ``HookMappingConfig``.
    """
    id: Optional[str] = None
    match_path: Optional[str] = None
    match_source: Optional[str] = None
    action: Literal["wake", "agent"] = "agent"
    wake_mode: Literal["now", "next-heartbeat"] = "now"
    name: Optional[str] = None
    agent_id: Optional[str] = None
    session_key: Optional[str] = None
    message_template: Optional[str] = None
    channel: Optional[str] = None
    to: Optional[str] = None
    model: Optional[str] = None
    timeout_seconds: Optional[int] = None


class InternalHookHandlerConfig(BaseModel):
    """Configuración de un handler de hook interno.

    Portado de OpenClaw: types.hooks.ts ``InternalHookHandlerConfig``.
    """
    event: str
    module: str
    export: str = "default"


class HookEntryConfig(BaseModel):
    """Configuración de un hook individual.

    Portado de OpenClaw: types.hooks.ts ``HookConfig``.
    """
    enabled: bool = True
    env: Dict[str, str] = Field(default_factory=dict)


class InternalHooksConfig(BaseModel):
    """Configuración de hooks internos del agente.

    Portado de OpenClaw: types.hooks.ts ``InternalHooksConfig``.
    """
    enabled: bool = True
    handlers: List[InternalHookHandlerConfig] = Field(default_factory=list)
    entries: Dict[str, HookEntryConfig] = Field(default_factory=dict)
    extra_dirs: List[str] = Field(default_factory=list)


class HooksConfig(BaseModel):
    """Configuración del sistema de hooks.

    Portado de OpenClaw: types.hooks.ts ``HooksConfig``.
    """
    enabled: bool = True
    path: Optional[str] = None
    token: Optional[str] = None
    default_session_key: Optional[str] = None
    allow_request_session_key: bool = False
    allowed_session_key_prefixes: List[str] = Field(default_factory=list)
    allowed_agent_ids: Optional[List[str]] = None
    max_body_bytes: int = 1_000_000
    mappings: List[HookMappingConfig] = Field(default_factory=list)
    internal: InternalHooksConfig = Field(default_factory=InternalHooksConfig)


# ════════════════════════════════════════════════════════════════
# Plugins
# ════════════════════════════════════════════════════════════════

class PluginEntryConfig(BaseModel):
    """Configuración de un plugin individual.

    Portado de OpenClaw: types.plugins.ts ``PluginEntryConfig``.
    """
    enabled: bool = True
    config: Dict[str, Any] = Field(default_factory=dict)
    allow_prompt_injection: bool = False
    allow_model_override: bool = False
    allowed_models: List[str] = Field(default_factory=list)


class PluginSlotsConfig(BaseModel):
    """Asignación de slots a plugins.

    Portado de OpenClaw: types.plugins.ts ``PluginSlotsConfig``.
    """
    memory: Optional[str] = None
    context_engine: Optional[str] = None


class PluginsConfig(BaseModel):
    """Configuración del sistema de plugins.

    Portado de OpenClaw: types.plugins.ts ``PluginsConfig``.
    """
    enabled: bool = True
    allow: List[str] = Field(default_factory=list)
    deny: List[str] = Field(default_factory=list)
    load_paths: List[str] = Field(default_factory=list)
    slots: PluginSlotsConfig = Field(default_factory=PluginSlotsConfig)
    entries: Dict[str, PluginEntryConfig] = Field(default_factory=dict)


# ════════════════════════════════════════════════════════════════
# Skills
# ════════════════════════════════════════════════════════════════

class SkillEntryConfig(BaseModel):
    """Configuración de un skill individual.

    Portado de OpenClaw: types.skills.ts ``SkillConfig``.
    """
    enabled: bool = True
    api_key_env: Optional[str] = None
    env: Dict[str, str] = Field(default_factory=dict)
    config: Dict[str, Any] = Field(default_factory=dict)


class SkillsLoadConfig(BaseModel):
    """Configuración de carga de skills.

    Portado de OpenClaw: types.skills.ts ``SkillsLoadConfig``.
    """
    extra_dirs: List[str] = Field(default_factory=list)
    watch: bool = False
    watch_debounce_ms: int = 500


class SkillsLimitsConfig(BaseModel):
    """Límites del sistema de skills.

    Portado de OpenClaw: types.skills.ts ``SkillsLimitsConfig``.
    """
    max_candidates_per_root: int = 500
    max_skills_loaded_per_source: int = 200
    max_skills_in_prompt: int = 50
    max_skills_prompt_chars: int = 100_000
    max_skill_file_bytes: int = 500_000


class SkillsConfig(BaseModel):
    """Configuración del sistema de skills.

    Portado de OpenClaw: types.skills.ts ``SkillsConfig``.
    """
    dirs: List[str] = Field(default_factory=lambda: ["skills"])
    allow_bundled: Optional[List[str]] = None
    load: SkillsLoadConfig = Field(default_factory=SkillsLoadConfig)
    limits: SkillsLimitsConfig = Field(default_factory=SkillsLimitsConfig)
    entries: Dict[str, SkillEntryConfig] = Field(default_factory=dict)


# ════════════════════════════════════════════════════════════════
# Cron
# ════════════════════════════════════════════════════════════════

class CronRetryConfig(BaseModel):
    """Configuración de reintentos para jobs cron.

    Portado de OpenClaw: types.cron.ts ``CronRetryConfig``.
    """
    max_attempts: int = 3
    backoff_ms: List[int] = Field(default_factory=lambda: [30_000, 60_000, 300_000])
    retry_on: List[str] = Field(default_factory=list)


class CronFailureAlertConfig(BaseModel):
    """Configuración de alertas de fallo de cron.

    Portado de OpenClaw: types.cron.ts ``CronFailureAlertConfig``.
    """
    enabled: bool = False
    after: int = 3
    cooldown_ms: int = 3_600_000
    mode: Literal["announce", "webhook"] = "announce"
    channel: Optional[str] = None
    to: Optional[str] = None


class CronConfig(BaseModel):
    """Configuración del scheduler cron.

    Portado de OpenClaw: types.cron.ts ``CronConfig``.
    """
    enabled: bool = False
    store: Optional[str] = None
    max_concurrent_runs: int = 3
    retry: CronRetryConfig = Field(default_factory=CronRetryConfig)
    session_retention: str = "24h"
    run_log_max_bytes: int = 2_000_000
    run_log_keep_lines: int = 2000
    failure_alert: CronFailureAlertConfig = Field(
        default_factory=CronFailureAlertConfig
    )


# ════════════════════════════════════════════════════════════════
# TTS (Text-to-Speech)
# ════════════════════════════════════════════════════════════════

class TtsElevenLabsConfig(BaseModel):
    """Configuración de ElevenLabs TTS.

    Portado de OpenClaw: types.tts.ts ``TtsConfig.elevenlabs``.
    """
    api_key_env: Optional[str] = None
    base_url: Optional[str] = None
    voice_id: Optional[str] = None
    model_id: Optional[str] = None
    seed: Optional[int] = None
    language_code: Optional[str] = None
    stability: Optional[float] = None
    similarity_boost: Optional[float] = None
    speed: Optional[float] = None


class TtsOpenAIConfig(BaseModel):
    """Configuración de OpenAI TTS.

    Portado de OpenClaw: types.tts.ts ``TtsConfig.openai``.
    """
    api_key_env: Optional[str] = None
    base_url: Optional[str] = None
    model: str = "tts-1"
    voice: str = "alloy"
    speed: float = 1.0
    instructions: Optional[str] = None


class TtsConfig(BaseModel):
    """Configuración de text-to-speech.

    Portado de OpenClaw: types.tts.ts ``TtsConfig``.
    """
    auto: Literal["off", "always", "inbound", "tagged"] = "off"
    enabled: bool = False
    mode: Literal["final", "all"] = "final"
    provider: Optional[str] = None
    summary_model: Optional[str] = None
    elevenlabs: Optional[TtsElevenLabsConfig] = None
    openai: Optional[TtsOpenAIConfig] = None
    max_text_length: int = 5000
    timeout_ms: int = 30_000


# ════════════════════════════════════════════════════════════════
# Web Search
# ════════════════════════════════════════════════════════════════

class WebSearchProviderConfig(BaseModel):
    """Configuración de un provider de búsqueda web."""
    enabled: bool = True
    api_key_env: Optional[str] = None
    max_results: int = 10
    timeout_secs: float = 15.0
    base_url: Optional[str] = None


class WebSearchConfig(BaseModel):
    """Configuración del sistema de búsqueda web."""
    enabled: bool = False
    default_provider: Literal["tavily", "brave", "duckduckgo"] = "tavily"
    providers: Dict[str, WebSearchProviderConfig] = Field(default_factory=dict)


# ════════════════════════════════════════════════════════════════
# Media
# ════════════════════════════════════════════════════════════════

class MediaConfig(BaseModel):
    """Configuración de procesamiento de media.

    Portado de OpenClaw: types.openclaw.ts ``media``.
    """
    preserve_filenames: bool = False
    ttl_hours: Optional[int] = None


# ════════════════════════════════════════════════════════════════
# MCP (Model Context Protocol)
# ════════════════════════════════════════════════════════════════

class McpServerConfig(BaseModel):
    """Configuración de un servidor MCP.

    Portado de OpenClaw: types.mcp.ts ``McpServerConfig``.
    """
    command: Optional[str] = None
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    cwd: Optional[str] = None
    url: Optional[str] = None


class McpConfig(BaseModel):
    """Configuración de MCP.

    Portado de OpenClaw: types.mcp.ts ``McpConfig``.
    """
    servers: Dict[str, McpServerConfig] = Field(default_factory=dict)


# ════════════════════════════════════════════════════════════════
# Secrets
# ════════════════════════════════════════════════════════════════

class SecretsConfig(BaseModel):
    """Configuración del sistema de secretos.

    Portado de OpenClaw: types.secrets.ts ``SecretsConfig``.
    """
    providers: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    defaults: Dict[str, str] = Field(default_factory=dict)


# ════════════════════════════════════════════════════════════════
# Logging & Diagnostics
# ════════════════════════════════════════════════════════════════

class LoggingConfig(BaseModel):
    """Configuración de logging.

    Portado de OpenClaw: types.base.ts ``LoggingConfig``.
    """
    level: Literal[
        "silent", "fatal", "error", "warn", "info", "debug", "trace"
    ] = "info"
    file: Optional[str] = None
    max_file_bytes: int = 500_000_000
    console_level: Optional[str] = None
    console_style: Literal["pretty", "compact", "json"] = "pretty"
    redact_sensitive: Literal["off", "tools"] = "tools"
    redact_patterns: List[str] = Field(default_factory=list)


class DiagnosticsOtelConfig(BaseModel):
    """Configuración de OpenTelemetry.

    Portado de OpenClaw: types.base.ts ``DiagnosticsOtelConfig``.
    """
    enabled: bool = False
    endpoint: Optional[str] = None
    protocol: Literal["http/protobuf", "grpc"] = "http/protobuf"
    headers: Dict[str, str] = Field(default_factory=dict)
    service_name: str = "somer"
    traces: bool = True
    metrics: bool = True
    logs: bool = False
    sample_rate: float = 1.0
    flush_interval_ms: int = 30_000


class DiagnosticsConfig(BaseModel):
    """Configuración de diagnósticos.

    Portado de OpenClaw: types.base.ts ``DiagnosticsConfig``.
    """
    enabled: bool = False
    flags: List[str] = Field(default_factory=list)
    stuck_session_warn_ms: int = 120_000
    otel: Optional[DiagnosticsOtelConfig] = None


# ════════════════════════════════════════════════════════════════
# Browser
# ════════════════════════════════════════════════════════════════

class BrowserConfig(BaseModel):
    """Configuración de automatización de navegador.

    Portado de OpenClaw: types.browser.ts ``BrowserConfig``.
    """
    enabled: bool = False
    headless: bool = False
    executable_path: Optional[str] = None
    cdp_url: Optional[str] = None
    default_profile: str = "chrome"
    no_sandbox: bool = False
    attach_only: bool = False
    extra_args: List[str] = Field(default_factory=list)


# ════════════════════════════════════════════════════════════════
# Messages
# ════════════════════════════════════════════════════════════════

class GroupChatConfig(BaseModel):
    """Configuración de chat grupal.

    Portado de OpenClaw: types.messages.ts ``GroupChatConfig``.
    """
    mention_patterns: List[str] = Field(default_factory=list)
    history_limit: Optional[int] = None


class QueueConfig(BaseModel):
    """Configuración de cola de mensajes.

    Portado de OpenClaw: types.messages.ts ``QueueConfig``.
    """
    mode: Literal["fifo", "lifo", "priority"] = "fifo"
    debounce_ms: int = 0
    cap: int = 100
    drop: Literal["oldest", "newest"] = "oldest"
    max_concurrent_per_user: int = 5


class StatusReactionsConfig(BaseModel):
    """Configuración de reacciones de estado.

    Portado de OpenClaw: types.messages.ts ``StatusReactionsConfig``.
    """
    enabled: bool = False
    debounce_ms: int = 700
    stall_soft_ms: int = 25_000
    stall_hard_ms: int = 60_000


class MessagesConfig(BaseModel):
    """Configuración de mensajes.

    Portado de OpenClaw: types.messages.ts ``MessagesConfig``.
    """
    response_prefix: Optional[str] = None
    group_chat: GroupChatConfig = Field(default_factory=GroupChatConfig)
    queue: QueueConfig = Field(default_factory=QueueConfig)
    ack_reaction: Optional[str] = None
    ack_reaction_scope: Literal[
        "group-mentions", "group-all", "direct", "all", "off", "none"
    ] = "group-mentions"
    remove_ack_after_reply: bool = False
    status_reactions: StatusReactionsConfig = Field(
        default_factory=StatusReactionsConfig
    )
    suppress_tool_errors: bool = False
    tts: Optional[TtsConfig] = None


# ════════════════════════════════════════════════════════════════
# Planning Engine
# ════════════════════════════════════════════════════════════════

class PlanningConfig(BaseModel):
    """Configuración del planning engine nativo."""
    enabled: bool = True
    max_plan_steps: int = 20
    max_retries_per_step: int = 3
    max_replans: int = 3
    step_timeout_secs: int = 300
    max_concurrent_steps: int = 1
    auto_replan: bool = True


# ════════════════════════════════════════════════════════════════
# Episodic Memory
# ════════════════════════════════════════════════════════════════

class EpisodicMemoryConfig(BaseModel):
    """Configuración de la memoria episódica."""
    enabled: bool = True
    database_path: Optional[str] = None
    max_episodes: int = 1000
    temporal_decay_days: int = 90
    min_score_threshold: float = 0.3
    auto_record: bool = True
    auto_decay: bool = True


# ════════════════════════════════════════════════════════════════
# Proactive Alerts
# ════════════════════════════════════════════════════════════════

class ProactiveAlertRuleConfig(BaseModel):
    """Configuración de una regla de alerta."""
    monitor_id: str = ""
    condition: str = ""
    severity: Literal["info", "warning", "error", "critical"] = "warning"
    notify_channels: List[str] = Field(default_factory=list)
    check_interval_secs: int = 300
    dedup_window_secs: int = 3600
    enabled: bool = True


class ProactiveAlertsConfig(BaseModel):
    """Configuración del sistema de alertas proactivas."""
    enabled: bool = False
    default_check_interval_secs: int = 300
    default_notify_channels: List[str] = Field(default_factory=list)
    dedup_window_secs: int = 3600
    max_alert_history: int = 500
    rules: Dict[str, ProactiveAlertRuleConfig] = Field(default_factory=dict)


# ════════════════════════════════════════════════════════════════
# Knowledge Graph
# ════════════════════════════════════════════════════════════════

class KnowledgeGraphConfig(BaseModel):
    """Configuración del knowledge graph."""
    enabled: bool = True
    database_path: Optional[str] = None
    max_entities: int = 10000
    max_traversal_depth: int = 3
    auto_extract: bool = False


# ════════════════════════════════════════════════════════════════
# Config Meta
# ════════════════════════════════════════════════════════════════

class ConfigMeta(BaseModel):
    """Metadatos de la configuración.

    Portado de OpenClaw: types.openclaw.ts ``meta``.
    """
    last_touched_version: Optional[str] = None
    last_touched_at: Optional[str] = None


# ════════════════════════════════════════════════════════════════
# Config Raíz
# ════════════════════════════════════════════════════════════════

class SomerConfig(BaseModel):
    """Configuración raíz de SOMER 2.0.

    Portado de OpenClaw: types.openclaw.ts ``OpenClawConfig``.
    Contiene TODOS los subsistemas de SOMER.
    """
    # ── Meta ─────────────────────────────────────────────────
    version: str = "2.0"
    meta: Optional[ConfigMeta] = None

    # ── Zona horaria del usuario ─────────────────────────────
    timezone: str = "America/Bogota"

    # ── Modelos por defecto ──────────────────────────────────
    default_model: str = "claude-sonnet-4-5-20250929"
    fast_model: str = "claude-haiku-4-5-20251001"

    # ── Cadena de fallback de modelos ────────────────────────
    # Lista de [provider, model] que se intentan en orden si el
    # modelo principal falla (billing, quota, rate-limit, etc.)
    fallback_models: List[List[str]] = Field(default_factory=list)

    # ── Auth (portado de OpenClaw) ───────────────────────────
    auth: AuthConfig = Field(default_factory=AuthConfig)

    # ── Gateway ──────────────────────────────────────────────
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)

    # ── Providers (legacy top-level, migrar a models.providers)
    providers: Dict[str, ProviderSettings] = Field(default_factory=dict)

    # ── Models (nuevo sistema de providers/modelos) ──────────
    models: ModelsConfig = Field(default_factory=ModelsConfig)

    # ── Canales ──────────────────────────────────────────────
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)

    # ── Memoria ──────────────────────────────────────────────
    memory: MemoryConfig = Field(default_factory=MemoryConfig)

    # ── Sesiones ─────────────────────────────────────────────
    sessions: SessionConfig = Field(default_factory=SessionConfig)

    # ── Context engine ───────────────────────────────────────
    context_engine: ContextEngineConfig = Field(
        default_factory=ContextEngineConfig
    )

    # ── Seguridad ────────────────────────────────────────────
    security: SecurityConfig = Field(default_factory=SecurityConfig)

    # ── Heartbeat ────────────────────────────────────────────
    heartbeat: HeartbeatConfig = Field(default_factory=HeartbeatConfig)

    # ── Hooks ────────────────────────────────────────────────
    hooks: HooksConfig = Field(default_factory=HooksConfig)

    # ── Skills ───────────────────────────────────────────────
    skills: SkillsConfig = Field(default_factory=SkillsConfig)

    # ── Plugins ──────────────────────────────────────────────
    plugins: PluginsConfig = Field(default_factory=PluginsConfig)

    # ── Cron ─────────────────────────────────────────────────
    cron: CronConfig = Field(default_factory=CronConfig)

    # ── TTS ──────────────────────────────────────────────────
    tts: TtsConfig = Field(default_factory=TtsConfig)

    # ── Web Search ───────────────────────────────────────────
    web_search: WebSearchConfig = Field(default_factory=WebSearchConfig)

    # ── Media ────────────────────────────────────────────────
    media: MediaConfig = Field(default_factory=MediaConfig)

    # ── MCP ──────────────────────────────────────────────────
    mcp: McpConfig = Field(default_factory=McpConfig)

    # ── Secrets ──────────────────────────────────────────────
    secrets: SecretsConfig = Field(default_factory=SecretsConfig)

    # ── Logging ──────────────────────────────────────────────
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    # ── Diagnostics ──────────────────────────────────────────
    diagnostics: DiagnosticsConfig = Field(default_factory=DiagnosticsConfig)

    # ── Messages ─────────────────────────────────────────────
    messages: MessagesConfig = Field(default_factory=MessagesConfig)

    # ── Browser ──────────────────────────────────────────────
    browser: BrowserConfig = Field(default_factory=BrowserConfig)

    # ── Planning Engine ───────────────────────────────────────
    planning: PlanningConfig = Field(default_factory=PlanningConfig)

    # ── Episodic Memory ───────────────────────────────────────
    episodic_memory: EpisodicMemoryConfig = Field(
        default_factory=EpisodicMemoryConfig
    )

    # ── Proactive Alerts ──────────────────────────────────────
    proactive_alerts: ProactiveAlertsConfig = Field(
        default_factory=ProactiveAlertsConfig
    )

    # ── Knowledge Graph ───────────────────────────────────────
    knowledge_graph: KnowledgeGraphConfig = Field(
        default_factory=KnowledgeGraphConfig
    )

    # ── Routing (portado de OpenClaw) ────────────────────────
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    bindings: List[AgentRouteBinding] = Field(default_factory=list)

    # ── Env vars inline (portado de OpenClaw) ────────────────
    env_vars: Dict[str, str] = Field(default_factory=dict)

    # ── Metadata libre ───────────────────────────────────────
    metadata: Dict[str, Any] = Field(default_factory=dict)
