"""Provider OpenAI (Completions API)."""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

from providers.base import BaseProvider
from providers.catalogs.openai import OPENAI_CATALOG
from shared.errors import ProviderAuthError, ProviderError, ProviderRateLimitError
from shared.types import ModelDefinition

logger = logging.getLogger(__name__)

OPENAI_MODELS = OPENAI_CATALOG


class OpenAIProvider(BaseProvider):
    """Provider para OpenAI Completions / Responses API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        models: Optional[List[ModelDefinition]] = None,
        provider_id: str = "openai",
    ):
        super().__init__(
            provider_id=provider_id,
            api="openai-completions",
            api_key=api_key,
            base_url=base_url,
            models=models or OPENAI_MODELS,
        )
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import openai
            except ImportError:
                raise ProviderError("openai no instalado. Ejecuta: pip install openai")
            if not self.api_key:
                raise ProviderAuthError(
                    f"API key no configurada para provider '{self.provider_id}'"
                )
            kwargs: Dict[str, Any] = {"api_key": self.api_key}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = openai.AsyncOpenAI(**kwargs)
        return self._client

    # ── Conversión de mensajes ─────────────────────────────────

    @staticmethod
    def _convert_messages(
        messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Convierte mensajes del formato interno al formato OpenAI API.

        Normaliza:
        - assistant tool_calls: agrega "type":"function" y wrapper "function"
          con arguments como JSON string.
        - tool messages: asegura formato correcto con tool_call_id.
        - Elimina mensajes tool huérfanos (sin tool_calls previo).
        """
        # Recopilar IDs de tool_calls válidos de mensajes assistant
        valid_tool_call_ids: set = set()
        for msg in messages:
            if msg.get("role") == "assistant":
                for tc in msg.get("tool_calls", []):
                    tc_id = tc.get("id", "")
                    if tc_id:
                        valid_tool_call_ids.add(tc_id)

        result: List[Dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role", "")

            # Descartar mensajes tool sin tool_call_id válido
            if role == "tool":
                tc_id = msg.get("tool_call_id", "")
                if tc_id not in valid_tool_call_ids:
                    logger.warning(
                        "Descartando mensaje tool huérfano (tool_call_id=%s)",
                        tc_id,
                    )
                    continue

            if role == "assistant" and "tool_calls" in msg:
                # Convertir tool_calls al formato OpenAI
                openai_tool_calls: List[Dict[str, Any]] = []
                for tc in msg["tool_calls"]:
                    # Si ya tiene "type": "function", pasar tal cual
                    if tc.get("type") == "function":
                        openai_tool_calls.append(tc)
                        continue
                    # Convertir formato interno → OpenAI
                    args = tc.get("arguments", {})
                    if isinstance(args, dict):
                        args_str = json.dumps(args, ensure_ascii=False)
                    else:
                        args_str = str(args)
                    openai_tool_calls.append({
                        "id": tc.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": tc.get("name", ""),
                            "arguments": args_str,
                        },
                    })
                converted: Dict[str, Any] = {
                    "role": "assistant",
                    "content": msg.get("content", "") or None,
                    "tool_calls": openai_tool_calls,
                }
                result.append(converted)
            elif role == "tool":
                # Asegurar formato correcto para tool results
                result.append({
                    "role": "tool",
                    "content": msg.get("content", ""),
                    "tool_call_id": msg.get("tool_call_id", ""),
                })
            else:
                result.append(msg)

        return result

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

        # Convertir mensajes al formato OpenAI
        openai_messages = self._convert_messages(messages)

        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": openai_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools

        try:
            logger.info(
                "[PROVIDER:%s] Llamando a %s con %d mensajes, %d tools",
                self.provider_id, model, len(openai_messages),
                len(tools) if tools else 0,
            )
            response = await client.chat.completions.create(**kwargs)
            self.auth.record_success()
            choice = response.choices[0]

            result: Dict[str, Any] = {
                "content": choice.message.content or "",
                "model": response.model,
                "usage": {
                    "input_tokens": response.usage.prompt_tokens,
                    "output_tokens": response.usage.completion_tokens,
                },
                "stop_reason": choice.finish_reason,
            }

            logger.info(
                "[PROVIDER:%s] Respuesta: finish_reason=%s, content_len=%d, "
                "has_tool_calls=%s, tokens=%d/%d",
                self.provider_id, choice.finish_reason,
                len(choice.message.content or ""),
                bool(choice.message.tool_calls),
                response.usage.prompt_tokens,
                response.usage.completion_tokens,
            )

            # Extraer tool_calls si los hay
            if choice.message.tool_calls:
                tool_calls: List[Dict[str, Any]] = []
                for tc in choice.message.tool_calls:
                    logger.info(
                        "[PROVIDER:%s] Tool call: id=%s, name='%s', args=%s",
                        self.provider_id, tc.id,
                        tc.function.name,
                        tc.function.arguments[:200] if tc.function.arguments else "None",
                    )
                    args = tc.function.arguments
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except (json.JSONDecodeError, ValueError):
                            args = {"raw": args}
                    tool_calls.append({
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": args,
                    })
                result["tool_calls"] = tool_calls
                # OpenAI usa "tool_calls" como finish_reason
                result["stop_reason"] = "tool_use"

            return result
        except Exception as exc:
            exc_str = str(exc).lower()
            if "rate" in exc_str or "429" in exc_str:
                self.auth.record_failure()
                raise ProviderRateLimitError(str(exc))
            if "auth" in exc_str or "401" in exc_str:
                self.auth.record_failure()
                raise ProviderAuthError(str(exc))
            raise ProviderError(str(exc)) from exc
