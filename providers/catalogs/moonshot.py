"""Catálogo enriquecido de modelos Moonshot."""

from __future__ import annotations

from shared.types import ModelCostConfig, ModelDefinition

MOONSHOT_CATALOG = [
    ModelDefinition(
        id="kimi-k2.5",
        name="Kimi K2.5",
        api="openai-completions",
        provider="moonshot",
        max_input_tokens=256_000,
        max_output_tokens=16_000,
        cost=ModelCostConfig(input=1.0, output=4.0),
    ),
]
