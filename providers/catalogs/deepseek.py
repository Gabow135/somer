"""Catálogo enriquecido de modelos DeepSeek."""

from __future__ import annotations

from shared.types import ModelCompatConfig, ModelCostConfig, ModelDefinition

DEEPSEEK_CATALOG = [
    ModelDefinition(
        id="deepseek-chat",
        name="DeepSeek V3 (Chat)",
        api="openai-completions",
        provider="deepseek",
        max_input_tokens=64_000,
        max_output_tokens=8_192,
        cost=ModelCostConfig(input=0.27, output=1.10, cache_read=0.07, cache_write=0.27),
        metadata={"reasoning": False},
    ),
    ModelDefinition(
        id="deepseek-reasoner",
        name="DeepSeek R1 (Reasoner)",
        api="openai-completions",
        provider="deepseek",
        max_input_tokens=64_000,
        max_output_tokens=8_192,
        reasoning=True,
        cost=ModelCostConfig(input=0.55, output=2.19, cache_read=0.14, cache_write=0.55),
        compat=ModelCompatConfig(
            requires_thinking_as_text=True,
        ),
        metadata={"reasoning": True},
    ),
]
