"""Provider HuggingFace (OpenAI-compatible)."""

from __future__ import annotations

import os
from typing import List, Optional

from providers.catalogs.huggingface import HUGGINGFACE_CATALOG
from providers.openai import OpenAIProvider
from shared.types import ModelDefinition

HUGGINGFACE_MODELS = HUGGINGFACE_CATALOG


class HuggingFaceProvider(OpenAIProvider):
    """Provider para HuggingFace Inference API (API compatible con OpenAI)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        models: Optional[List[ModelDefinition]] = None,
    ):
        # HuggingFace acepta HF_TOKEN o HUGGINGFACE_HUB_TOKEN
        if api_key is None:
            api_key = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN")
        super().__init__(
            api_key=api_key,
            base_url="https://api-inference.huggingface.co/v1",
            models=models or HUGGINGFACE_MODELS,
            provider_id="huggingface",
        )
