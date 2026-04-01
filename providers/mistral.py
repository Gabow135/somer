"""Provider Mistral (OpenAI-compatible)."""

from __future__ import annotations

from typing import List, Optional

from providers.catalogs.mistral import MISTRAL_CATALOG
from providers.openai import OpenAIProvider
from shared.types import ModelDefinition

MISTRAL_MODELS = MISTRAL_CATALOG


class MistralProvider(OpenAIProvider):
    """Provider para Mistral (API compatible con OpenAI)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        models: Optional[List[ModelDefinition]] = None,
    ):
        super().__init__(
            api_key=api_key,
            base_url="https://api.mistral.ai/v1",
            models=models or MISTRAL_MODELS,
            provider_id="mistral",
        )
