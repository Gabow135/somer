"""Validación de secretos — verificación de formato y conectividad.

Portado de OpenClaw: audit.ts (validación de secretos),
configure.ts (verificación de API keys).

Proporciona validación de formato para API keys de distintos providers
y pruebas de conectividad opcionales.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from secrets.refs import SecretRef, SecretSource
from secrets.store import CredentialStore
from shared.errors import SecretError

logger = logging.getLogger(__name__)


# ── Patrones de validación por provider ─────────────────────

class ApiKeyPattern:
    """Patrones regex para validar formato de API keys por provider."""

    ANTHROPIC = re.compile(r"^sk-ant-[a-zA-Z0-9_-]{20,}$")
    OPENAI = re.compile(r"^sk-[a-zA-Z0-9_-]{20,}$")
    DEEPSEEK = re.compile(r"^sk-[a-zA-Z0-9]{20,}$")
    GOOGLE = re.compile(r"^AI[a-zA-Z0-9_-]{30,}$")
    GROQ = re.compile(r"^gsk_[a-zA-Z0-9]{20,}$")
    MISTRAL = re.compile(r"^[a-zA-Z0-9]{20,}$")
    TOGETHER = re.compile(r"^[a-f0-9]{40,}$")
    XAI = re.compile(r"^xai-[a-zA-Z0-9]{20,}$")
    OPENROUTER = re.compile(r"^sk-or-[a-zA-Z0-9_-]{20,}$")
    HUGGINGFACE = re.compile(r"^hf_[a-zA-Z0-9]{20,}$")
    PERPLEXITY = re.compile(r"^pplx-[a-zA-Z0-9]{40,}$")
    NVIDIA = re.compile(r"^nvapi-[a-zA-Z0-9_-]{20,}$")
    # Patrón genérico para providers sin formato específico
    GENERIC = re.compile(r"^.{10,}$")


# Mapeo provider → patrón
PROVIDER_KEY_PATTERNS: Dict[str, re.Pattern[str]] = {
    "anthropic": ApiKeyPattern.ANTHROPIC,
    "openai": ApiKeyPattern.OPENAI,
    "deepseek": ApiKeyPattern.DEEPSEEK,
    "google": ApiKeyPattern.GOOGLE,
    "groq": ApiKeyPattern.GROQ,
    "mistral": ApiKeyPattern.MISTRAL,
    "together": ApiKeyPattern.TOGETHER,
    "xai": ApiKeyPattern.XAI,
    "openrouter": ApiKeyPattern.OPENROUTER,
    "huggingface": ApiKeyPattern.HUGGINGFACE,
    "perplexity": ApiKeyPattern.PERPLEXITY,
    "nvidia": ApiKeyPattern.NVIDIA,
}


class ValidationSeverity(str, Enum):
    """Severidad de un resultado de validación."""
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class ValidationResult:
    """Resultado de la validación de un secreto."""
    path: str
    severity: ValidationSeverity
    message: str
    provider_id: Optional[str] = None
    channel_id: Optional[str] = None


@dataclass
class ValidationReport:
    """Reporte completo de validación de secretos."""
    results: List[ValidationResult] = field(default_factory=list)
    total_checked: int = 0
    total_ok: int = 0
    total_warnings: int = 0
    total_errors: int = 0

    @property
    def is_clean(self) -> bool:
        """True si no hay errores ni warnings."""
        return self.total_errors == 0 and self.total_warnings == 0

    def add(self, result: ValidationResult) -> None:
        """Agrega un resultado al reporte."""
        self.results.append(result)
        self.total_checked += 1
        if result.severity == ValidationSeverity.OK:
            self.total_ok += 1
        elif result.severity == ValidationSeverity.WARNING:
            self.total_warnings += 1
        elif result.severity == ValidationSeverity.ERROR:
            self.total_errors += 1

    def summary(self) -> str:
        """Genera un resumen textual del reporte."""
        return (
            f"Validación de secretos: {self.total_checked} verificados, "
            f"{self.total_ok} OK, {self.total_warnings} warnings, "
            f"{self.total_errors} errores"
        )


def validate_api_key_format(
    provider_id: str,
    api_key: str,
) -> ValidationResult:
    """Valida el formato de una API key para un provider.

    Args:
        provider_id: ID del provider (anthropic, openai, etc.).
        api_key: La API key a validar.

    Returns:
        ValidationResult con el resultado de la validación.
    """
    path = f"providers.{provider_id}.auth.api_key"

    if not api_key or not api_key.strip():
        return ValidationResult(
            path=path,
            severity=ValidationSeverity.ERROR,
            message=f"API key de {provider_id} está vacía.",
            provider_id=provider_id,
        )

    pattern = PROVIDER_KEY_PATTERNS.get(provider_id, ApiKeyPattern.GENERIC)
    if pattern.match(api_key.strip()):
        return ValidationResult(
            path=path,
            severity=ValidationSeverity.OK,
            message=f"API key de {provider_id} tiene formato válido.",
            provider_id=provider_id,
        )
    else:
        return ValidationResult(
            path=path,
            severity=ValidationSeverity.WARNING,
            message=f"API key de {provider_id} no coincide con el patrón esperado. "
                    f"Puede ser válida pero no se pudo verificar el formato.",
            provider_id=provider_id,
        )


def validate_secret_ref(ref: SecretRef) -> ValidationResult:
    """Valida que un SecretRef puede resolverse.

    Args:
        ref: La referencia a validar.

    Returns:
        ValidationResult con el resultado.
    """
    path = f"ref:{ref.ref_key()}"
    try:
        value = ref.resolve()
        if not value or not value.strip():
            return ValidationResult(
                path=path,
                severity=ValidationSeverity.ERROR,
                message=f"Referencia {ref.ref_key()} se resolvió a valor vacío.",
            )
        return ValidationResult(
            path=path,
            severity=ValidationSeverity.OK,
            message=f"Referencia {ref.ref_key()} resuelta correctamente.",
        )
    except Exception as exc:
        return ValidationResult(
            path=path,
            severity=ValidationSeverity.ERROR,
            message=f"No se pudo resolver {ref.ref_key()}: {exc}",
        )


async def validate_provider_connectivity(
    provider_id: str,
    api_key: str,
    base_url: Optional[str] = None,
) -> ValidationResult:
    """Prueba de conectividad con un provider LLM.

    Intenta hacer una solicitud mínima al provider para verificar
    que la API key funciona.

    Args:
        provider_id: ID del provider.
        api_key: API key a verificar.
        base_url: URL base opcional.

    Returns:
        ValidationResult con el resultado de conectividad.
    """
    path = f"providers.{provider_id}.connectivity"

    # Importar aiohttp/httpx si disponible
    try:
        import aiohttp
        _has_aiohttp = True
    except ImportError:
        _has_aiohttp = False

    if not _has_aiohttp:
        return ValidationResult(
            path=path,
            severity=ValidationSeverity.WARNING,
            message=f"No se puede verificar conectividad de {provider_id}: "
                    f"aiohttp no está instalado.",
            provider_id=provider_id,
        )

    # URLs de verificación por provider
    health_urls: Dict[str, str] = {
        "anthropic": "https://api.anthropic.com/v1/messages",
        "openai": "https://api.openai.com/v1/models",
        "deepseek": "https://api.deepseek.com/v1/models",
        "groq": "https://api.groq.com/openai/v1/models",
        "mistral": "https://api.mistral.ai/v1/models",
        "together": "https://api.together.xyz/v1/models",
        "xai": "https://api.x.ai/v1/models",
        "openrouter": "https://openrouter.ai/api/v1/models",
        "perplexity": "https://api.perplexity.ai/chat/completions",
    }

    url = base_url or health_urls.get(provider_id)
    if not url:
        return ValidationResult(
            path=path,
            severity=ValidationSeverity.WARNING,
            message=f"No hay URL de verificación para {provider_id}.",
            provider_id=provider_id,
        )

    try:
        headers: Dict[str, str] = {}
        if provider_id == "anthropic":
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            }
        else:
            headers = {"Authorization": f"Bearer {api_key}"}

        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url if provider_id != "anthropic" else "https://api.anthropic.com/v1/models",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status in (200, 401, 403):
                    if resp.status == 200:
                        return ValidationResult(
                            path=path,
                            severity=ValidationSeverity.OK,
                            message=f"Conectividad con {provider_id} verificada.",
                            provider_id=provider_id,
                        )
                    else:
                        return ValidationResult(
                            path=path,
                            severity=ValidationSeverity.ERROR,
                            message=f"API key de {provider_id} rechazada (HTTP {resp.status}).",
                            provider_id=provider_id,
                        )
                else:
                    return ValidationResult(
                        path=path,
                        severity=ValidationSeverity.WARNING,
                        message=f"Respuesta inesperada de {provider_id}: HTTP {resp.status}.",
                        provider_id=provider_id,
                    )
    except Exception as exc:
        return ValidationResult(
            path=path,
            severity=ValidationSeverity.WARNING,
            message=f"Error de conectividad con {provider_id}: {exc}",
            provider_id=provider_id,
        )


def validate_config_secrets(
    config: Any,
    store: Optional[CredentialStore] = None,
) -> ValidationReport:
    """Valida todos los secretos en una configuración de SOMER.

    Portado de OpenClaw: audit.ts (sección de validación de secretos).

    Verifica formato de API keys, disponibilidad de env vars,
    y accesibilidad de archivos de secretos.

    Args:
        config: Configuración de SOMER (SomerConfig).
        store: CredentialStore opcional para verificar secretos almacenados.

    Returns:
        ValidationReport con todos los resultados.
    """
    report = ValidationReport()

    # Validar providers
    for provider_id, provider_settings in config.providers.items():
        if not provider_settings.enabled:
            continue
        auth = provider_settings.auth

        # Verificar que tiene alguna fuente de API key configurada
        has_key = bool(auth.api_key or auth.api_key_env or auth.api_key_file)
        has_store = store is not None and store.has(provider_id)
        has_env = bool(auth.api_key_env and os.environ.get(auth.api_key_env))

        if not has_key and not has_store and not has_env:
            report.add(ValidationResult(
                path=f"providers.{provider_id}",
                severity=ValidationSeverity.ERROR,
                message=f"Provider {provider_id} habilitado sin API key configurada.",
                provider_id=provider_id,
            ))
            continue

        # Validar formato si tenemos la key
        key_value = None
        if auth.api_key:
            key_value = auth.api_key
        elif auth.api_key_env:
            key_value = os.environ.get(auth.api_key_env)

        if key_value:
            result = validate_api_key_format(provider_id, key_value)
            report.add(result)
        elif auth.api_key_file:
            # Verificar que el archivo existe
            ref = SecretRef.from_file(auth.api_key_file)
            result = validate_secret_ref(ref)
            result.provider_id = provider_id
            report.add(result)
        elif has_store:
            report.add(ValidationResult(
                path=f"providers.{provider_id}",
                severity=ValidationSeverity.OK,
                message=f"Provider {provider_id} tiene credenciales en store.",
                provider_id=provider_id,
            ))

    # Validar canales
    for channel_id, channel_config in config.channels.entries.items():
        if not channel_config.enabled:
            continue

        from secrets.collectors import CHANNEL_REQUIRED_SECRETS
        required = CHANNEL_REQUIRED_SECRETS.get(channel_id, [])
        for secret_spec in required:
            field_name = secret_spec["field"]
            env_var = secret_spec["env"]
            label = secret_spec["label"]

            has_config = bool(channel_config.config.get(field_name))
            has_env_val = bool(os.environ.get(env_var))

            if not has_config and not has_env_val:
                # Algunos campos son opcionales (ej: webhook_secret)
                report.add(ValidationResult(
                    path=f"channels.{channel_id}.config.{field_name}",
                    severity=ValidationSeverity.WARNING,
                    message=f"Canal {channel_id}: {label} no configurado "
                            f"(env: {env_var}).",
                    channel_id=channel_id,
                ))
            else:
                report.add(ValidationResult(
                    path=f"channels.{channel_id}.config.{field_name}",
                    severity=ValidationSeverity.OK,
                    message=f"Canal {channel_id}: {label} configurado.",
                    channel_id=channel_id,
                ))

    return report
