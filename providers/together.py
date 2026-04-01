"""Provider Together (OpenAI-compatible)."""

from __future__ import annotations

from typing import List, Optional

from providers.catalogs.together import TOGETHER_CATALOG
from providers.openai import OpenAIProvider
from shared.types import ModelDefinition

TOGETHER_MODELS = TOGETHER_CATALOG


class TogetherProvider(OpenAIProvider):
    """Provider para Together (API compatible con OpenAI)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        models: Optional[List[ModelDefinition]] = None,
    ):
        super().__init__(
            api_key=api_key,
            base_url="https://api.together.xyz/v1",
            models=models or TOGETHER_MODELS,
            provider_id="together",
        )
