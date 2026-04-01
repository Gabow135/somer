"""Cadena de fallback entre modelos/providers.

Portado de OpenClaw: model-fallback.ts, model-fallback.types.ts.
Ejecuta una operación con fallback automático a través de múltiples
candidatos (provider+modelo), con detección de abort, clasificación
de errores y reportes de intento.

Python 3.9+ — ``from __future__ import annotations``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple, TypeVar

from providers.registry import FailureReason, classify_error
from shared.errors import AgentError, ProviderError

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ── Tipos ─────────────────────────────────────────────────────


@dataclass
class ModelCandidate:
    """Candidato de modelo para la cadena de fallback.

    Portado de OpenClaw: model-fallback.types.ts → ModelCandidate.
    """

    provider: str
    model: str


@dataclass
class FallbackAttempt:
    """Registro de un intento de fallback.

    Portado de OpenClaw: model-fallback.types.ts → FallbackAttempt.
    """

    provider: str
    model: str
    error: str
    reason: Optional[FailureReason] = None
    status: Optional[int] = None
    code: Optional[str] = None


@dataclass
class FallbackResult:
    """Resultado de una ejecución con fallback.

    Contiene el resultado, el proveedor/modelo que lo produjo
    y la lista de intentos realizados.
    """

    result: Any
    provider: str
    model: str
    attempts: List[FallbackAttempt] = field(default_factory=list)


# ── Opciones de ejecución ─────────────────────────────────────


@dataclass
class FallbackRunOptions:
    """Opciones para un intento de fallback.

    Portado de OpenClaw: model-fallback.ts → ModelFallbackRunOptions.
    """

    allow_transient_cooldown_probe: bool = False


# ── Funciones internas ────────────────────────────────────────


def _model_key(provider: str, model: str) -> str:
    """Clave canónica para deduplicar candidatos."""
    return f"{provider}/{model}"


def _is_abort_error(err: BaseException) -> bool:
    """Detecta si es un error de abort del usuario (no failover).

    Portado de OpenClaw: model-fallback.ts → isFallbackAbortError.
    Solo trata AbortError o asyncio.CancelledError como aborts reales.
    """
    if isinstance(err, asyncio.CancelledError):
        return True
    name = getattr(err, "name", "") or type(err).__name__
    return name == "AbortError"


def _is_timeout_error(err: BaseException) -> bool:
    """Detecta si es un error de timeout."""
    if isinstance(err, (asyncio.TimeoutError, TimeoutError)):
        return True
    msg = str(err).lower()
    return "timeout" in msg or "timed out" in msg


def _is_context_overflow_error(err: BaseException) -> bool:
    """Detecta error de overflow de ventana de contexto.

    Portado de OpenClaw: pi-embedded-helpers.ts → isLikelyContextOverflowError.
    """
    msg = str(err).lower()
    overflow_hints = [
        "context_length_exceeded",
        "maximum context length",
        "token limit",
        "prompt is too long",
        "context window",
        "max_tokens",
    ]
    return any(hint in msg for hint in overflow_hints)


def _should_rethrow(err: BaseException) -> bool:
    """Determina si un error debe relanzarse sin intentar fallback.

    Context overflow se relanza para que el runner pueda compactar
    y reintentar con un contexto más reducido.
    """
    if _is_abort_error(err) and not _is_timeout_error(err):
        return True
    if _is_context_overflow_error(err):
        return True
    return False


# ── Collector de candidatos ───────────────────────────────────


class CandidateCollector:
    """Recolecta candidatos de modelo deduplicados.

    Portado de OpenClaw: model-fallback.ts → createModelCandidateCollector.
    """

    def __init__(self, allowlist: Optional[Set[str]] = None) -> None:
        self._seen: Set[str] = set()
        self._allowlist = allowlist
        self.candidates: List[ModelCandidate] = []

    def add_explicit(self, candidate: ModelCandidate) -> None:
        """Añade un candidato explícito (no filtrado por allowlist)."""
        self._add(candidate, enforce_allowlist=False)

    def add_allowlisted(self, candidate: ModelCandidate) -> None:
        """Añade un candidato solo si está en el allowlist."""
        self._add(candidate, enforce_allowlist=True)

    def _add(self, candidate: ModelCandidate, enforce_allowlist: bool) -> None:
        if not candidate.provider or not candidate.model:
            return
        key = _model_key(candidate.provider, candidate.model)
        if key in self._seen:
            return
        if enforce_allowlist and self._allowlist and key not in self._allowlist:
            return
        self._seen.add(key)
        self.candidates.append(candidate)


# ── Ejecución con fallback ────────────────────────────────────


# Tipo para la función de ejecución
RunFn = Callable[[str, str], Awaitable[Any]]
ErrorHandler = Callable[[Dict[str, Any]], Awaitable[None]]


async def run_with_model_fallback(
    candidates: List[ModelCandidate],
    run: RunFn,
    *,
    on_error: Optional[ErrorHandler] = None,
    label: str = "model fallback",
) -> FallbackResult:
    """Ejecuta una operación iterando sobre candidatos de modelo con fallback.

    Portado de OpenClaw: model-fallback.ts → runWithModelFallback.

    Intenta cada candidato en orden. Si uno falla con un error recuperable,
    pasa al siguiente. Errores de abort se relanzan inmediatamente.

    Args:
        candidates: Lista ordenada de candidatos (provider/model).
        run: Función async que ejecuta la operación con (provider, model).
        on_error: Callback opcional para notificar errores de cada intento.
        label: Etiqueta para mensajes de log y error.

    Returns:
        FallbackResult con resultado, proveedor/modelo exitoso e intentos.

    Raises:
        AgentError: Si todos los candidatos fallan.
    """
    if not candidates:
        raise AgentError(f"Sin candidatos para {label}")

    attempts: List[FallbackAttempt] = []
    last_error: Optional[BaseException] = None

    for idx, candidate in enumerate(candidates):
        try:
            result = await run(candidate.provider, candidate.model)
            return FallbackResult(
                result=result,
                provider=candidate.provider,
                model=candidate.model,
                attempts=attempts,
            )
        except BaseException as err:
            # Abort real: relanzar inmediatamente
            if _should_rethrow(err):
                raise

            last_error = err
            reason = classify_error(err) if isinstance(err, Exception) else FailureReason.UNKNOWN
            error_msg = str(err)[:500]

            attempt = FallbackAttempt(
                provider=candidate.provider,
                model=candidate.model,
                error=error_msg,
                reason=reason,
            )
            attempts.append(attempt)

            logger.warning(
                "%s: intento %d/%d falló — %s/%s (%s: %s)",
                label,
                idx + 1,
                len(candidates),
                candidate.provider,
                candidate.model,
                reason.value,
                error_msg[:200],
            )

            if on_error:
                try:
                    await on_error({
                        "provider": candidate.provider,
                        "model": candidate.model,
                        "error": err,
                        "attempt": idx + 1,
                        "total": len(candidates),
                    })
                except Exception:
                    pass  # No fallar por el handler de errores

    # Todos fallaron
    if len(attempts) <= 1 and last_error:
        raise last_error

    summary = " | ".join(
        f"{a.provider}/{a.model}:{a.reason.value if a.reason else 'unknown'}"
        for a in attempts
    )
    raise AgentError(
        f"Todos los {label} fallaron ({len(attempts)}): {summary}"
    )


def build_fallback_candidates(
    primary_provider: str,
    primary_model: str,
    fallback_specs: Optional[List[Tuple[str, str]]] = None,
    *,
    allowlist: Optional[Set[str]] = None,
) -> List[ModelCandidate]:
    """Construye la lista de candidatos de fallback.

    Portado de OpenClaw: model-fallback.ts → buildFallbackCandidates.

    Args:
        primary_provider: Provider primario.
        primary_model: Modelo primario.
        fallback_specs: Lista de (provider, model) de fallback.
        allowlist: Si se provee, filtra candidatos de fallback por allowlist.

    Returns:
        Lista deduplicada de ModelCandidate.
    """
    collector = CandidateCollector(allowlist)
    collector.add_explicit(ModelCandidate(provider=primary_provider, model=primary_model))

    if fallback_specs:
        for provider, model in fallback_specs:
            collector.add_allowlisted(ModelCandidate(provider=provider, model=model))

    return collector.candidates


def is_context_overflow(error: BaseException) -> bool:
    """Comprueba si un error indica overflow de ventana de contexto.

    Útil para decidir si compactar antes de reintentar.
    """
    return _is_context_overflow_error(error)
