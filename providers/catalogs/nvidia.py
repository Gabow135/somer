"""Catálogo enriquecido de modelos NVIDIA."""

from __future__ import annotations

from shared.types import ModelCostConfig, ModelDefinition

NVIDIA_CATALOG = [
    ModelDefinition(
        id="nvidia/llama-3.1-nemotron-70b-instruct",
        name="Llama 3.1 Nemotron 70B Instruct",
        api="openai-completions",
        provider="nvidia",
        max_input_tokens=131_000,
        max_output_tokens=4_000,
        cost=ModelCostConfig(input=0.0, output=0.0),
    ),
    ModelDefinition(
        id="meta/llama-3.3-70b-instruct",
        name="Llama 3.3 70B Instruct",
        api="openai-completions",
        provider="nvidia",
        max_input_tokens=131_000,
        max_output_tokens=4_000,
        cost=ModelCostConfig(input=0.0, output=0.0),
    ),
]
