"""Provider OpenRouter (OpenAI-compatible)."""

from __future__ import annotations

from typing import List, Optional

from providers.catalogs.openrouter import OPENROUTER_CATALOG
from providers.openai import OpenAIProvider
from shared.types import ModelDefinition

OPENROUTER_MODELS = OPENROUTER_CATALOG


class OpenRouterProvider(OpenAIProvider):
    """Provider para OpenRouter (API compatible con OpenAI)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        models: Optional[List[ModelDefinition]] = None,
    ):
        super().__init__(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
            models=models or OPENROUTER_MODELS,
            provider_id="openrouter",
        )
