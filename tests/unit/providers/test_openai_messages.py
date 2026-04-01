"""Tests para la conversión de mensajes en providers/openai.py."""

from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest

from providers.openai import OpenAIProvider


class TestConvertMessages:
    """Tests para OpenAIProvider._convert_messages()."""

    def test_simple_messages_passthrough(self) -> None:
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello"},
        ]
        result = OpenAIProvider._convert_messages(messages)
        assert result == messages

    def test_assistant_without_tool_calls(self) -> None:
        messages = [{"role": "assistant", "content": "Hi there"}]
        result = OpenAIProvider._convert_messages(messages)
        assert result == [{"role": "assistant", "content": "Hi there"}]

    def test_assistant_with_internal_tool_calls(self) -> None:
        """Verifica conversión de formato interno → OpenAI."""
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
        result = OpenAIProvider._convert_messages(messages)
        assert len(result) == 1
        msg = result[0]
        assert msg["role"] == "assistant"
        assert msg["content"] == "Let me check..."
        tc = msg["tool_calls"][0]
        assert tc["id"] == "tc_123"
        assert tc["type"] == "function"
        assert tc["function"]["name"] == "http_request"
        # arguments debe ser string JSON
        args = json.loads(tc["function"]["arguments"])
        assert args["method"] == "GET"
        assert args["url"] == "https://api.notion.com"

    def test_assistant_tool_calls_already_openai_format(self) -> None:
        """No re-convierte si ya tiene type=function."""
        messages = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "tc_1",
                        "type": "function",
                        "function": {
                            "name": "foo",
                            "arguments": '{"bar": 1}',
                        },
                    }
                ],
            }
        ]
        result = OpenAIProvider._convert_messages(messages)
        tc = result[0]["tool_calls"][0]
        assert tc["type"] == "function"
        assert tc["function"]["name"] == "foo"

    def test_tool_result_message(self) -> None:
        messages = [
            {
                "role": "assistant",
                "content": "Checking...",
                "tool_calls": [
                    {"id": "tc_123", "name": "search", "arguments": {"q": "test"}},
                ],
            },
            {"role": "tool", "content": "Result data", "tool_call_id": "tc_123"},
        ]
        result = OpenAIProvider._convert_messages(messages)
        assert result[1]["role"] == "tool"
        assert result[1]["content"] == "Result data"
        assert result[1]["tool_call_id"] == "tc_123"

    def test_orphaned_tool_message_discarded(self) -> None:
        """Mensajes tool sin tool_calls previo válido se descartan."""
        messages = [
            {"role": "tool", "content": "Orphan", "tool_call_id": "tc_999"},
        ]
        result = OpenAIProvider._convert_messages(messages)
        assert len(result) == 0

    def test_full_tool_use_conversation(self) -> None:
        """Tests complete multi-turn tool use flow."""
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Search Notion"},
            {
                "role": "assistant",
                "content": "Searching...",
                "tool_calls": [
                    {"id": "tc_1", "name": "http_request", "arguments": {"method": "POST", "url": "https://api.notion.com/v1/search"}},
                ],
            },
            {"role": "tool", "content": '{"results": []}', "tool_call_id": "tc_1"},
            {"role": "assistant", "content": "No results found."},
        ]
        result = OpenAIProvider._convert_messages(messages)
        assert len(result) == 5
        # System and user pass through
        assert result[0]["role"] == "system"
        assert result[1]["role"] == "user"
        # Assistant with tool_calls converted
        assert result[2]["tool_calls"][0]["type"] == "function"
        assert result[2]["tool_calls"][0]["function"]["name"] == "http_request"
        # Tool result
        assert result[3]["role"] == "tool"
        assert result[3]["tool_call_id"] == "tc_1"
        # Final assistant
        assert result[4]["content"] == "No results found."

    def test_multiple_tool_calls(self) -> None:
        messages = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "tc_1", "name": "a", "arguments": {"x": 1}},
                    {"id": "tc_2", "name": "b", "arguments": {"y": 2}},
                ],
            }
        ]
        result = OpenAIProvider._convert_messages(messages)
        tcs = result[0]["tool_calls"]
        assert len(tcs) == 2
        assert all(tc["type"] == "function" for tc in tcs)
        assert tcs[0]["function"]["name"] == "a"
        assert tcs[1]["function"]["name"] == "b"

    def test_empty_content_becomes_none(self) -> None:
        """OpenAI requiere content=null cuando hay tool_calls sin texto."""
        messages = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "tc_1", "name": "foo", "arguments": {}},
                ],
            }
        ]
        result = OpenAIProvider._convert_messages(messages)
        assert result[0]["content"] is None
