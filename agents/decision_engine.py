"""Motor de decisiones autonomas para el agente.

Framework ligero de razonamiento que clasifica la intencion del usuario,
consulta la memoria para contexto relevante, y genera planes de ejecucion.
No hace llamadas al LLM — solo keyword matching + consultas a memoria.

Diseñado para degradacion elegante: si algun subsistema de memoria
no esta disponible, opera con menor contexto pero sin fallar.

Python 3.9+ — ``from __future__ import annotations``.
"""

from __future__ import annotations

import logging
import re
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ── Modelos Pydantic ──────────────────────────────────────────


class ActionType(str, Enum):
    """Tipo de accion solicitada por el usuario."""
    QUERY = "query"
    COMMAND = "command"
    CONVERSATION = "conversation"
    EMERGENCY = "emergency"


class ActionSafety(str, Enum):
    """Nivel de seguridad de una accion."""
    SAFE = "safe"
    MODERATE = "moderate"
    DANGEROUS = "dangerous"


class IntentAnalysis(BaseModel):
    """Resultado del analisis de intencion del usuario."""
    action_type: ActionType = ActionType.CONVERSATION
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    keywords_matched: List[str] = Field(default_factory=list)
    relevant_tools: List[str] = Field(default_factory=list)
    relevant_memories: List[Dict[str, Any]] = Field(default_factory=list)
    relevant_lessons: List[Dict[str, Any]] = Field(default_factory=list)
    suggested_approach: str = ""
    safety: ActionSafety = ActionSafety.SAFE
    raw_message: str = ""


class ExecutionStep(BaseModel):
    """Un paso en un plan de ejecucion."""
    order: int = 0
    description: str = ""
    tool: Optional[str] = None
    depends_on: List[int] = Field(default_factory=list)
    fallback: Optional[str] = None
    is_optional: bool = False


class ExecutionPlan(BaseModel):
    """Plan de ejecucion para solicitudes complejas."""
    steps: List[ExecutionStep] = Field(default_factory=list)
    estimated_complexity: str = "simple"
    requires_confirmation: bool = False
    rationale: str = ""


# ── Patrones de clasificacion (espanol) ───────────────────────

_QUERY_KEYWORDS = [
    "qué", "que", "cuánto", "cuanto", "cuándo", "cuando",
    "cómo", "como", "dónde", "donde", "quién", "quien",
    "muéstrame", "muestrame", "lista", "busca", "encuentra",
    "explica", "describe", "cuál", "cual", "por qué", "por que",
    "dame", "dime", "consulta", "revisa", "verifica",
]

_COMMAND_KEYWORDS = [
    "haz", "ejecuta", "crea", "elimina", "borra", "envía", "envia",
    "configura", "instala", "despliega", "deploy", "actualiza",
    "modifica", "cambia", "mueve", "copia", "renombra",
    "inicia", "detén", "deten", "para", "reinicia", "escribe",
    "genera", "construye", "compila", "publica", "sube",
    "descarga", "importa", "exporta", "migra", "restaura",
]

_CONVERSATION_KEYWORDS = [
    "hola", "buenos días", "buenos dias", "buenas tardes",
    "buenas noches", "gracias", "ok", "vale", "genial",
    "perfecto", "claro", "entiendo", "de acuerdo", "bien",
    "opino", "creo que", "pienso que", "me parece",
    "qué tal", "que tal", "cómo estás", "como estas",
]

_EMERGENCY_KEYWORDS = [
    "urgente", "error", "caído", "caido", "falla", "no funciona",
    "roto", "crítico", "critico", "emergencia", "ayuda urgente",
    "se cayó", "se cayo", "alerta", "incidente", "down",
    "bloqueado", "no responde", "timeout", "crash",
]

# Tools sugeridas segun tipo de intencion
_TOOL_SUGGESTIONS: Dict[ActionType, List[str]] = {
    ActionType.QUERY: ["memory_search", "kg_query", "web_search"],
    ActionType.COMMAND: ["shell", "file_write", "file_read"],
    ActionType.CONVERSATION: [],
    ActionType.EMERGENCY: ["shell", "memory_search", "kg_query"],
}

# Keywords peligrosas que requieren confirmacion
_DANGEROUS_KEYWORDS = [
    "elimina", "borra", "destruye", "drop", "trunca",
    "rm -rf", "delete", "purge", "wipe", "format",
    "producción", "produccion", "prod",
]


# ── DecisionEngine ────────────────────────────────────────────


class DecisionEngine:
    """Motor de decisiones autonomas basado en keyword matching y memoria.

    No hace llamadas al LLM. Clasifica la intencion del usuario,
    consulta los subsistemas de memoria para obtener contexto,
    y genera planes de ejecucion ligeros.

    Args:
        memory_manager: MemoryManager para buscar recuerdos relevantes.
        lessons_memory: LessonsMemory para buscar lecciones aplicables.
        episodic_memory: EpisodicMemory para buscar episodios similares.
        kg_manager: KnowledgeGraphStore para relaciones de entidades.
    """

    def __init__(
        self,
        memory_manager: Any = None,
        lessons_memory: Any = None,
        episodic_memory: Any = None,
        kg_manager: Any = None,
    ) -> None:
        self.memory = memory_manager
        self.lessons = lessons_memory
        self.episodic = episodic_memory
        self.kg = kg_manager

    # ── Analisis de intencion ─────────────────────────────────

    async def analyze_intent(self, user_message: str) -> IntentAnalysis:
        """Analiza la intencion del usuario sin llamar al LLM.

        Usa keyword matching para clasificar el tipo de accion,
        luego consulta los subsistemas de memoria para enriquecer
        el analisis con contexto relevante.

        Args:
            user_message: Mensaje del usuario a analizar.

        Returns:
            IntentAnalysis con tipo, confianza, tools y memorias relevantes.
        """
        text = user_message.lower().strip()

        # Clasificar por keywords
        action_type, confidence, matched = self._classify_intent(text)

        # Evaluar seguridad
        safety = self._assess_safety(text)

        # Buscar contexto en memoria (tolerante a fallos)
        memories = await self._search_memories(text)
        lessons = await self._search_lessons(text)

        # Tools sugeridas
        tools = list(_TOOL_SUGGESTIONS.get(action_type, []))

        # Generar sugerencia de enfoque
        approach = self._suggest_approach(action_type, safety, memories, lessons)

        return IntentAnalysis(
            action_type=action_type,
            confidence=confidence,
            keywords_matched=matched,
            relevant_tools=tools,
            relevant_memories=memories,
            relevant_lessons=lessons,
            suggested_approach=approach,
            safety=safety,
            raw_message=user_message,
        )

    # ── Autonomia ─────────────────────────────────────────────

    async def should_act_autonomously(self, intent: IntentAnalysis) -> bool:
        """Decide si el agente debe actuar sin pedir confirmacion.

        Criterios:
        - Confianza alta en la clasificacion (>= 0.6)
        - Accion segura (safety == SAFE)
        - No es una operacion destructiva
        - Para queries: siempre autonomo
        - Para commands: solo si es seguro y confianza alta
        - Para emergencias: siempre autonomo (la urgencia lo justifica)
        - Para conversacion: siempre autonomo

        Args:
            intent: Resultado del analisis de intencion.

        Returns:
            True si el agente puede actuar sin preguntar.
        """
        # Conversacion y queries: siempre autonomo
        if intent.action_type in (ActionType.CONVERSATION, ActionType.QUERY):
            return True

        # Emergencias: actuar rapido
        if intent.action_type == ActionType.EMERGENCY:
            return True

        # Comandos: depende de seguridad y confianza
        if intent.action_type == ActionType.COMMAND:
            if intent.safety == ActionSafety.DANGEROUS:
                return False
            if intent.safety == ActionSafety.MODERATE and intent.confidence < 0.7:
                return False
            return intent.confidence >= 0.6

        return False

    # ── Plan de ejecucion ─────────────────────────────────────

    async def get_execution_plan(self, intent: IntentAnalysis) -> ExecutionPlan:
        """Crea un plan de ejecucion ligero para solicitudes complejas.

        Genera pasos ordenados con dependencias y fallbacks basados
        en el tipo de intencion y las lecciones aprendidas.

        Args:
            intent: Resultado del analisis de intencion.

        Returns:
            ExecutionPlan con pasos, complejidad y justificacion.
        """
        steps: List[ExecutionStep] = []
        complexity = "simple"
        needs_confirmation = intent.safety == ActionSafety.DANGEROUS

        if intent.action_type == ActionType.QUERY:
            steps = self._plan_query(intent)
            complexity = "simple"

        elif intent.action_type == ActionType.COMMAND:
            steps = self._plan_command(intent)
            complexity = "moderate" if len(steps) > 2 else "simple"

        elif intent.action_type == ActionType.EMERGENCY:
            steps = self._plan_emergency(intent)
            complexity = "urgent"
            needs_confirmation = False  # No hay tiempo para confirmar

        elif intent.action_type == ActionType.CONVERSATION:
            steps = [
                ExecutionStep(
                    order=1,
                    description="Responder al usuario de forma conversacional",
                )
            ]

        # Inyectar advertencias de lecciones previas
        if intent.relevant_lessons:
            lesson_step = ExecutionStep(
                order=0,
                description=(
                    "Considerar lecciones previas: "
                    + "; ".join(
                        l.get("error", "")[:60]
                        for l in intent.relevant_lessons[:3]
                    )
                ),
                is_optional=True,
            )
            steps.insert(0, lesson_step)

        rationale = self._build_rationale(intent, steps)

        return ExecutionPlan(
            steps=steps,
            estimated_complexity=complexity,
            requires_confirmation=needs_confirmation,
            rationale=rationale,
        )

    # ── Clasificacion interna ─────────────────────────────────

    def _classify_intent(
        self, text: str
    ) -> tuple:
        """Clasifica la intencion por keyword matching.

        Returns:
            Tupla (ActionType, confidence, keywords_matched).
        """
        scores: Dict[ActionType, List[str]] = {
            ActionType.QUERY: [],
            ActionType.COMMAND: [],
            ActionType.CONVERSATION: [],
            ActionType.EMERGENCY: [],
        }

        for kw in _EMERGENCY_KEYWORDS:
            if kw in text:
                scores[ActionType.EMERGENCY].append(kw)

        for kw in _QUERY_KEYWORDS:
            if kw in text:
                scores[ActionType.QUERY].append(kw)

        for kw in _COMMAND_KEYWORDS:
            if kw in text:
                scores[ActionType.COMMAND].append(kw)

        for kw in _CONVERSATION_KEYWORDS:
            if kw in text:
                scores[ActionType.CONVERSATION].append(kw)

        # Elegir la categoria con mas matches
        best_type = ActionType.CONVERSATION
        best_count = 0
        best_matched: List[str] = []

        # Prioridad: emergency > command > query > conversation
        priority = [
            ActionType.EMERGENCY,
            ActionType.COMMAND,
            ActionType.QUERY,
            ActionType.CONVERSATION,
        ]

        for action_type in priority:
            matched = scores[action_type]
            count = len(matched)
            if count > best_count:
                best_type = action_type
                best_count = count
                best_matched = matched

        # Calcular confianza basada en densidad de keywords
        words_in_text = max(len(text.split()), 1)
        confidence = min(best_count / max(words_in_text * 0.3, 1), 1.0)

        # Minimo de confianza si hay al menos un match
        if best_count > 0 and confidence < 0.3:
            confidence = 0.3

        # Sin matches: baja confianza en conversacion
        if best_count == 0:
            best_type = ActionType.CONVERSATION
            confidence = 0.2

        return best_type, round(confidence, 2), best_matched

    def _assess_safety(self, text: str) -> ActionSafety:
        """Evalua el nivel de seguridad de la solicitud."""
        danger_count = sum(1 for kw in _DANGEROUS_KEYWORDS if kw in text)

        if danger_count >= 2:
            return ActionSafety.DANGEROUS
        if danger_count == 1:
            return ActionSafety.MODERATE
        return ActionSafety.SAFE

    # ── Busquedas en memoria ──────────────────────────────────

    async def _search_memories(self, text: str) -> List[Dict[str, Any]]:
        """Busca recuerdos relevantes en MemoryManager."""
        if not self.memory:
            return []
        try:
            results = await self.memory.search(query=text, limit=5)
            return [
                {
                    "id": entry.id,
                    "content": entry.content[:200],
                    "category": entry.category.value if hasattr(entry.category, "value") else str(entry.category),
                    "importance": entry.importance,
                    "score": entry.score,
                }
                for entry in results
            ]
        except Exception:
            logger.debug("DecisionEngine: fallo buscando memorias", exc_info=True)
            return []

    async def _search_lessons(self, text: str) -> List[Dict[str, Any]]:
        """Busca lecciones aplicables en LessonsMemory."""
        if not self.lessons:
            return []
        try:
            return self.lessons.recall_lessons(query=text, limit=3)
        except Exception:
            logger.debug("DecisionEngine: fallo buscando lecciones", exc_info=True)
            return []

    # ── Generacion de planes ──────────────────────────────────

    def _plan_query(self, intent: IntentAnalysis) -> List[ExecutionStep]:
        """Plan para solicitudes de consulta."""
        steps = [
            ExecutionStep(
                order=1,
                description="Buscar en memoria y knowledge graph",
                tool="memory_search",
            ),
        ]
        # Si hay herramientas relevantes, agregar paso de consulta
        if "kg_query" in intent.relevant_tools:
            steps.append(ExecutionStep(
                order=2,
                description="Consultar grafo de conocimiento",
                tool="kg_query",
                depends_on=[1],
                is_optional=True,
            ))
        steps.append(ExecutionStep(
            order=len(steps) + 1,
            description="Sintetizar respuesta con informacion recopilada",
            depends_on=[s.order for s in steps],
        ))
        return steps

    def _plan_command(self, intent: IntentAnalysis) -> List[ExecutionStep]:
        """Plan para solicitudes de comando."""
        steps = [
            ExecutionStep(
                order=1,
                description="Verificar lecciones previas para esta accion",
                is_optional=True,
            ),
            ExecutionStep(
                order=2,
                description="Ejecutar la accion solicitada",
                depends_on=[1],
            ),
            ExecutionStep(
                order=3,
                description="Verificar resultado y reportar",
                depends_on=[2],
                fallback="Reportar error y sugerir alternativa",
            ),
        ]
        return steps

    def _plan_emergency(self, intent: IntentAnalysis) -> List[ExecutionStep]:
        """Plan para solicitudes de emergencia."""
        return [
            ExecutionStep(
                order=1,
                description="Diagnosticar el problema inmediatamente",
                tool="shell",
            ),
            ExecutionStep(
                order=2,
                description="Buscar soluciones en lecciones previas",
                tool="memory_search",
                depends_on=[1],
            ),
            ExecutionStep(
                order=3,
                description="Aplicar solucion o workaround",
                depends_on=[1, 2],
                fallback="Escalar y notificar",
            ),
            ExecutionStep(
                order=4,
                description="Confirmar que el problema se resolvio",
                depends_on=[3],
            ),
        ]

    # ── Helpers ───────────────────────────────────────────────

    def _suggest_approach(
        self,
        action_type: ActionType,
        safety: ActionSafety,
        memories: List[Dict[str, Any]],
        lessons: List[Dict[str, Any]],
    ) -> str:
        """Genera una sugerencia textual del enfoque recomendado."""
        parts: List[str] = []

        if action_type == ActionType.EMERGENCY:
            parts.append("Prioridad maxima: diagnosticar y resolver rapido.")
        elif action_type == ActionType.COMMAND:
            parts.append("Ejecutar la accion solicitada.")
        elif action_type == ActionType.QUERY:
            parts.append("Buscar informacion y responder.")
        else:
            parts.append("Conversar normalmente.")

        if safety == ActionSafety.DANGEROUS:
            parts.append("PRECAUCION: accion potencialmente destructiva, pedir confirmacion.")
        elif safety == ActionSafety.MODERATE:
            parts.append("Precaucion moderada: verificar antes de ejecutar.")

        if memories:
            parts.append(f"Hay {len(memories)} recuerdos relevantes disponibles.")

        if lessons:
            parts.append(f"Hay {len(lessons)} lecciones previas aplicables.")

        return " ".join(parts)

    def _build_rationale(
        self,
        intent: IntentAnalysis,
        steps: List[ExecutionStep],
    ) -> str:
        """Construye la justificacion del plan."""
        return (
            f"Tipo: {intent.action_type.value} "
            f"(confianza: {intent.confidence:.0%}). "
            f"Seguridad: {intent.safety.value}. "
            f"Plan de {len(steps)} paso(s)."
        )
