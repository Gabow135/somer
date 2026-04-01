"""Provider Qianfan (OpenAI-compatible)."""

from __future__ import annotations

from typing import List, Optional

from providers.catalogs.qianfan import QIANFAN_CATALOG
from providers.openai import OpenAIProvider
from shared.types import ModelDefinition

QIANFAN_MODELS = QIANFAN_CATALOG


class QianfanProvider(OpenAIProvider):
    """Provider para Qianfan / Baidu (API compatible con OpenAI)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        models: Optional[List[ModelDefinition]] = None,
    ):
        super().__init__(
            api_key=api_key,
            base_url="https://qianfan.baidubce.com/v2",
            models=models or QIANFAN_MODELS,
            provider_id="qianfan",
        )
