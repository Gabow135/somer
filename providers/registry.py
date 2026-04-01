"""Registry de providers LLM.

Portado de OpenClaw: auth-profiles/usage.ts, auth-profiles/order.ts,
model-selection.ts, provider-capabilities.ts, failover-matches.ts,
api-key-rotation.ts.

Implementa:
- Registro de providers con metadatos y capacidades
- Resolución de modelo → provider + config
- Health tracking con cooldown exponencial y clasificación de errores
- Cadena de fallback (primario → secundario → terciario)
- Capability matching (streaming, tools, vision)
- Listado unificado de modelos de todos los providers
- Prioridad/ordenamiento de providers (round-robin + tipo preferencia)
- Rate limit tracking por provider con ventana deslizante
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from providers.base import BaseProvider
from shared.errors import (
    ProviderAuthError,
    ProviderBillingError,
    ProviderError,
    ProviderModelNotFoundError,
    ProviderRateLimitError,
)
from shared.types import ModelApi, ModelDefinition

logger = logging.getLogger(__name__)


# ── Razones de fallo (portado de OpenClaw: types.ts) ─────────

class FailureReason(str, Enum):
    """Clasificación de errores de provider.

    Portado de OpenClaw: pi-embedded-helpers/types.ts → FailoverReason.
    Prioridad descendente: auth_permanent es el más grave.
    """
    AUTH_PERMANENT = "auth_permanent"
    AUTH = "auth"
    BILLING = "billing"
    FORMAT = "format"
    MODEL_NOT_FOUND = "model_not_found"
    OVERLOADED = "overloaded"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    UNKNOWN = "unknown"


# Orden de prioridad para determinar razón dominante (menor = más grave)
_FAILURE_PRIORITY: Dict[FailureReason, int] = {
    reason: idx for idx, reason in enumerate(FailureReason)
}


# ── Patrones de error (portado de OpenClaw: failover-matches.ts) ──

_RATE_LIMIT_PATTERNS = [
    re.compile(r"rate[_ ]limit|too many requests|429", re.I),
    re.compile(r"model_cooldown", re.I),
    re.compile(r"exceeded your current quota", re.I),
    re.compile(r"resource has been exhausted", re.I),
    re.compile(r"quota exceeded", re.I),
    re.compile(r"resource_exhausted", re.I),
    re.compile(r"usage limit", re.I),
    re.compile(r"\btpm\b", re.I),
    re.compile(r"tokens per (minute|day)", re.I),
]

_OVERLOADED_PATTERNS = [
    re.compile(r"overloaded_error", re.I),
    re.compile(r"overloaded", re.I),
    re.compile(r"high demand", re.I),
]

_TIMEOUT_PATTERNS = [
    re.compile(r"timeout|timed out", re.I),
    re.compile(r"service unavailable", re.I),
    re.compile(r"deadline exceeded", re.I),
    re.compile(r"connection error|network error", re.I),
    re.compile(r"fetch failed|socket hang up", re.I),
    re.compile(r"\beconn(?:refused|reset|aborted)\b", re.I),
    re.compile(r"\betimedout\b", re.I),
]

_BILLING_PATTERNS = [
    re.compile(
        r'["\'"]?(?:status|code)["\'"]?\s*[:=]\s*402\b'
        r"|\bhttp\s*402\b|\b(?:got|returned|received)\s+(?:a\s+)?402\b",
        re.I,
    ),
    re.compile(r"payment required", re.I),
    re.compile(r"insufficient credits", re.I),
    re.compile(r"insufficient[_ ]quota", re.I),
    re.compile(r"credit balance", re.I),
    re.compile(r"insufficient balance", re.I),
]

_AUTH_PERMANENT_PATTERNS = [
    re.compile(r"api[_ ]?key[_ ]?(?:revoked|invalid|deactivated|deleted)", re.I),
    re.compile(r"invalid_api_key", re.I),
    re.compile(r"key has been (disabled|revoked)", re.I),
    re.compile(r"account has been deactivated", re.I),
    re.compile(r"permission_error", re.I),
]

_AUTH_PATTERNS = [
    re.compile(r"invalid[_ ]?api[_ ]?key", re.I),
    re.compile(r"incorrect api key", re.I),
    re.compile(r"authentication|unauthorized|forbidden", re.I),
    re.compile(r"access denied", re.I),
    re.compile(r"expired|token has expired", re.I),
    re.compile(r"\b401\b|\b403\b", re.I),
    re.compile(r"no (credentials|api key) found", re.I),
]


def _matches_any(text: str, patterns: List[re.Pattern[str]]) -> bool:
    """Verifica si el texto coincide con algún patrón."""
    for pat in patterns:
        if pat.search(text):
            return True
    return False


def classify_error(error: BaseException) -> FailureReason:
    """Clasifica un error en una razón de fallo.

    Portado de OpenClaw: failover-matches.ts → classifyFailoverReason.
    """
    msg = str(error).lower()

    if isinstance(error, ProviderAuthError):
        return FailureReason.AUTH
    if isinstance(error, ProviderBillingError):
        return FailureReason.BILLING
    if isinstance(error, ProviderRateLimitError):
        return FailureReason.RATE_LIMIT
    if isinstance(error, ProviderModelNotFoundError):
        return FailureReason.MODEL_NOT_FOUND

    if _matches_any(msg, _AUTH_PERMANENT_PATTERNS):
        return FailureReason.AUTH_PERMANENT
    if _matches_any(msg, _BILLING_PATTERNS):
        return FailureReason.BILLING
    if _matches_any(msg, _RATE_LIMIT_PATTERNS):
        return FailureReason.RATE_LIMIT
    if _matches_any(msg, _OVERLOADED_PATTERNS):
        return FailureReason.OVERLOADED
    if _matches_any(msg, _AUTH_PATTERNS):
        return FailureReason.AUTH
    if _matches_any(msg, _TIMEOUT_PATTERNS):
        return FailureReason.TIMEOUT
    return FailureReason.UNKNOWN


# ── Capacidades de provider ──────────────────────────────────

@dataclass
class ProviderCapabilities:
    """Capacidades detectadas de un provider.

    Portado de OpenClaw: provider-capabilities.ts.
    """
    supports_streaming: bool = True
    supports_tools: bool = True
    supports_vision: bool = False
    supports_reasoning: bool = False
    max_context_tokens: int = 128_000
    max_output_tokens: int = 8_192
    provider_family: str = "default"  # "default", "openai", "anthropic", "google"


# ── Metadatos de provider ────────────────────────────────────

@dataclass
class ProviderMeta:
    """Metadatos extendidos asociados a un provider registrado.

    Incluye estado de salud, estadísticas de uso y configuración de
    fallback. Portado de OpenClaw: auth-profiles/types.ts → ProfileUsageStats.
    """
    provider_id: str
    priority: int = 0  # menor = más prioritario
    capabilities: ProviderCapabilities = field(
        default_factory=ProviderCapabilities
    )
    fallback_chain: List[str] = field(default_factory=list)  # IDs de fallback en orden
    enabled: bool = True
    tags: Set[str] = field(default_factory=set)

    # ── Health tracking ──────────────────────────────────────
    error_count: int = 0
    failure_counts: Dict[FailureReason, int] = field(default_factory=dict)
    last_failure_at: float = 0.0
    last_success_at: float = 0.0
    last_used_at: float = 0.0
    cooldown_until: float = 0.0
    disabled_until: float = 0.0
    disabled_reason: Optional[FailureReason] = None

    # ── Rate limit tracking ──────────────────────────────────
    rate_limit_window_secs: float = 60.0
    rate_limit_requests: List[float] = field(default_factory=list)
    rate_limit_max_rpm: Optional[int] = None  # requests por minuto, None = sin límite

    # ── Configuración de cooldown ────────────────────────────
    cooldown_base_secs: float = 60.0
    billing_backoff_secs: float = 18_000.0  # 5 horas default
    billing_max_secs: float = 86_400.0      # 24 horas max
    failure_window_secs: float = 86_400.0   # 24 horas ventana de errores

    @property
    def is_available(self) -> bool:
        """Verifica si el provider está disponible (no en cooldown ni deshabilitado)."""
        now = time.monotonic()
        if not self.enabled:
            return False
        if self.disabled_until > 0 and now < self.disabled_until:
            return False
        if self.cooldown_until > 0 and now < self.cooldown_until:
            return False
        return True

    @property
    def unusable_until(self) -> Optional[float]:
        """Retorna el timestamp hasta el que no se puede usar, o None si disponible."""
        values = []
        if self.cooldown_until > 0:
            values.append(self.cooldown_until)
        if self.disabled_until > 0:
            values.append(self.disabled_until)
        return max(values) if values else None


def _calculate_cooldown_secs(error_count: int, base_secs: float = 60.0) -> float:
    """Calcula el cooldown exponencial para errores transitorios.

    Portado de OpenClaw: usage.ts → calculateAuthProfileCooldownMs.
    Progresión: 1min → 5min → 25min → max 1 hora.
    """
    normalized = max(1, error_count)
    return min(
        3600.0,  # 1 hora max
        base_secs * (5 ** min(normalized - 1, 3)),
    )


def _calculate_billing_disable_secs(
    error_count: int,
    base_secs: float = 18_000.0,
    max_secs: float = 86_400.0,
) -> float:
    """Calcula el backoff para errores de billing/auth permanente.

    Portado de OpenClaw: usage.ts → calculateAuthProfileBillingDisableMsWithConfig.
    Backoff exponencial base×2^n, limitado a max_secs.
    """
    normalized = max(1, error_count)
    base = max(60.0, base_secs)
    cap = max(base, max_secs)
    exponent = min(normalized - 1, 10)
    raw = base * (2 ** exponent)
    return min(cap, raw)


# ── Referencia de modelo ─────────────────────────────────────

@dataclass
class ModelRef:
    """Referencia a un modelo con su provider.

    Portado de OpenClaw: model-selection.ts → ModelRef.
    """
    provider: str
    model: str

    @property
    def key(self) -> str:
        """Clave canónica provider/model."""
        if not self.provider:
            return self.model
        if self.model.lower().startswith(f"{self.provider.lower()}/"):
            return self.model
        return f"{self.provider}/{self.model}"


def parse_model_ref(raw: str, default_provider: str = "anthropic") -> Optional[ModelRef]:
    """Parsea una cadena 'provider/model' o 'model' en un ModelRef.

    Portado de OpenClaw: model-selection.ts → parseModelRef.
    """
    trimmed = raw.strip()
    if not trimmed:
        return None
    slash = trimmed.find("/")
    if slash == -1:
        return ModelRef(provider=default_provider, model=trimmed)
    provider = trimmed[:slash].strip()
    model = trimmed[slash + 1:].strip()
    if not provider or not model:
        return None
    return ModelRef(provider=provider, model=model)


# ── Resultado de resolución ──────────────────────────────────

@dataclass
class ResolvedModel:
    """Resultado de la resolución de un modelo.

    Contiene el provider, la definición del modelo y los fallbacks disponibles.
    """
    provider: BaseProvider
    model: ModelDefinition
    fallback_providers: List[BaseProvider] = field(default_factory=list)


# ── Registry ─────────────────────────────────────────────────

class ProviderRegistry:
    """Registro central de providers LLM.

    Portado de la arquitectura OpenClaw (auth-profiles, model-selection,
    provider-capabilities, failover-observation) adaptado a SOMER 2.0.

    Soporta:
    - Registro con metadatos y capacidades por provider
    - Resolución de modelo → provider + config con alias
    - Health tracking con cooldown exponencial y clasificación de errores
    - Cadena de fallback con ordenamiento por prioridad y round-robin
    - Capability matching (streaming, tools, vision)
    - Listado de modelos unificado con filtrado
    - Rate limit tracking por provider con ventana deslizante
    - Limpieza automática de cooldowns expirados
    """

    def __init__(self) -> None:
        self._providers: Dict[str, BaseProvider] = {}
        self._meta: Dict[str, ProviderMeta] = {}
        self._model_index: Dict[str, str] = {}   # model_id → provider_id
        self._alias_index: Dict[str, ModelRef] = {}  # alias → ModelRef
        self._lock = asyncio.Lock()

    # ── Registro y desregistro ───────────────────────────────

    def register(
        self,
        provider: BaseProvider,
        *,
        priority: int = 0,
        capabilities: Optional[ProviderCapabilities] = None,
        fallback_chain: Optional[List[str]] = None,
        tags: Optional[Set[str]] = None,
        rate_limit_max_rpm: Optional[int] = None,
        cooldown_base_secs: float = 60.0,
    ) -> None:
        """Registra un provider con metadatos extendidos.

        Args:
            provider: Instancia del provider.
            priority: Menor = más prioritario (default 0).
            capabilities: Capacidades del provider. Si no se provee,
                se infieren de los modelos registrados.
            fallback_chain: Lista ordenada de provider IDs de fallback.
            tags: Etiquetas para clasificación libre.
            rate_limit_max_rpm: Límite de requests por minuto.
            cooldown_base_secs: Base para el cooldown exponencial.
        """
        pid = provider.provider_id
        self._providers[pid] = provider

        # Inferir capacidades si no se proveen
        if capabilities is None:
            capabilities = self._infer_capabilities(provider)

        meta = ProviderMeta(
            provider_id=pid,
            priority=priority,
            capabilities=capabilities,
            fallback_chain=fallback_chain or [],
            tags=tags or set(),
            rate_limit_max_rpm=rate_limit_max_rpm,
            cooldown_base_secs=cooldown_base_secs,
        )

        # Sincronizar estado de salud si el provider ya tiene cooldown previo
        if not provider.auth.is_available:
            meta.error_count = provider.auth.failure_count
            meta.cooldown_until = provider.auth._cooldown_until

        self._meta[pid] = meta

        # Indexar modelos
        for model in provider.list_models():
            self._model_index[model.id] = pid
            # Indexar también con clave canónica
            canonical = f"{pid}/{model.id}"
            self._model_index[canonical] = pid

        logger.debug(
            "Provider registrado: %s (prioridad=%d, modelos=%d, caps=%s)",
            pid, priority, len(provider.list_models()),
            self._describe_capabilities(capabilities),
        )

    def unregister(self, provider_id: str) -> None:
        """Desregistra un provider y limpia todos sus índices."""
        provider = self._providers.pop(provider_id, None)
        self._meta.pop(provider_id, None)
        if provider:
            for model in provider.list_models():
                self._model_index.pop(model.id, None)
                self._model_index.pop(f"{provider_id}/{model.id}", None)
            # Limpiar de cadenas de fallback de otros providers
            for meta in self._meta.values():
                if provider_id in meta.fallback_chain:
                    meta.fallback_chain = [
                        pid for pid in meta.fallback_chain
                        if pid != provider_id
                    ]
        logger.debug("Provider desregistrado: %s", provider_id)

    # ── Aliases de modelo ────────────────────────────────────

    def register_alias(self, alias: str, provider: str, model: str) -> None:
        """Registra un alias de modelo.

        Portado de OpenClaw: model-selection.ts → buildModelAliasIndex.
        Permite referirse a un modelo con un nombre corto, e.g.
        'sonnet' → anthropic/claude-sonnet-4-5.
        """
        key = alias.strip().lower()
        if key:
            self._alias_index[key] = ModelRef(provider=provider, model=model)
            logger.debug("Alias registrado: %s → %s/%s", alias, provider, model)

    def unregister_alias(self, alias: str) -> None:
        """Elimina un alias de modelo."""
        self._alias_index.pop(alias.strip().lower(), None)

    # ── Obtención de providers ───────────────────────────────

    def get_provider(self, provider_id: str) -> Optional[BaseProvider]:
        """Obtiene un provider por ID."""
        return self._providers.get(provider_id)

    def get_meta(self, provider_id: str) -> Optional[ProviderMeta]:
        """Obtiene los metadatos de un provider."""
        return self._meta.get(provider_id)

    def get_provider_for_model(self, model_id: str) -> Optional[BaseProvider]:
        """Obtiene el provider que soporta un modelo.

        Busca por ID directo, por clave canónica (provider/model) y por alias.
        """
        # Búsqueda directa
        provider_id = self._model_index.get(model_id)
        if provider_id:
            return self._providers.get(provider_id)

        # Búsqueda por alias
        alias_key = model_id.strip().lower()
        ref = self._alias_index.get(alias_key)
        if ref:
            return self._providers.get(ref.provider)

        return None

    # ── Resolución de modelo ─────────────────────────────────

    def resolve_model(
        self,
        model_ref: str,
        *,
        default_provider: str = "anthropic",
    ) -> Optional[ResolvedModel]:
        """Resuelve una referencia de modelo a su provider y definición.

        Portado de OpenClaw: model-selection.ts → resolveConfiguredModelRef,
        resolveModelRefFromString.

        Soporta los formatos:
        - 'model_id' → busca en todos los providers
        - 'provider/model_id' → busca en el provider específico
        - alias registrado → resuelve al ModelRef asociado

        Returns:
            ResolvedModel con provider, definición y fallbacks disponibles,
            o None si no se encuentra.
        """
        # 1. Verificar alias
        alias_key = model_ref.strip().lower()
        ref = self._alias_index.get(alias_key)
        if ref:
            return self._resolve_ref(ref)

        # 2. Parsear como provider/model
        parsed = parse_model_ref(model_ref, default_provider)
        if parsed:
            result = self._resolve_ref(parsed)
            if result:
                return result

        # 3. Búsqueda directa por model_id en todos los providers
        provider_id = self._model_index.get(model_ref)
        if provider_id:
            provider = self._providers.get(provider_id)
            if provider:
                model_def = provider.get_model(model_ref)
                if model_def:
                    return ResolvedModel(
                        provider=provider,
                        model=model_def,
                        fallback_providers=self._build_fallback_list(provider_id),
                    )

        return None

    def _resolve_ref(self, ref: ModelRef) -> Optional[ResolvedModel]:
        """Resuelve un ModelRef a un ResolvedModel."""
        provider = self._providers.get(ref.provider)
        if not provider:
            return None
        model_def = provider.get_model(ref.model)
        if not model_def:
            return None
        return ResolvedModel(
            provider=provider,
            model=model_def,
            fallback_providers=self._build_fallback_list(ref.provider),
        )

    # ── Listado ──────────────────────────────────────────────

    def list_providers(self) -> List[BaseProvider]:
        """Lista todos los providers registrados, ordenados por prioridad."""
        return sorted(
            self._providers.values(),
            key=lambda p: self._meta.get(p.provider_id, ProviderMeta(provider_id="")).priority,
        )

    def list_available_providers(self) -> List[BaseProvider]:
        """Lista providers disponibles (no en cooldown ni deshabilitados).

        Solo retorna providers que están actualmente operativos.
        """
        self._clear_expired_cooldowns()

        available: List[Tuple[int, float, BaseProvider]] = []

        for pid, provider in self._providers.items():
            meta = self._meta.get(pid)
            if meta is None or not meta.enabled:
                continue
            if meta.is_available:
                priority = meta.priority
                last_used = meta.last_used_at
                available.append((priority, last_used, provider))

        # Ordenar por prioridad, luego round-robin (last_used más antiguo primero)
        available.sort(key=lambda x: (x[0], x[1]))
        return [p for _, _, p in available]

    def list_providers_ordered(self) -> List[BaseProvider]:
        """Lista todos los providers ordenados: disponibles primero, luego en cooldown.

        Portado de OpenClaw: auth-profiles/order.ts → orderProfilesByMode.
        Retorna providers disponibles ordenados por prioridad y round-robin,
        seguidos de providers en cooldown ordenados por expiración más cercana.
        Útil para construir cadenas de fallback.
        """
        self._clear_expired_cooldowns()

        available: List[Tuple[int, float, BaseProvider]] = []
        in_cooldown: List[Tuple[float, BaseProvider]] = []

        for pid, provider in self._providers.items():
            meta = self._meta.get(pid)
            if meta is None or not meta.enabled:
                continue
            if meta.is_available:
                priority = meta.priority
                last_used = meta.last_used_at
                available.append((priority, last_used, provider))
            else:
                until = meta.unusable_until or 0.0
                in_cooldown.append((until, provider))

        # Disponibles: por prioridad, luego round-robin
        available.sort(key=lambda x: (x[0], x[1]))
        # Cooldown: soonest first
        in_cooldown.sort(key=lambda x: x[0])

        return [p for _, _, p in available] + [p for _, p in in_cooldown]

    def list_all_models(self) -> List[ModelDefinition]:
        """Lista todos los modelos de todos los providers."""
        models: List[ModelDefinition] = []
        for provider in self._providers.values():
            models.extend(provider.list_models())
        return models

    def list_models_with_capabilities(
        self,
        *,
        streaming: Optional[bool] = None,
        tools: Optional[bool] = None,
        vision: Optional[bool] = None,
    ) -> List[ModelDefinition]:
        """Lista modelos filtrados por capacidades requeridas.

        Portado de OpenClaw: provider-capabilities.ts → capability matching.
        """
        result: List[ModelDefinition] = []
        for provider in self._providers.values():
            for model in provider.list_models():
                if streaming is not None and model.supports_streaming != streaming:
                    continue
                if tools is not None and model.supports_tools != tools:
                    continue
                if vision is not None and model.supports_vision != vision:
                    continue
                result.append(model)
        return result

    # ── Health tracking ──────────────────────────────────────

    async def record_success(self, provider_id: str) -> None:
        """Registra un uso exitoso del provider.

        Portado de OpenClaw: usage.ts → markAuthProfileUsed.
        Resetea contadores de error y actualiza timestamps.
        """
        async with self._lock:
            meta = self._meta.get(provider_id)
            if meta is None:
                return
            now = time.monotonic()
            meta.error_count = 0
            meta.failure_counts.clear()
            meta.cooldown_until = 0.0
            meta.disabled_until = 0.0
            meta.disabled_reason = None
            meta.last_success_at = now
            meta.last_used_at = now

            # También actualizar el AuthProfile del provider base
            provider = self._providers.get(provider_id)
            if provider:
                provider.auth.record_success()

            logger.debug("Provider %s: éxito registrado", provider_id)

    async def record_failure(
        self,
        provider_id: str,
        error: BaseException,
    ) -> Optional[float]:
        """Registra un fallo del provider con clasificación automática.

        Portado de OpenClaw: usage.ts → markAuthProfileFailure,
        computeNextProfileUsageStats.

        Aplica:
        - Billing/auth_permanent → disabled con backoff largo (5h-24h)
        - Rate limit/overloaded/timeout → cooldown exponencial (1min-1h)
        - Ventana de errores: resetea contadores si la ventana anterior expiró

        Returns:
            Segundos hasta que el provider vuelva a estar disponible, o None.
        """
        reason = classify_error(error)
        return await self._record_failure_reason(provider_id, reason)

    async def _record_failure_reason(
        self,
        provider_id: str,
        reason: FailureReason,
    ) -> Optional[float]:
        """Registra un fallo con razón específica."""
        async with self._lock:
            meta = self._meta.get(provider_id)
            if meta is None:
                return None

            now = time.monotonic()

            # Verificar si la ventana de errores expiró
            window_expired = (
                meta.last_failure_at > 0
                and (now - meta.last_failure_at) > meta.failure_window_secs
            )
            # Verificar si el cooldown anterior ya expiró
            previous_expired = (
                meta.unusable_until is not None
                and now >= meta.unusable_until
            )

            should_reset = window_expired or previous_expired
            if should_reset:
                meta.error_count = 0
                meta.failure_counts.clear()

            meta.error_count += 1
            meta.failure_counts[reason] = meta.failure_counts.get(reason, 0) + 1
            meta.last_failure_at = now

            # Calcular nuevo cooldown según tipo de error
            if reason in (FailureReason.BILLING, FailureReason.AUTH_PERMANENT):
                count = meta.failure_counts.get(reason, 1)
                backoff = _calculate_billing_disable_secs(
                    count,
                    meta.billing_backoff_secs,
                    meta.billing_max_secs,
                )
                # No extender ventanas activas (portado de OpenClaw:
                # keepActiveWindowOrRecompute)
                if meta.disabled_until <= 0 or now >= meta.disabled_until:
                    meta.disabled_until = now + backoff
                meta.disabled_reason = reason
                cooldown_secs = backoff
            else:
                cooldown_secs = _calculate_cooldown_secs(
                    meta.error_count,
                    meta.cooldown_base_secs,
                )
                if meta.cooldown_until <= 0 or now >= meta.cooldown_until:
                    meta.cooldown_until = now + cooldown_secs

            # Sincronizar con AuthProfile del provider base
            provider = self._providers.get(provider_id)
            if provider:
                is_billing = reason == FailureReason.BILLING
                provider.auth.record_failure(is_billing=is_billing)

            logger.warning(
                "Provider %s: fallo #%d (%s), cooldown %.0fs",
                provider_id, meta.error_count, reason.value, cooldown_secs,
            )
            return cooldown_secs

    async def clear_cooldown(self, provider_id: str) -> None:
        """Limpia manualmente el cooldown de un provider.

        Portado de OpenClaw: usage.ts → clearAuthProfileCooldown.
        """
        async with self._lock:
            meta = self._meta.get(provider_id)
            if meta is None:
                return
            meta.error_count = 0
            meta.failure_counts.clear()
            meta.cooldown_until = 0.0
            meta.disabled_until = 0.0
            meta.disabled_reason = None

            provider = self._providers.get(provider_id)
            if provider:
                provider.auth.reset()

            logger.info("Provider %s: cooldown limpiado", provider_id)

    def _clear_expired_cooldowns(self) -> bool:
        """Limpia cooldowns expirados de todos los providers.

        Portado de OpenClaw: usage.ts → clearExpiredCooldowns.
        Se ejecuta automáticamente antes de listar providers disponibles.
        Cuando un cooldown expira, resetea contadores de error para dar
        una nueva oportunidad (circuit-breaker half-open → closed).

        Returns:
            True si algún provider fue modificado.
        """
        now = time.monotonic()
        mutated = False

        for meta in self._meta.values():
            provider_mutated = False

            cooldown_expired = (
                meta.cooldown_until > 0 and now >= meta.cooldown_until
            )
            disabled_expired = (
                meta.disabled_until > 0 and now >= meta.disabled_until
            )

            if cooldown_expired:
                meta.cooldown_until = 0.0
                provider_mutated = True

            if disabled_expired:
                meta.disabled_until = 0.0
                meta.disabled_reason = None
                provider_mutated = True

            # Resetear contadores cuando TODOS los cooldowns expiraron
            if provider_mutated and meta.unusable_until is None:
                meta.error_count = 0
                meta.failure_counts.clear()
                # También sincronizar AuthProfile
                provider = self._providers.get(meta.provider_id)
                if provider:
                    provider.auth.reset()

            if provider_mutated:
                mutated = True

        return mutated

    def get_unavailable_reason(
        self,
        provider_ids: Optional[List[str]] = None,
    ) -> Optional[FailureReason]:
        """Determina la razón dominante por la que los providers no están disponibles.

        Portado de OpenClaw: usage.ts → resolveProfilesUnavailableReason.
        Útil para mostrar al usuario por qué no hay providers disponibles.
        """
        ids = provider_ids or list(self._meta.keys())
        now = time.monotonic()
        scores: Dict[FailureReason, float] = {}

        for pid in ids:
            meta = self._meta.get(pid)
            if meta is None:
                continue

            # Disabled reasons son explícitas y de alta señal
            disabled_active = meta.disabled_until > 0 and now < meta.disabled_until
            if disabled_active and meta.disabled_reason:
                scores[meta.disabled_reason] = scores.get(
                    meta.disabled_reason, 0
                ) + 1000

                continue

            cooldown_active = meta.cooldown_until > 0 and now < meta.cooldown_until
            if not cooldown_active:
                continue

            recorded_any = False
            for reason, count in meta.failure_counts.items():
                if count > 0:
                    scores[reason] = scores.get(reason, 0) + count
                    recorded_any = True
            if not recorded_any:
                scores[FailureReason.UNKNOWN] = scores.get(
                    FailureReason.UNKNOWN, 0
                ) + 1

        if not scores:
            return None

        # Seleccionar razón con mayor score; desempatar por prioridad
        best: Optional[FailureReason] = None
        best_score = -1.0
        best_priority = 999

        for reason in FailureReason:
            score = scores.get(reason, 0)
            priority = _FAILURE_PRIORITY.get(reason, 999)
            if score > best_score or (score == best_score and priority < best_priority):
                best = reason
                best_score = score
                best_priority = priority

        return best

    def get_soonest_cooldown_expiry(
        self,
        provider_ids: Optional[List[str]] = None,
    ) -> Optional[float]:
        """Retorna el timestamp más cercano de expiración de cooldown.

        Portado de OpenClaw: usage.ts → getSoonestCooldownExpiry.

        Returns:
            Timestamp monotónico de expiración más cercana, o None.
        """
        ids = provider_ids or list(self._meta.keys())
        soonest: Optional[float] = None

        for pid in ids:
            meta = self._meta.get(pid)
            if meta is None:
                continue
            until = meta.unusable_until
            if until is None or until <= 0:
                continue
            if soonest is None or until < soonest:
                soonest = until

        return soonest

    # ── Rate limit tracking ──────────────────────────────────

    def check_rate_limit(self, provider_id: str) -> bool:
        """Verifica si el provider está dentro de su rate limit.

        Returns:
            True si se puede enviar otra request, False si se excedió.
        """
        meta = self._meta.get(provider_id)
        if meta is None or meta.rate_limit_max_rpm is None:
            return True

        now = time.monotonic()
        window_start = now - meta.rate_limit_window_secs

        # Limpiar requests fuera de la ventana
        meta.rate_limit_requests = [
            t for t in meta.rate_limit_requests if t > window_start
        ]

        return len(meta.rate_limit_requests) < meta.rate_limit_max_rpm

    def record_request(self, provider_id: str) -> None:
        """Registra una request para el tracking de rate limit."""
        meta = self._meta.get(provider_id)
        if meta is not None:
            meta.rate_limit_requests.append(time.monotonic())
            meta.last_used_at = time.monotonic()

    # ── Fallback chain ───────────────────────────────────────

    def find_fallback(
        self,
        failed_provider_id: str,
        *,
        model_id: Optional[str] = None,
        require_capabilities: Optional[ProviderCapabilities] = None,
    ) -> Optional[BaseProvider]:
        """Encuentra el siguiente provider en la cadena de fallback.

        Portado de OpenClaw: resolveAllowedFallbacks + failover-observation.

        Orden de búsqueda:
        1. Cadena de fallback explícita del provider fallido
        2. Otros providers disponibles que soporten el modelo
        3. Otros providers disponibles ordenados por prioridad

        Args:
            failed_provider_id: ID del provider que falló.
            model_id: Si se provee, busca providers que soporten este modelo.
            require_capabilities: Capacidades mínimas requeridas.

        Returns:
            El primer provider alternativo disponible, o None.
        """
        self._clear_expired_cooldowns()
        meta = self._meta.get(failed_provider_id)

        # 1. Cadena de fallback explícita
        if meta and meta.fallback_chain:
            for pid in meta.fallback_chain:
                candidate = self._check_fallback_candidate(
                    pid, model_id, require_capabilities
                )
                if candidate:
                    return candidate

        # 2. Providers que soporten el mismo modelo
        if model_id:
            for pid, provider in self._providers.items():
                if pid == failed_provider_id:
                    continue
                if provider.get_model(model_id) is None:
                    continue
                candidate = self._check_fallback_candidate(
                    pid, model_id, require_capabilities
                )
                if candidate:
                    return candidate

        # 3. Cualquier provider disponible por prioridad
        sorted_providers = sorted(
            self._meta.items(),
            key=lambda x: x[1].priority,
        )
        for pid, pmeta in sorted_providers:
            if pid == failed_provider_id:
                continue
            if pmeta.is_available and pmeta.enabled:
                provider = self._providers.get(pid)
                if provider and self._meets_capabilities(
                    pid, require_capabilities
                ):
                    return provider

        return None

    def _check_fallback_candidate(
        self,
        provider_id: str,
        model_id: Optional[str],
        require_capabilities: Optional[ProviderCapabilities],
    ) -> Optional[BaseProvider]:
        """Verifica si un candidato de fallback es viable."""
        meta = self._meta.get(provider_id)
        if meta is None or not meta.is_available or not meta.enabled:
            return None
        provider = self._providers.get(provider_id)
        if provider is None:
            return None
        if model_id and provider.get_model(model_id) is None:
            return None
        if not self._meets_capabilities(provider_id, require_capabilities):
            return None
        return provider

    def _meets_capabilities(
        self,
        provider_id: str,
        required: Optional[ProviderCapabilities],
    ) -> bool:
        """Verifica si un provider cumple con las capacidades requeridas."""
        if required is None:
            return True
        meta = self._meta.get(provider_id)
        if meta is None:
            return False
        caps = meta.capabilities
        if required.supports_streaming and not caps.supports_streaming:
            return False
        if required.supports_tools and not caps.supports_tools:
            return False
        if required.supports_vision and not caps.supports_vision:
            return False
        return True

    def _build_fallback_list(self, primary_id: str) -> List[BaseProvider]:
        """Construye la lista de fallbacks para un provider primario."""
        meta = self._meta.get(primary_id)
        result: List[BaseProvider] = []
        seen: Set[str] = {primary_id}

        # Primero la cadena explícita
        if meta and meta.fallback_chain:
            for pid in meta.fallback_chain:
                if pid not in seen:
                    provider = self._providers.get(pid)
                    if provider:
                        result.append(provider)
                        seen.add(pid)

        # Luego otros providers por prioridad
        sorted_providers = sorted(
            self._meta.items(),
            key=lambda x: x[1].priority,
        )
        for pid, _ in sorted_providers:
            if pid not in seen:
                provider = self._providers.get(pid)
                if provider:
                    result.append(provider)
                    seen.add(pid)

        return result

    # ── Ejecución con fallback ───────────────────────────────

    async def execute_with_fallback(
        self,
        model_ref: str,
        execute: Callable[[BaseProvider, str], Any],
        *,
        default_provider: str = "anthropic",
        max_attempts: int = 3,
    ) -> Any:
        """Ejecuta una operación con fallback automático entre providers.

        Portado de OpenClaw: api-key-rotation.ts → executeWithApiKeyRotation,
        run/attempt.ts → failover logic.

        Intenta con el provider primario, y si falla, rota a los fallbacks
        en orden. Registra éxitos y fallos automáticamente.

        Args:
            model_ref: Referencia al modelo ('provider/model' o alias).
            execute: Callable async que recibe (provider, model_id).
            default_provider: Provider por defecto si no se especifica.
            max_attempts: Máximo de intentos totales.

        Returns:
            El resultado de execute().

        Raises:
            ProviderError: Si todos los intentos fallan.
        """
        resolved = self.resolve_model(
            model_ref, default_provider=default_provider
        )
        if not resolved:
            raise ProviderModelNotFoundError(
                f"Modelo no encontrado: {model_ref}"
            )

        # Construir lista de intentos: primario + fallbacks
        attempts: List[Tuple[BaseProvider, str]] = [
            (resolved.provider, resolved.model.id)
        ]
        for fb_provider in resolved.fallback_providers:
            # Buscar si el fallback tiene el mismo modelo o uno compatible
            fb_model = fb_provider.get_model(resolved.model.id)
            if fb_model:
                attempts.append((fb_provider, fb_model.id))
            elif fb_provider.list_models():
                # Usar el primer modelo disponible del fallback
                attempts.append(
                    (fb_provider, fb_provider.list_models()[0].id)
                )

        last_error: Optional[BaseException] = None
        for i, (provider, model_id) in enumerate(attempts[:max_attempts]):
            pid = provider.provider_id
            meta = self._meta.get(pid)

            # Verificar rate limit
            if not self.check_rate_limit(pid):
                logger.warning(
                    "Provider %s: rate limit excedido, saltando", pid
                )
                continue

            # Verificar disponibilidad
            if meta and not meta.is_available:
                logger.debug(
                    "Provider %s: en cooldown, saltando", pid
                )
                continue

            self.record_request(pid)
            try:
                result = await execute(provider, model_id)
                await self.record_success(pid)
                return result
            except Exception as e:
                last_error = e
                reason = classify_error(e)
                await self._record_failure_reason(pid, reason)
                logger.warning(
                    "Provider %s: intento %d/%d falló (%s: %s)",
                    pid, i + 1, max_attempts, reason.value, str(e)[:200],
                )

        if last_error:
            raise last_error
        raise ProviderError("Todos los providers fallaron")

    # ── Health check ─────────────────────────────────────────

    async def health_check_all(self) -> Dict[str, bool]:
        """Ejecuta health check en todos los providers.

        Returns:
            Dict de provider_id → estado de salud.
        """
        results: Dict[str, bool] = {}
        for pid, provider in self._providers.items():
            try:
                healthy = await provider.health_check()
                results[pid] = healthy
                if healthy:
                    await self.record_success(pid)
            except Exception as e:
                results[pid] = False
                await self.record_failure(pid, e)
        return results

    # ── Propiedades ──────────────────────────────────────────

    @property
    def provider_count(self) -> int:
        """Número total de providers registrados."""
        return len(self._providers)

    @property
    def model_count(self) -> int:
        """Número total de modelos indexados (incluyendo canónicos)."""
        # Contar solo modelos únicos (sin claves canónicas duplicadas)
        unique_models: Set[str] = set()
        for provider in self._providers.values():
            for model in provider.list_models():
                unique_models.add(model.id)
        return len(unique_models)

    @property
    def available_provider_count(self) -> int:
        """Número de providers actualmente disponibles."""
        self._clear_expired_cooldowns()
        return sum(
            1 for meta in self._meta.values()
            if meta.is_available and meta.enabled
        )

    # ── Utilidades internas ──────────────────────────────────

    @staticmethod
    def _infer_capabilities(provider: BaseProvider) -> ProviderCapabilities:
        """Infiere capacidades de un provider a partir de sus modelos."""
        models = provider.list_models()
        if not models:
            return ProviderCapabilities()

        return ProviderCapabilities(
            supports_streaming=any(m.supports_streaming for m in models),
            supports_tools=any(m.supports_tools for m in models),
            supports_vision=any(m.supports_vision for m in models),
            max_context_tokens=max(m.max_input_tokens for m in models),
            max_output_tokens=max(m.max_output_tokens for m in models),
            provider_family=_infer_provider_family(provider.provider_id),
        )

    @staticmethod
    def _describe_capabilities(caps: ProviderCapabilities) -> str:
        """Genera una descripción corta de las capacidades para logging."""
        flags = []
        if caps.supports_streaming:
            flags.append("stream")
        if caps.supports_tools:
            flags.append("tools")
        if caps.supports_vision:
            flags.append("vision")
        if caps.supports_reasoning:
            flags.append("reasoning")
        return "+".join(flags) if flags else "basic"


def _infer_provider_family(provider_id: str) -> str:
    """Infiere la familia del provider desde su ID.

    Portado de OpenClaw: provider-capabilities.ts → CORE_PROVIDER_CAPABILITIES.
    """
    pid = provider_id.lower()
    if "anthropic" in pid or "bedrock" in pid:
        return "anthropic"
    if "openai" in pid or "deepseek" in pid or "together" in pid or "groq" in pid:
        return "openai"
    if "google" in pid or "gemini" in pid or "vertex" in pid:
        return "google"
    if "ollama" in pid:
        return "ollama"
    return "default"
