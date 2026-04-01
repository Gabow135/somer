"""Provider Google Generative AI."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from providers.base import BaseProvider
from providers.catalogs.google import GOOGLE_CATALOG
from shared.errors import ProviderAuthError, ProviderError
from shared.types import ModelDefinition

logger = logging.getLogger(__name__)

GOOGLE_MODELS = GOOGLE_CATALOG


class GoogleProvider(BaseProvider):
    """Provider para Google Generative AI."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        models: Optional[List[ModelDefinition]] = None,
    ):
        super().__init__(
            provider_id="google",
            api="google-generative-ai",
            api_key=api_key,
            models=models or GOOGLE_MODELS,
        )
        self._configured = False

    def _configure(self) -> None:
        if self._configured:
            return
        try:
            import google.generativeai as genai
        except ImportError:
            raise ProviderError(
                "google-generativeai no instalado. Ejecuta: pip install google-generativeai"
            )
        if not self.api_key:
            raise ProviderAuthError("GOOGLE_API_KEY no configurada")
        genai.configure(api_key=self.api_key)
        self._configured = True

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
        self._configure()
        import google.generativeai as genai

        gmodel = genai.GenerativeModel(model)
        # Convertir mensajes a formato Gemini
        contents = []
        for msg in messages:
            role = "user" if msg.get("role") in ("user", "system") else "model"
            contents.append({"role": role, "parts": [msg.get("content", "")]})

        try:
            response = await gmodel.generate_content_async(
                contents,
                generation_config=genai.GenerationConfig(
                    max_output_tokens=max_tokens,
                    temperature=temperature,
                ),
            )
            self.auth.record_success()
            return {
                "content": response.text or "",
                "model": model,
                "usage": {"input_tokens": 0, "output_tokens": 0},
                "stop_reason": "end_turn",
            }
        except Exception as exc:
            self.auth.record_failure()
            raise ProviderError(str(exc)) from exc
