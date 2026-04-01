"""Detector automático de credenciales en texto libre.

Analiza mensajes del usuario para detectar API keys, tokens y otros
secretos. Cuando encuentra coincidencias, las asocia con variables de
entorno conocidas y las guarda en ~/.somer/.env.

Uso:
    from secrets.detector import CredentialDetector
    detector = CredentialDetector()
    results = detector.scan(text)
    saved = detector.save_detected(results)
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from infra.env import mask_secret, save_env_var, list_env_vars

logger = logging.getLogger(__name__)


# ── Patrones de detección ─────────────────────────────────
# Cada entrada: (nombre_servicio, env_var, regex_patrón, descripción)

@dataclass
class CredentialPattern:
    """Patrón de detección para un tipo de credencial."""
    service: str
    env_var: str
    pattern: re.Pattern[str]
    description: str
    kind: str = "api_key"  # api_key, token, secret, id


# Patrones por prefijo conocido de API keys
_PREFIX_PATTERNS: List[CredentialPattern] = [
    CredentialPattern("anthropic", "ANTHROPIC_API_KEY",
                      re.compile(r"sk-ant-[a-zA-Z0-9_-]{20,}"),
                      "Anthropic API Key"),
    CredentialPattern("openai", "OPENAI_API_KEY",
                      re.compile(r"sk-(?!ant-|or-)[a-zA-Z0-9_-]{20,}"),
                      "OpenAI API Key"),
    CredentialPattern("openrouter", "OPENROUTER_API_KEY",
                      re.compile(r"sk-or-[a-zA-Z0-9_-]{20,}"),
                      "OpenRouter API Key"),
    CredentialPattern("groq", "GROQ_API_KEY",
                      re.compile(r"gsk_[a-zA-Z0-9]{20,}"),
                      "Groq API Key"),
    CredentialPattern("google", "GOOGLE_API_KEY",
                      re.compile(r"AIza[a-zA-Z0-9_-]{30,}"),
                      "Google API Key"),
    CredentialPattern("huggingface", "HUGGINGFACE_API_KEY",
                      re.compile(r"hf_[a-zA-Z0-9]{20,}"),
                      "HuggingFace Token"),
    CredentialPattern("xai", "XAI_API_KEY",
                      re.compile(r"xai-[a-zA-Z0-9]{20,}"),
                      "xAI API Key"),
    CredentialPattern("perplexity", "PERPLEXITY_API_KEY",
                      re.compile(r"pplx-[a-zA-Z0-9]{40,}"),
                      "Perplexity API Key"),
    CredentialPattern("nvidia", "NVIDIA_API_KEY",
                      re.compile(r"nvapi-[a-zA-Z0-9_-]{20,}"),
                      "NVIDIA API Key"),
    CredentialPattern("notion", "NOTION_API_KEY",
                      re.compile(r"secret_[a-zA-Z0-9]{40,}"),
                      "Notion API Key", "token"),
    CredentialPattern("github", "GITHUB_TOKEN",
                      re.compile(r"ghp_[a-zA-Z0-9]{36,}"),
                      "GitHub Personal Access Token", "token"),
    CredentialPattern("github", "GITHUB_TOKEN",
                      re.compile(r"gho_[a-zA-Z0-9]{36,}"),
                      "GitHub OAuth Token", "token"),
    CredentialPattern("gitlab", "GITLAB_TOKEN",
                      re.compile(r"glpat-[a-zA-Z0-9_-]{20,}"),
                      "GitLab Token", "token"),
    CredentialPattern("slack", "SLACK_BOT_TOKEN",
                      re.compile(r"xoxb-[0-9]+-[a-zA-Z0-9-]+"),
                      "Slack Bot Token", "token"),
    CredentialPattern("slack", "SLACK_APP_TOKEN",
                      re.compile(r"xapp-[0-9]+-[a-zA-Z0-9-]+"),
                      "Slack App Token", "token"),
    CredentialPattern("discord", "DISCORD_TOKEN",
                      re.compile(r"[A-Za-z0-9_-]{24}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}"),
                      "Discord Bot Token", "token"),
    CredentialPattern("telegram", "TELEGRAM_BOT_TOKEN",
                      re.compile(r"\d{8,13}:[A-Za-z0-9_-]{30,50}"),
                      "Telegram Bot Token", "token"),
    CredentialPattern("twilio", "TWILIO_AUTH_TOKEN",
                      re.compile(r"(?<=TWILIO|twilio)[^a-f0-9]*([a-f0-9]{32})"),
                      "Twilio Auth Token", "token"),
]

# Patrones para detección por contexto: el usuario dice "mi X es Y"
# Soporta español e inglés
_CONTEXT_KEYWORDS: Dict[str, List[str]] = {
    # Trello
    "TRELLO_API_KEY": [
        r"trello[\s_-]*(?:api[\s_-]*)?key",
    ],
    "TRELLO_TOKEN": [
        r"trello[\s_-]*(?:api[\s_-]*)?token",
        r"trello[\s_-]*(?:oauth[\s_-]*)?token",
    ],
    "TRELLO_BOARD_ID": [
        r"trello[\s_-]*board[\s_-]*id",
        r"(?:id|ID)[\s_-]*(?:del?|of)?[\s_-]*(?:tablero|board)[\s_-]*(?:de[\s_-]*)?trello",
    ],
    # Notion
    "NOTION_API_KEY": [
        r"notion[\s_-]*(?:api[\s_-]*)?(?:key|token|secret)",
    ],
    "NOTION_DEFAULT_DATABASE": [
        r"notion[\s_-]*(?:database|db)[\s_-]*(?:id)?",
    ],
    # GitHub
    "GITHUB_TOKEN": [
        r"github[\s_-]*(?:personal[\s_-]*)?(?:access[\s_-]*)?token",
        r"github[\s_-]*pat",
    ],
    # Telegram
    "TELEGRAM_BOT_TOKEN": [
        r"telegram[\s_-]*(?:bot[\s_-]*)?token",
    ],
    # Discord
    "DISCORD_TOKEN": [
        r"discord[\s_-]*(?:bot[\s_-]*)?token",
    ],
    # Slack
    "SLACK_BOT_TOKEN": [
        r"slack[\s_-]*(?:bot[\s_-]*)?token",
    ],
    # APIs genéricas
    "ANTHROPIC_API_KEY": [
        r"anthropic[\s_-]*(?:api[\s_-]*)?key",
        r"claude[\s_-]*(?:api[\s_-]*)?key",
    ],
    "OPENAI_API_KEY": [
        r"openai[\s_-]*(?:api[\s_-]*)?key",
    ],
    "DEEPSEEK_API_KEY": [
        r"deepseek[\s_-]*(?:api[\s_-]*)?key",
    ],
    "GOOGLE_API_KEY": [
        r"google[\s_-]*(?:api[\s_-]*)?key",
        r"gemini[\s_-]*(?:api[\s_-]*)?key",
    ],
    "GROQ_API_KEY": [
        r"groq[\s_-]*(?:api[\s_-]*)?key",
    ],
    # Servicios adicionales
    "REDIS_URL": [
        r"redis[\s_-]*(?:url|uri|connection)",
    ],
    "ELEVENLABS_API_KEY": [
        r"eleven[\s_-]*labs?[\s_-]*(?:api[\s_-]*)?key",
    ],
    "TAVILY_API_KEY": [
        r"tavily[\s_-]*(?:api[\s_-]*)?key",
    ],
    "BRAVE_API_KEY": [
        r"brave[\s_-]*(?:search[\s_-]*)?(?:api[\s_-]*)?key",
    ],
}

# Patrón para extraer el valor que el usuario da después de un keyword
# Soporta: "es X", "is X", ": X", "= X", formatos con comillas, backticks
_VALUE_EXTRACT = re.compile(
    r"(?:es|is|[:=])\s*[`\"']?([^\s`\"',]+)[`\"']?",
    re.IGNORECASE,
)

# Patrón alternativo: valor en la siguiente línea o después de un salto
_VALUE_MULTILINE = re.compile(
    r"[:\-]\s*\n\s*[`\"']?([^\s`\"'\n,]+)[`\"']?",
)


@dataclass
class DetectedCredential:
    """Credencial detectada en el texto."""
    env_var: str
    value: str
    service: str
    description: str
    kind: str = "api_key"
    confidence: str = "high"  # high, medium, low
    source: str = "prefix"  # prefix (patrón conocido), context (keyword + valor)
    already_set: bool = False

    @property
    def masked_value(self) -> str:
        return mask_secret(self.value)


@dataclass
class DetectionReport:
    """Reporte de detección de credenciales."""
    credentials: List[DetectedCredential] = field(default_factory=list)
    text_scanned: int = 0

    @property
    def total(self) -> int:
        return len(self.credentials)

    @property
    def new_credentials(self) -> List[DetectedCredential]:
        return [c for c in self.credentials if not c.already_set]

    @property
    def existing_credentials(self) -> List[DetectedCredential]:
        return [c for c in self.credentials if c.already_set]

    def summary(self) -> str:
        new = len(self.new_credentials)
        existing = len(self.existing_credentials)
        parts = [f"{self.total} credencial(es) detectada(s)"]
        if new:
            parts.append(f"{new} nueva(s)")
        if existing:
            parts.append(f"{existing} ya configurada(s)")
        return " | ".join(parts)


class CredentialDetector:
    """Detector de credenciales en texto libre.

    Combina dos estrategias:
    1. Detección por prefijo: busca patrones conocidos (sk-ant-, ghp_, etc.)
    2. Detección por contexto: busca "mi TRELLO_API_KEY es XYZ" o similar

    Uso:
        detector = CredentialDetector()
        report = detector.scan("mi trello api key es abc123def456")
        saved = detector.save_detected(report)
    """

    def __init__(self) -> None:
        self._current_env = list_env_vars()

    def scan(self, text: str) -> DetectionReport:
        """Escanea texto en busca de credenciales.

        Args:
            text: Texto libre (mensaje del usuario).

        Returns:
            DetectionReport con las credenciales encontradas.
        """
        report = DetectionReport(text_scanned=len(text))
        seen_vars: Dict[str, str] = {}  # env_var → value (evita duplicados)

        # Estrategia 1: Detección por prefijo conocido
        for cp in _PREFIX_PATTERNS:
            for match in cp.pattern.finditer(text):
                value = match.group(0).strip()
                if len(value) < 10:
                    continue
                if cp.env_var in seen_vars:
                    continue
                seen_vars[cp.env_var] = value
                report.credentials.append(DetectedCredential(
                    env_var=cp.env_var,
                    value=value,
                    service=cp.service,
                    description=cp.description,
                    kind=cp.kind,
                    confidence="high",
                    source="prefix",
                    already_set=self._is_already_set(cp.env_var, value),
                ))

        # Estrategia 2: Detección por contexto (keyword + valor)
        for env_var, keywords in _CONTEXT_KEYWORDS.items():
            if env_var in seen_vars:
                continue
            for kw_pattern in keywords:
                kw_re = re.compile(kw_pattern, re.IGNORECASE)
                kw_match = kw_re.search(text)
                if not kw_match:
                    continue
                # Buscar el valor después del keyword
                after_kw = text[kw_match.end():]
                val_match = _VALUE_EXTRACT.search(after_kw[:200])
                if not val_match:
                    val_match = _VALUE_MULTILINE.search(after_kw[:200])
                if val_match:
                    value = val_match.group(1).strip()
                    if len(value) < 5:
                        continue
                    # Limpiar posibles caracteres trailing
                    value = value.rstrip(".,;:!?)")
                    if not value:
                        continue
                    service = self._env_var_to_service(env_var)
                    seen_vars[env_var] = value
                    report.credentials.append(DetectedCredential(
                        env_var=env_var,
                        value=value,
                        service=service,
                        description=f"{service} — {env_var}",
                        kind=self._classify_kind(env_var),
                        confidence="medium",
                        source="context",
                        already_set=self._is_already_set(env_var, value),
                    ))
                    break

        # Estrategia 3: Detección directa "VARIABLE=valor" o "VARIABLE: valor"
        direct_re = re.compile(
            r"\b([A-Z][A-Z0-9_]{3,}_(?:API_KEY|TOKEN|SECRET|PASSWORD|ID|URL|SID))\s*[=:]\s*[`\"']?([^\s`\"'\n,]+)[`\"']?",
        )
        for dm in direct_re.finditer(text):
            env_var = dm.group(1).strip()
            value = dm.group(2).strip().rstrip(".,;:!?)")
            if env_var in seen_vars or len(value) < 5:
                continue
            service = self._env_var_to_service(env_var)
            seen_vars[env_var] = value
            report.credentials.append(DetectedCredential(
                env_var=env_var,
                value=value,
                service=service,
                description=f"{service} — {env_var}",
                kind=self._classify_kind(env_var),
                confidence="high",
                source="direct",
                already_set=self._is_already_set(env_var, value),
            ))

        return report

    def save_detected(
        self,
        report: DetectionReport,
        *,
        only_new: bool = True,
    ) -> List[Tuple[str, str]]:
        """Guarda las credenciales detectadas en ~/.somer/.env.

        Args:
            report: Reporte de detección.
            only_new: Si True, solo guarda credenciales que no existen.

        Returns:
            Lista de (env_var, masked_value) guardadas.
        """
        saved: List[Tuple[str, str]] = []
        creds = report.new_credentials if only_new else report.credentials

        for cred in creds:
            try:
                save_env_var(cred.env_var, cred.value)
                saved.append((cred.env_var, cred.masked_value))
                logger.info(
                    "Credencial guardada: %s = %s (%s)",
                    cred.env_var, cred.masked_value, cred.service,
                )
            except Exception as exc:
                logger.error(
                    "Error guardando %s: %s", cred.env_var, exc,
                )

        # Refrescar cache interno
        self._current_env = list_env_vars()
        return saved

    def check_skill_requirements(
        self,
        required_env: List[str],
    ) -> List[str]:
        """Verifica qué variables faltan para un skill.

        Args:
            required_env: Lista de env vars requeridas.

        Returns:
            Lista de env vars faltantes.
        """
        self._current_env = list_env_vars()
        missing = []
        for var in required_env:
            if not os.environ.get(var) and var not in self._current_env:
                missing.append(var)
        return missing

    def _is_already_set(self, env_var: str, value: str) -> bool:
        """Verifica si una variable ya tiene el mismo valor."""
        current = self._current_env.get(env_var) or os.environ.get(env_var)
        if not current:
            return False
        return current.strip() == value.strip()

    @staticmethod
    def _env_var_to_service(env_var: str) -> str:
        """Deriva el nombre del servicio desde la variable de entorno."""
        # TRELLO_API_KEY → trello, TELEGRAM_BOT_TOKEN → telegram
        parts = env_var.lower().split("_")
        # Quitar suffixes conocidos
        suffixes = {"api", "key", "token", "secret", "password", "id", "url", "sid", "bot"}
        service_parts = [p for p in parts if p not in suffixes]
        return service_parts[0] if service_parts else parts[0]

    @staticmethod
    def _classify_kind(env_var: str) -> str:
        """Clasifica el tipo de credencial según el nombre de variable."""
        upper = env_var.upper()
        if "TOKEN" in upper:
            return "token"
        if "SECRET" in upper or "PASSWORD" in upper:
            return "secret"
        if "_ID" in upper or "_SID" in upper:
            return "id"
        if "_URL" in upper or "_URI" in upper:
            return "url"
        return "api_key"
