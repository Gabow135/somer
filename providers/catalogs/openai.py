"""Catálogo enriquecido de modelos OpenAI."""

from __future__ import annotations

from shared.types import ModelCompatConfig, ModelCostConfig, ModelDefinition

OPENAI_CATALOG = [
    ModelDefinition(
        id="gpt-4o",
        name="GPT-4o",
        api="openai-completions",
        provider="openai",
        max_input_tokens=128_000,
        max_output_tokens=4_096,
        supports_vision=True,
        input_modalities=["text", "image"],
        cost=ModelCostConfig(input=2.50, output=10.0, cache_read=1.25, cache_write=2.50),
        compat=ModelCompatConfig(supports_developer_role=True),
    ),
    ModelDefinition(
        id="gpt-4o-mini",
        name="GPT-4o mini",
        api="openai-completions",
        provider="openai",
        max_input_tokens=128_000,
        max_output_tokens=16_384,
        input_modalities=["text", "image"],
        cost=ModelCostConfig(input=0.15, output=0.60, cache_read=0.075, cache_write=0.15),
        compat=ModelCompatConfig(supports_developer_role=True),
    ),
    ModelDefinition(
        id="o3-mini",
        name="o3-mini",
        api="openai-completions",
        provider="openai",
        max_input_tokens=128_000,
        max_output_tokens=65_536,
        reasoning=True,
        cost=ModelCostConfig(input=1.10, output=4.40, cache_read=0.55, cache_write=1.10),
        compat=ModelCompatConfig(
            supports_developer_role=True,
            supports_reasoning_effort=True,
            max_tokens_field="max_completion_tokens",
        ),
    ),
    ModelDefinition(
        id="gpt-4-turbo",
        name="GPT-4 Turbo",
        api="openai-completions",
        provider="openai",
        max_input_tokens=128_000,
        max_output_tokens=4_096,
        supports_vision=True,
        input_modalities=["text", "image"],
        cost=ModelCostConfig(input=10.0, output=30.0),
        compat=ModelCompatConfig(supports_developer_role=True),
    ),
]
