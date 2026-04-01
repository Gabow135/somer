"""Tests para el Agent Runner."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock

import pytest

from agents.auth_profiles import AuthProfileManager
from agents.context_window import ContextWindowGuard, estimate_tokens
from agents.runner import AgentRunner
from providers.base import BaseProvider
from providers.registry import ProviderRegistry
from shared.types import ModelDefinition


class MockProvider(BaseProvider):
    """Provider mock para tests."""

    def __init__(self, provider_id: str = "mock"):
        super().__init__(
            provider_id=provider_id,
            api="openai-completions",
            api_key="test",
            models=[
                ModelDefinition(
                    id="mock-model",
                    name="Mock",
                    api="openai-completions",
                    provider=provider_id,
                )
            ],
        )
        self.complete_mock = AsyncMock(return_value={
            "content": "Mock response",
            "model": "mock-model",
            "usage": {"input_tokens": 10, "output_tokens": 5},
            "stop_reason": "end_turn",
        })

    async def complete(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        *,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: Optional[List[Dict[str, Any]]] = None,
        stream: bool = False,
    ) -> Dict[str, Any]:
        return await self.complete_mock(messages, model, max_tokens=max_tokens, tools=tools)


class TestContextWindowGuard:
    """Tests del guard de contexto."""

    def test_check_fits(self) -> None:
        guard = ContextWindowGuard(max_input_tokens=10000)
        result = guard.check([{"role": "user", "content": "hello"}])
        assert result["fits"]

    def test_check_exceeds(self) -> None:
        guard = ContextWindowGuard(max_input_tokens=100)
        msgs = [{"role": "user", "content": "x" * 1000}]
        result = guard.check(msgs)
        assert not result["fits"]

    def test_enforce_truncates(self) -> None:
        guard = ContextWindowGuard(max_input_tokens=200)
        msgs = [
            {"role": "system", "content": "Be helpful"},
            {"role": "user", "content": "old message " * 100},
            {"role": "assistant", "content": "old response " * 100},
            {"role": "user", "content": "recent"},
        ]
        result = guard.enforce(msgs)
        # System prompt preserved
        assert result[0]["role"] == "system"
        # Recent message preserved
        assert any("recent" in m.get("content", "") for m in result)

    def test_enforce_no_truncation_needed(self) -> None:
        guard = ContextWindowGuard(max_input_tokens=10000)
        msgs = [{"role": "user", "content": "hello"}]
        result = guard.enforce(msgs)
        assert result == msgs


class TestEstimateTokens:
    def test_basic(self) -> None:
        assert estimate_tokens("hello world") > 0

    def test_empty(self) -> None:
        assert estimate_tokens("") >= 1

    def test_long_text(self) -> None:
        text = "word " * 1000
        tokens = estimate_tokens(text)
        assert 900 < tokens < 2000


class TestAuthProfileManager:
    def test_get_or_create(self) -> None:
        mgr = AuthProfileManager()
        profile = mgr.get_or_create("test")
        assert profile.is_available

    def test_record_failure_and_check(self) -> None:
        mgr = AuthProfileManager()
        mgr.get_or_create("test", cooldown_secs=1.0)
        mgr.record_failure("test")
        assert not mgr.is_available("test")

    def test_status(self) -> None:
        mgr = AuthProfileManager()
        mgr.get_or_create("p1")
        mgr.get_or_create("p2")
        mgr.record_failure("p1")
        status = mgr.status()
        assert not status["p1"]["available"]
        assert status["p2"]["available"]

    def test_reset_all(self) -> None:
        mgr = AuthProfileManager()
        mgr.get_or_create("p1", cooldown_secs=1.0)
        mgr.record_failure("p1")
        mgr.reset_all()
        assert mgr.is_available("p1")


class TestAgentRunner:
    """Tests del AgentRunner."""

    @pytest.fixture
    def runner_setup(self):
        registry = ProviderRegistry()
        provider = MockProvider()
        registry.register(provider)
        runner = AgentRunner(
            provider_registry=registry,
            default_model="mock-model",
        )
        return runner, provider

    @pytest.mark.asyncio
    async def test_basic_run(self, runner_setup) -> None:
        runner, provider = runner_setup
        turn = await runner.run("s1", "Hello")
        assert len(turn.messages) >= 2  # user + assistant
        assert turn.messages[0].content == "Hello"
        assert turn.messages[1].content == "Mock response"

    @pytest.mark.asyncio
    async def test_with_system_prompt(self, runner_setup) -> None:
        runner, provider = runner_setup
        turn = await runner.run("s1", "Hello", system_prompt="Be concise")
        provider.complete_mock.assert_called_once()
        call_args = provider.complete_mock.call_args[0][0]
        assert call_args[0]["role"] == "system"

    @pytest.mark.asyncio
    async def test_register_tool(self, runner_setup) -> None:
        runner, _ = runner_setup
        async def my_tool(name, args):
            return {"result": "ok"}
        runner.register_tool("my_tool", my_tool)
        assert "my_tool" in runner.tool_names
        runner.unregister_tool("my_tool")
        assert "my_tool" not in runner.tool_names

    @pytest.mark.asyncio
    async def test_no_providers_raises(self) -> None:
        registry = ProviderRegistry()
        runner = AgentRunner(provider_registry=registry)
        from shared.errors import AgentError
        with pytest.raises(AgentError, match="No hay providers"):
            await runner.run("s1", "Hello")
