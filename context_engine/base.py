"""ContextEngine protocol — interface pluggable."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from shared.types import (
    AgentMessage,
    AssembleResult,
    BootstrapResult,
    CompactResult,
    IngestResult,
)


class ContextEngine(ABC):
    """Interface para el context engine.

    Define el ciclo de vida del contexto de una sesión:
    bootstrap → ingest → assemble → compact → after_turn
    """

    @abstractmethod
    async def bootstrap(
        self, session_id: str, session_file: str
    ) -> BootstrapResult:
        """Inicializa el contexto de una sesión.

        Carga el system prompt y mensajes previos si existen.
        """
        ...

    @abstractmethod
    async def ingest(
        self, session_id: str, message: AgentMessage
    ) -> IngestResult:
        """Ingresa un nuevo mensaje al contexto."""
        ...

    @abstractmethod
    async def assemble(
        self, session_id: str, messages: List[Any], token_budget: int
    ) -> AssembleResult:
        """Ensambla mensajes para enviar al LLM respetando el budget."""
        ...

    @abstractmethod
    async def compact(
        self, session_id: str, token_budget: int, force: bool = False
    ) -> CompactResult:
        """Compacta el contexto cuando se excede el budget."""
        ...

    @abstractmethod
    async def after_turn(
        self, session_id: str, messages: List[Any]
    ) -> None:
        """Hook post-turno para cleanup o persistencia."""
        ...
