"""Provider SGLang (OpenAI-compatible, local inference)."""

from __future__ import annotations

from typing import List, Optional

from providers.openai import OpenAIProvider
from shared.types import ModelDefinition

# Modelos vacíos por defecto — se descubren en tiempo de ejecución.
SGLANG_MODELS: List[ModelDefinition] = []


class SGLangProvider(OpenAIProvider):
    """Provider para SGLang (API compatible con OpenAI, inferencia local)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        models: Optional[List[ModelDefinition]] = None,
    ):
        super().__init__(
            api_key=api_key or "EMPTY",
            base_url=base_url or "http://localhost:30000/v1",
            models=models or SGLANG_MODELS,
            provider_id="sglang",
        )
