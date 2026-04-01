"""Tests para el sistema de model fallback."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from agents.model_fallback import (
    CandidateCollector,
    FallbackAttempt,
    FallbackResult,
    ModelCandidate,
    build_fallback_candidates,
    is_context_overflow,
    run_with_model_fallback,
)
from shared.errors import AgentError, ProviderError


class TestModelCandidate:
    def test_basic(self) -> None:
        c = ModelCandidate(provider="anthropic", model="claude-sonnet")
        assert c.provider == "anthropic"
        assert c.model == "claude-sonnet"


class TestCandidateCollector:
    def test_deduplication(self) -> None:
        collector = CandidateCollector()
        collector.add_explicit(ModelCandidate("a", "m1"))
        collector.add_explicit(ModelCandidate("a", "m1"))
        assert len(collector.candidates) == 1

    def test_allowlist_filtering(self) -> None:
        collector = CandidateCollector(allowlist={"a/m1"})
        collector.add_allowlisted(ModelCandidate("a", "m1"))
        collector.add_allowlisted(ModelCandidate("b", "m2"))
        assert len(collector.candidates) == 1
        assert collector.candidates[0].model == "m1"

    def test_explicit_bypasses_allowlist(self) -> None:
        collector = CandidateCollector(allowlist={"a/m1"})
        collector.add_explicit(ModelCandidate("b", "m2"))
        assert len(collector.candidates) == 1

    def test_empty_provider_rejected(self) -> None:
        collector = CandidateCollector()
        collector.add_explicit(ModelCandidate("", "m1"))
        assert len(collector.candidates) == 0


class TestBuildFallbackCandidates:
    def test_primary_only(self) -> None:
        candidates = build_fallback_candidates("anthropic", "claude")
        assert len(candidates) == 1
        assert candidates[0].provider == "anthropic"

    def test_with_fallbacks(self) -> None:
        candidates = build_fallback_candidates(
            "anthropic", "claude",
            [("openai", "gpt-4"), ("google", "gemini")],
        )
        assert len(candidates) == 3
        assert candidates[0].provider == "anthropic"
        assert candidates[1].provider == "openai"
        assert candidates[2].provider == "google"

    def test_deduplication(self) -> None:
        candidates = build_fallback_candidates(
            "anthropic", "claude",
            [("anthropic", "claude"), ("openai", "gpt-4")],
        )
        assert len(candidates) == 2


class TestRunWithModelFallback:
    @pytest.mark.asyncio
    async def test_first_succeeds(self) -> None:
        async def run(provider: str, model: str) -> str:
            return f"result-{provider}"

        candidates = [ModelCandidate("a", "m1")]
        result = await run_with_model_fallback(candidates, run)
        assert result.result == "result-a"
        assert result.provider == "a"
        assert len(result.attempts) == 0

    @pytest.mark.asyncio
    async def test_fallback_on_failure(self) -> None:
        call_count = 0

        async def run(provider: str, model: str) -> str:
            nonlocal call_count
            call_count += 1
            if provider == "a":
                raise ProviderError("fail")
            return f"result-{provider}"

        candidates = [ModelCandidate("a", "m1"), ModelCandidate("b", "m2")]
        result = await run_with_model_fallback(candidates, run)
        assert result.result == "result-b"
        assert result.provider == "b"
        assert len(result.attempts) == 1
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_all_fail(self) -> None:
        async def run(provider: str, model: str) -> str:
            raise ProviderError(f"fail-{provider}")

        candidates = [ModelCandidate("a", "m1"), ModelCandidate("b", "m2")]
        with pytest.raises(AgentError, match="Todos los .* fallaron"):
            await run_with_model_fallback(candidates, run)

    @pytest.mark.asyncio
    async def test_no_candidates(self) -> None:
        async def run(provider: str, model: str) -> str:
            return "ok"

        with pytest.raises(AgentError, match="Sin candidatos"):
            await run_with_model_fallback([], run)

    @pytest.mark.asyncio
    async def test_single_fail_rethrows(self) -> None:
        """Con un solo candidato, relanza el error original."""
        async def run(provider: str, model: str) -> str:
            raise ProviderError("error original")

        candidates = [ModelCandidate("a", "m1")]
        with pytest.raises(ProviderError, match="error original"):
            await run_with_model_fallback(candidates, run)

    @pytest.mark.asyncio
    async def test_on_error_callback(self) -> None:
        errors: List[Dict[str, Any]] = []

        async def run(provider: str, model: str) -> str:
            if provider == "a":
                raise ProviderError("fail-a")
            return "ok"

        async def on_error(info: Dict[str, Any]) -> None:
            errors.append(info)

        candidates = [ModelCandidate("a", "m1"), ModelCandidate("b", "m2")]
        await run_with_model_fallback(candidates, run, on_error=on_error)
        assert len(errors) == 1
        assert errors[0]["provider"] == "a"


class TestIsContextOverflow:
    def test_overflow_detected(self) -> None:
        assert is_context_overflow(
            ProviderError("context_length_exceeded: too many tokens")
        )

    def test_max_tokens(self) -> None:
        assert is_context_overflow(
            ProviderError("max_tokens exceeded for this model")
        )

    def test_normal_error_not_detected(self) -> None:
        assert not is_context_overflow(ProviderError("rate limit exceeded"))
