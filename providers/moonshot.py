"""Provider Moonshot (OpenAI-compatible)."""

from __future__ import annotations

from typing import List, Optional

from providers.catalogs.moonshot import MOONSHOT_CATALOG
from providers.openai import OpenAIProvider
from shared.types import ModelDefinition

MOONSHOT_MODELS = MOONSHOT_CATALOG


class MoonshotProvider(OpenAIProvider):
    """Provider para Moonshot (API compatible con OpenAI)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        models: Optional[List[ModelDefinition]] = None,
    ):
        super().__init__(
            api_key=api_key,
            base_url="https://api.moonshot.ai/v1",
            models=models or MOONSHOT_MODELS,
            provider_id="moonshot",
        )
