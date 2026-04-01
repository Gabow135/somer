"""Provider xAI (OpenAI-compatible)."""

from __future__ import annotations

from typing import List, Optional

from providers.catalogs.xai import XAI_CATALOG
from providers.openai import OpenAIProvider
from shared.types import ModelDefinition

XAI_MODELS = XAI_CATALOG


class XAIProvider(OpenAIProvider):
    """Provider para xAI (API compatible con OpenAI)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        models: Optional[List[ModelDefinition]] = None,
    ):
        super().__init__(
            api_key=api_key,
            base_url="https://api.x.ai/v1",
            models=models or XAI_MODELS,
            provider_id="xai",
        )
