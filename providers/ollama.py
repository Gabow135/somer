"""Provider Ollama — soporte completo con auto-discovery, streaming y tools.

Portado de OpenClaw: ollama-stream.ts, ollama-models.ts, ollama-defaults.ts.
Usa la API nativa de Ollama (/api/*), no la compatible con OpenAI (/v1).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from providers.base import BaseProvider
from shared.errors import ProviderError
from shared.types import ModelDefinition

logger = logging.getLogger(__name__)

# ── Constantes (de OpenClaw ollama-defaults / ollama-models) ──────────
OLLAMA_DEFAULT_URL = "http://127.0.0.1:11434"
OLLAMA_DEFAULT_CONTEXT_WINDOW = 32_768
OLLAMA_DEFAULT_MAX_TOKENS = 8_192
OLLAMA_DISCOVERY_TIMEOUT = 5.0
OLLAMA_CONTEXT_QUERY_TIMEOUT = 3.0
OLLAMA_CHAT_TIMEOUT = 120.0
OLLAMA_CONCURRENT_ENRICHMENT = 8

# Patrones para detectar modelos de razonamiento
_REASONING_PATTERNS = re.compile(
    r"(^|[/:\-_])r1([:\-_]|$)|reasoning|think|reason",
    re.IGNORECASE,
)


def _is_reasoning_model(name: str) -> bool:
    """Heurística para detectar modelos de razonamiento (R1, etc.)."""
    return bool(_REASONING_PATTERNS.search(name))


def _resolve_api_base(url: str) -> str:
    """Normaliza la URL base: quita /v1 si presente (usamos API nativa)."""
    return url.rstrip("/").removesuffix("/v1")


class OllamaProvider(BaseProvider):
    """Provider para Ollama con auto-discovery, streaming NDJSON y tool calling.

    Características (portadas de OpenClaw):
    - Auto-descubrimiento de modelos vía /api/tags
    - Detección de ventana de contexto vía /api/show
    - Streaming NDJSON nativo
    - Tool calling en formato Ollama
    - Detección automática de modelos de razonamiento
    - Embeddings vía /api/embeddings
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        models: Optional[List[ModelDefinition]] = None,
    ):
        resolved_url = _resolve_api_base(base_url or OLLAMA_DEFAULT_URL)
        super().__init__(
            provider_id="ollama",
            api="ollama",
            api_key="local",
            base_url=resolved_url,
            models=models or [],
        )
        self._discovered = False

    # ── Descubrimiento de modelos ─────────────────────────────────

    async def discover_models(self) -> List[ModelDefinition]:
        """Descubre modelos disponibles en Ollama y enriquece con context windows.

        Equivalente a fetchOllamaModels() + enrichOllamaModelsWithContext()
        de OpenClaw.
        """
        raw_models = await self._fetch_models()
        if not raw_models:
            return []

        enriched = await self._enrich_with_context(raw_models)
        definitions = []
        for model_info in enriched:
            defn = self._build_model_definition(model_info)
            definitions.append(defn)

        self._models = definitions
        self._discovered = True
        logger.info("Ollama: %d modelos descubiertos", len(definitions))
        return definitions

    async def _fetch_models(self) -> List[Dict[str, Any]]:
        """Obtiene lista de modelos desde /api/tags."""
        try:
            async with httpx.AsyncClient(timeout=OLLAMA_DISCOVERY_TIMEOUT) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                resp.raise_for_status()
                data = resp.json()
                return data.get("models", [])
        except httpx.ConnectError:
            logger.warning("Ollama no disponible en %s", self.base_url)
            return []
        except Exception as exc:
            logger.warning("Error descubriendo modelos Ollama: %s", exc)
            return []

    async def _query_context_window(self, model_name: str) -> int:
        """Consulta la ventana de contexto de un modelo vía /api/show."""
        try:
            async with httpx.AsyncClient(timeout=OLLAMA_CONTEXT_QUERY_TIMEOUT) as client:
                resp = await client.post(
                    f"{self.base_url}/api/show",
                    json={"model": model_name},
                )
                resp.raise_for_status()
                data = resp.json()
                # model_info.parameters puede contener num_ctx
                params = data.get("model_info", {})
                for key, value in params.items():
                    if "context_length" in key:
                        return int(value)
                # Fallback: buscar en parameters string
                params_str = data.get("parameters", "")
                if "num_ctx" in params_str:
                    for line in params_str.split("\n"):
                        if "num_ctx" in line:
                            parts = line.strip().split()
                            if len(parts) >= 2:
                                return int(parts[-1])
        except Exception as exc:
            logger.debug("No se pudo consultar context window de %s: %s", model_name, exc)
        return OLLAMA_DEFAULT_CONTEXT_WINDOW

    async def _enrich_with_context(
        self, models: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Enriquece modelos con context windows (concurrente, 8 simultáneos)."""
        semaphore = asyncio.Semaphore(OLLAMA_CONCURRENT_ENRICHMENT)

        async def _enrich_one(model: Dict[str, Any]) -> Dict[str, Any]:
            async with semaphore:
                name = model.get("name", model.get("model", ""))
                ctx = await self._query_context_window(name)
                model["context_window"] = ctx
                return model

        return await asyncio.gather(*[_enrich_one(m) for m in models])

    def _build_model_definition(self, model_info: Dict[str, Any]) -> ModelDefinition:
        """Construye ModelDefinition desde la info de Ollama."""
        name = model_info.get("name", model_info.get("model", "unknown"))
        ctx_window = model_info.get("context_window", OLLAMA_DEFAULT_CONTEXT_WINDOW)
        max_tokens = min(OLLAMA_DEFAULT_MAX_TOKENS, ctx_window)
        is_reasoning = _is_reasoning_model(name)

        display_name = name.split(":")[0].replace("/", " ").replace("-", " ").title()

        return ModelDefinition(
            id=name,
            name=display_name,
            api="ollama",
            provider="ollama",
            max_input_tokens=ctx_window,
            max_output_tokens=max_tokens,
            supports_streaming=True,
            supports_tools=True,
            supports_vision=False,
            cost_per_input_token=0.0,
            cost_per_output_token=0.0,
            metadata={
                "reasoning": is_reasoning,
                "local": True,
                "size": model_info.get("size", 0),
                "family": model_info.get("details", {}).get("family", ""),
                "parameter_size": model_info.get("details", {}).get("parameter_size", ""),
            },
        )

    # ── Completions ───────────────────────────────────────────────

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
        """Completion vía /api/chat (sin streaming)."""
        if not self._discovered:
            await self.discover_models()

        model_def = self.get_model(model)
        ctx_window = model_def.max_input_tokens if model_def else OLLAMA_DEFAULT_CONTEXT_WINDOW

        payload: Dict[str, Any] = {
            "model": model,
            "messages": self._convert_messages(messages),
            "stream": False,
            "options": {
                "num_ctx": ctx_window,
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }

        if tools:
            payload["tools"] = self._convert_tools(tools)

        try:
            async with httpx.AsyncClient(timeout=OLLAMA_CHAT_TIMEOUT) as client:
                resp = await client.post(f"{self.base_url}/api/chat", json=payload)
                if resp.status_code >= 400:
                    body = resp.text[:500]
                    logger.error(
                        "Ollama error %d para %s (num_ctx=%d, tools=%d): %s",
                        resp.status_code, model, ctx_window,
                        len(tools) if tools else 0, body,
                    )
                resp.raise_for_status()
                data = resp.json()
                self.auth.record_success()

                message = data.get("message", {})
                tool_calls = message.get("tool_calls", [])

                result: Dict[str, Any] = {
                    "content": message.get("content", ""),
                    "model": model,
                    "usage": {
                        "input_tokens": data.get("prompt_eval_count", 0),
                        "output_tokens": data.get("eval_count", 0),
                    },
                    "stop_reason": "end_turn",
                }

                if tool_calls:
                    valid_tcs = [
                        {
                            "id": f"ollama_{i}",
                            "type": "function",
                            "function": {
                                "name": tc.get("function", {}).get("name", ""),
                                "arguments": json.dumps(
                                    tc.get("function", {}).get("arguments", {})
                                ),
                            },
                        }
                        for i, tc in enumerate(tool_calls)
                        if tc.get("function", {}).get("name")
                    ]
                    if valid_tcs:
                        result["tool_calls"] = valid_tcs
                        result["stop_reason"] = "tool_use"

                return result

        except httpx.ConnectError:
            raise ProviderError("Ollama no está corriendo. Ejecuta: ollama serve")
        except Exception as exc:
            self.auth.record_failure()
            raise ProviderError(str(exc)) from exc

    # ── Streaming ─────────────────────────────────────────────────

    async def stream(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        *,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Streaming NDJSON vía /api/chat.

        Portado de createOllamaStreamFn() de OpenClaw.
        Ollama envía tool_calls en chunks intermedios (no en el final).
        """
        if not self._discovered:
            await self.discover_models()

        model_def = self.get_model(model)
        ctx_window = model_def.max_input_tokens if model_def else OLLAMA_DEFAULT_CONTEXT_WINDOW

        payload: Dict[str, Any] = {
            "model": model,
            "messages": self._convert_messages(messages),
            "stream": True,
            "options": {
                "num_ctx": ctx_window,
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }

        if tools:
            payload["tools"] = self._convert_tools(tools)

        collected_tool_calls: List[Dict[str, Any]] = []
        full_content = ""
        input_tokens = 0
        output_tokens = 0

        try:
            async with httpx.AsyncClient(timeout=OLLAMA_CHAT_TIMEOUT) as client:
                async with client.stream(
                    "POST", f"{self.base_url}/api/chat", json=payload
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            logger.debug("NDJSON malformado: %s", line[:100])
                            continue

                        message = chunk.get("message", {})
                        content = message.get("content", "")

                        # Recoger tool_calls de chunks intermedios
                        chunk_tool_calls = message.get("tool_calls", [])
                        if chunk_tool_calls:
                            collected_tool_calls.extend(chunk_tool_calls)

                        if content:
                            full_content += content
                            yield {
                                "type": "content_delta",
                                "content": content,
                            }

                        if chunk.get("done", False):
                            input_tokens = chunk.get("prompt_eval_count", 0)
                            output_tokens = chunk.get("eval_count", 0)

            self.auth.record_success()

            # Emitir resultado final
            result: Dict[str, Any] = {
                "type": "message_complete",
                "content": full_content,
                "model": model,
                "usage": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                },
                "stop_reason": "end_turn",
            }

            if collected_tool_calls:
                valid_tcs = [
                    {
                        "id": f"ollama_{i}",
                        "type": "function",
                        "function": {
                            "name": tc.get("function", {}).get("name", ""),
                            "arguments": json.dumps(
                                tc.get("function", {}).get("arguments", {})
                            ),
                        },
                    }
                    for i, tc in enumerate(collected_tool_calls)
                    if tc.get("function", {}).get("name")
                ]
                if valid_tcs:
                    result["tool_calls"] = valid_tcs
                    result["stop_reason"] = "tool_use"

            yield result

        except httpx.ConnectError:
            raise ProviderError("Ollama no está corriendo. Ejecuta: ollama serve")
        except Exception as exc:
            self.auth.record_failure()
            raise ProviderError(str(exc)) from exc

    # ── Embeddings ────────────────────────────────────────────────

    async def embed(
        self,
        text: str,
        model: str = "nomic-embed-text",
    ) -> List[float]:
        """Genera embedding vía /api/embeddings."""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": model, "prompt": text},
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("embedding", [])
        except httpx.ConnectError:
            raise ProviderError("Ollama no está corriendo. Ejecuta: ollama serve")
        except Exception as exc:
            raise ProviderError(f"Error en embeddings Ollama: {exc}") from exc

    async def embed_batch(
        self,
        texts: List[str],
        model: str = "nomic-embed-text",
    ) -> List[List[float]]:
        """Genera embeddings en batch (concurrente)."""
        semaphore = asyncio.Semaphore(OLLAMA_CONCURRENT_ENRICHMENT)

        async def _one(text: str) -> List[float]:
            async with semaphore:
                return await self.embed(text, model)

        return await asyncio.gather(*[_one(t) for t in texts])

    # ── Health Check ──────────────────────────────────────────────

    async def health_check(self) -> bool:
        """Verifica que Ollama está corriendo."""
        try:
            async with httpx.AsyncClient(timeout=OLLAMA_DISCOVERY_TIMEOUT) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False

    async def list_local_models(self) -> List[str]:
        """Lista nombres de modelos disponibles en Ollama."""
        models = await self._fetch_models()
        return [m.get("name", m.get("model", "")) for m in models]

    async def pull_model(self, model_name: str) -> bool:
        """Descarga un modelo en Ollama."""
        try:
            async with httpx.AsyncClient(timeout=600) as client:
                resp = await client.post(
                    f"{self.base_url}/api/pull",
                    json={"model": model_name, "stream": False},
                )
                return resp.status_code == 200
        except Exception as exc:
            logger.error("Error descargando modelo %s: %s", model_name, exc)
            return False

    # ── Conversiones internas ─────────────────────────────────────

    @staticmethod
    def _convert_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convierte mensajes al formato Ollama nativo."""
        converted = []
        for msg in messages:
            ollama_msg: Dict[str, Any] = {
                "role": msg.get("role", "user"),
                "content": msg.get("content", ""),
            }
            # Imágenes: Ollama espera base64 en campo "images"
            images = msg.get("images", [])
            if images:
                ollama_msg["images"] = images
            converted.append(ollama_msg)
        return converted

    @staticmethod
    def _convert_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convierte tools al formato Ollama.

        OpenAI format:
            {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}
        Ollama format (igual):
            {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}
        """
        return tools
