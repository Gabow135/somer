"""Catálogo enriquecido de modelos Volcengine."""

from __future__ import annotations

from shared.types import ModelCostConfig, ModelDefinition

VOLCENGINE_CATALOG = [
    ModelDefinition(
        id="ark-code-latest",
        name="Ark Code",
        api="openai-completions",
        provider="volcengine",
        max_input_tokens=32_000,
        max_output_tokens=4_000,
        cost=ModelCostConfig(input=0.0, output=0.0),
    ),
]
