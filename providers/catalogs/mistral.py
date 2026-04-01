"""Catálogo enriquecido de modelos Mistral."""

from __future__ import annotations

from shared.types import ModelCompatConfig, ModelCostConfig, ModelDefinition

MISTRAL_CATALOG = [
    ModelDefinition(
        id="mistral-large-latest",
        name="Mistral Large",
        api="openai-completions",
        provider="mistral",
        max_input_tokens=262_000,
        max_output_tokens=32_000,
        cost=ModelCostConfig(input=2.0, output=6.0),
        compat=ModelCompatConfig(
            requires_mistral_tool_ids=True,
        ),
    ),
]
