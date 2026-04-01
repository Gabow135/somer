"""Provider Anthropic (Messages API)."""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

from providers.base import BaseProvider
from providers.catalogs.anthropic import ANTHROPIC_CATALOG
from shared.errors import ProviderAuthError, ProviderError, ProviderRateLimitError
from shared.types import ModelDefinition

logger = logging.getLogger(__name__)

ANTHROPIC_MODELS = ANTHROPIC_CATALOG


class AnthropicProvider(BaseProvider):
    """Provider para Anthropic Messages API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        models: Optional[List[ModelDefinition]] = None,
    ):
        super().__init__(
            provider_id="anthropic",
            api="anthropic-messages",
            api_key=api_key,
            base_url=base_url,
            models=models or ANTHROPIC_MODELS,
        )
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import anthropic
            except ImportError:
                raise ProviderError(
                    "anthropic no instalado. Ejecuta: pip install anthropic"
                )
            if not self.api_key:
                raise ProviderAuthError("ANTHROPIC_API_KEY no configurada")
            kwargs: Dict[str, Any] = {"api_key": self.api_key}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = anthropic.AsyncAnthropic(**kwargs)
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
        client = self._get_client()

        # Convertir mensajes al formato Anthropic
        anthropic_messages = self._convert_messages(messages)

        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": anthropic_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        # Separar system message
        if anthropic_messages and anthropic_messages[0].get("role") == "system":
            kwargs["system"] = anthropic_messages[0]["content"]
            kwargs["messages"] = anthropic_messages[1:]

        # Convertir tools al formato Anthropic
        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        try:
            response = await client.messages.create(**kwargs)
            self.auth.record_success()

            # Extraer texto y tool_calls de los content blocks
            text_parts: List[str] = []
            tool_calls: List[Dict[str, Any]] = []

            for block in response.content:
                if block.type == "text":
                    text_parts.append(block.text)
                elif block.type == "tool_use":
                    tool_calls.append({
                        "id": block.id,
                        "name": block.name,
                        "arguments": block.input if isinstance(block.input, dict) else {},
                    })

            result: Dict[str, Any] = {
                "content": "\n".join(text_parts),
                "model": response.model,
                "usage": {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                },
                "stop_reason": response.stop_reason,
            }

            if tool_calls:
                result["tool_calls"] = tool_calls

            return result
        except Exception as exc:
            exc_str = str(exc).lower()
            if "rate" in exc_str or "429" in exc_str:
                self.auth.record_failure()
                raise ProviderRateLimitError(str(exc))
            if "auth" in exc_str or "401" in exc_str or "key" in exc_str:
                self.auth.record_failure()
                raise ProviderAuthError(str(exc))
            if "billing" in exc_str or "credit" in exc_str:
                self.auth.record_failure(is_billing=True)
                raise ProviderError(str(exc))
            raise ProviderError(str(exc)) from exc

    # ── Conversiones de formato ────────────────────────────────

    @staticmethod
    def _convert_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convierte tool definitions de formato OpenAI a formato Anthropic."""
        anthropic_tools: List[Dict[str, Any]] = []
        for tool in tools:
            if "function" in tool:
                # Formato OpenAI → Anthropic
                func = tool["function"]
                anthropic_tools.append({
                    "name": func["name"],
                    "description": func.get("description", ""),
                    "input_schema": func.get("parameters", {
                        "type": "object", "properties": {},
                    }),
                })
            elif "name" in tool and "input_schema" in tool:
                # Ya es formato Anthropic
                anthropic_tools.append(tool)
            elif "name" in tool:
                # Formato simple (del ToolRegistry.to_provider_format("anthropic"))
                anthropic_tools.append({
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "input_schema": tool.get("input_schema", tool.get("parameters", {
                        "type": "object", "properties": {},
                    })),
                })
        return anthropic_tools

    @staticmethod
    def _convert_messages(
        messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Convierte mensajes del formato runner al formato Anthropic.

        Maneja:
        - assistant messages con tool_calls → content array con tool_use blocks
        - tool messages → user messages con tool_result blocks
        - Agrupa tool results consecutivos en un solo user message
        """
        result: List[Dict[str, Any]] = []
        i = 0
        while i < len(messages):
            msg = messages[i]
            role = msg.get("role", "")

            if role == "system":
                result.append(msg)
                i += 1
                continue

            if role == "assistant":
                tool_calls = msg.get("tool_calls", [])
                if tool_calls:
                    # Construir content array con texto + tool_use blocks
                    content_blocks: List[Dict[str, Any]] = []
                    text = msg.get("content", "")
                    if text:
                        content_blocks.append({"type": "text", "text": text})
                    for tc in tool_calls:
                        content_blocks.append({
                            "type": "tool_use",
                            "id": tc.get("id", ""),
                            "name": tc.get("name", ""),
                            "input": tc.get("arguments", {}),
                        })
                    result.append({"role": "assistant", "content": content_blocks})
                else:
                    content = msg.get("content", "")
                    result.append({"role": "assistant", "content": content})
                i += 1
                continue

            if role == "tool":
                # Agrupar tool results consecutivos en un solo user message
                tool_results: List[Dict[str, Any]] = []
                while i < len(messages) and messages[i].get("role") == "tool":
                    tr = messages[i]
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tr.get("tool_call_id", ""),
                        "content": tr.get("content", ""),
                    })
                    i += 1
                result.append({"role": "user", "content": tool_results})
                continue

            # user, etc.
            result.append(msg)
            i += 1

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
        client = self._get_client()

        anthropic_messages = self._convert_messages(messages)

        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": anthropic_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if anthropic_messages and anthropic_messages[0].get("role") == "system":
            kwargs["system"] = anthropic_messages[0]["content"]
            kwargs["messages"] = anthropic_messages[1:]
        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        try:
            async with client.messages.stream(**kwargs) as stream_resp:
                async for text in stream_resp.text_stream:
                    yield {"type": "text_delta", "content": text}
            self.auth.record_success()
        except Exception as exc:
            self.auth.record_failure()
            raise ProviderError(str(exc)) from exc
