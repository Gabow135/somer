"""Token guard para ventana de contexto del agente."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from shared.constants import DEFAULT_MAX_CONTEXT_TOKENS, DEFAULT_MAX_OUTPUT_TOKENS
from shared.errors import ContextWindowExceededError

logger = logging.getLogger(__name__)


def estimate_tokens(text: str) -> int:
    """Estimación rápida de tokens (~4 chars por token)."""
    return max(1, len(text) // 4)


def estimate_messages_tokens(messages: List[Dict[str, Any]]) -> int:
    """Estima tokens totales de una lista de mensajes."""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    total += estimate_tokens(block.get("text", ""))
        total += 4  # Overhead por mensaje (role, separadores)
    return total


class ContextWindowGuard:
    """Guardia que previene exceder la ventana de contexto.

    Trunca o compacta mensajes automáticamente.
    """

    def __init__(
        self,
        max_input_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        reserve_ratio: float = 0.15,
    ):
        self.max_input = max_input_tokens
        self.max_output = max_output_tokens
        self._reserve = int(max_input_tokens * reserve_ratio)
        self._effective_limit = max_input_tokens - self._reserve

    def check(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Verifica que los mensajes caben en la ventana.

        Returns:
            Dict con info: tokens, fits, should_compact
        """
        tokens = estimate_messages_tokens(messages)
        return {
            "tokens": tokens,
            "max_tokens": self.max_input,
            "effective_limit": self._effective_limit,
            "fits": tokens <= self._effective_limit,
            "should_compact": tokens > self._effective_limit * 0.85,
            "utilization": tokens / self.max_input if self.max_input else 0,
        }

    def enforce(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Trunca mensajes si exceden el límite.

        Preserva system prompt y últimos mensajes.

        Returns:
            Lista truncada de mensajes.

        Raises:
            ContextWindowExceededError: Si ni truncando cabe.
        """
        info = self.check(messages)
        if info["fits"]:
            return messages

        logger.warning(
            "Context window: %d tokens > %d limit, truncando",
            info["tokens"], self._effective_limit,
        )

        # Preservar system y últimos mensajes
        system_msgs = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]

        result = list(system_msgs)
        budget = self._effective_limit - estimate_messages_tokens(system_msgs)

        # Añadir mensajes desde el final
        for msg in reversed(non_system):
            msg_tokens = estimate_tokens(msg.get("content", "")) + 4
            if budget - msg_tokens < 0:
                break
            result.append(msg)
            budget -= msg_tokens

        # Reordenar (system primero, luego cronológico)
        final = system_msgs + list(reversed([m for m in result if m not in system_msgs]))

        if not final:
            raise ContextWindowExceededError("No caben mensajes en la ventana de contexto")

        return final
