"""Override de configuración vía variables de entorno.

Portado de OpenClaw: env-vars.ts, runtime-overrides.ts.
"""

from __future__ import annotations

import os
import logging
from typing import Any, Dict

from config.schema import SomerConfig
from config.loader import merge_config

logger = logging.getLogger(__name__)

# Mapeo de env vars → rutas en config.
# Formato: ENV_VAR → dotted.path.in.config
ENV_OVERRIDES: Dict[str, str] = {
    # ── Modelos ──────────────────────────────────────────────
    "SOMER_DEFAULT_MODEL": "default_model",
    "SOMER_FAST_MODEL": "fast_model",

    # ── Gateway ──────────────────────────────────────────────
    "SOMER_GATEWAY_HOST": "gateway.host",
    "SOMER_GATEWAY_PORT": "gateway.port",
    "SOMER_GATEWAY_BIND": "gateway.bind",

    # ── Memory ───────────────────────────────────────────────
    "SOMER_MEMORY_BACKEND": "memory.backend",
    "SOMER_MEMORY_EMBEDDING_PROVIDER": "memory.embedding_provider",
    "SOMER_MEMORY_EMBEDDING_MODEL": "memory.embedding_model",
    "SOMER_MEMORY_ENABLED": "memory.enabled",

    # ── Sessions ─────────────────────────────────────────────
    "SOMER_SESSION_TIMEOUT": "sessions.idle_timeout_secs",
    "SOMER_SESSION_MAX_TURNS": "sessions.max_turns",
    "SOMER_SESSION_PERSIST": "sessions.persist",
    "SOMER_SESSION_SCOPE": "sessions.scope",
    "SOMER_DM_SCOPE": "sessions.dm_scope",

    # ── Context ──────────────────────────────────────────────
    "SOMER_CONTEXT_MAX_TOKENS": "context_engine.max_context_tokens",
    "SOMER_CONTEXT_MAX_OUTPUT": "context_engine.max_output_tokens",

    # ── Security ─────────────────────────────────────────────
    "SOMER_AUDIT_ON_START": "security.audit_on_start",

    # ── Logging ──────────────────────────────────────────────
    "SOMER_LOG_LEVEL": "logging.level",
    "SOMER_LOG_FILE": "logging.file",

    # ── Hooks ────────────────────────────────────────────────
    "SOMER_HOOKS_ENABLED": "hooks.enabled",
    "SOMER_HOOKS_TOKEN": "hooks.token",

    # ── Plugins ──────────────────────────────────────────────
    "SOMER_PLUGINS_ENABLED": "plugins.enabled",

    # ── Cron ─────────────────────────────────────────────────
    "SOMER_CRON_ENABLED": "cron.enabled",

    # ── TTS ──────────────────────────────────────────────────
    "SOMER_TTS_PROVIDER": "tts.provider",

    # ── Web Search ───────────────────────────────────────────
    "SOMER_WEB_SEARCH_ENABLED": "web_search.enabled",
    "SOMER_WEB_SEARCH_PROVIDER": "web_search.default_provider",

    # ── Browser ──────────────────────────────────────────────
    "SOMER_BROWSER_ENABLED": "browser.enabled",
    "SOMER_BROWSER_HEADLESS": "browser.headless",

    # ── Heartbeat ────────────────────────────────────────────
    "SOMER_HEARTBEAT_ENABLED": "heartbeat.enabled",
    "SOMER_HEARTBEAT_EVERY": "heartbeat.every",
    "SOMER_HEARTBEAT_TARGET": "heartbeat.target",
}

# Env vars de providers → config
PROVIDER_KEY_VARS: Dict[str, str] = {
    "ANTHROPIC_API_KEY": "anthropic",
    "OPENAI_API_KEY": "openai",
    "DEEPSEEK_API_KEY": "deepseek",
    "GOOGLE_API_KEY": "google",
    "GEMINI_API_KEY": "google",
    "AWS_ACCESS_KEY_ID": "bedrock",
    "XAI_API_KEY": "xai",
    "OPENROUTER_API_KEY": "openrouter",
    "MISTRAL_API_KEY": "mistral",
    "TOGETHER_API_KEY": "together",
    "GROQ_API_KEY": "groq",
    "HUGGINGFACE_API_KEY": "huggingface",
    "PERPLEXITY_API_KEY": "perplexity",
}

# Env vars de channels → auto-enable
CHANNEL_TOKEN_VARS: Dict[str, str] = {
    "TELEGRAM_BOT_TOKEN": "telegram",
    "DISCORD_BOT_TOKEN": "discord",
    "SLACK_BOT_TOKEN": "slack",
    "SLACK_APP_TOKEN": "slack",
}

# Env vars para web search providers
WEB_SEARCH_KEY_VARS: Dict[str, str] = {
    "TAVILY_API_KEY": "tavily",
    "BRAVE_API_KEY": "brave",
}

# Env vars para TTS providers
TTS_KEY_VARS: Dict[str, str] = {
    "ELEVENLABS_API_KEY": "elevenlabs",
}


def apply_env_overrides(config: SomerConfig) -> SomerConfig:
    """Aplica overrides desde variables de entorno.

    Portado de OpenClaw: env-vars.ts ``applyConfigEnvVars``,
    runtime-overrides.ts ``applyConfigOverrides``.

    Args:
        config: Configuración base.

    Returns:
        Nueva SomerConfig con overrides aplicados.
    """
    overrides: Dict[str, Any] = {}

    # ── Overrides directos ───────────────────────────────────
    for env_var, config_path in ENV_OVERRIDES.items():
        value = os.environ.get(env_var)
        if value is not None:
            _set_nested(overrides, config_path, _coerce_value(value))
            logger.debug("Override: %s → %s", env_var, config_path)

    # ── Auto-enable providers si tienen API key ──────────────
    # Solo auto-habilitar si el usuario no desactivó explícitamente
    for env_var, provider_id in PROVIDER_KEY_VARS.items():
        if os.environ.get(env_var):
            # Respetar enabled: false explícito en config del usuario
            existing = config.providers.get(provider_id)
            if existing and not existing.enabled:
                continue
            providers = overrides.setdefault("providers", {})
            provider = providers.setdefault(provider_id, {})
            provider.setdefault("enabled", True)
            auth = provider.setdefault("auth", {})
            auth.setdefault("api_key_env", env_var)

    # ── Auto-enable web search providers ─────────────────────
    for env_var, provider_id in WEB_SEARCH_KEY_VARS.items():
        if os.environ.get(env_var):
            ws = overrides.setdefault("web_search", {})
            ws.setdefault("enabled", True)
            providers = ws.setdefault("providers", {})
            provider = providers.setdefault(provider_id, {})
            provider.setdefault("enabled", True)
            provider.setdefault("api_key_env", env_var)

    # ── Auto-enable TTS providers ────────────────────────────
    for env_var, provider_id in TTS_KEY_VARS.items():
        if os.environ.get(env_var):
            tts = overrides.setdefault("tts", {})
            provider_config = tts.setdefault(provider_id, {})
            provider_config.setdefault("api_key_env", env_var)

    # ── Gateway auth token/password ──────────────────────────
    gw_token = os.environ.get("SOMER_GATEWAY_TOKEN")
    if gw_token:
        gw = overrides.setdefault("gateway", {})
        gw_auth = gw.setdefault("auth", {})
        gw_auth.setdefault("mode", "token")
        gw_auth["token"] = gw_token

    gw_password = os.environ.get("SOMER_GATEWAY_PASSWORD")
    if gw_password:
        gw = overrides.setdefault("gateway", {})
        gw_auth = gw.setdefault("auth", {})
        gw_auth.setdefault("mode", "password")
        gw_auth["password"] = gw_password

    if overrides:
        return merge_config(config, overrides)
    return config


def _set_nested(data: Dict[str, Any], path: str, value: Any) -> None:
    """Establece un valor en un dict anidado usando notación de puntos."""
    parts = path.split(".")
    current = data
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value


def _coerce_value(value: str) -> Any:
    """Intenta convertir string a tipo apropiado."""
    if value.lower() in ("true", "yes", "1"):
        return True
    if value.lower() in ("false", "no", "0"):
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value
