"""Provider AWS Bedrock (Converse Stream)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from providers.base import BaseProvider
from providers.catalogs.bedrock import BEDROCK_CATALOG
from shared.errors import ProviderAuthError, ProviderError
from shared.types import ModelDefinition

logger = logging.getLogger(__name__)

BEDROCK_MODELS = BEDROCK_CATALOG


class BedrockProvider(BaseProvider):
    """Provider para AWS Bedrock Converse API."""

    def __init__(
        self,
        region: str = "us-east-1",
        models: Optional[List[ModelDefinition]] = None,
    ):
        super().__init__(
            provider_id="bedrock",
            api="bedrock-converse-stream",
            api_key="aws",  # Usa credenciales AWS
            models=models or BEDROCK_MODELS,
        )
        self.region = region
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import boto3
            except ImportError:
                raise ProviderError(
                    "boto3 no instalado. Ejecuta: pip install boto3"
                )
            self._client = boto3.client(
                "bedrock-runtime", region_name=self.region
            )
        return self._client

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
        import asyncio
        client = self._get_client()

        # Convertir a formato Bedrock Converse
        bedrock_messages = []
        system_prompt = None
        for msg in messages:
            if msg.get("role") == "system":
                system_prompt = msg["content"]
            else:
                bedrock_messages.append({
                    "role": msg.get("role", "user"),
                    "content": [{"text": msg.get("content", "")}],
                })

        kwargs: Dict[str, Any] = {
            "modelId": model,
            "messages": bedrock_messages,
            "inferenceConfig": {
                "maxTokens": max_tokens,
                "temperature": temperature,
            },
        }
        if system_prompt:
            kwargs["system"] = [{"text": system_prompt}]

        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, lambda: client.converse(**kwargs)
            )
            self.auth.record_success()
            output = response.get("output", {}).get("message", {})
            content_blocks = output.get("content", [])
            text = content_blocks[0].get("text", "") if content_blocks else ""
            usage = response.get("usage", {})
            return {
                "content": text,
                "model": model,
                "usage": {
                    "input_tokens": usage.get("inputTokens", 0),
                    "output_tokens": usage.get("outputTokens", 0),
                },
                "stop_reason": response.get("stopReason", "end_turn"),
            }
        except Exception as exc:
            self.auth.record_failure()
            raise ProviderError(str(exc)) from exc
