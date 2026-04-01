"""Provider vLLM (OpenAI-compatible, local inference)."""

from __future__ import annotations

from typing import List, Optional

from providers.openai import OpenAIProvider
from shared.types import ModelDefinition

# Modelos vacíos por defecto — se descubren en tiempo de ejecución.
VLLM_MODELS: List[ModelDefinition] = []


class VLLMProvider(OpenAIProvider):
    """Provider para vLLM (API compatible con OpenAI, inferencia local)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        models: Optional[List[ModelDefinition]] = None,
    ):
        super().__init__(
            api_key=api_key or "EMPTY",
            base_url=base_url or "http://localhost:8000/v1",
            models=models or VLLM_MODELS,
            provider_id="vllm",
        )
