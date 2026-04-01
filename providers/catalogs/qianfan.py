"""Catálogo enriquecido de modelos Qianfan (Baidu)."""

from __future__ import annotations

from shared.types import ModelCostConfig, ModelDefinition

QIANFAN_CATALOG = [
    ModelDefinition(
        id="deepseek-v3.2",
        name="DeepSeek V3.2",
        api="openai-completions",
        provider="qianfan",
        max_input_tokens=98_000,
        max_output_tokens=8_000,
        cost=ModelCostConfig(input=0.27, output=1.10),
    ),
    ModelDefinition(
        id="ernie-5.0-thinking-preview",
        name="ERNIE 5.0 Thinking Preview",
        api="openai-completions",
        provider="qianfan",
        max_input_tokens=119_000,
        max_output_tokens=8_000,
        reasoning=True,
        cost=ModelCostConfig(input=1.0, output=4.0),
    ),
]
