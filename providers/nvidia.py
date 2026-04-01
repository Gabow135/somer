"""Provider NVIDIA (OpenAI-compatible)."""

from __future__ import annotations

from typing import List, Optional

from providers.catalogs.nvidia import NVIDIA_CATALOG
from providers.openai import OpenAIProvider
from shared.types import ModelDefinition

NVIDIA_MODELS = NVIDIA_CATALOG


class NvidiaProvider(OpenAIProvider):
    """Provider para NVIDIA (API compatible con OpenAI)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        models: Optional[List[ModelDefinition]] = None,
    ):
        super().__init__(
            api_key=api_key,
            base_url="https://integrate.api.nvidia.com/v1",
            models=models or NVIDIA_MODELS,
            provider_id="nvidia",
        )
