"""Catálogo enriquecido de modelos MiniMax."""

from __future__ import annotations

from shared.types import ModelCostConfig, ModelDefinition

MINIMAX_CATALOG = [
    ModelDefinition(
        id="MiniMax-M2.7",
        name="MiniMax M2.7",
        api="openai-completions",
        provider="minimax",
        max_input_tokens=200_000,
        max_output_tokens=16_000,
        cost=ModelCostConfig(input=1.0, output=5.0),
    ),
    ModelDefinition(
        id="MiniMax-M2.5",
        name="MiniMax M2.5",
        api="openai-completions",
        provider="minimax",
        max_input_tokens=200_000,
        max_output_tokens=16_000,
        cost=ModelCostConfig(input=0.50, output=2.50),
    ),
]
