"""Catálogo enriquecido de modelos Perplexity."""

from __future__ import annotations

from shared.types import ModelCompatConfig, ModelCostConfig, ModelDefinition

PERPLEXITY_CATALOG = [
    ModelDefinition(
        id="sonar-pro",
        name="Sonar Pro",
        api="openai-completions",
        provider="perplexity",
        max_input_tokens=200_000,
        max_output_tokens=8_000,
        cost=ModelCostConfig(input=3.0, output=15.0),
        compat=ModelCompatConfig(native_web_search_tool=True),
    ),
    ModelDefinition(
        id="sonar",
        name="Sonar",
        api="openai-completions",
        provider="perplexity",
        max_input_tokens=200_000,
        max_output_tokens=8_000,
        cost=ModelCostConfig(input=1.0, output=1.0),
        compat=ModelCompatConfig(native_web_search_tool=True),
    ),
]
