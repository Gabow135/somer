"""Tests para la conversión de tools y mensajes en providers/anthropic.py."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from providers.anthropic import AnthropicProvider


class TestConvertTools:
    """Tests para AnthropicProvider._convert_tools()."""

    def test_openai_format_to_anthropic(self) -> None:
        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": "http_request",
                    "description": "Make HTTP request",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string"},
                        },
                    },
                },
            },
        ]
        result = AnthropicProvider._convert_tools(openai_tools)
        assert len(result) == 1
        assert result[0]["name"] == "http_request"
        assert result[0]["description"] == "Make HTTP request"
        assert "input_schema" in result[0]
        assert result[0]["input_schema"]["properties"]["url"]["type"] == "string"

    def test_already_anthropic_format(self) -> None:
        tools = [
            {
                "name": "my_tool",
                "description": "A tool",
                "input_schema": {"type": "object", "properties": {}},
            },
        ]
        result = AnthropicProvider._convert_tools(tools)
        assert len(result) == 1
        assert result[0]["name"] == "my_tool"
        assert result[0]["input_schema"] == {"type": "object", "properties": {}}

    def test_simple_name_format(self) -> None:
        tools = [
            {
                "name": "simple",
                "description": "Simple tool",
            },
        ]
        result = AnthropicProvider._convert_tools(tools)
        assert len(result) == 1
        assert result[0]["name"] == "simple"
        assert "input_schema" in result[0]

    def test_empty_tools_list(self) -> None:
        result = AnthropicProvider._convert_tools([])
        assert result == []

    def test_multiple_tools(self) -> None:
        tools = [
            {"type": "function", "function": {"name": "a", "description": "Tool A", "parameters": {}}},
            {"type": "function", "function": {"name": "b", "description": "Tool B", "parameters": {}}},
        ]
        result = AnthropicProvider._convert_tools(tools)
        assert len(result) == 2
        assert result[0]["name"] == "a"
        assert result[1]["name"] == "b"


class TestConvertMessages:
    """Tests para AnthropicProvider._convert_messages()."""

    def test_simple_user_message(self) -> None:
        messages = [{"role": "user", "content": "Hello"}]
        result = AnthropicProvider._convert_messages(messages)
        assert result == [{"role": "user", "content": "Hello"}]

    def test_system_message_preserved(self) -> None:
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hi"},
        ]
        result = AnthropicProvider._convert_messages(messages)
        assert result[0]["role"] == "system"
        assert result[1]["role"] == "user"

    def test_assistant_without_tool_calls(self) -> None:
        messages = [{"role": "assistant", "content": "I'll help you."}]
        result = AnthropicProvider._convert_messages(messages)
        assert result[0] == {"role": "assistant", "content": "I'll help you."}

    def test_assistant_with_tool_calls(self) -> None:
        messages = [
            {
                "role": "assistant",
                "content": "Let me check...",
                "tool_calls": [
                    {
                        "id": "tc_123",
                        "name": "http_request",
                        "arguments": {"method": "GET", "url": "https://api.notion.com"},
                    }
                ],
            }
        ]
        result = AnthropicProvider._convert_messages(messages)
        assert result[0]["role"] == "assistant"
        content = result[0]["content"]
        assert isinstance(content, list)
        assert len(content) == 2
        assert content[0] == {"type": "text", "text": "Let me check..."}
        assert content[1]["type"] == "tool_use"
        assert content[1]["id"] == "tc_123"
        assert content[1]["name"] == "http_request"
        assert content[1]["input"]["method"] == "GET"

    def test_assistant_with_tool_calls_no_text(self) -> None:
        messages = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "tc_1", "name": "tool_a", "arguments": {}},
                ],
            }
        ]
        result = AnthropicProvider._convert_messages(messages)
        content = result[0]["content"]
        # No text block when content is empty
        assert len(content) == 1
        assert content[0]["type"] == "tool_use"

    def test_tool_results_converted(self) -> None:
        messages = [
            {"role": "tool", "content": "Result data", "tool_call_id": "tc_123"},
        ]
        result = AnthropicProvider._convert_messages(messages)
        assert result[0]["role"] == "user"
        content = result[0]["content"]
        assert isinstance(content, list)
        assert len(content) == 1
        assert content[0]["type"] == "tool_result"
        assert content[0]["tool_use_id"] == "tc_123"
        assert content[0]["content"] == "Result data"

    def test_consecutive_tool_results_grouped(self) -> None:
        messages = [
            {"role": "tool", "content": "Result 1", "tool_call_id": "tc_1"},
            {"role": "tool", "content": "Result 2", "tool_call_id": "tc_2"},
        ]
        result = AnthropicProvider._convert_messages(messages)
        # Should be grouped into one user message
        assert len(result) == 1
        assert result[0]["role"] == "user"
        content = result[0]["content"]
        assert len(content) == 2
        assert content[0]["tool_use_id"] == "tc_1"
        assert content[1]["tool_use_id"] == "tc_2"

    def test_full_tool_use_conversation(self) -> None:
        """Tests complete multi-turn tool use flow."""
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Check my tasks"},
            {
                "role": "assistant",
                "content": "I'll check Notion...",
                "tool_calls": [
                    {"id": "tc_1", "name": "http_request", "arguments": {"method": "GET", "url": "https://api.notion.com/v1/search"}},
                ],
            },
            {"role": "tool", "content": '{"results": []}', "tool_call_id": "tc_1"},
            {"role": "assistant", "content": "No tasks found."},
        ]
        result = AnthropicProvider._convert_messages(messages)
        assert len(result) == 5
        assert result[0]["role"] == "system"
        assert result[1]["role"] == "user"
        assert result[2]["role"] == "assistant"
        assert isinstance(result[2]["content"], list)  # tool_use blocks
        assert result[3]["role"] == "user"  # tool_result wrapped in user
        assert result[4]["role"] == "assistant"
        assert result[4]["content"] == "No tasks found."
