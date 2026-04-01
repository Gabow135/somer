"""Tests para el registro y ejecución de tools."""

from __future__ import annotations

from typing import Any, Dict

import pytest

from agents.tools.registry import (
    LoopDetectionConfig,
    ToolDefinition,
    ToolLoopDetector,
    ToolProfile,
    ToolRegistry,
    ToolSection,
)
from shared.types import ToolCall


class TestToolDefinition:
    def test_basic(self) -> None:
        tool = ToolDefinition(
            id="my_tool",
            name="my_tool",
            description="A test tool",
        )
        assert tool.name == "my_tool"

    def test_to_openai_format(self) -> None:
        tool = ToolDefinition(
            id="test",
            name="test",
            description="Test tool",
            parameters={
                "type": "object",
                "properties": {"q": {"type": "string"}},
            },
        )
        fmt = tool.to_provider_format("default")
        assert fmt["type"] == "function"
        assert fmt["function"]["name"] == "test"

    def test_to_anthropic_format(self) -> None:
        tool = ToolDefinition(
            id="test",
            name="test",
            description="Test tool",
        )
        fmt = tool.to_provider_format("anthropic")
        assert fmt["name"] == "test"
        assert "input_schema" in fmt


class TestToolLoopDetector:
    def test_no_loop(self) -> None:
        detector = ToolLoopDetector()
        detector.record("tool_a", '{"url": "a"}')
        detector.record("tool_b", '{"url": "b"}')
        assert not detector.is_looping()

    def test_different_args_no_loop(self) -> None:
        """Mismo nombre pero diferentes args NO es loop."""
        detector = ToolLoopDetector(LoopDetectionConfig(
            max_identical_consecutive=3,
        ))
        detector.record("http_request", '{"url": "https://api.notion.com/v1/search"}')
        detector.record("http_request", '{"url": "https://api.notion.com/v1/databases/123/query"}')
        detector.record("http_request", '{"url": "https://api.notion.com/v1/pages/456"}')
        assert not detector.is_looping()

    def test_identical_consecutive_is_loop(self) -> None:
        """Misma tool + mismos args repetidos = loop real."""
        detector = ToolLoopDetector(LoopDetectionConfig(
            max_identical_consecutive=3,
        ))
        for _ in range(3):
            detector.record("http_request", '{"url": "https://api.notion.com/v1/search"}')
        assert detector.is_looping()

    def test_identical_not_consecutive_no_loop(self) -> None:
        """Mismos args pero intercalados NO es loop consecutivo."""
        detector = ToolLoopDetector(LoopDetectionConfig(
            max_identical_consecutive=3,
            max_same_name_in_window=20,
        ))
        detector.record("http_request", '{"url": "a"}')
        detector.record("http_request", '{"url": "b"}')
        detector.record("http_request", '{"url": "a"}')
        assert not detector.is_looping()

    def test_total_limit(self) -> None:
        detector = ToolLoopDetector(LoopDetectionConfig(
            max_total_calls=5,
        ))
        for i in range(5):
            detector.record(f"tool_{i}", str(i))
        assert detector.is_looping()

    def test_same_name_window_limit(self) -> None:
        """Muchas llamadas al mismo nombre (aunque args distintos) en ventana."""
        detector = ToolLoopDetector(LoopDetectionConfig(
            max_same_name_in_window=5,
            window_size=10,
            max_identical_consecutive=100,
        ))
        for i in range(5):
            detector.record("http_request", f'{{"url": "endpoint_{i}"}}')
        assert detector.is_looping()

    def test_reset(self) -> None:
        detector = ToolLoopDetector(LoopDetectionConfig(
            max_total_calls=3,
        ))
        for _ in range(3):
            detector.record("tool_a", "args")
        assert detector.is_looping()
        detector.reset()
        assert not detector.is_looping()


class TestToolRegistry:
    def test_register_and_list(self) -> None:
        reg = ToolRegistry()
        tool = ToolDefinition(
            id="test", name="test", description="Test",
        )
        reg.register(tool)
        assert "test" in reg.tool_names
        assert reg.get("test") is not None

    def test_unregister(self) -> None:
        reg = ToolRegistry()
        tool = ToolDefinition(id="test", name="test", description="Test")
        reg.register(tool)
        reg.unregister("test")
        assert "test" not in reg.tool_names

    def test_register_simple(self) -> None:
        reg = ToolRegistry()

        async def handler(args: Dict[str, Any]) -> str:
            return "ok"

        reg.register_simple("my_tool", "Does things", handler)
        assert "my_tool" in reg.tool_names

    @pytest.mark.asyncio
    async def test_execute(self) -> None:
        reg = ToolRegistry()

        async def handler(args: Dict[str, Any]) -> str:
            return f"result: {args.get('q', 'none')}"

        reg.register_simple("search", "Search", handler)
        tc = ToolCall(id="tc1", name="search", arguments={"q": "test"})
        result = await reg.execute(tc)
        assert not result.is_error
        assert "result: test" in result.content

    @pytest.mark.asyncio
    async def test_execute_missing_tool(self) -> None:
        reg = ToolRegistry()
        tc = ToolCall(id="tc1", name="nonexistent", arguments={})
        result = await reg.execute(tc)
        assert result.is_error
        assert "no encontrada" in result.content

    @pytest.mark.asyncio
    async def test_execute_with_error(self) -> None:
        reg = ToolRegistry()

        async def handler(args: Dict[str, Any]) -> str:
            raise RuntimeError("Tool broken")

        reg.register_simple("broken", "Broken tool", handler)
        tc = ToolCall(id="tc1", name="broken", arguments={})
        result = await reg.execute(tc)
        assert result.is_error
        assert "Tool broken" in result.content

    @pytest.mark.asyncio
    async def test_execute_timeout(self) -> None:
        import asyncio
        reg = ToolRegistry()

        async def handler(args: Dict[str, Any]) -> str:
            await asyncio.sleep(10)
            return "slow"

        reg.register_simple("slow", "Slow tool", handler, timeout_secs=0.1)
        tc = ToolCall(id="tc1", name="slow", arguments={})
        result = await reg.execute(tc)
        assert result.is_error
        assert "timeout" in result.content.lower()

    @pytest.mark.asyncio
    async def test_loop_detection(self) -> None:
        reg = ToolRegistry()

        async def handler(args: Dict[str, Any]) -> str:
            return "ok"

        reg.register_simple("loopy", "Loopy", handler)

        # Llamar muchas veces
        for _ in range(100):
            tc = ToolCall(id="tc", name="loopy", arguments={})
            result = await reg.execute(tc)

        # Última llamada debería ser bloqueada
        assert result.is_error
        assert "loop" in result.content.lower()

    @pytest.mark.asyncio
    async def test_execute_batch(self) -> None:
        reg = ToolRegistry()

        async def handler(args: Dict[str, Any]) -> str:
            return "ok"

        reg.register_simple("tool1", "Tool 1", handler)
        reg.register_simple("tool2", "Tool 2", handler)

        calls = [
            ToolCall(id="tc1", name="tool1", arguments={}),
            ToolCall(id="tc2", name="tool2", arguments={}),
        ]
        results = await reg.execute_batch(calls)
        assert len(results) == 2
        assert all(not r.is_error for r in results)

    def test_to_provider_format(self) -> None:
        reg = ToolRegistry()
        reg.register(ToolDefinition(
            id="t1", name="t1", description="Tool 1",
        ))
        reg.register(ToolDefinition(
            id="t2", name="t2", description="Tool 2",
        ))
        defs = reg.to_provider_format()
        assert len(defs) == 2

    def test_filter_by_profile(self) -> None:
        reg = ToolRegistry()
        reg.register(ToolDefinition(
            id="t1", name="t1", description="Tool 1",
            profiles=[ToolProfile.CODING],
        ))
        reg.register(ToolDefinition(
            id="t2", name="t2", description="Tool 2",
            profiles=[ToolProfile.FULL],
        ))
        coding = reg.list_tools(profile=ToolProfile.CODING)
        assert len(coding) == 1
        assert coding[0].name == "t1"

    def test_filter_by_section(self) -> None:
        reg = ToolRegistry()
        reg.register(ToolDefinition(
            id="t1", name="t1", description="Tool 1",
            section=ToolSection.WEB,
        ))
        reg.register(ToolDefinition(
            id="t2", name="t2", description="Tool 2",
            section=ToolSection.FS,
        ))
        web = reg.list_tools(section=ToolSection.WEB)
        assert len(web) == 1
