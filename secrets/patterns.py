"""Fuente única de verdad para patrones de detección de credenciales.

Este módulo centraliza TODOS los regex de API keys, tokens y secretos.
Tanto ``agents.credential_interceptor`` como ``secrets.detector`` importan
de aquí para evitar duplicación y desincronización.

Uso:
    from secrets.patterns import CREDENTIAL_PATTERNS
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class CredentialPatternDef:
    """Definición unificada de un patrón de credencial."""

    service_id: str
    env_var: str
    pattern: str  # regex string (no compilado)
    description: str
    kind: str = "api_key"  # api_key, token, secret, id
    unique_prefix: bool = True  # True = se puede detectar sin contexto


# ── Patrones unificados ─────────────────────────────────────────────
# Orden: patrones más específicos primero.
# Los patrones son los MÁS PERMISIVOS de ambos archivos originales
# para no perder detecciones legítimas.

CREDENTIAL_PATTERNS: List[CredentialPatternDef] = [
    # --- Prefijo único (detectables sin contexto) ---
    CredentialPatternDef(
        "anthropic", "ANTHROPIC_API_KEY",
        r"sk-ant-[a-zA-Z0-9_-]{20,}",
        "Anthropic API Key",
    ),
    CredentialPatternDef(
        "openrouter", "OPENROUTER_API_KEY",
        r"sk-or-[a-zA-Z0-9_-]{20,}",
        "OpenRouter API Key",
    ),
    CredentialPatternDef(
        "groq", "GROQ_API_KEY",
        r"gsk_[a-zA-Z0-9]{20,}",
        "Groq API Key",
    ),
    CredentialPatternDef(
        "google", "GOOGLE_API_KEY",
        r"AIza[a-zA-Z0-9_-]{30,}",
        "Google API Key",
    ),
    CredentialPatternDef(
        "huggingface", "HF_TOKEN",
        r"hf_[a-zA-Z0-9]{20,}",
        "HuggingFace Token", "token",
    ),
    CredentialPatternDef(
        "xai", "XAI_API_KEY",
        r"xai-[a-zA-Z0-9]{20,}",
        "xAI API Key",
    ),
    CredentialPatternDef(
        "perplexity", "PERPLEXITY_API_KEY",
        r"pplx-[a-zA-Z0-9]{40,}",
        "Perplexity API Key",
    ),
    CredentialPatternDef(
        "nvidia", "NVIDIA_API_KEY",
        r"nvapi-[a-zA-Z0-9_-]{20,}",
        "NVIDIA API Key",
    ),
    CredentialPatternDef(
        "notion", "NOTION_API_KEY",
        r"(?:ntn_|secret_)[a-zA-Z0-9]{20,}",
        "Notion API Key", "token",
    ),
    CredentialPatternDef(
        "github_pat", "GITHUB_TOKEN",
        r"ghp_[a-zA-Z0-9]{36,}",
        "GitHub Personal Access Token", "token",
    ),
    CredentialPatternDef(
        "github_oauth", "GITHUB_TOKEN",
        r"gho_[a-zA-Z0-9]{36,}",
        "GitHub OAuth Token", "token",
    ),
    CredentialPatternDef(
        "gitlab", "GITLAB_TOKEN",
        r"glpat-[a-zA-Z0-9_-]{20,}",
        "GitLab Token", "token",
    ),
    CredentialPatternDef(
        "slack_bot", "SLACK_BOT_TOKEN",
        r"xoxb-[0-9]+-[a-zA-Z0-9-]+",
        "Slack Bot Token", "token",
    ),
    CredentialPatternDef(
        "slack_app", "SLACK_APP_TOKEN",
        r"xapp-[0-9]+-[a-zA-Z0-9-]+",
        "Slack App Token", "token",
    ),
    CredentialPatternDef(
        "tavily", "TAVILY_API_KEY",
        r"tvly-[a-zA-Z0-9]{20,}",
        "Tavily API Key",
    ),
    CredentialPatternDef(
        "telegram", "TELEGRAM_BOT_TOKEN",
        r"\d{8,13}:[A-Za-z0-9_-]{30,50}",
        "Telegram Bot Token", "token",
    ),
    CredentialPatternDef(
        "discord", "DISCORD_TOKEN",
        r"[A-Za-z0-9_-]{24}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}",
        "Discord Bot Token", "token",
    ),
    # --- OpenAI después de Anthropic/OpenRouter para que sk- no matchee antes ---
    CredentialPatternDef(
        "openai", "OPENAI_API_KEY",
        r"sk-(?!ant-|or-)[a-zA-Z0-9_-]{20,}",
        "OpenAI API Key",
    ),
    # --- Prefijo NO único (necesitan contexto) ---
    CredentialPatternDef(
        "deepseek", "DEEPSEEK_API_KEY",
        r"sk-[a-f0-9]{30,}",
        "DeepSeek API Key",
        unique_prefix=False,
    ),
    CredentialPatternDef(
        "trello_key", "TRELLO_API_KEY",
        r"[a-f0-9]{32}",
        "Trello API Key",
        unique_prefix=False,
    ),
    CredentialPatternDef(
        "trello_token", "TRELLO_TOKEN",
        r"ATTA[a-f0-9]{56,}|[a-f0-9]{64}",
        "Trello Token", "token",
        unique_prefix=False,
    ),
    CredentialPatternDef(
        "mistral", "MISTRAL_API_KEY",
        r"[A-Za-z0-9]{32}",
        "Mistral API Key",
        unique_prefix=False,
    ),
    CredentialPatternDef(
        "together", "TOGETHER_API_KEY",
        r"[a-f0-9]{64}",
        "Together AI API Key",
        unique_prefix=False,
    ),
]


def get_unique_patterns() -> List[CredentialPatternDef]:
    """Retorna solo patrones con prefijo único (detectables sin contexto)."""
    return [p for p in CREDENTIAL_PATTERNS if p.unique_prefix]


def get_context_patterns() -> List[CredentialPatternDef]:
    """Retorna patrones que necesitan contexto para ser detectados."""
    return [p for p in CREDENTIAL_PATTERNS if not p.unique_prefix]
