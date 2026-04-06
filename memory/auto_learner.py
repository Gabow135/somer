"""Auto-aprendizaje desde conversaciones.

Extrae automaticamente conocimiento de cada turno de conversacion
y lo almacena en los sistemas de memoria correspondientes:
- Preferencias del usuario → Knowledge Graph
- Hechos sobre personas/proyectos → Knowledge Graph
- Lecciones de errores → LessonsMemory
- Fragmentos importantes → MemoryManager

Diseñado para ser no bloqueante: si algun subsistema falla,
el resto continua sin afectar la respuesta al usuario.

Python 3.9+ — ``from __future__ import annotations``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Tipos de extraccion ────────────────────────────────────────


class ExtractionType(str, Enum):
    """Tipo de conocimiento extraido de una conversacion."""
    PREFERENCE = "preference"
    FACT = "fact"
    LESSON = "lesson"
    DECISION = "decision"
    ACTION_PATTERN = "action_pattern"
    IMPORTANT_FRAGMENT = "important_fragment"


@dataclass
class Extraction:
    """Un dato extraido de la conversacion."""
    extraction_type: ExtractionType
    content: str
    subject: str = ""
    predicate: str = ""
    obj: str = ""
    tags: List[str] = field(default_factory=list)
    confidence: float = 0.5
    source_text: str = ""


# ── Patrones de deteccion (espanol) ───────────────────────────

# Preferencias positivas (negative lookbehind para evitar "no me gusta")
_PREF_POSITIVE = re.compile(
    r"(?<!\bno\s)(?:yo\s+)?(?:prefiero|me gusta|quiero|siempre(?:\s+quiero)?|"
    r"me encanta|favorito es|elijo|opto por|me va mejor con)\s+(.+)",
    re.IGNORECASE,
)

# Preferencias negativas
_PREF_NEGATIVE = re.compile(
    r"(?:yo\s+)?(?:no me gusta|no quiero|nunca|odio|detesto|"
    r"evito|no uso|prefiero no|no soporto)\s+(.+)",
    re.IGNORECASE,
)

# Hechos: "X trabaja en Y", "X es Y", "X usa Y", etc.
_FACT_PATTERNS = [
    # "Juan trabaja en Acme"
    re.compile(
        r"(\w[\w\s]{0,30}?)\s+trabaja(?:\s+en)\s+(.+)",
        re.IGNORECASE,
    ),
    # "el proyecto usa React"
    re.compile(
        r"(?:el\s+)?(\w[\w\s]{0,30}?)\s+usa(?:mos)?\s+(.+)",
        re.IGNORECASE,
    ),
    # "X es Y" (solo frases cortas para evitar falsos positivos)
    re.compile(
        r"(\w[\w\s]{0,20}?)\s+es\s+([\w\s]{2,40}?)(?:\.|,|$)",
        re.IGNORECASE,
    ),
    # "X tiene Y"
    re.compile(
        r"(?:el\s+|la\s+)?(\w[\w\s]{0,30}?)\s+tiene\s+(.+)",
        re.IGNORECASE,
    ),
    # "X se llama Y"
    re.compile(
        r"(\w[\w\s]{0,20}?)\s+se\s+llama\s+(.+)",
        re.IGNORECASE,
    ),
    # "X depende de Y"
    re.compile(
        r"(?:el\s+|la\s+)?(\w[\w\s]{0,30}?)\s+depende\s+de\s+(.+)",
        re.IGNORECASE,
    ),
    # "X pertenece a Y"
    re.compile(
        r"(?:el\s+|la\s+)?(\w[\w\s]{0,30}?)\s+pertenece\s+a\s+(.+)",
        re.IGNORECASE,
    ),
]

# Decisiones
_DECISION_PATTERN = re.compile(
    r"(?:decidimos|acordamos|vamos a|la solucion es|la decision es|"
    r"el plan es|haremos|implementaremos|optamos por)\s+(.+)",
    re.IGNORECASE,
)

# Longitud minima para considerar un fragmento "importante"
_MIN_IMPORTANT_LENGTH = 200


# ── AutoLearner ────────────────────────────────────────────────


class AutoLearner:
    """Extrae conocimiento de conversaciones y lo almacena automaticamente.

    Se invoca despues de cada turno de conversacion. Es tolerante a fallos:
    si un subsistema de memoria no esta disponible, se loguea el error
    y se continua con los demas.

    Args:
        memory_manager: Instancia de MemoryManager (almacen general).
        kg_manager: Instancia de KnowledgeGraphStore (grafo de conocimiento).
        lessons_memory: Instancia de LessonsMemory (lecciones aprendidas).
    """

    def __init__(
        self,
        memory_manager: Any = None,
        kg_manager: Any = None,
        lessons_memory: Any = None,
    ) -> None:
        self.memory = memory_manager
        self.kg = kg_manager
        self.lessons = lessons_memory

    # ── API publica ───────────────────────────────────────────

    async def learn_from_turn(
        self,
        user_message: str,
        assistant_response: str,
        tool_results: Optional[List[Dict[str, Any]]] = None,
        session_id: Optional[str] = None,
    ) -> List[Extraction]:
        """Extrae y almacena conocimiento de un turno de conversacion.

        Analiza el mensaje del usuario y la respuesta del asistente
        para extraer preferencias, hechos, lecciones y fragmentos
        importantes. Almacena cada extraccion en el subsistema
        correspondiente.

        Args:
            user_message: Mensaje original del usuario.
            assistant_response: Respuesta generada por el asistente.
            tool_results: Resultados de tools ejecutadas (lista de dicts
                con al menos ``content`` y opcionalmente ``is_error``).
            session_id: ID de sesion para contexto.

        Returns:
            Lista de Extraction con todo lo aprendido en este turno.
        """
        tool_results = tool_results or []
        all_extractions: List[Extraction] = []

        # 1. Preferencias del usuario
        prefs = self._extract_preferences(user_message)
        all_extractions.extend(prefs)

        # 2. Hechos sobre entidades
        facts = self._extract_facts(user_message)
        all_extractions.extend(facts)

        # 3. Lecciones de errores
        lessons = self._extract_lessons_from_errors(
            user_message, assistant_response, tool_results
        )
        all_extractions.extend(lessons)

        # 4. Patrones de accion (secuencias de tools exitosas)
        patterns = self._extract_action_patterns(tool_results)
        all_extractions.extend(patterns)

        # 5. Decisiones
        decisions = self._extract_decisions(user_message)
        all_extractions.extend(decisions)

        # 6. Fragmentos importantes
        fragments = self._extract_important_fragments(
            user_message, assistant_response
        )
        all_extractions.extend(fragments)

        # Almacenar todo (tolerante a fallos)
        await self._store_extractions(all_extractions, session_id)

        if all_extractions:
            logger.info(
                "AutoLearner: %d extracciones de turno (session=%s)",
                len(all_extractions),
                session_id or "?",
            )

        return all_extractions

    # ── Extractores ───────────────────────────────────────────

    def _extract_preferences(self, text: str) -> List[Extraction]:
        """Detecta preferencias del usuario en el texto."""
        extractions: List[Extraction] = []

        match = _PREF_POSITIVE.search(text)
        if match:
            value = match.group(1).strip().rstrip(".")
            extractions.append(Extraction(
                extraction_type=ExtractionType.PREFERENCE,
                content=f"El usuario prefiere: {value}",
                subject="usuario",
                predicate="prefers",
                obj=value,
                tags=["preferencia", "positiva"],
                confidence=0.7,
                source_text=match.group(0),
            ))

        match = _PREF_NEGATIVE.search(text)
        if match:
            value = match.group(1).strip().rstrip(".")
            extractions.append(Extraction(
                extraction_type=ExtractionType.PREFERENCE,
                content=f"El usuario no quiere: {value}",
                subject="usuario",
                predicate="dislikes",
                obj=value,
                tags=["preferencia", "negativa"],
                confidence=0.7,
                source_text=match.group(0),
            ))

        return extractions

    def _extract_facts(self, text: str) -> List[Extraction]:
        """Detecta hechos sobre personas, proyectos y entidades."""
        extractions: List[Extraction] = []
        seen: set = set()

        for pattern in _FACT_PATTERNS:
            for match in pattern.finditer(text):
                subject = match.group(1).strip()
                obj = match.group(2).strip().rstrip(".,;")

                # Evitar extracciones triviales o duplicadas
                key = (subject.lower(), obj.lower())
                if key in seen:
                    continue
                if len(subject) < 2 or len(obj) < 2:
                    continue
                # Filtrar articulos sueltos como sujeto
                if subject.lower() in ("el", "la", "los", "las", "un", "una", "yo", "tu"):
                    continue
                seen.add(key)

                # Determinar predicado del regex
                match_text = match.group(0).lower()
                if "trabaja" in match_text:
                    predicate = "works_at"
                elif "usa" in match_text:
                    predicate = "uses"
                elif " es " in match_text:
                    predicate = "is"
                elif "tiene" in match_text:
                    predicate = "has"
                elif "llama" in match_text:
                    predicate = "named"
                elif "depende" in match_text:
                    predicate = "depends_on"
                elif "pertenece" in match_text:
                    predicate = "belongs_to"
                else:
                    predicate = "related_to"

                extractions.append(Extraction(
                    extraction_type=ExtractionType.FACT,
                    content=f"{subject} {predicate} {obj}",
                    subject=subject,
                    predicate=predicate,
                    obj=obj,
                    tags=["hecho", "auto_extraido"],
                    confidence=0.6,
                    source_text=match.group(0),
                ))

        return extractions

    def _extract_lessons_from_errors(
        self,
        user_message: str,
        assistant_response: str,
        tool_results: List[Dict[str, Any]],
    ) -> List[Extraction]:
        """Detecta errores en tool_results y crea lecciones."""
        extractions: List[Extraction] = []

        for result in tool_results:
            is_error = result.get("is_error", False)
            if not is_error:
                continue

            content = result.get("content", "")
            tool_name = result.get("tool_name", result.get("name", "unknown"))

            extractions.append(Extraction(
                extraction_type=ExtractionType.LESSON,
                content=content,
                subject=tool_name,
                predicate="caused_error",
                obj=content[:100] if content else "error desconocido",
                tags=["error", "auto_lesson", tool_name],
                confidence=0.8,
                source_text=content[:300],
            ))

        return extractions

    def _extract_action_patterns(
        self, tool_results: List[Dict[str, Any]]
    ) -> List[Extraction]:
        """Detecta secuencias exitosas de tools (patrones de accion).

        Si hay 2+ tools ejecutadas sin errores en secuencia,
        se registra como un patron reutilizable.
        """
        extractions: List[Extraction] = []

        successful_tools = [
            r.get("tool_name", r.get("name", "unknown"))
            for r in tool_results
            if not r.get("is_error", False) and r.get("content", "")
        ]

        if len(successful_tools) >= 2:
            sequence = " → ".join(successful_tools)
            extractions.append(Extraction(
                extraction_type=ExtractionType.ACTION_PATTERN,
                content=f"Secuencia exitosa: {sequence}",
                tags=["patron_accion", "auto_extraido"] + successful_tools,
                confidence=0.5,
                source_text=sequence,
            ))

        return extractions

    def _extract_decisions(self, text: str) -> List[Extraction]:
        """Detecta decisiones o acuerdos en el texto."""
        extractions: List[Extraction] = []

        match = _DECISION_PATTERN.search(text)
        if match:
            decision = match.group(1).strip().rstrip(".")
            extractions.append(Extraction(
                extraction_type=ExtractionType.DECISION,
                content=f"Decision: {decision}",
                tags=["decision", "auto_extraido"],
                confidence=0.7,
                source_text=match.group(0),
            ))

        return extractions

    def _extract_important_fragments(
        self, user_message: str, assistant_response: str
    ) -> List[Extraction]:
        """Marca fragmentos largos o relevantes para almacenamiento.

        Se considera importante si el mensaje del usuario es largo
        (indicando que proporciona contexto detallado).
        """
        extractions: List[Extraction] = []

        if len(user_message) >= _MIN_IMPORTANT_LENGTH:
            extractions.append(Extraction(
                extraction_type=ExtractionType.IMPORTANT_FRAGMENT,
                content=user_message[:1000],
                tags=["fragmento_importante", "contexto_usuario"],
                confidence=0.4,
                source_text=user_message[:200],
            ))

        return extractions

    # ── Almacenamiento ────────────────────────────────────────

    async def _store_extractions(
        self,
        extractions: List[Extraction],
        session_id: Optional[str] = None,
    ) -> None:
        """Almacena las extracciones en los subsistemas correspondientes.

        Cada subsistema se invoca de forma independiente. Si uno falla,
        se loguea el error y se continua con el resto.
        """
        for ext in extractions:
            try:
                if ext.extraction_type == ExtractionType.PREFERENCE:
                    await self._store_preference(ext)
                elif ext.extraction_type == ExtractionType.FACT:
                    await self._store_fact(ext)
                elif ext.extraction_type == ExtractionType.LESSON:
                    await self._store_lesson(ext)
                elif ext.extraction_type == ExtractionType.DECISION:
                    await self._store_decision(ext, session_id)
                elif ext.extraction_type == ExtractionType.ACTION_PATTERN:
                    await self._store_action_pattern(ext, session_id)
                elif ext.extraction_type == ExtractionType.IMPORTANT_FRAGMENT:
                    await self._store_fragment(ext, session_id)
            except Exception:
                logger.warning(
                    "AutoLearner: fallo al almacenar extraccion tipo=%s",
                    ext.extraction_type.value,
                    exc_info=True,
                )

    async def _store_preference(self, ext: Extraction) -> None:
        """Almacena una preferencia en el KG."""
        if not self.kg:
            return
        self.kg.add_relation(
            ext.subject,
            ext.predicate,
            ext.obj,
            source="auto_learner",
        )
        logger.debug("KG: preferencia almacenada — %s %s %s",
                      ext.subject, ext.predicate, ext.obj)

    async def _store_fact(self, ext: Extraction) -> None:
        """Almacena un hecho en el KG."""
        if not self.kg:
            return
        self.kg.add_relation(
            ext.subject,
            ext.predicate,
            ext.obj,
            source="auto_learner",
        )
        logger.debug("KG: hecho almacenado — %s %s %s",
                      ext.subject, ext.predicate, ext.obj)

    async def _store_lesson(self, ext: Extraction) -> None:
        """Almacena una leccion de error en LessonsMemory."""
        if not self.lessons:
            return
        self.lessons.save_lesson(
            context=ext.source_text,
            error=ext.obj,
            solution="(pendiente — error detectado automaticamente)",
            tags=ext.tags,
            tool_name=ext.subject,
            severity="warning",
        )
        logger.debug("Leccion almacenada para tool=%s", ext.subject)

    async def _store_decision(
        self, ext: Extraction, session_id: Optional[str]
    ) -> None:
        """Almacena una decision en MemoryManager."""
        if not self.memory:
            return
        # Importar aqui para evitar circular imports
        from shared.types import MemoryCategory, MemorySource

        await self.memory.store(
            content=ext.content,
            session_id=session_id,
            category=MemoryCategory.KNOWLEDGE,
            tags=ext.tags,
            source=MemorySource.MEMORY,
            importance=0.7,
        )
        logger.debug("Decision almacenada en memoria")

    async def _store_action_pattern(
        self, ext: Extraction, session_id: Optional[str]
    ) -> None:
        """Almacena un patron de accion en MemoryManager."""
        if not self.memory:
            return
        from shared.types import MemoryCategory, MemorySource

        await self.memory.store(
            content=ext.content,
            session_id=session_id,
            category=MemoryCategory.TASK,
            tags=ext.tags,
            source=MemorySource.MEMORY,
            importance=0.5,
        )
        logger.debug("Patron de accion almacenado")

    async def _store_fragment(
        self, ext: Extraction, session_id: Optional[str]
    ) -> None:
        """Almacena un fragmento importante en MemoryManager."""
        if not self.memory:
            return
        from shared.types import MemoryCategory, MemorySource

        await self.memory.store(
            content=ext.content,
            session_id=session_id,
            category=MemoryCategory.CONVERSATION,
            tags=ext.tags,
            source=MemorySource.SESSIONS,
            importance=0.4,
        )
        logger.debug("Fragmento importante almacenado")
