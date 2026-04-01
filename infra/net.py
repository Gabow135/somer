"""Utilidades de red, retry y backoff — SOMER.

Portado de OpenClaw: retry.ts, backoff.ts + utilidades de red existentes.

Incluye verificación de puertos (delegada a infra.ports para lógica
avanzada), retry con backoff exponencial y jitter.
"""

from __future__ import annotations

import asyncio
import logging
import random
import socket
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ── Utilidades de puerto (compatibilidad) ───────────────────


def is_port_available(host: str = "127.0.0.1", port: int = 0) -> bool:
    """Verifica si un puerto está disponible."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
            return True
    except OSError:
        return False


def find_free_port(host: str = "127.0.0.1") -> int:
    """Encuentra un puerto libre."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


async def wait_for_port(
    host: str,
    port: int,
    timeout: float = 10.0,
    interval: float = 0.1,
) -> bool:
    """Espera hasta que un puerto esté disponible para conexión."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=1.0,
            )
            writer.close()
            await writer.wait_closed()
            return True
        except (ConnectionRefusedError, asyncio.TimeoutError, OSError):
            await asyncio.sleep(interval)
    return False


# ── Backoff y Retry ─────────────────────────────────────────


@dataclass
class BackoffPolicy:
    """Política de backoff exponencial."""

    initial_ms: float = 300
    max_ms: float = 30_000
    factor: float = 2.0
    jitter: float = 0.0  # 0-1, fracción de jitter


@dataclass
class RetryConfig:
    """Configuración de reintentos."""

    attempts: int = 3
    min_delay_ms: float = 300
    max_delay_ms: float = 30_000
    jitter: float = 0.0  # 0-1


@dataclass
class RetryInfo:
    """Información de un reintento."""

    attempt: int
    max_attempts: int
    delay_ms: float
    error: Exception
    label: Optional[str] = None


def compute_backoff(policy: BackoffPolicy, attempt: int) -> float:
    """Calcula el delay de backoff para un intento dado.

    Args:
        policy: Política de backoff.
        attempt: Número de intento (1-based).

    Returns:
        Delay en milisegundos.
    """
    base = policy.initial_ms * (policy.factor ** max(attempt - 1, 0))
    jitter_amount = base * policy.jitter * random.random()
    return min(policy.max_ms, round(base + jitter_amount))


def _apply_jitter(delay_ms: float, jitter: float) -> float:
    """Aplica jitter a un delay."""
    if jitter <= 0:
        return delay_ms
    offset = (random.random() * 2 - 1) * jitter
    return max(0, round(delay_ms * (1 + offset)))


def resolve_retry_config(
    overrides: Optional[RetryConfig] = None,
) -> RetryConfig:
    """Resuelve una configuración de retry con defaults.

    Args:
        overrides: Overrides opcionales.

    Returns:
        Configuración resuelta.
    """
    if overrides is None:
        return RetryConfig()

    return RetryConfig(
        attempts=max(1, overrides.attempts),
        min_delay_ms=max(0, overrides.min_delay_ms),
        max_delay_ms=max(overrides.min_delay_ms, overrides.max_delay_ms),
        jitter=max(0.0, min(1.0, overrides.jitter)),
    )


async def retry_async(
    fn: Callable[..., Any],
    attempts: int = 3,
    min_delay_ms: float = 300,
    max_delay_ms: float = 30_000,
    jitter: float = 0.0,
    should_retry: Optional[Callable[[Exception, int], bool]] = None,
    on_retry: Optional[Callable[[RetryInfo], None]] = None,
    label: Optional[str] = None,
) -> Any:
    """Ejecuta una función async con reintentos y backoff exponencial.

    Args:
        fn: Función async a ejecutar.
        attempts: Número máximo de intentos.
        min_delay_ms: Delay mínimo entre reintentos (ms).
        max_delay_ms: Delay máximo entre reintentos (ms).
        jitter: Factor de jitter (0-1).
        should_retry: Función que decide si reintentar.
        on_retry: Callback llamado antes de cada reintento.
        label: Etiqueta para logging.

    Returns:
        Resultado de fn.

    Raises:
        Exception: La última excepción si se agotan los intentos.
    """
    max_attempts = max(1, attempts)
    last_error: Optional[Exception] = None

    for attempt in range(1, max_attempts + 1):
        try:
            return await fn()
        except Exception as exc:
            last_error = exc

            if attempt >= max_attempts:
                break

            if should_retry and not should_retry(exc, attempt):
                break

            # Calcular delay con backoff exponencial
            base_delay = min_delay_ms * (2 ** (attempt - 1))
            delay = min(base_delay, max_delay_ms)
            delay = _apply_jitter(delay, jitter)
            delay = min(max(delay, min_delay_ms), max_delay_ms)

            info = RetryInfo(
                attempt=attempt,
                max_attempts=max_attempts,
                delay_ms=delay,
                error=exc,
                label=label,
            )

            if on_retry:
                on_retry(info)
            else:
                logger.debug(
                    "Reintento %d/%d%s en %.0fms: %s",
                    attempt,
                    max_attempts,
                    f" [{label}]" if label else "",
                    delay,
                    exc,
                )

            await asyncio.sleep(delay / 1000)

    if last_error is not None:
        raise last_error
    raise RuntimeError("Retry agotado sin error capturado")


async def with_timeout(
    coro: Any,
    timeout_seconds: float,
    fallback: Any = None,
) -> Any:
    """Ejecuta una corutina con timeout, retornando fallback si expira.

    Args:
        coro: Corutina a ejecutar.
        timeout_seconds: Timeout en segundos.
        fallback: Valor a retornar si expira.

    Returns:
        Resultado de la corutina o fallback.
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout_seconds)
    except asyncio.TimeoutError:
        return fallback


# ── Deduplicación ───────────────────────────────────────────


class DedupeCache:
    """Cache de deduplicación con TTL.

    Portado de OpenClaw: dedupe.ts.
    Permite verificar si una clave ya fue vista dentro
    de una ventana de tiempo configurable.
    """

    def __init__(self, ttl_seconds: float = 60.0, max_size: int = 1000) -> None:
        """Inicializa el cache.

        Args:
            ttl_seconds: Tiempo de vida de las entradas.
            max_size: Tamaño máximo del cache.
        """
        self._ttl = ttl_seconds
        self._max_size = max_size
        self._cache: dict[str, float] = {}

    def check(self, key: Optional[str], now: Optional[float] = None) -> bool:
        """Verifica y registra una clave.

        Returns:
            True si la clave ya existía (duplicado).
        """
        if not key:
            return False

        current = now or time.time()

        # Verificar si existe y no ha expirado
        existing = self._cache.get(key)
        if existing is not None:
            if self._ttl > 0 and (current - existing) >= self._ttl:
                del self._cache[key]
            else:
                # Actualizar timestamp
                self._cache[key] = current
                return True

        # Registrar nueva entrada
        self._cache[key] = current
        self._prune(current)
        return False

    def peek(self, key: Optional[str], now: Optional[float] = None) -> bool:
        """Verifica si una clave existe sin registrarla.

        Returns:
            True si la clave existe y no ha expirado.
        """
        if not key:
            return False
        current = now or time.time()
        existing = self._cache.get(key)
        if existing is None:
            return False
        if self._ttl > 0 and (current - existing) >= self._ttl:
            del self._cache[key]
            return False
        return True

    def delete(self, key: Optional[str]) -> None:
        """Elimina una clave del cache."""
        if key:
            self._cache.pop(key, None)

    def clear(self) -> None:
        """Limpia todo el cache."""
        self._cache.clear()

    @property
    def size(self) -> int:
        """Tamaño actual del cache."""
        return len(self._cache)

    def _prune(self, now: float) -> None:
        """Elimina entradas expiradas y excedentes."""
        # Eliminar expiradas
        if self._ttl > 0:
            cutoff = now - self._ttl
            expired = [k for k, ts in self._cache.items() if ts < cutoff]
            for k in expired:
                del self._cache[k]

        # Limitar tamaño (eliminar las más antiguas)
        if self._max_size > 0 and len(self._cache) > self._max_size:
            sorted_keys = sorted(
                self._cache.keys(), key=lambda k: self._cache[k]
            )
            excess = len(self._cache) - self._max_size
            for k in sorted_keys[:excess]:
                del self._cache[k]
