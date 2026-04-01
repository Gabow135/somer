"""Recolectores de secretos requeridos desde la configuración.

Portado de OpenClaw: runtime-config-collectors.ts,
runtime-config-collectors-core.ts, runtime-config-collectors-channels.ts,
runtime-config-collectors-tts.ts.

Cada recolector inspecciona una sección de la configuración de SOMER,
identifica campos que contienen SecretRefs, y los registra como
asignaciones pendientes en el ResolverContext.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from config.schema import SomerConfig
from secrets.refs import SecretExpectedValue, SecretRef
from secrets.resolve import (
    ResolverContext,
    collect_secret_input_assignment,
)

logger = logging.getLogger(__name__)


# ── Mapa de env vars por provider ───────────────────────────
# Portado de OpenClaw: provider-env-vars.ts PROVIDER_ENV_VARS

PROVIDER_ENV_VARS: Dict[str, List[str]] = {
    "anthropic": ["ANTHROPIC_API_KEY"],
    "openai": ["OPENAI_API_KEY"],
    "deepseek": ["DEEPSEEK_API_KEY"],
    "google": ["GOOGLE_API_KEY", "GEMINI_API_KEY"],
    "ollama": [],
    "bedrock": ["AWS_ACCESS_KEY_ID"],
    "xai": ["XAI_API_KEY"],
    "openrouter": ["OPENROUTER_API_KEY"],
    "mistral": ["MISTRAL_API_KEY"],
    "together": ["TOGETHER_API_KEY"],
    "groq": ["GROQ_API_KEY"],
    "nvidia": ["NVIDIA_API_KEY"],
    "huggingface": ["HUGGINGFACE_API_KEY", "HF_TOKEN"],
    "perplexity": ["PERPLEXITY_API_KEY"],
    "moonshot": ["MOONSHOT_API_KEY"],
    "venice": ["VENICE_API_KEY"],
    "qianfan": ["QIANFAN_API_KEY"],
    "volcengine": ["VOLCENGINE_API_KEY"],
    "minimax": ["MINIMAX_API_KEY"],
    "vllm": [],
    "sglang": [],
}

# ── Credenciales requeridas por canal ───────────────────────
# Portado de OpenClaw: runtime-config-collectors-channels.ts

CHANNEL_REQUIRED_SECRETS: Dict[str, List[Dict[str, str]]] = {
    "telegram": [
        {"field": "bot_token", "env": "TELEGRAM_BOT_TOKEN", "label": "Bot Token"},
        {"field": "webhook_secret", "env": "TELEGRAM_WEBHOOK_SECRET", "label": "Webhook Secret"},
    ],
    "slack": [
        {"field": "bot_token", "env": "SLACK_BOT_TOKEN", "label": "Bot Token"},
        {"field": "app_token", "env": "SLACK_APP_TOKEN", "label": "App Token (socket mode)"},
        {"field": "signing_secret", "env": "SLACK_SIGNING_SECRET", "label": "Signing Secret"},
    ],
    "discord": [
        {"field": "token", "env": "DISCORD_TOKEN", "label": "Bot Token"},
    ],
    "whatsapp": [
        {"field": "api_token", "env": "WHATSAPP_API_TOKEN", "label": "API Token"},
        {"field": "verify_token", "env": "WHATSAPP_VERIFY_TOKEN", "label": "Verify Token"},
    ],
    "signal": [
        {"field": "phone_number", "env": "SIGNAL_PHONE", "label": "Número de teléfono"},
    ],
    "matrix": [
        {"field": "access_token", "env": "MATRIX_ACCESS_TOKEN", "label": "Access Token"},
        {"field": "password", "env": "MATRIX_PASSWORD", "label": "Contraseña"},
    ],
    "irc": [
        {"field": "password", "env": "IRC_PASSWORD", "label": "Contraseña"},
    ],
    "msteams": [
        {"field": "app_id", "env": "MSTEAMS_APP_ID", "label": "App ID"},
        {"field": "app_password", "env": "MSTEAMS_APP_PASSWORD", "label": "App Password"},
    ],
    "googlechat": [
        {"field": "service_account", "env": "GOOGLECHAT_SERVICE_ACCOUNT", "label": "Service Account JSON"},
    ],
    "line": [
        {"field": "channel_access_token", "env": "LINE_CHANNEL_ACCESS_TOKEN", "label": "Channel Access Token"},
        {"field": "channel_secret", "env": "LINE_CHANNEL_SECRET", "label": "Channel Secret"},
    ],
    "twitch": [
        {"field": "oauth_token", "env": "TWITCH_OAUTH_TOKEN", "label": "OAuth Token"},
    ],
    "mattermost": [
        {"field": "bot_token", "env": "MATTERMOST_BOT_TOKEN", "label": "Bot Token"},
    ],
    "nostr": [
        {"field": "private_key", "env": "NOSTR_PRIVATE_KEY", "label": "Clave privada"},
    ],
    "feishu": [
        {"field": "app_secret", "env": "FEISHU_APP_SECRET", "label": "App Secret"},
        {"field": "encrypt_key", "env": "FEISHU_ENCRYPT_KEY", "label": "Encrypt Key"},
        {"field": "verification_token", "env": "FEISHU_VERIFICATION_TOKEN", "label": "Verification Token"},
    ],
    "webchat": [],
}

# ── Credenciales requeridas por skill/integración ─────────
# Mapea skills que requieren variables de entorno para funcionar

SKILL_REQUIRED_SECRETS: Dict[str, List[Dict[str, str]]] = {
    "trello": [
        {"field": "api_key", "env": "TRELLO_API_KEY", "label": "API Key"},
        {"field": "token", "env": "TRELLO_TOKEN", "label": "Token de autorización"},
        {"field": "board_id", "env": "TRELLO_BOARD_ID", "label": "Board ID (opcional)"},
    ],
    "notion": [
        {"field": "api_key", "env": "NOTION_API_KEY", "label": "API Key (Integration Token)"},
        {"field": "database_id", "env": "NOTION_DEFAULT_DATABASE", "label": "Database ID"},
    ],
    "github": [
        {"field": "token", "env": "GITHUB_TOKEN", "label": "Personal Access Token"},
    ],
    "gitlab": [
        {"field": "token", "env": "GITLAB_TOKEN", "label": "Personal Access Token"},
    ],
    "tavily": [
        {"field": "api_key", "env": "TAVILY_API_KEY", "label": "API Key"},
    ],
    "brave-search": [
        {"field": "api_key", "env": "BRAVE_API_KEY", "label": "API Key"},
    ],
    "elevenlabs": [
        {"field": "api_key", "env": "ELEVENLABS_API_KEY", "label": "API Key"},
    ],
    "bitbucket": [
        {"field": "username", "env": "BITBUCKET_USERNAME", "label": "Username"},
        {"field": "app_password", "env": "BITBUCKET_APP_PASSWORD", "label": "App Password"},
    ],
}


def collect_all_assignments(
    *,
    config: SomerConfig,
    context: ResolverContext,
) -> None:
    """Recolecta todas las asignaciones de secretos de la configuración.

    Portado de OpenClaw: runtime-config-collectors.ts collectConfigAssignments().

    Args:
        config: Configuración de SOMER a inspeccionar.
        context: Contexto de resolución donde se acumulan asignaciones.
    """
    collect_provider_assignments(config=config, context=context)
    collect_channel_assignments(config=config, context=context)
    collect_gateway_assignments(config=config, context=context)
    collect_tts_assignments(config=config, context=context)


# ── Providers ───────────────────────────────────────────────

def collect_provider_assignments(
    *,
    config: SomerConfig,
    context: ResolverContext,
) -> None:
    """Recolecta asignaciones de secretos de providers LLM.

    Portado de OpenClaw: runtime-config-collectors-core.ts
    collectModelProviderAssignments().

    Inspecciona api_key, api_key_env y api_key_file de cada provider.
    """
    for provider_id, provider_settings in config.providers.items():
        is_active = provider_settings.enabled
        auth = provider_settings.auth

        # api_key directa (puede ser SecretRef string)
        collect_secret_input_assignment(
            value=auth.api_key,
            path=f"providers.{provider_id}.auth.api_key",
            expected=SecretExpectedValue.STRING,
            context=context,
            active=is_active,
            inactive_reason=f"provider {provider_id} está deshabilitado.",
            apply=lambda v, a=auth: setattr(a, "api_key", v),
        )

        # api_key_env (referencia implícita a env var)
        if auth.api_key_env and not auth.api_key:
            ref = SecretRef.from_env(auth.api_key_env)
            env_value = context.env.get(auth.api_key_env)
            if env_value:
                # Ya disponible en env, no necesita resolución
                continue

        # api_key_file (referencia implícita a archivo)
        if auth.api_key_file and not auth.api_key:
            collect_secret_input_assignment(
                value=f"file:{auth.api_key_file}",
                path=f"providers.{provider_id}.auth.api_key_file",
                expected=SecretExpectedValue.STRING,
                context=context,
                active=is_active,
                inactive_reason=f"provider {provider_id} está deshabilitado.",
                apply=lambda v, a=auth: setattr(a, "api_key", v),
            )


# ── Canales ─────────────────────────────────────────────────

def collect_channel_assignments(
    *,
    config: SomerConfig,
    context: ResolverContext,
) -> None:
    """Recolecta asignaciones de secretos de canales.

    Portado de OpenClaw: runtime-config-collectors-channels.ts
    collectChannelConfigAssignments().

    Inspecciona los campos de configuración de cada canal habilitado.
    """
    for channel_id, channel_config in config.channels.entries.items():
        is_active = channel_config.enabled
        channel_data = channel_config.config

        # Buscar SecretRefs en la config del canal
        for key, value in channel_data.items():
            collect_secret_input_assignment(
                value=value,
                path=f"channels.{channel_id}.config.{key}",
                expected=SecretExpectedValue.STRING,
                context=context,
                active=is_active,
                inactive_reason=f"canal {channel_id} está deshabilitado.",
                apply=_make_dict_setter(channel_data, key),
            )

        # Verificar env vars conocidas para el canal
        required = CHANNEL_REQUIRED_SECRETS.get(channel_id, [])
        for secret_spec in required:
            field_name = secret_spec["field"]
            env_var = secret_spec["env"]
            # Si el campo no está explícito en config, verificar env
            if field_name not in channel_data:
                env_value = context.env.get(env_var)
                if env_value:
                    channel_data[field_name] = env_value


# ── Gateway ─────────────────────────────────────────────────

def collect_gateway_assignments(
    *,
    config: SomerConfig,
    context: ResolverContext,
) -> None:
    """Recolecta asignaciones de secretos del gateway.

    Portado de OpenClaw: runtime-config-collectors-core.ts
    collectGatewayAssignments().
    """
    # El gateway de SOMER no tiene auth por ahora,
    # pero dejamos el esqueleto para extensión futura
    gateway = config.gateway
    metadata = config.metadata

    # Verificar si hay token de auth en metadata
    if "gateway_token" in metadata:
        collect_secret_input_assignment(
            value=metadata.get("gateway_token"),
            path="metadata.gateway_token",
            expected=SecretExpectedValue.STRING,
            context=context,
            apply=lambda v: metadata.__setitem__("gateway_token", v),
        )


# ── TTS ─────────────────────────────────────────────────────

def collect_tts_assignments(
    *,
    config: SomerConfig,
    context: ResolverContext,
) -> None:
    """Recolecta asignaciones de secretos de TTS.

    Portado de OpenClaw: runtime-config-collectors-tts.ts
    collectTtsApiKeyAssignments().
    """
    # TTS está en metadata.tts si existe
    tts_config = config.metadata.get("tts")
    if not isinstance(tts_config, dict):
        return

    # ElevenLabs
    elevenlabs = tts_config.get("elevenlabs")
    if isinstance(elevenlabs, dict) and "api_key" in elevenlabs:
        collect_secret_input_assignment(
            value=elevenlabs.get("api_key"),
            path="metadata.tts.elevenlabs.api_key",
            expected=SecretExpectedValue.STRING,
            context=context,
            apply=_make_dict_setter(elevenlabs, "api_key"),
        )

    # OpenAI TTS
    openai_tts = tts_config.get("openai")
    if isinstance(openai_tts, dict) and "api_key" in openai_tts:
        collect_secret_input_assignment(
            value=openai_tts.get("api_key"),
            path="metadata.tts.openai.api_key",
            expected=SecretExpectedValue.STRING,
            context=context,
            apply=_make_dict_setter(openai_tts, "api_key"),
        )


# ── Descubrimiento de secretos requeridos ───────────────────

def discover_required_secrets(
    config: SomerConfig,
) -> List[Dict[str, Any]]:
    """Descubre todos los secretos requeridos por la configuración actual.

    Portado de OpenClaw: configure-plan.ts buildConfigureCandidates().

    Retorna una lista de candidatos indicando qué secretos necesitan
    ser configurados.

    Args:
        config: Configuración de SOMER.

    Returns:
        Lista de dicts con info de cada secreto requerido:
        - path: Ruta en la config
        - label: Etiqueta legible
        - source: Fuente sugerida (env, file, etc.)
        - env_var: Variable de entorno sugerida
        - configured: Si ya tiene un valor configurado
    """
    candidates: List[Dict[str, Any]] = []

    # Providers
    for provider_id, provider_settings in config.providers.items():
        if not provider_settings.enabled:
            continue
        auth = provider_settings.auth
        env_vars = PROVIDER_ENV_VARS.get(provider_id, [])
        primary_env = env_vars[0] if env_vars else f"{provider_id.upper()}_API_KEY"

        configured = bool(
            auth.api_key
            or (auth.api_key_env and _env_has(auth.api_key_env))
            or auth.api_key_file
        )
        candidates.append({
            "path": f"providers.{provider_id}.auth.api_key",
            "label": f"API Key de {provider_id}",
            "source": "env",
            "env_var": primary_env,
            "configured": configured,
            "provider_id": provider_id,
        })

    # Canales
    for channel_id, channel_config in config.channels.entries.items():
        if not channel_config.enabled:
            continue
        required = CHANNEL_REQUIRED_SECRETS.get(channel_id, [])
        for secret_spec in required:
            field_name = secret_spec["field"]
            env_var = secret_spec["env"]
            label = secret_spec["label"]

            configured = bool(
                channel_config.config.get(field_name)
                or _env_has(env_var)
            )
            candidates.append({
                "path": f"channels.{channel_id}.config.{field_name}",
                "label": f"{channel_id} — {label}",
                "source": "env",
                "env_var": env_var,
                "configured": configured,
                "channel_id": channel_id,
            })

    return candidates


def list_known_provider_env_vars() -> List[str]:
    """Lista todas las env vars conocidas de providers.

    Portado de OpenClaw: provider-env-vars.ts listKnownProviderAuthEnvVarNames().
    """
    result: List[str] = []
    seen = set()
    for env_vars in PROVIDER_ENV_VARS.values():
        for var in env_vars:
            if var not in seen:
                seen.add(var)
                result.append(var)
    return result


def list_known_secret_env_vars() -> List[str]:
    """Lista todas las env vars conocidas que contienen secretos.

    Portado de OpenClaw: provider-env-vars.ts listKnownSecretEnvVarNames().
    Incluye vars de providers y de canales.
    """
    result = set(list_known_provider_env_vars())
    for channel_secrets in CHANNEL_REQUIRED_SECRETS.values():
        for secret_spec in channel_secrets:
            result.add(secret_spec["env"])
    for skill_secrets in SKILL_REQUIRED_SECRETS.values():
        for secret_spec in skill_secrets:
            result.add(secret_spec["env"])
    return sorted(result)


# ── Helpers ─────────────────────────────────────────────────

def _make_dict_setter(d: Dict[str, Any], key: str) -> Any:
    """Crea una función setter para un dict."""
    def _setter(value: Any) -> None:
        d[key] = value
    return _setter


def _env_has(var_name: str) -> bool:
    """Verifica si una env var está definida y no vacía."""
    import os
    value = os.environ.get(var_name, "")
    return len(value.strip()) > 0
