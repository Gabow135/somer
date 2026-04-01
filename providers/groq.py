"""Provider Groq (OpenAI-compatible)."""

from __future__ import annotations

from typing import List, Optional

from providers.catalogs.groq import GROQ_CATALOG
from providers.openai import OpenAIProvider
from shared.types import ModelDefinition

GROQ_MODELS = GROQ_CATALOG


class GroqProvider(OpenAIProvider):
    """Provider para Groq (API compatible con OpenAI)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        models: Optional[List[ModelDefinition]] = None,
    ):
        super().__init__(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
            models=models or GROQ_MODELS,
            provider_id="groq",
        )
