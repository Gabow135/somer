"""Catálogo enriquecido de modelos Groq."""

from __future__ import annotations

from shared.types import ModelCostConfig, ModelDefinition

GROQ_CATALOG = [
    ModelDefinition(
        id="llama-3.3-70b-versatile",
        name="Llama 3.3 70B Versatile",
        api="openai-completions",
        provider="groq",
        max_input_tokens=131_000,
        max_output_tokens=32_000,
        cost=ModelCostConfig(input=0.59, output=0.79),
    ),
    ModelDefinition(
        id="mixtral-8x7b-32768",
        name="Mixtral 8x7B",
        api="openai-completions",
        provider="groq",
        max_input_tokens=32_000,
        max_output_tokens=32_000,
        cost=ModelCostConfig(input=0.24, output=0.24),
    ),
]
