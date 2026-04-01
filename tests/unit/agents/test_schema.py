"""Tests para schemas de output estructurado."""

from __future__ import annotations

import pytest

from agents.schema import (
    OutputSchema,
    clean_for_gemini,
    clean_for_xai,
    json_response_schema,
    text_response_schema,
)


class TestOutputSchema:
    def test_basic(self) -> None:
        schema = OutputSchema(
            schema={"type": "object", "properties": {"x": {"type": "string"}}},
            name="test",
        )
        assert schema.name == "test"

    def test_to_anthropic_format(self) -> None:
        schema = OutputSchema(
            schema={"type": "object"},
            name="test",
            description="Test schema",
        )
        fmt = schema.to_anthropic_format()
        assert fmt["name"] == "test"
        assert "input_schema" in fmt

    def test_to_openai_format(self) -> None:
        schema = OutputSchema(
            schema={"type": "object"},
            name="test",
        )
        fmt = schema.to_openai_format()
        assert fmt["type"] == "json_schema"
        assert fmt["json_schema"]["name"] == "test"
        assert fmt["json_schema"]["strict"] is True

    def test_for_provider_google(self) -> None:
        schema = OutputSchema(
            schema={
                "type": "object",
                "properties": {"x": {"type": "string"}},
                "additionalProperties": False,
            }
        )
        cleaned = schema.for_provider("google")
        assert "additionalProperties" not in cleaned

    def test_for_provider_default(self) -> None:
        raw = {"type": "object", "additionalProperties": False}
        schema = OutputSchema(schema=raw)
        result = schema.for_provider("default")
        assert result is raw


class TestCleanForGemini:
    def test_removes_additional_properties(self) -> None:
        result = clean_for_gemini({
            "type": "object",
            "additionalProperties": False,
        })
        assert "additionalProperties" not in result

    def test_removes_schema(self) -> None:
        result = clean_for_gemini({
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
        })
        assert "$schema" not in result

    def test_converts_const_to_enum(self) -> None:
        result = clean_for_gemini({
            "type": "object",
            "properties": {
                "status": {"const": "active"},
            },
        })
        assert result["properties"]["status"]["enum"] == ["active"]
        assert "const" not in result["properties"]["status"]

    def test_removes_nested_title(self) -> None:
        result = clean_for_gemini({
            "type": "object",
            "title": "Root",
            "properties": {
                "child": {"type": "string", "title": "Child"},
            },
        })
        # Root title preserved
        assert result.get("title") == "Root"
        # Nested title removed
        assert "title" not in result["properties"]["child"]

    def test_recursive_anyof(self) -> None:
        result = clean_for_gemini({
            "anyOf": [
                {"type": "string", "additionalProperties": False},
                {"type": "number"},
            ],
        })
        assert "additionalProperties" not in result["anyOf"][0]


class TestCleanForXai:
    def test_removes_additional_properties(self) -> None:
        result = clean_for_xai({
            "type": "object",
            "additionalProperties": False,
        })
        assert "additionalProperties" not in result

    def test_removes_schema(self) -> None:
        result = clean_for_xai({
            "$schema": "http://json-schema.org/draft-07/schema#",
        })
        assert "$schema" not in result

    def test_recursive(self) -> None:
        result = clean_for_xai({
            "type": "object",
            "properties": {
                "nested": {
                    "type": "object",
                    "additionalProperties": True,
                },
            },
        })
        assert "additionalProperties" not in result["properties"]["nested"]


class TestHelperSchemas:
    def test_text_response(self) -> None:
        schema = text_response_schema()
        assert schema.name == "text_response"
        assert "text" in schema.schema["properties"]

    def test_text_response_max_length(self) -> None:
        schema = text_response_schema(max_length=100)
        assert schema.schema["properties"]["text"]["maxLength"] == 100

    def test_json_response(self) -> None:
        schema = json_response_schema(
            properties={"count": {"type": "integer"}},
            required=["count"],
            name="counter",
        )
        assert schema.name == "counter"
        assert "count" in schema.schema["properties"]
        assert "count" in schema.schema["required"]
