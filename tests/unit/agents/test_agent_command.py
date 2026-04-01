"""Tests para el sistema de comandos de agente."""

from __future__ import annotations

from typing import Any, Dict

import pytest

from agents.agent_command import (
    AgentCommandExecutor,
    AgentCommandOpts,
    AgentCommandResult,
    CommandType,
    parse_command,
    validate_override_value,
)
from shared.errors import AgentError


class TestParseCommand:
    def test_not_a_command(self) -> None:
        assert parse_command("Hello world") is None

    def test_model_override(self) -> None:
        result = parse_command("/model gpt-4o")
        assert result is not None
        cmd_type, arg = result
        assert cmd_type == CommandType.MODEL_OVERRIDE
        assert arg == "gpt-4o"

    def test_provider_override(self) -> None:
        result = parse_command("/provider openai")
        assert result is not None
        cmd_type, arg = result
        assert cmd_type == CommandType.PROVIDER_OVERRIDE
        assert arg == "openai"

    def test_reset(self) -> None:
        result = parse_command("/reset")
        assert result is not None
        cmd_type, arg = result
        assert cmd_type == CommandType.RESET_SESSION

    def test_compact(self) -> None:
        result = parse_command("/compact")
        assert result is not None
        cmd_type, _ = result
        assert cmd_type == CommandType.COMPACT

    def test_status(self) -> None:
        result = parse_command("/status")
        assert result is not None
        cmd_type, _ = result
        assert cmd_type == CommandType.STATUS

    def test_clear(self) -> None:
        result = parse_command("/clear")
        assert result is not None
        cmd_type, _ = result
        assert cmd_type == CommandType.CLEAR_OVERRIDES

    def test_case_insensitive(self) -> None:
        result = parse_command("/Model gpt-4")
        assert result is not None

    def test_unknown_slash_command(self) -> None:
        result = parse_command("/unknown")
        assert result is None


class TestValidateOverrideValue:
    def test_valid(self) -> None:
        assert validate_override_value("gpt-4o") == "gpt-4o"

    def test_strips_whitespace(self) -> None:
        assert validate_override_value("  gpt-4o  ") == "gpt-4o"

    def test_empty_raises(self) -> None:
        with pytest.raises(AgentError, match="no puede estar vacío"):
            validate_override_value("")

    def test_too_long(self) -> None:
        with pytest.raises(AgentError, match="demasiado largo"):
            validate_override_value("x" * 300)

    def test_control_chars(self) -> None:
        with pytest.raises(AgentError, match="caracteres de control"):
            validate_override_value("model\x00name")


class TestAgentCommandExecutor:
    @pytest.fixture
    def executor(self):
        async def run_agent(opts: AgentCommandOpts) -> AgentCommandResult:
            return AgentCommandResult(
                success=True,
                content="Agent response",
                tokens_used=42,
            )

        return AgentCommandExecutor(run_agent=run_agent)

    @pytest.mark.asyncio
    async def test_normal_message(self, executor) -> None:
        opts = AgentCommandOpts(
            session_key="s1",
            message="Hello",
        )
        result = await executor.execute(opts)
        assert result.success
        assert result.content == "Agent response"

    @pytest.mark.asyncio
    async def test_model_command(self, executor) -> None:
        opts = AgentCommandOpts(
            session_key="s1",
            message="/model gpt-4o",
        )
        result = await executor.execute(opts)
        assert result.success
        assert "gpt-4o" in result.content
        assert result.model == "gpt-4o"

    @pytest.mark.asyncio
    async def test_status_command(self, executor) -> None:
        opts = AgentCommandOpts(
            session_key="s1",
            message="/status",
        )
        result = await executor.execute(opts)
        assert result.success

    @pytest.mark.asyncio
    async def test_reset_command(self, executor) -> None:
        opts = AgentCommandOpts(
            session_key="s1",
            message="/reset",
        )
        result = await executor.execute(opts)
        assert result.success
        assert "reseteada" in result.content.lower()

    @pytest.mark.asyncio
    async def test_duration_tracked(self, executor) -> None:
        opts = AgentCommandOpts(
            session_key="s1",
            message="Hello",
        )
        result = await executor.execute(opts)
        assert result.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_model_override_callback(self) -> None:
        overrides = []

        async def run_agent(opts: AgentCommandOpts) -> AgentCommandResult:
            return AgentCommandResult(success=True)

        async def on_model(session_key: str, model: str) -> None:
            overrides.append((session_key, model))

        executor = AgentCommandExecutor(
            run_agent=run_agent,
            on_model_override=on_model,
        )
        opts = AgentCommandOpts(
            session_key="s1",
            message="/model claude-sonnet",
        )
        await executor.execute(opts)
        assert len(overrides) == 1
        assert overrides[0] == ("s1", "claude-sonnet")
