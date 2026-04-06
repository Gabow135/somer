"""Capa cognitiva — orquesta auto-aprendizaje y toma de decisiones.

Integra AutoLearner y DecisionEngine en un punto unico de entrada
que se invoca antes y despues de cada respuesta del agente.

Antes de responder: analiza intencion, busca contexto, genera plan.
Despues de responder: extrae conocimiento y lo almacena.

Python 3.9+ — ``from __future__ import annotations``.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from agents.decision_engine import (
    ActionType,
    DecisionEngine,
    ExecutionPlan,
    IntentAnalysis,
)
from memory.auto_learner import AutoLearner, Extraction

logger = logging.getLogger(__name__)


# ── Modelos de contexto cognitivo ─────────────────────────────


class CognitiveContext(BaseModel):
    """Contexto cognitivo generado antes de la respuesta del LLM.

    Contiene el analisis de intencion, plan de ejecucion,
    y la decision de autonomia para el turno actual.
    """
    intent: IntentAnalysis = Field(default_factory=IntentAnalysis)
    plan: ExecutionPlan = Field(default_factory=ExecutionPlan)
    should_act: bool = False
    processing_time_ms: float = 0.0
    session_id: Optional[str] = None


class LearningResult(BaseModel):
    """Resultado del aprendizaje post-respuesta."""
    extractions_count: int = 0
    extractions: List[Dict[str, Any]] = Field(default_factory=list)
    processing_time_ms: float = 0.0
    session_id: Optional[str] = None


# ── CognitiveLayer ────────────────────────────────────────────


class CognitiveLayer:
    """Orquesta los sistemas cognitivos del agente.

    Punto de integracion entre AutoLearner (aprendizaje automatico)
    y DecisionEngine (toma de decisiones). Se conecta al ciclo de vida
    del agente via ``before_response`` y ``after_response``.

    Uso tipico::

        cognitive = CognitiveLayer(
            memory_manager=memory,
            kg_manager=kg_store,
            lessons_memory=lessons,
            episodic_memory=episodic,
        )

        # Antes de generar respuesta
        ctx = await cognitive.before_response(user_msg, session_id)
        # ... generar respuesta con LLM ...

        # Despues de enviar respuesta
        result = await cognitive.after_response(
            user_msg, response, tool_results, session_id
        )

    Args:
        memory_manager: MemoryManager para almacenamiento general.
        kg_manager: KnowledgeGraphStore para grafo de conocimiento.
        lessons_memory: LessonsMemory para lecciones aprendidas.
        episodic_memory: EpisodicMemory para episodios.
    """

    def __init__(
        self,
        memory_manager: Any = None,
        kg_manager: Any = None,
        lessons_memory: Any = None,
        episodic_memory: Any = None,
    ) -> None:
        self.auto_learner = AutoLearner(
            memory_manager=memory_manager,
            kg_manager=kg_manager,
            lessons_memory=lessons_memory,
        )
        self.decision_engine = DecisionEngine(
            memory_manager=memory_manager,
            lessons_memory=lessons_memory,
            episodic_memory=episodic_memory,
            kg_manager=kg_manager,
        )
        self._enabled = True

    # ── Control ───────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        """Indica si la capa cognitiva esta activa."""
        return self._enabled

    def enable(self) -> None:
        """Activa la capa cognitiva."""
        self._enabled = True
        logger.info("CognitiveLayer activada")

    def disable(self) -> None:
        """Desactiva la capa cognitiva."""
        self._enabled = False
        logger.info("CognitiveLayer desactivada")

    # ── Pre-respuesta ─────────────────────────────────────────

    async def before_response(
        self,
        user_message: str,
        session_id: Optional[str] = None,
    ) -> CognitiveContext:
        """Analiza el mensaje del usuario antes de generar la respuesta.

        Ejecuta el analisis de intencion, genera un plan de ejecucion,
        y decide si el agente debe actuar autonomamente.

        Args:
            user_message: Mensaje del usuario.
            session_id: ID de sesion actual.

        Returns:
            CognitiveContext con toda la informacion pre-respuesta.
        """
        if not self._enabled:
            return CognitiveContext(session_id=session_id)

        start = time.monotonic()

        try:
            # 1. Analizar intencion
            intent = await self.decision_engine.analyze_intent(user_message)

            # 2. Decidir autonomia
            should_act = await self.decision_engine.should_act_autonomously(intent)

            # 3. Generar plan de ejecucion
            plan = await self.decision_engine.get_execution_plan(intent)

            elapsed = (time.monotonic() - start) * 1000

            ctx = CognitiveContext(
                intent=intent,
                plan=plan,
                should_act=should_act,
                processing_time_ms=round(elapsed, 2),
                session_id=session_id,
            )

            logger.debug(
                "CognitiveLayer.before: tipo=%s confianza=%.2f autonomo=%s "
                "plan=%d pasos (%.1fms) session=%s",
                intent.action_type.value,
                intent.confidence,
                should_act,
                len(plan.steps),
                elapsed,
                session_id or "?",
            )

            return ctx

        except Exception:
            logger.warning(
                "CognitiveLayer.before_response fallo, retornando contexto vacio",
                exc_info=True,
            )
            elapsed = (time.monotonic() - start) * 1000
            return CognitiveContext(
                processing_time_ms=round(elapsed, 2),
                session_id=session_id,
            )

    # ── Post-respuesta ────────────────────────────────────────

    async def after_response(
        self,
        user_message: str,
        assistant_response: str,
        tool_results: Optional[List[Dict[str, Any]]] = None,
        session_id: Optional[str] = None,
    ) -> LearningResult:
        """Extrae conocimiento despues de enviar la respuesta.

        Invoca al AutoLearner para analizar el turno completo
        y almacenar automaticamente lo aprendido.

        Args:
            user_message: Mensaje original del usuario.
            assistant_response: Respuesta generada por el agente.
            tool_results: Resultados de tools ejecutadas.
            session_id: ID de sesion actual.

        Returns:
            LearningResult con las extracciones realizadas.
        """
        if not self._enabled:
            return LearningResult(session_id=session_id)

        start = time.monotonic()

        try:
            extractions = await self.auto_learner.learn_from_turn(
                user_message=user_message,
                assistant_response=assistant_response,
                tool_results=tool_results,
                session_id=session_id,
            )

            elapsed = (time.monotonic() - start) * 1000

            result = LearningResult(
                extractions_count=len(extractions),
                extractions=[
                    {
                        "type": e.extraction_type.value,
                        "content": e.content[:200],
                        "confidence": e.confidence,
                    }
                    for e in extractions
                ],
                processing_time_ms=round(elapsed, 2),
                session_id=session_id,
            )

            if extractions:
                logger.debug(
                    "CognitiveLayer.after: %d extracciones (%.1fms) session=%s",
                    len(extractions),
                    elapsed,
                    session_id or "?",
                )

            return result

        except Exception:
            logger.warning(
                "CognitiveLayer.after_response fallo",
                exc_info=True,
            )
            elapsed = (time.monotonic() - start) * 1000
            return LearningResult(
                processing_time_ms=round(elapsed, 2),
                session_id=session_id,
            )

    # ── Utilidades ────────────────────────────────────────────

    async def quick_classify(self, user_message: str) -> ActionType:
        """Clasificacion rapida sin buscar en memoria.

        Util para filtrado o routing rapido donde no se necesita
        el contexto completo de IntentAnalysis.

        Args:
            user_message: Mensaje del usuario.

        Returns:
            ActionType clasificado.
        """
        intent = await self.decision_engine.analyze_intent(user_message)
        return intent.action_type

    def get_system_prompt_additions(self, ctx: CognitiveContext) -> str:
        """Genera adiciones al system prompt basadas en el contexto cognitivo.

        Puede usarse para inyectar contexto relevante en el prompt
        del LLM antes de generar la respuesta.

        Args:
            ctx: CognitiveContext del turno actual.

        Returns:
            Texto adicional para el system prompt (vacio si no hay nada).
        """
        parts: List[str] = []

        # Agregar memorias relevantes
        if ctx.intent.relevant_memories:
            memories_text = "\n".join(
                f"- {m['content']}"
                for m in ctx.intent.relevant_memories[:3]
            )
            parts.append(f"Recuerdos relevantes:\n{memories_text}")

        # Agregar lecciones relevantes
        if ctx.intent.relevant_lessons:
            lessons_text = "\n".join(
                f"- {l.get('error', '')[:80]} → {l.get('solution', '')[:80]}"
                for l in ctx.intent.relevant_lessons[:3]
            )
            parts.append(f"Lecciones previas:\n{lessons_text}")

        # Agregar plan si es complejo
        if ctx.plan.estimated_complexity != "simple" and ctx.plan.steps:
            plan_text = "\n".join(
                f"  {s.order}. {s.description}"
                for s in ctx.plan.steps
            )
            parts.append(f"Plan sugerido:\n{plan_text}")

        # Agregar advertencia de seguridad
        if ctx.plan.requires_confirmation:
            parts.append(
                "ADVERTENCIA: La accion solicitada es potencialmente "
                "destructiva. Pedir confirmacion antes de ejecutar."
            )

        return "\n\n".join(parts)
