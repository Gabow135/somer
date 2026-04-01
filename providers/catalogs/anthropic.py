"""Catálogo enriquecido de modelos Anthropic."""

from __future__ import annotations

from shared.types import ModelCompatConfig, ModelCostConfig, ModelDefinition

ANTHROPIC_CATALOG = [
    ModelDefinition(
        id="claude-opus-4-6",
        name="Claude Opus 4.6",
        api="anthropic-messages",
        provider="anthropic",
        max_input_tokens=200_000,
        max_output_tokens=32_000,
        supports_vision=True,
        reasoning=True,
        input_modalities=["text", "image"],
        cost=ModelCostConfig(input=15.0, output=75.0, cache_read=1.5, cache_write=18.75),
        compat=ModelCompatConfig(
            thinking_format="anthropic",
            supports_reasoning_effort=True,
        ),
    ),
    ModelDefinition(
        id="claude-sonnet-4-5-20250929",
        name="Claude Sonnet 4.5",
        api="anthropic-messages",
        provider="anthropic",
        max_input_tokens=200_000,
        max_output_tokens=8_192,
        supports_vision=True,
        reasoning=True,
        input_modalities=["text", "image"],
        cost=ModelCostConfig(input=3.0, output=15.0, cache_read=0.3, cache_write=3.75),
        compat=ModelCompatConfig(
            thinking_format="anthropic",
            supports_reasoning_effort=True,
        ),
    ),
    ModelDefinition(
        id="claude-haiku-4-5-20251001",
        name="Claude Haiku 4.5",
        api="anthropic-messages",
        provider="anthropic",
        max_input_tokens=200_000,
        max_output_tokens=8_192,
        supports_vision=True,
        input_modalities=["text", "image"],
        cost=ModelCostConfig(input=0.80, output=4.0, cache_read=0.08, cache_write=1.0),
    ),
]
