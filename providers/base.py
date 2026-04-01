"""Base para providers LLM."""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Dict, List, Optional

from shared.types import ModelApi, ModelDefinition

logger = logging.getLogger(__name__)


class AuthProfile:
    """Perfil de autenticación con cooldown y backoff exponencial."""

    def __init__(self, provider_id: str, cooldown_secs: float = 60.0):
        self.provider_id = provider_id
        self.cooldown_secs = cooldown_secs
        self._failures: int = 0
        self._cooldown_until: float = 0.0
        self._last_success: float = 0.0

    @property
    def is_available(self) -> bool:
        return time.monotonic() >= self._cooldown_until

    @property
    def failure_count(self) -> int:
        return self._failures

    def record_success(self) -> None:
        self._failures = 0
        self._cooldown_until = 0.0
        self._last_success = time.monotonic()

    def record_failure(self, is_billing: bool = False) -> float:
        """Registra un fallo y aplica cooldown exponencial.

        Returns:
            Segundos hasta que vuelva a estar disponible.
        """
        self._failures += 1
        if is_billing:
            # Billing errors: cooldown más largo (5h-24h)
            cooldown = min(self.cooldown_secs * (10 ** self._failures), 86400)
        else:
            cooldown = min(self.cooldown_secs * (2 ** (self._failures - 1)), 3600)
        self._cooldown_until = time.monotonic() + cooldown
        logger.warning(
            "Provider %s: fallo #%d, cooldown %.0fs",
            self.provider_id, self._failures, cooldown,
        )
        return cooldown

    def reset(self) -> None:
        self._failures = 0
        self._cooldown_until = 0.0


class BaseProvider(ABC):
    """Clase base para providers LLM."""

    def __init__(
        self,
        provider_id: str,
        api: ModelApi,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        models: Optional[List[ModelDefinition]] = None,
    ):
        self.provider_id = provider_id
        self.api = api
        self.api_key = api_key
        self.base_url = base_url
        self._models = models or []
        self.auth = AuthProfile(provider_id)

    def list_models(self) -> List[ModelDefinition]:
        return self._models

    def get_model(self, model_id: str) -> Optional[ModelDefinition]:
        for m in self._models:
            if m.id == model_id:
                return m
        return None

    @abstractmethod
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
        """Ejecuta una completion."""
        ...

    async def stream(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        *,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Streaming completion. Default: una sola yield del complete."""
        result = await self.complete(
            messages, model,
            max_tokens=max_tokens,
            temperature=temperature,
            tools=tools,
            stream=False,
        )
        yield result

    async def health_check(self) -> bool:
        """Verifica que el provider está disponible."""
        return self.auth.is_available and self.api_key is not None
