"""Tests para infra/net.py — Utilidades de red, retry y backoff."""

from __future__ import annotations

import asyncio
from typing import List

import pytest

from infra.net import (
    BackoffPolicy,
    DedupeCache,
    RetryConfig,
    compute_backoff,
    retry_async,
    with_timeout,
)


# ── Backoff ──────────────────────────────────────────────────


class TestComputeBackoff:
    """Tests de cálculo de backoff."""

    def test_first_attempt(self) -> None:
        policy = BackoffPolicy(initial_ms=100, max_ms=10000, factor=2.0, jitter=0)
        delay = compute_backoff(policy, 1)
        assert delay == 100

    def test_exponential_growth(self) -> None:
        policy = BackoffPolicy(initial_ms=100, max_ms=100000, factor=2.0, jitter=0)
        assert compute_backoff(policy, 1) == 100
        assert compute_backoff(policy, 2) == 200
        assert compute_backoff(policy, 3) == 400

    def test_respects_max(self) -> None:
        policy = BackoffPolicy(initial_ms=100, max_ms=500, factor=2.0, jitter=0)
        delay = compute_backoff(policy, 10)
        assert delay <= 500

    def test_jitter_adds_randomness(self) -> None:
        policy = BackoffPolicy(initial_ms=1000, max_ms=10000, factor=2.0, jitter=0.5)
        delays = {compute_backoff(policy, 1) for _ in range(20)}
        # Con jitter, deberían haber valores diferentes
        assert len(delays) > 1


# ── Retry ────────────────────────────────────────────────────


class TestRetryAsync:
    """Tests de retry async."""

    @pytest.mark.asyncio
    async def test_success_first_try(self) -> None:
        """Éxito en el primer intento."""
        async def return_42():
            return 42

        result = await retry_async(return_42, attempts=3)
        assert result == 42

    @pytest.mark.asyncio
    async def test_success_after_retries(self) -> None:
        """Éxito después de reintentos."""
        counter = [0]

        async def flaky():
            counter[0] += 1
            if counter[0] < 3:
                raise ValueError("not yet")
            return "ok"

        result = await retry_async(flaky, attempts=5, min_delay_ms=10)
        assert result == "ok"
        assert counter[0] == 3

    @pytest.mark.asyncio
    async def test_exhausted_retries(self) -> None:
        """Se agotan los reintentos."""
        async def always_fail():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            await retry_async(always_fail, attempts=2, min_delay_ms=10)

    @pytest.mark.asyncio
    async def test_should_retry_callback(self) -> None:
        """should_retry puede detener reintentos."""
        counter = [0]

        async def fail():
            counter[0] += 1
            raise TypeError("stop")

        with pytest.raises(TypeError):
            await retry_async(
                fail,
                attempts=5,
                min_delay_ms=10,
                should_retry=lambda err, attempt: False,
            )

        assert counter[0] == 1  # Solo un intento

    @pytest.mark.asyncio
    async def test_on_retry_callback(self) -> None:
        """on_retry es llamado antes de cada reintento."""
        retries: list = []
        counter = [0]

        async def fail_twice():
            counter[0] += 1
            if counter[0] < 3:
                raise ValueError("retry me")
            return "done"

        await retry_async(
            fail_twice,
            attempts=5,
            min_delay_ms=10,
            on_retry=lambda info: retries.append(info.attempt),
        )

        assert retries == [1, 2]


# ── With Timeout ─────────────────────────────────────────────


class TestWithTimeout:
    """Tests de with_timeout."""

    @pytest.mark.asyncio
    async def test_completes_in_time(self) -> None:
        """Corutina completa dentro del timeout."""
        async def fast():
            return 42

        result = await with_timeout(fast(), timeout_seconds=1.0)
        assert result == 42

    @pytest.mark.asyncio
    async def test_timeout_returns_fallback(self) -> None:
        """Timeout retorna el fallback."""
        async def slow():
            await asyncio.sleep(10)
            return 42

        result = await with_timeout(slow(), timeout_seconds=0.1, fallback="timeout")
        assert result == "timeout"


# ── DedupeCache ──────────────────────────────────────────────


class TestDedupeCache:
    """Tests del cache de deduplicación."""

    def test_first_check_returns_false(self) -> None:
        """Primera vez que se ve una clave → no es duplicado."""
        cache = DedupeCache(ttl_seconds=60)
        assert cache.check("key1") is False

    def test_second_check_returns_true(self) -> None:
        """Segunda vez → es duplicado."""
        cache = DedupeCache(ttl_seconds=60)
        cache.check("key1")
        assert cache.check("key1") is True

    def test_different_keys(self) -> None:
        """Claves diferentes no son duplicados."""
        cache = DedupeCache(ttl_seconds=60)
        cache.check("key1")
        assert cache.check("key2") is False

    def test_ttl_expiry(self) -> None:
        """Entradas expiradas no son duplicados."""
        cache = DedupeCache(ttl_seconds=10)
        cache.check("key1", now=100)
        assert cache.check("key1", now=105) is True  # Dentro del TTL
        assert cache.check("key1", now=115) is False  # Expirado (TTL check in peek is False)

    def test_peek_no_register(self) -> None:
        """peek no registra la clave."""
        cache = DedupeCache(ttl_seconds=60)
        assert cache.peek("key1") is False
        assert cache.peek("key1") is False  # Sigue siendo False

    def test_delete(self) -> None:
        """Eliminar una clave."""
        cache = DedupeCache(ttl_seconds=60)
        cache.check("key1")
        cache.delete("key1")
        assert cache.check("key1") is False

    def test_clear(self) -> None:
        """Limpiar todo el cache."""
        cache = DedupeCache(ttl_seconds=60)
        cache.check("a")
        cache.check("b")
        cache.clear()
        assert cache.size == 0

    def test_max_size(self) -> None:
        """Respetar tamaño máximo."""
        cache = DedupeCache(ttl_seconds=60, max_size=3)
        for i in range(10):
            cache.check(f"key{i}")
        assert cache.size <= 3

    def test_none_key(self) -> None:
        """Clave None retorna False."""
        cache = DedupeCache(ttl_seconds=60)
        assert cache.check(None) is False
        assert cache.peek(None) is False
