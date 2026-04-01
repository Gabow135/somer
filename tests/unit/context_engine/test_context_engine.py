"""Tests para el Context Engine."""

from __future__ import annotations

import pytest

from context_engine.default import DefaultContextEngine
from context_engine.registry import ContextEngineRegistry
from shared.types import AgentMessage, Role


class TestDefaultContextEngine:
    """Tests del DefaultContextEngine."""

    @pytest.mark.asyncio
    async def test_bootstrap(self) -> None:
        engine = DefaultContextEngine(system_prompt="You are helpful.")
        result = await engine.bootstrap("s1", "")
        assert result.session_id == "s1"
        assert result.system_prompt == "You are helpful."

    @pytest.mark.asyncio
    async def test_ingest(self) -> None:
        engine = DefaultContextEngine()
        await engine.bootstrap("s1", "")
        msg = AgentMessage(role=Role.USER, content="Hello world")
        result = await engine.ingest("s1", msg)
        assert result.accepted
        assert result.token_count > 0

    @pytest.mark.asyncio
    async def test_assemble(self) -> None:
        engine = DefaultContextEngine(system_prompt="System")
        await engine.bootstrap("s1", "")
        await engine.ingest("s1", AgentMessage(role=Role.USER, content="Hello"))
        await engine.ingest("s1", AgentMessage(role=Role.ASSISTANT, content="Hi there"))
        result = await engine.assemble("s1", [], 10000)
        assert len(result.messages) >= 2  # system + messages
        assert result.messages[0]["role"] == "system"

    @pytest.mark.asyncio
    async def test_assemble_truncation(self) -> None:
        engine = DefaultContextEngine(system_prompt="System")
        await engine.bootstrap("s1", "")
        for i in range(50):
            await engine.ingest("s1", AgentMessage(role=Role.USER, content=f"Message {i} " * 100))
        result = await engine.assemble("s1", [], 500)
        assert result.truncated

    @pytest.mark.asyncio
    async def test_compact(self) -> None:
        # Use high token limit to avoid auto-compact, then force-compact
        engine = DefaultContextEngine(max_context_tokens=100_000, compact_ratio=0.85)
        await engine.bootstrap("s1", "")
        for i in range(20):
            await engine.ingest("s1", AgentMessage(role=Role.USER, content=f"Message {i} " * 50))
        tokens_before = engine.get_token_count("s1")
        result = await engine.compact("s1", 100_000, force=True)
        assert result.compacted
        assert result.tokens_after < tokens_before

    @pytest.mark.asyncio
    async def test_get_counts(self) -> None:
        engine = DefaultContextEngine()
        await engine.bootstrap("s1", "")
        await engine.ingest("s1", AgentMessage(role=Role.USER, content="hello"))
        assert engine.get_message_count("s1") == 1
        assert engine.get_token_count("s1") > 0

    @pytest.mark.asyncio
    async def test_unknown_session(self) -> None:
        engine = DefaultContextEngine()
        assert engine.get_message_count("nonexistent") == 0


class TestContextEngineRegistry:
    """Tests del registry."""

    def test_default_registered(self) -> None:
        registry = ContextEngineRegistry()
        assert registry.get("default") is not None

    def test_list(self) -> None:
        registry = ContextEngineRegistry()
        assert "default" in registry.list_engines()
