"""Catálogo enriquecido de modelos Bedrock."""

from __future__ import annotations

from shared.types import ModelCompatConfig, ModelCostConfig, ModelDefinition

BEDROCK_CATALOG = [
    ModelDefinition(
        id="anthropic.claude-sonnet-4-5-20250929-v1:0",
        name="Claude Sonnet 4.5 (Bedrock)",
        api="bedrock-converse-stream",
        provider="bedrock",
        max_input_tokens=200_000,
        max_output_tokens=8_192,
        supports_vision=True,
        input_modalities=["text", "image"],
        cost=ModelCostConfig(input=3.0, output=15.0, cache_read=0.3, cache_write=3.75),
        compat=ModelCompatConfig(thinking_format="anthropic"),
    ),
]
