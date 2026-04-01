"""Provider Perplexity (OpenAI-compatible)."""

from __future__ import annotations

from typing import List, Optional

from providers.catalogs.perplexity import PERPLEXITY_CATALOG
from providers.openai import OpenAIProvider
from shared.types import ModelDefinition

PERPLEXITY_MODELS = PERPLEXITY_CATALOG


class PerplexityProvider(OpenAIProvider):
    """Provider para Perplexity (API compatible con OpenAI)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        models: Optional[List[ModelDefinition]] = None,
    ):
        super().__init__(
            api_key=api_key,
            base_url="https://api.perplexity.ai",
            models=models or PERPLEXITY_MODELS,
            provider_id="perplexity",
        )
