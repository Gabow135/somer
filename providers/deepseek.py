"""Provider DeepSeek (OpenAI-compatible).

Soporta la API directa de DeepSeek (api.deepseek.com).
Para DeepSeek vía terceros (Together, Chutes, QianFan, OpenRouter),
cada provider tiene sus propios modelos DeepSeek registrados.
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Dict, List, Optional

from providers.catalogs.deepseek import DEEPSEEK_CATALOG
from providers.openai import OpenAIProvider
from shared.types import ModelDefinition

DEEPSEEK_MODELS = DEEPSEEK_CATALOG


class DeepSeekProvider(OpenAIProvider):
    """Provider para DeepSeek (API directa, compatible con OpenAI).

    Hereda streaming y tool calling de OpenAIProvider.
    El modelo reasoner (R1) soporta reasoning tokens nativos.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        models: Optional[List[ModelDefinition]] = None,
    ):
        super().__init__(
            api_key=api_key,
            base_url="https://api.deepseek.com/v1",
            models=models or DEEPSEEK_MODELS,
            provider_id="deepseek",
        )

    async def complete(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        *,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: Optional[List[Dict[str, Any]]] = None,
        stream: bool = False,
    ) -> Dict[str, Any]:
        """Completion con soporte para reasoning tokens de DeepSeek R1."""
        result = await super().complete(
            messages, model,
            max_tokens=max_tokens,
            temperature=temperature,
            tools=tools,
            stream=stream,
        )

        # DeepSeek R1 puede incluir reasoning_content en la respuesta
        if model == "deepseek-reasoner" and "raw_response" in result:
            raw = result.get("raw_response", {})
            reasoning = raw.get("reasoning_content", "")
            if reasoning:
                result["metadata"] = result.get("metadata", {})
                result["metadata"]["reasoning_content"] = reasoning

        return result

    async def stream(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        *,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Streaming con soporte para reasoning tokens."""
        async for chunk in super().stream(
            messages, model,
            max_tokens=max_tokens,
            temperature=temperature,
            tools=tools,
        ):
            yield chunk
