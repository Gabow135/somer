"""SmartContextEngine — inyecta memoria, lecciones y KG en el contexto.

Envuelve al DefaultContextEngine y enriquece assemble() con datos
relevantes de los sistemas de memoria ANTES de que el LLM responda.

Python 3.9+ — ``from __future__ import annotations``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from context_engine.base import ContextEngine
from context_engine.default import DefaultContextEngine, _estimate_tokens
from shared.types import (
    AgentMessage,
    AssembleResult,
    BootstrapResult,
    CompactResult,
    IngestResult,
)

logger = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────

_MAX_MEMORY_TOKENS = 500          # Budget máximo para el bloque de memoria
_MAX_MEMORY_RESULTS = 5
_MAX_LESSON_RESULTS = 3
_MAX_EPISODIC_RESULTS = 3
_MAX_KG_RESULTS = 5


# ── Helpers ───────────────────────────────────────────────────

def _extract_last_user_message(messages: List[Any]) -> str:
    """Extrae el texto del último mensaje del usuario."""
    for msg in reversed(messages):
        if isinstance(msg, dict):
            if msg.get("role") == "user":
                return str(msg.get("content", ""))
        elif hasattr(msg, "role"):
            role_val = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
            if role_val == "user":
                return str(msg.content)
    return ""


def _truncate(text: str, max_chars: int = 200) -> str:
    """Trunca texto a max_chars preservando palabras completas."""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    last_space = truncated.rfind(" ")
    if last_space > max_chars // 2:
        truncated = truncated[:last_space]
    return truncated + "..."


# ── SmartContextEngine ────────────────────────────────────────


class SmartContextEngine(ContextEngine):
    """Context engine que inyecta memoria relevante antes de cada llamada al LLM.

    Delega todas las operaciones al DefaultContextEngine base y enriquece
    assemble() buscando en:
      1. MemoryManager (búsqueda híbrida BM25+vector)
      2. LessonsMemory (lecciones aprendidas / errores previos)
      3. EpisodicMemory (episodios de acciones pasadas)
      4. KnowledgeGraphStore (entidades y relaciones)

    Si cualquier sistema de memoria no está disponible, se omite
    silenciosamente sin afectar el funcionamiento.
    """

    def __init__(
        self,
        max_context_tokens: Optional[int] = None,
        compact_ratio: Optional[float] = None,
        system_prompt: str = "",
        memory_manager: Any = None,
        lessons_memory: Any = None,
        episodic_memory: Any = None,
        knowledge_graph: Any = None,
        memory_token_budget: int = _MAX_MEMORY_TOKENS,
    ) -> None:
        # Construir kwargs para el engine base
        base_kwargs: Dict[str, Any] = {}
        if system_prompt:
            base_kwargs["system_prompt"] = system_prompt
        if max_context_tokens is not None:
            base_kwargs["max_context_tokens"] = max_context_tokens
        if compact_ratio is not None:
            base_kwargs["compact_ratio"] = compact_ratio

        self._base = DefaultContextEngine(**base_kwargs)
        self._memory_manager = memory_manager
        self._lessons_memory = lessons_memory
        self._episodic_memory = episodic_memory
        self._knowledge_graph = knowledge_graph
        self._memory_token_budget = memory_token_budget

    # ── Delegación directa al engine base ─────────────────────

    async def bootstrap(
        self, session_id: str, session_file: str
    ) -> BootstrapResult:
        return await self._base.bootstrap(session_id, session_file)

    async def ingest(
        self, session_id: str, message: AgentMessage
    ) -> IngestResult:
        return await self._base.ingest(session_id, message)

    async def compact(
        self, session_id: str, token_budget: int, force: bool = False
    ) -> CompactResult:
        return await self._base.compact(session_id, token_budget, force)

    async def after_turn(
        self, session_id: str, messages: List[Any]
    ) -> None:
        return await self._base.after_turn(session_id, messages)

    # ── Métodos delegados de conveniencia ─────────────────────

    def get_token_count(self, session_id: str) -> int:
        return self._base.get_token_count(session_id)

    def get_message_count(self, session_id: str) -> int:
        return self._base.get_message_count(session_id)

    # ── assemble enriquecido ──────────────────────────────────

    async def assemble(
        self, session_id: str, messages: List[Any], token_budget: int
    ) -> AssembleResult:
        """Ensambla contexto inyectando memoria relevante.

        1. Extrae el último mensaje del usuario como query.
        2. Busca en los sistemas de memoria disponibles.
        3. Construye un bloque [Contexto de Memoria] en español.
        4. Lo inyecta como mensaje de sistema justo después del system prompt.
        5. Ajusta el token_budget para no exceder el límite.
        """
        # Obtener el contexto base primero
        base_result = await self._base.assemble(
            session_id, messages, token_budget
        )

        # Extraer query del último mensaje del usuario
        query = _extract_last_user_message(base_result.messages)
        if not query:
            # Sin mensaje de usuario, nada que buscar
            return base_result

        # Construir bloque de memoria
        memory_block = await self._build_memory_block(query)
        if not memory_block:
            return base_result

        # Verificar que el bloque cabe en el budget
        block_tokens = _estimate_tokens(memory_block)
        if block_tokens > self._memory_token_budget:
            # Truncar el bloque para que quepa
            max_chars = self._memory_token_budget * 4  # ~4 chars/token
            memory_block = memory_block[:max_chars] + "\n[/Contexto de Memoria]"
            block_tokens = _estimate_tokens(memory_block)

        # Verificar que no excedemos el budget total
        if base_result.token_count + block_tokens > token_budget:
            # No hay espacio, devolver resultado base
            logger.debug(
                "Sin espacio para memoria en sesión %s (%d + %d > %d)",
                session_id, base_result.token_count, block_tokens, token_budget,
            )
            return base_result

        # Inyectar bloque de memoria después del primer system message
        enriched_messages = list(base_result.messages)
        memory_msg = {"role": "system", "content": memory_block}

        # Encontrar la posición después del system prompt
        insert_pos = 0
        for i, msg in enumerate(enriched_messages):
            if isinstance(msg, dict) and msg.get("role") == "system":
                insert_pos = i + 1
                break

        enriched_messages.insert(insert_pos, memory_msg)

        logger.info(
            "Memoria inyectada en sesión %s: %d tokens (%d items)",
            session_id, block_tokens,
            memory_block.count("\n- "),
        )

        return AssembleResult(
            messages=enriched_messages,
            token_count=base_result.token_count + block_tokens,
            truncated=base_result.truncated,
        )

    # ── Construcción del bloque de memoria ────────────────────

    async def _build_memory_block(self, query: str) -> str:
        """Construye el bloque [Contexto de Memoria] consultando todos los sistemas."""
        items: List[str] = []

        # 1. Memoria semántica (MemoryManager)
        mem_items = await self._search_memory(query)
        items.extend(mem_items)

        # 2. Lecciones aprendidas
        lesson_items = await self._search_lessons(query)
        items.extend(lesson_items)

        # 3. Memoria episódica
        episodic_items = await self._search_episodic(query)
        items.extend(episodic_items)

        # 4. Knowledge Graph
        kg_items = await self._search_knowledge_graph(query)
        items.extend(kg_items)

        if not items:
            return ""

        # Construir bloque respetando el budget de tokens
        block_lines = ["[Contexto de Memoria]"]
        current_tokens = _estimate_tokens(block_lines[0])

        for item in items:
            item_tokens = _estimate_tokens(item)
            if current_tokens + item_tokens > self._memory_token_budget - 10:
                break
            block_lines.append(item)
            current_tokens += item_tokens

        block_lines.append("[/Contexto de Memoria]")

        # Solo devolver si hay contenido real
        if len(block_lines) <= 2:
            return ""

        return "\n".join(block_lines)

    async def _search_memory(self, query: str) -> List[str]:
        """Busca en MemoryManager (BM25 + vector)."""
        if self._memory_manager is None:
            return []
        try:
            results = await self._memory_manager.search(
                query=query,
                limit=_MAX_MEMORY_RESULTS,
            )
            items: List[str] = []
            for entry in results:
                content = _truncate(entry.content, 150)
                items.append(f"- Memoria: \"{content}\"")
            return items
        except Exception:
            logger.debug("Error buscando en MemoryManager", exc_info=True)
            return []

    async def _search_lessons(self, query: str) -> List[str]:
        """Busca lecciones relevantes."""
        if self._lessons_memory is None:
            return []
        try:
            results = self._lessons_memory.recall_lessons(
                query=query,
                limit=_MAX_LESSON_RESULTS,
            )
            items: List[str] = []
            for lesson in results:
                error = _truncate(lesson.get("error", ""), 100)
                solution = _truncate(lesson.get("solution", ""), 100)
                severity = lesson.get("severity", "warning")
                items.append(
                    f"- Lección ({severity}): \"{error}\" → Solución: \"{solution}\""
                )
            return items
        except Exception:
            logger.debug("Error buscando en LessonsMemory", exc_info=True)
            return []

    async def _search_episodic(self, query: str) -> List[str]:
        """Busca episodios similares."""
        if self._episodic_memory is None:
            return []
        try:
            episodes = self._episodic_memory.recall(
                query=query,
                limit=_MAX_EPISODIC_RESULTS,
            )
            items: List[str] = []
            for ep in episodes:
                title = _truncate(ep.title, 80)
                outcome = ep.outcome.value if hasattr(ep.outcome, "value") else str(ep.outcome)
                score = f"{ep.success_score:.0%}" if hasattr(ep, "success_score") else ""
                items.append(
                    f"- Episodio similar: \"{title}\" ({outcome}, {score})"
                )
            return items
        except Exception:
            logger.debug("Error buscando en EpisodicMemory", exc_info=True)
            return []

    async def _search_knowledge_graph(self, query: str) -> List[str]:
        """Busca entidades y relaciones en el KG."""
        if self._knowledge_graph is None:
            return []
        try:
            # Buscar entidades que coincidan con palabras del query
            entities = self._knowledge_graph.search_entities(
                query=query,
                limit=_MAX_KG_RESULTS,
            )
            if not entities:
                return []

            items: List[str] = []
            for entity in entities[:3]:
                name = entity.get("name", "")
                etype = entity.get("entity_type", "")
                # Buscar relaciones de esta entidad
                relations = self._knowledge_graph.query_relations(
                    subject=name,
                    limit=3,
                )
                if relations:
                    rel_parts = []
                    for rel in relations:
                        pred = rel.get("predicate", "")
                        obj_name = rel.get("object_name", rel.get("object", ""))
                        rel_parts.append(f"{pred} {obj_name}")
                    rels_str = "; ".join(rel_parts)
                    items.append(
                        f"- KG [{etype}] {name}: {rels_str}"
                    )
                else:
                    items.append(f"- KG [{etype}] {name}")

            return items
        except Exception:
            logger.debug("Error buscando en KnowledgeGraph", exc_info=True)
            return []

    # ── Setters para inyección tardía de dependencias ─────────

    def set_memory_manager(self, manager: Any) -> None:
        """Permite inyectar el MemoryManager después de la construcción."""
        self._memory_manager = manager

    def set_lessons_memory(self, lessons: Any) -> None:
        """Permite inyectar LessonsMemory después de la construcción."""
        self._lessons_memory = lessons

    def set_episodic_memory(self, episodic: Any) -> None:
        """Permite inyectar EpisodicMemory después de la construcción."""
        self._episodic_memory = episodic

    def set_knowledge_graph(self, kg: Any) -> None:
        """Permite inyectar KnowledgeGraphStore después de la construcción."""
        self._knowledge_graph = kg
