"""Default ContextEngine implementation."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from context_engine.base import ContextEngine
from shared.constants import COMPACT_THRESHOLD_RATIO, DEFAULT_MAX_CONTEXT_TOKENS
from shared.types import (
    AgentMessage,
    AssembleResult,
    BootstrapResult,
    CompactResult,
    IngestResult,
    Role,
)

logger = logging.getLogger(__name__)


def _estimate_tokens(text: str) -> int:
    """Estimación rápida de tokens (~4 chars por token)."""
    return max(1, len(text) // 4)


class DefaultContextEngine(ContextEngine):
    """Implementación default del context engine.

    - Mantiene un buffer de mensajes por sesión.
    - Estima tokens y compacta cuando se excede el threshold.
    - Compactación: resume mensajes antiguos en un summary.
    """

    def __init__(
        self,
        max_context_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS,
        compact_ratio: float = COMPACT_THRESHOLD_RATIO,
        system_prompt: str = "",
    ):
        self._max_tokens = max_context_tokens
        self._compact_ratio = compact_ratio
        self._system_prompt = system_prompt
        self._sessions: Dict[str, _SessionContext] = {}

    async def bootstrap(
        self, session_id: str, session_file: str
    ) -> BootstrapResult:
        ctx = _SessionContext(
            session_id=session_id,
            system_prompt=self._system_prompt,
        )
        self._sessions[session_id] = ctx
        return BootstrapResult(
            session_id=session_id,
            system_prompt=self._system_prompt,
            messages=[],
            token_count=_estimate_tokens(self._system_prompt),
        )

    async def ingest(
        self, session_id: str, message: AgentMessage
    ) -> IngestResult:
        ctx = self._get_context(session_id)
        tokens = _estimate_tokens(message.content)
        ctx.messages.append(message)
        ctx.token_count += tokens

        # Auto-compact si se excede el threshold
        threshold = int(self._max_tokens * self._compact_ratio)
        if ctx.token_count > threshold:
            await self.compact(session_id, self._max_tokens)

        return IngestResult(accepted=True, token_count=tokens)

    async def assemble(
        self, session_id: str, messages: List[Any], token_budget: int
    ) -> AssembleResult:
        ctx = self._get_context(session_id)
        assembled: List[Dict[str, Any]] = []
        total_tokens = 0

        # System prompt siempre primero
        if ctx.system_prompt:
            sys_tokens = _estimate_tokens(ctx.system_prompt)
            assembled.append({"role": "system", "content": ctx.system_prompt})
            total_tokens += sys_tokens

        # Summary de compactación si existe
        if ctx.summary:
            sum_tokens = _estimate_tokens(ctx.summary)
            assembled.append({
                "role": "system",
                "content": f"[Resumen de conversación previa]\n{ctx.summary}",
            })
            total_tokens += sum_tokens

        # Mensajes desde el más reciente
        truncated = False
        for msg in ctx.messages:
            msg_tokens = _estimate_tokens(msg.content)
            if total_tokens + msg_tokens > token_budget:
                truncated = True
                break
            assembled.append({
                "role": msg.role.value,
                "content": msg.content,
            })
            total_tokens += msg_tokens

        return AssembleResult(
            messages=assembled,
            token_count=total_tokens,
            truncated=truncated,
        )

    async def compact(
        self, session_id: str, token_budget: int, force: bool = False
    ) -> CompactResult:
        ctx = self._get_context(session_id)
        tokens_before = ctx.token_count

        if not force and ctx.token_count < int(token_budget * self._compact_ratio):
            return CompactResult(compacted=False, tokens_before=tokens_before, tokens_after=tokens_before)

        # Compactar: resumir la primera mitad de mensajes
        if len(ctx.messages) <= 2:
            return CompactResult(compacted=False, tokens_before=tokens_before, tokens_after=tokens_before)

        midpoint = len(ctx.messages) // 2
        old_messages = ctx.messages[:midpoint]
        summary_parts = []
        for msg in old_messages:
            prefix = "User" if msg.role == Role.USER else "Assistant"
            summary_parts.append(f"{prefix}: {msg.content[:200]}")
        new_summary = "\n".join(summary_parts)

        if ctx.summary:
            ctx.summary = ctx.summary + "\n---\n" + new_summary
        else:
            ctx.summary = new_summary

        ctx.messages = ctx.messages[midpoint:]
        ctx.token_count = sum(_estimate_tokens(m.content) for m in ctx.messages)
        ctx.token_count += _estimate_tokens(ctx.summary)

        logger.info(
            "Contexto compactado para sesión %s: %d → %d tokens",
            session_id, tokens_before, ctx.token_count,
        )
        return CompactResult(
            compacted=True,
            tokens_before=tokens_before,
            tokens_after=ctx.token_count,
            summary=new_summary,
        )

    async def after_turn(
        self, session_id: str, messages: List[Any]
    ) -> None:
        pass  # Hook para subclases

    def get_token_count(self, session_id: str) -> int:
        ctx = self._sessions.get(session_id)
        return ctx.token_count if ctx else 0

    def get_message_count(self, session_id: str) -> int:
        ctx = self._sessions.get(session_id)
        return len(ctx.messages) if ctx else 0

    def _get_context(self, session_id: str) -> "_SessionContext":
        if session_id not in self._sessions:
            self._sessions[session_id] = _SessionContext(session_id=session_id)
        return self._sessions[session_id]


class _SessionContext:
    """Estado interno de contexto por sesión."""

    def __init__(self, session_id: str, system_prompt: str = ""):
        self.session_id = session_id
        self.system_prompt = system_prompt
        self.messages: List[AgentMessage] = []
        self.summary: str = ""
        self.token_count: int = 0
