"""Provider Volcengine (OpenAI-compatible)."""

from __future__ import annotations

from typing import List, Optional

from providers.catalogs.volcengine import VOLCENGINE_CATALOG
from providers.openai import OpenAIProvider
from shared.types import ModelDefinition

VOLCENGINE_MODELS = VOLCENGINE_CATALOG


class VolcengineProvider(OpenAIProvider):
    """Provider para Volcengine / ByteDance (API compatible con OpenAI)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        models: Optional[List[ModelDefinition]] = None,
    ):
        super().__init__(
            api_key=api_key,
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            models=models or VOLCENGINE_MODELS,
            provider_id="volcengine",
        )
