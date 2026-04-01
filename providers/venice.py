"""Provider Venice (OpenAI-compatible)."""

from __future__ import annotations

from typing import List, Optional

from providers.catalogs.venice import VENICE_CATALOG
from providers.openai import OpenAIProvider
from shared.types import ModelDefinition

VENICE_MODELS = VENICE_CATALOG


class VeniceProvider(OpenAIProvider):
    """Provider para Venice (API compatible con OpenAI)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        models: Optional[List[ModelDefinition]] = None,
    ):
        super().__init__(
            api_key=api_key,
            base_url="https://api.venice.ai/api/v1",
            models=models or VENICE_MODELS,
            provider_id="venice",
        )
