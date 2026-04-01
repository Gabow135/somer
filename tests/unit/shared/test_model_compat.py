"""Tests para ModelCostConfig, ModelCompatConfig y ModelDefinition mejorado."""

from __future__ import annotations

import pytest

from shared.types import ModelCompatConfig, ModelCostConfig, ModelDefinition


class TestModelCostConfig:
    """Tests de ModelCostConfig."""

    def test_defaults(self) -> None:
        cost = ModelCostConfig()
        assert cost.input == 0.0
        assert cost.output == 0.0
        assert cost.cache_read == 0.0
        assert cost.cache_write == 0.0

    def test_custom_values(self) -> None:
        cost = ModelCostConfig(input=3.0, output=15.0, cache_read=0.3, cache_write=3.75)
        assert cost.input == 3.0
        assert cost.output == 15.0
        assert cost.cache_read == 0.3
        assert cost.cache_write == 3.75

    def test_serialization(self) -> None:
        cost = ModelCostConfig(input=1.5, output=7.5)
        data = cost.model_dump()
        assert data["input"] == 1.5
        assert data["output"] == 7.5
        assert data["cache_read"] == 0.0

    def test_from_dict(self) -> None:
        cost = ModelCostConfig(**{"input": 2.0, "output": 10.0})
        assert cost.input == 2.0


class TestModelCompatConfig:
    """Tests de ModelCompatConfig."""

    def test_defaults(self) -> None:
        compat = ModelCompatConfig()
        assert compat.supports_developer_role is False
        assert compat.requires_tool_result_name is False
        assert compat.supports_usage_in_streaming is True
        assert compat.supports_strict_mode is True
        assert compat.supports_tools is True
        assert compat.max_tokens_field is None
        assert compat.thinking_format is None
        assert compat.tool_schema_profile is None
        assert compat.native_web_search_tool is False
        assert compat.requires_mistral_tool_ids is False

    def test_anthropic_compat(self) -> None:
        compat = ModelCompatConfig(
            thinking_format="anthropic",
            supports_reasoning_effort=True,
        )
        assert compat.thinking_format == "anthropic"
        assert compat.supports_reasoning_effort is True

    def test_openai_compat(self) -> None:
        compat = ModelCompatConfig(
            supports_developer_role=True,
            max_tokens_field="max_completion_tokens",
        )
        assert compat.supports_developer_role is True
        assert compat.max_tokens_field == "max_completion_tokens"

    def test_mistral_compat(self) -> None:
        compat = ModelCompatConfig(requires_mistral_tool_ids=True)
        assert compat.requires_mistral_tool_ids is True

    def test_xai_compat(self) -> None:
        compat = ModelCompatConfig(
            tool_schema_profile="xai",
            native_web_search_tool=True,
        )
        assert compat.tool_schema_profile == "xai"
        assert compat.native_web_search_tool is True

    def test_serialization(self) -> None:
        compat = ModelCompatConfig(supports_developer_role=True)
        data = compat.model_dump()
        assert data["supports_developer_role"] is True
        assert data["requires_mistral_tool_ids"] is False


class TestModelDefinitionEnriched:
    """Tests de ModelDefinition con campos enriquecidos."""

    def test_new_fields_defaults(self) -> None:
        model = ModelDefinition(
            id="test", name="Test", api="openai-completions", provider="test"
        )
        assert model.reasoning is False
        assert model.input_modalities == ["text"]
        assert model.cost.input == 0.0
        assert model.cost.output == 0.0
        assert model.compat.supports_developer_role is False

    def test_new_fields_custom(self) -> None:
        model = ModelDefinition(
            id="test", name="Test", api="openai-completions", provider="test",
            reasoning=True,
            input_modalities=["text", "image"],
            cost=ModelCostConfig(input=3.0, output=15.0),
            compat=ModelCompatConfig(supports_developer_role=True),
        )
        assert model.reasoning is True
        assert model.input_modalities == ["text", "image"]
        assert model.cost.input == 3.0
        assert model.compat.supports_developer_role is True

    def test_legacy_cost_migration(self) -> None:
        """cost_per_input_token y cost_per_output_token migran a cost."""
        model = ModelDefinition(
            id="test", name="Test", api="openai-completions", provider="test",
            cost_per_input_token=1.5,
            cost_per_output_token=7.5,
        )
        assert model.cost.input == 1.5
        assert model.cost.output == 7.5

    def test_legacy_properties(self) -> None:
        """Properties de retrocompatibilidad."""
        model = ModelDefinition(
            id="test", name="Test", api="openai-completions", provider="test",
            cost=ModelCostConfig(input=2.0, output=10.0),
        )
        assert model.cost_per_input_token == 2.0
        assert model.cost_per_output_token == 10.0

    def test_cost_field_takes_priority(self) -> None:
        """Si se pasa cost directamente, no se migran legacy fields."""
        model = ModelDefinition(
            id="test", name="Test", api="openai-completions", provider="test",
            cost=ModelCostConfig(input=5.0, output=25.0),
        )
        assert model.cost.input == 5.0
        assert model.cost.output == 25.0

    def test_serialization_roundtrip(self) -> None:
        """Serialización y deserialización."""
        model = ModelDefinition(
            id="test", name="Test", api="openai-completions", provider="test",
            reasoning=True,
            cost=ModelCostConfig(input=3.0, output=15.0, cache_read=0.3),
            compat=ModelCompatConfig(thinking_format="anthropic"),
        )
        data = model.model_dump()
        restored = ModelDefinition(**data)
        assert restored.reasoning is True
        assert restored.cost.input == 3.0
        assert restored.cost.cache_read == 0.3
        assert restored.compat.thinking_format == "anthropic"

    def test_backward_compat_existing_fields(self) -> None:
        """Los campos existentes siguen funcionando."""
        model = ModelDefinition(
            id="m1", name="Model 1", api="anthropic-messages",
            provider="anthropic",
            max_input_tokens=200_000,
            max_output_tokens=32_000,
            supports_streaming=True,
            supports_tools=True,
            supports_vision=True,
        )
        assert model.max_input_tokens == 200_000
        assert model.supports_vision is True
