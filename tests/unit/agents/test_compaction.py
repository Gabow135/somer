"""Tests para el sistema de compactación."""

from __future__ import annotations

from typing import List, Optional

import pytest

from agents.compaction import (
    BASE_CHUNK_RATIO,
    CompactionConfig,
    CompactionResult,
    chunk_messages_by_max_tokens,
    compact_messages,
    compute_adaptive_chunk_ratio,
    estimate_agent_messages_tokens,
    should_compact,
    split_messages_by_token_share,
    build_summarization_instructions,
    serialize_messages_for_summary,
)
from shared.types import AgentMessage, Role


def _msg(content: str, role: Role = Role.USER) -> AgentMessage:
    """Helper para crear un AgentMessage."""
    return AgentMessage(role=role, content=content)


class TestEstimateAgentMessagesTokens:
    def test_empty(self) -> None:
        assert estimate_agent_messages_tokens([]) == 0

    def test_single_message(self) -> None:
        tokens = estimate_agent_messages_tokens([_msg("hello world")])
        assert tokens > 0

    def test_multiple_messages(self) -> None:
        msgs = [_msg("hello"), _msg("world", Role.ASSISTANT)]
        tokens = estimate_agent_messages_tokens(msgs)
        assert tokens > 0


class TestShouldCompact:
    def test_off_mode(self) -> None:
        config = CompactionConfig(mode="off")
        assert not should_compact([_msg("x" * 10000)], config)

    def test_below_threshold(self) -> None:
        config = CompactionConfig(
            context_window=128_000,
            threshold_ratio=0.85,
        )
        assert not should_compact([_msg("hello")], config)

    def test_above_threshold(self) -> None:
        config = CompactionConfig(
            context_window=100,
            max_output_tokens=10,
            threshold_ratio=0.5,
        )
        msgs = [_msg("x" * 500)]
        assert should_compact(msgs, config)


class TestSplitMessagesByTokenShare:
    def test_empty(self) -> None:
        assert split_messages_by_token_share([]) == []

    def test_single_part(self) -> None:
        msgs = [_msg("a"), _msg("b")]
        result = split_messages_by_token_share(msgs, parts=1)
        assert len(result) == 1
        assert len(result[0]) == 2

    def test_two_parts(self) -> None:
        msgs = [_msg("x" * 100) for _ in range(10)]
        result = split_messages_by_token_share(msgs, parts=2)
        assert len(result) == 2
        total = sum(len(chunk) for chunk in result)
        assert total == 10

    def test_more_parts_than_messages(self) -> None:
        msgs = [_msg("a")]
        result = split_messages_by_token_share(msgs, parts=5)
        assert len(result) == 1


class TestChunkMessagesByMaxTokens:
    def test_empty(self) -> None:
        assert chunk_messages_by_max_tokens([], 1000) == []

    def test_all_fit(self) -> None:
        msgs = [_msg("hello"), _msg("world")]
        result = chunk_messages_by_max_tokens(msgs, 10000)
        assert len(result) == 1

    def test_split_needed(self) -> None:
        msgs = [_msg("x" * 200) for _ in range(10)]
        result = chunk_messages_by_max_tokens(msgs, 100)
        assert len(result) > 1
        total = sum(len(chunk) for chunk in result)
        assert total == 10


class TestComputeAdaptiveChunkRatio:
    def test_empty(self) -> None:
        assert compute_adaptive_chunk_ratio([], 128_000) == BASE_CHUNK_RATIO

    def test_small_messages(self) -> None:
        msgs = [_msg("short") for _ in range(10)]
        ratio = compute_adaptive_chunk_ratio(msgs, 128_000)
        assert ratio == BASE_CHUNK_RATIO

    def test_large_messages_reduce_ratio(self) -> None:
        msgs = [_msg("x" * 50000) for _ in range(5)]
        ratio = compute_adaptive_chunk_ratio(msgs, 128_000)
        assert ratio < BASE_CHUNK_RATIO


class TestBuildSummarizationInstructions:
    def test_strict(self) -> None:
        result = build_summarization_instructions(identifier_policy="strict")
        assert result is not None
        assert "identifiers" in result.lower()

    def test_off(self) -> None:
        result = build_summarization_instructions(identifier_policy="off")
        assert result is None

    def test_custom(self) -> None:
        result = build_summarization_instructions(
            custom_instructions="Keep code snippets",
            identifier_policy="custom",
        )
        assert result is not None
        assert "code snippets" in result.lower()


class TestSerializeMessagesForSummary:
    def test_basic(self) -> None:
        msgs = [_msg("Hello"), _msg("Response", Role.ASSISTANT)]
        text = serialize_messages_for_summary(msgs)
        assert "[user]" in text
        assert "[assistant]" in text
        assert "Hello" in text
        assert "Response" in text


class TestCompactMessages:
    @pytest.mark.asyncio
    async def test_off_mode(self) -> None:
        config = CompactionConfig(mode="off")

        async def summarize(text: str, instructions: Optional[str]) -> str:
            return "summary"

        result = await compact_messages([_msg("hello")], summarize, config)
        assert not result.compacted

    @pytest.mark.asyncio
    async def test_below_threshold_no_compact(self) -> None:
        config = CompactionConfig(
            context_window=128_000,
            threshold_ratio=0.85,
        )

        async def summarize(text: str, instructions: Optional[str]) -> str:
            return "summary"

        result = await compact_messages([_msg("hello")], summarize, config)
        assert not result.compacted

    @pytest.mark.asyncio
    async def test_successful_compaction(self) -> None:
        config = CompactionConfig(
            context_window=200,
            max_output_tokens=20,
            threshold_ratio=0.3,
        )
        msgs = [_msg("x" * 200) for _ in range(5)]

        async def summarize(text: str, instructions: Optional[str]) -> str:
            return "Short summary of the conversation."

        result = await compact_messages(msgs, summarize, config)
        assert result.compacted
        assert result.tokens_after < result.tokens_before
        assert len(result.summary) > 0

    @pytest.mark.asyncio
    async def test_summarize_error_handling(self) -> None:
        config = CompactionConfig(
            context_window=200,
            max_output_tokens=20,
            threshold_ratio=0.3,
        )
        msgs = [_msg("x" * 200) for _ in range(5)]

        async def summarize(text: str, instructions: Optional[str]) -> str:
            raise RuntimeError("Summarization failed")

        result = await compact_messages(msgs, summarize, config)
        assert not result.compacted
        assert result.error is not None
