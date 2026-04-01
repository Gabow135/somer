"""Catálogo enriquecido de modelos HuggingFace."""

from __future__ import annotations

from shared.types import ModelCostConfig, ModelDefinition

HUGGINGFACE_CATALOG = [
    ModelDefinition(
        id="meta-llama/Meta-Llama-3.1-8B-Instruct",
        name="Llama 3.1 8B Instruct",
        api="openai-completions",
        provider="huggingface",
        max_input_tokens=131_000,
        max_output_tokens=4_000,
        cost=ModelCostConfig(input=0.0, output=0.0),
    ),
]
