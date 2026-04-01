"""Catálogo enriquecido de modelos xAI."""

from __future__ import annotations

from shared.types import ModelCompatConfig, ModelCostConfig, ModelDefinition

XAI_CATALOG = [
    ModelDefinition(
        id="grok-4",
        name="Grok 4",
        api="openai-completions",
        provider="xai",
        max_input_tokens=131_000,
        max_output_tokens=32_000,
        reasoning=True,
        cost=ModelCostConfig(input=3.0, output=15.0),
        compat=ModelCompatConfig(
            tool_schema_profile="xai",
            native_web_search_tool=True,
        ),
    ),
    ModelDefinition(
        id="grok-4-fast-reasoning",
        name="Grok 4 Fast Reasoning",
        api="openai-completions",
        provider="xai",
        max_input_tokens=131_000,
        max_output_tokens=32_000,
        reasoning=True,
        cost=ModelCostConfig(input=3.0, output=15.0),
        compat=ModelCompatConfig(
            tool_schema_profile="xai",
            native_web_search_tool=True,
        ),
    ),
]
