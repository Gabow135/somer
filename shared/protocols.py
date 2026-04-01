"""Protocolos (interfaces) de SOMER 2.0."""

from __future__ import annotations

from typing import Any, Callable, Coroutine, Dict, List, Optional, Protocol, runtime_checkable

from shared.types import (
    AgentMessage,
    AssembleResult,
    BootstrapResult,
    ChannelCapabilities,
    ChannelMeta,
    CompactResult,
    IncomingMessage,
    IngestResult,
    MemoryEntry,
    ModelDefinition,
)


# ── Provider Protocol ────────────────────────────────────────
@runtime_checkable
class ProviderProtocol(Protocol):
    """Interface para providers LLM."""

    async def complete(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        *,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: Optional[List[Dict[str, Any]]] = None,
        stream: bool = False,
    ) -> Dict[str, Any]: ...

    async def health_check(self) -> bool: ...

    def list_models(self) -> List[ModelDefinition]: ...


# ── Context Engine Protocol ──────────────────────────────────
@runtime_checkable
class ContextEngineProtocol(Protocol):
    """Interface para el context engine."""

    async def bootstrap(
        self, session_id: str, session_file: str
    ) -> BootstrapResult: ...

    async def ingest(
        self, session_id: str, message: AgentMessage
    ) -> IngestResult: ...

    async def assemble(
        self, session_id: str, messages: List[Any], token_budget: int
    ) -> AssembleResult: ...

    async def compact(
        self, session_id: str, token_budget: int, force: bool = False
    ) -> CompactResult: ...

    async def after_turn(
        self, session_id: str, messages: List[Any]
    ) -> None: ...


# ── Channel Plugin Protocol ──────────────────────────────────
MessageCallback = Callable[[IncomingMessage], Coroutine[Any, Any, None]]


@runtime_checkable
class ChannelPluginProtocol(Protocol):
    """Interface para plugins de canal."""

    id: str
    meta: ChannelMeta
    capabilities: ChannelCapabilities

    async def setup(self, config: Dict[str, Any]) -> None: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def send_message(
        self,
        target: str,
        content: str,
        media: Optional[List[Dict[str, Any]]] = None,
    ) -> None: ...
    def on_message(self, callback: MessageCallback) -> None: ...


# ── Memory Protocol ──────────────────────────────────────────
@runtime_checkable
class MemoryProtocol(Protocol):
    """Interface para el sistema de memoria."""

    async def store(self, entry: MemoryEntry) -> str: ...
    async def search(
        self, query: str, limit: int = 10, filters: Optional[Dict[str, Any]] = None
    ) -> List[MemoryEntry]: ...
    async def get(self, entry_id: str) -> Optional[MemoryEntry]: ...
    async def delete(self, entry_id: str) -> bool: ...


# ── Skill Protocol ───────────────────────────────────────────
@runtime_checkable
class SkillProtocol(Protocol):
    """Interface para skills ejecutables."""

    name: str
    description: str

    async def execute(
        self, arguments: Dict[str, Any], context: Dict[str, Any]
    ) -> Dict[str, Any]: ...
