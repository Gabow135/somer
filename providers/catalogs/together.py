"""Catálogo enriquecido de modelos Together."""

from __future__ import annotations

from shared.types import ModelCostConfig, ModelDefinition

TOGETHER_CATALOG = [
    ModelDefinition(
        id="meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
        name="Llama 3.1 70B Instruct Turbo",
        api="openai-completions",
        provider="together",
        max_input_tokens=131_000,
        max_output_tokens=4_000,
        cost=ModelCostConfig(input=0.88, output=0.88),
    ),
    ModelDefinition(
        id="meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
        name="Llama 3.1 8B Instruct Turbo",
        api="openai-completions",
        provider="together",
        max_input_tokens=131_000,
        max_output_tokens=4_000,
        cost=ModelCostConfig(input=0.18, output=0.18),
    ),
]
