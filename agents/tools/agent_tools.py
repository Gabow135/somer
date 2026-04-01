"""Tools que exponen agentes especializados al agent runner.

Permite al agente principal invocar researcher y data_analyst
como tools directamente desde la conversación.

Python 3.9+ — ``from __future__ import annotations``.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from agents.tools.registry import (
    ToolDefinition,
    ToolProfile,
    ToolRegistry,
    ToolSection,
)

logger = logging.getLogger(__name__)


# ── Handlers ─────────────────────────────────────────────────


async def _research_handler(args: Dict[str, Any]) -> str:
    """Ejecuta una investigación usando el ResearchAgent."""
    from agents.researcher import ResearchAgent, ResearchDepth

    query = args.get("query", "").strip()
    if not query:
        return json.dumps({"error": "query es requerido."})

    depth_str = args.get("depth", "standard")
    try:
        depth = ResearchDepth(depth_str)
    except ValueError:
        depth = ResearchDepth.STANDARD

    context = args.get("context", "")
    max_sources = args.get("max_sources", 10)

    # Crear agente con búsqueda web si está disponible
    search_func = None
    try:
        from web_search.manager import get_search_manager
        manager = get_search_manager()
        if manager:
            async def _web_search(q: str, limit: int) -> list:
                results = await manager.search(q, max_results=limit)
                return [
                    {"title": r.title, "url": r.url, "content": r.snippet, "score": r.score}
                    for r in results
                ]
            search_func = _web_search
    except Exception:
        pass

    agent = ResearchAgent(search_func=search_func)
    result = await agent.research(
        query, depth=depth, context=context, max_sources=max_sources,
    )

    return json.dumps(result.to_dict(), ensure_ascii=False)


async def _analyze_data_handler(args: Dict[str, Any]) -> str:
    """Ejecuta análisis de datos usando el DataAnalystAgent."""
    from agents.data_analyst import DataAnalystAgent, DataSource, AnalysisType

    source_path = args.get("source", "").strip()
    if not source_path:
        return json.dumps({"error": "source es requerido (ruta a CSV/JSON o DSN)."})

    analysis_str = args.get("analysis_type", "summary")
    try:
        analysis_type = AnalysisType(analysis_str)
    except ValueError:
        analysis_type = AnalysisType.SUMMARY

    title = args.get("title", "")
    custom_code = args.get("custom_code", "")

    # Detectar tipo de fuente
    source_type = "file"
    fmt = "csv"
    if source_path.startswith(("postgres://", "postgresql://", "mysql://")):
        source_type = "sql"
    elif source_path.endswith(".json"):
        fmt = "json"
    elif source_path.endswith((".xlsx", ".xls")):
        fmt = "excel"

    source = DataSource(
        source_type=source_type,
        path=source_path,
        format=fmt,
    )

    # Crear ejecutor de código
    async def _code_exec(code: str, desc: str) -> Dict[str, Any]:
        from agents.tools.code_interpreter_tools import _code_interpreter_handler
        result_str = await _code_interpreter_handler({
            "code": code,
            "description": desc,
        })
        return json.loads(result_str)

    agent = DataAnalystAgent(code_exec_func=_code_exec)
    result = await agent.analyze(
        source,
        analysis_type=analysis_type,
        title=title,
        custom_code=custom_code,
    )

    return json.dumps(result.to_dict(), ensure_ascii=False)


async def _plan_task_handler(args: Dict[str, Any]) -> str:
    """Crea un plan para un objetivo usando el PlanningEngine."""
    from agents.planning import PlanningEngine, Plan

    goal = args.get("goal", "").strip()
    if not goal:
        return json.dumps({"error": "goal es requerido."})

    context = args.get("context", "")
    steps = args.get("steps")

    engine = PlanningEngine()
    plan = await engine.create_plan(goal, context=context, steps=steps)

    return json.dumps({
        "plan_id": plan.id,
        "goal": plan.goal,
        "status": plan.status.value,
        "steps": [s.to_dict() for s in plan.steps],
        "markdown": plan.to_markdown(),
    }, ensure_ascii=False)


async def _messaging_handler(args: Dict[str, Any]) -> str:
    """Envía o consulta mensajes inter-agente."""
    from agents.messaging import get_message_bus, AgentMessage, MessageType

    action = args.get("action", "status")
    bus = get_message_bus()

    if action == "send":
        from_agent = args.get("from_agent", "main")
        to_agent = args.get("to_agent", "")
        topic = args.get("topic", "")
        payload = args.get("payload", {})

        if not to_agent or not topic:
            return json.dumps({"error": "to_agent y topic son requeridos."})

        msg = AgentMessage(
            from_agent=from_agent,
            to_agent=to_agent,
            topic=topic,
            payload=payload,
        )
        msg_id = await bus.send(msg)
        return json.dumps({"status": "sent", "message_id": msg_id})

    elif action == "inbox":
        agent_id = args.get("agent_id", "main")
        messages = await bus.get_messages(agent_id, unread_only=True)
        return json.dumps({
            "agent_id": agent_id,
            "messages": [m.to_dict() for m in messages],
            "count": len(messages),
        }, ensure_ascii=False)

    elif action == "broadcast":
        from_agent = args.get("from_agent", "main")
        topic = args.get("topic", "")
        payload = args.get("payload", {})

        msg = AgentMessage(
            from_agent=from_agent,
            topic=topic,
            message_type=MessageType.BROADCAST,
            payload=payload,
        )
        msg_id = await bus.send(msg)
        return json.dumps({"status": "broadcast", "message_id": msg_id})

    elif action == "status":
        return json.dumps(bus.status())

    return json.dumps({"error": f"Acción no válida: {action}"})


async def _episodic_recall_handler(args: Dict[str, Any]) -> str:
    """Busca episodios similares en la memoria episódica."""
    from memory.episodic import EpisodicMemory

    query = args.get("query", "").strip()
    tags = args.get("tags", [])
    limit = args.get("limit", 5)

    memory = EpisodicMemory()
    episodes = memory.recall(query, tags=tags, limit=limit)
    memory.close()

    return json.dumps({
        "query": query,
        "episodes": [e.to_dict() for e in episodes],
        "count": len(episodes),
    }, ensure_ascii=False)


async def _episodic_save_handler(args: Dict[str, Any]) -> str:
    """Guarda un episodio en la memoria episódica."""
    from memory.episodic import EpisodicMemory, Episode, EpisodeStep, EpisodeOutcome

    title = args.get("title", "").strip()
    if not title:
        return json.dumps({"error": "title es requerido."})

    description = args.get("description", "")
    trigger = args.get("trigger_pattern", "")
    tags = args.get("tags", [])
    raw_steps = args.get("steps", [])

    steps = []
    for i, s in enumerate(raw_steps, 1):
        steps.append(EpisodeStep(
            step_index=i,
            action_type=s.get("type", "tool"),
            action_name=s.get("action", ""),
            action_args=s.get("args", {}),
            result_summary=s.get("result", ""),
            success=s.get("success", True),
        ))

    outcome_str = args.get("outcome", "success")
    try:
        outcome = EpisodeOutcome(outcome_str)
    except ValueError:
        outcome = EpisodeOutcome.SUCCESS

    episode = Episode(
        title=title,
        description=description,
        trigger_pattern=trigger,
        steps=steps,
        outcome=outcome,
        tags=tags,
    )

    memory = EpisodicMemory()
    episode_id = memory.save_episode(episode)
    memory.close()

    return json.dumps({
        "status": "saved",
        "episode_id": episode_id,
        "title": title,
        "steps_count": len(steps),
    })


# ── Registro ─────────────────────────────────────────────────


def register_agent_tools(registry: ToolRegistry) -> None:
    """Registra tools de agentes especializados en el registry."""

    registry.register(ToolDefinition(
        id="research",
        name="research",
        description=(
            "Ejecuta una investigación profunda sobre un tema usando búsqueda web "
            "y síntesis de múltiples fuentes. Retorna resumen, hallazgos clave, "
            "fuentes y preguntas de seguimiento. "
            "Usar para: investigar tecnologías, comparar soluciones, buscar información, "
            "compilar reportes de investigación."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Pregunta o tema a investigar.",
                },
                "depth": {
                    "type": "string",
                    "enum": ["quick", "standard", "deep"],
                    "description": "Profundidad: quick (1-2 búsquedas), standard (3-5), deep (5-10).",
                },
                "context": {
                    "type": "string",
                    "description": "Contexto adicional para refinar la búsqueda.",
                },
                "max_sources": {
                    "type": "integer",
                    "description": "Máximo de fuentes a incluir (default: 10).",
                },
            },
            "required": ["query"],
        },
        handler=_research_handler,
        section=ToolSection.WEB,
        profiles=[ToolProfile.FULL],
        timeout_secs=120.0,
    ))

    registry.register(ToolDefinition(
        id="analyze_data",
        name="analyze_data",
        description=(
            "Ejecuta análisis de datos sobre un archivo CSV/JSON o base de datos. "
            "Genera estadísticas descriptivas, correlaciones, distribuciones, "
            "tendencias y detección de anomalías con visualizaciones automáticas. "
            "Usar para: analizar datasets, generar gráficos, obtener insights."
        ),
        parameters={
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Ruta al archivo (CSV/JSON/Excel) o DSN de base de datos.",
                },
                "analysis_type": {
                    "type": "string",
                    "enum": ["descriptive", "correlation", "trend", "distribution", "comparison", "anomaly", "summary", "custom"],
                    "description": "Tipo de análisis (default: summary — ejecuta todos).",
                },
                "title": {
                    "type": "string",
                    "description": "Título del análisis.",
                },
                "custom_code": {
                    "type": "string",
                    "description": "Código Python personalizado (para analysis_type=custom).",
                },
            },
            "required": ["source"],
        },
        handler=_analyze_data_handler,
        section=ToolSection.RUNTIME,
        profiles=[ToolProfile.CODING, ToolProfile.FULL],
        timeout_secs=300.0,
    ))

    registry.register(ToolDefinition(
        id="plan_task",
        name="plan_task",
        description=(
            "Crea un plan estructurado para un objetivo complejo. "
            "Descompone el objetivo en pasos ejecutables con dependencias y verificación. "
            "Usar para: planificar implementaciones, descomponer tareas grandes, "
            "crear roadmaps de ejecución."
        ),
        parameters={
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "Objetivo a planificar.",
                },
                "context": {
                    "type": "string",
                    "description": "Contexto: tecnologías, restricciones, requisitos.",
                },
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "description": {"type": "string"},
                            "action": {"type": "string"},
                            "verification": {"type": "string"},
                            "depends_on": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                    "description": "Pasos predefinidos (opcional — si no, se generan automáticamente).",
                },
            },
            "required": ["goal"],
        },
        handler=_plan_task_handler,
        section=ToolSection.AGENTS,
        profiles=[ToolProfile.FULL],
        timeout_secs=60.0,
    ))

    registry.register(ToolDefinition(
        id="agent_messaging",
        name="agent_messaging",
        description=(
            "Envía, consulta o broadcast mensajes entre agentes. "
            "Usar para: coordinar entre agentes, enviar resultados, consultar inbox."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["send", "inbox", "broadcast", "status"],
                    "description": "Acción: send (enviar), inbox (leer), broadcast (a todos), status.",
                },
                "from_agent": {"type": "string", "description": "ID del agente emisor (default: main)."},
                "to_agent": {"type": "string", "description": "ID del agente destino (para send)."},
                "agent_id": {"type": "string", "description": "ID del agente (para inbox)."},
                "topic": {"type": "string", "description": "Topic del mensaje."},
                "payload": {"type": "object", "description": "Contenido del mensaje."},
            },
            "required": ["action"],
        },
        handler=_messaging_handler,
        section=ToolSection.AGENTS,
        profiles=[ToolProfile.FULL],
        timeout_secs=30.0,
    ))

    registry.register(ToolDefinition(
        id="episodic_recall",
        name="episodic_recall",
        description=(
            "Busca en la memoria episódica secuencias de acciones pasadas exitosas. "
            "Usar para: recordar cómo se hizo algo antes, replicar procedimientos, "
            "buscar patrones de acción previos."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Texto a buscar en episodios (título, descripción, trigger).",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags para filtrar episodios.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Máximo de episodios a retornar (default: 5).",
                },
            },
        },
        handler=_episodic_recall_handler,
        section=ToolSection.MEMORY,
        profiles=[ToolProfile.FULL],
        timeout_secs=15.0,
    ))

    registry.register(ToolDefinition(
        id="episodic_save",
        name="episodic_save",
        description=(
            "Guarda un episodio en la memoria episódica — una secuencia de acciones "
            "para recordar y replicar en el futuro. "
            "Usar para: registrar procedimientos exitosos, guardar workflows."
        ),
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Título del episodio."},
                "description": {"type": "string", "description": "Descripción del episodio."},
                "trigger_pattern": {"type": "string", "description": "Patrón que activa este episodio."},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags del episodio."},
                "outcome": {
                    "type": "string",
                    "enum": ["success", "partial", "failure"],
                    "description": "Resultado del episodio.",
                },
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "description": "Tipo: tool, shell, code, api, manual."},
                            "action": {"type": "string", "description": "Nombre de la acción."},
                            "args": {"type": "object", "description": "Argumentos usados."},
                            "result": {"type": "string", "description": "Resultado obtenido."},
                            "success": {"type": "boolean", "description": "Si fue exitoso."},
                        },
                    },
                    "description": "Pasos del episodio.",
                },
            },
            "required": ["title"],
        },
        handler=_episodic_save_handler,
        section=ToolSection.MEMORY,
        profiles=[ToolProfile.FULL],
        timeout_secs=15.0,
    ))

    logger.info("Agent tools registradas: 6 tools (research, analyze_data, plan_task, agent_messaging, episodic_recall, episodic_save)")
