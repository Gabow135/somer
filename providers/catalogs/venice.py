"""Catálogo enriquecido de modelos Venice."""

from __future__ import annotations

from shared.types import ModelCostConfig, ModelDefinition

VENICE_CATALOG = [
    ModelDefinition(
        id="venice-auto",
        name="Venice Auto",
        api="openai-completions",
        provider="venice",
        max_input_tokens=131_000,
        max_output_tokens=8_000,
        cost=ModelCostConfig(input=0.0, output=0.0),
    ),
]
