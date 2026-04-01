"""Provider MiniMax (OpenAI-compatible)."""

from __future__ import annotations

from typing import List, Optional

from providers.catalogs.minimax import MINIMAX_CATALOG
from providers.openai import OpenAIProvider
from shared.types import ModelDefinition

MINIMAX_MODELS = MINIMAX_CATALOG


class MiniMaxProvider(OpenAIProvider):
    """Provider para MiniMax (API compatible con OpenAI)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        models: Optional[List[ModelDefinition]] = None,
    ):
        super().__init__(
            api_key=api_key,
            base_url="https://api.minimax.io/v1",
            models=models or MINIMAX_MODELS,
            provider_id="minimax",
        )
