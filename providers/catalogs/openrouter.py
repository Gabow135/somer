"""Catálogo enriquecido de modelos OpenRouter."""

from __future__ import annotations

from shared.types import ModelCostConfig, ModelDefinition

OPENROUTER_CATALOG = [
    ModelDefinition(
        id="auto",
        name="OpenRouter Auto",
        api="openai-completions",
        provider="openrouter",
        max_input_tokens=200_000,
        max_output_tokens=16_000,
        cost=ModelCostConfig(input=0.0, output=0.0),
    ),
    ModelDefinition(
        id="openrouter/hunter-alpha",
        name="Hunter Alpha",
        api="openai-completions",
        provider="openrouter",
        max_input_tokens=1_000_000,
        max_output_tokens=32_000,
        cost=ModelCostConfig(input=2.0, output=6.0),
    ),
    ModelDefinition(
        id="openrouter/healer-alpha",
        name="Healer Alpha",
        api="openai-completions",
        provider="openrouter",
        max_input_tokens=262_000,
        max_output_tokens=32_000,
        cost=ModelCostConfig(input=1.0, output=3.0),
    ),
]
