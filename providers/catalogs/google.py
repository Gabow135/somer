"""Catálogo enriquecido de modelos Google."""

from __future__ import annotations

from shared.types import ModelCompatConfig, ModelCostConfig, ModelDefinition

GOOGLE_CATALOG = [
    ModelDefinition(
        id="gemini-2.0-flash",
        name="Gemini 2.0 Flash",
        api="google-generative-ai",
        provider="google",
        max_input_tokens=1_000_000,
        max_output_tokens=8_192,
        supports_vision=True,
        input_modalities=["text", "image", "video", "audio"],
        cost=ModelCostConfig(input=0.10, output=0.40, cache_read=0.025, cache_write=0.10),
    ),
    ModelDefinition(
        id="gemini-2.0-pro",
        name="Gemini 2.0 Pro",
        api="google-generative-ai",
        provider="google",
        max_input_tokens=1_000_000,
        max_output_tokens=8_192,
        supports_vision=True,
        input_modalities=["text", "image", "video", "audio"],
        cost=ModelCostConfig(input=1.25, output=10.0, cache_read=0.315, cache_write=1.25),
    ),
]
