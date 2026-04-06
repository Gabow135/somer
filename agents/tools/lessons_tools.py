"""Tools de lecciones aprendidas para agentes.

Permite a los agentes guardar, buscar y verificar lecciones
aprendidas (errores y workarounds) durante la ejecucion.

Python 3.9+ — ``from __future__ import annotations``.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from agents.tools.registry import (
    ToolDefinition,
    ToolProfile,
    ToolRegistry,
    ToolSection,
)
from memory.lessons import LessonsMemory

logger = logging.getLogger(__name__)

# ── Singleton ────────────────────────────────────────────────

_store: Optional[LessonsMemory] = None


def _get_store() -> LessonsMemory:
    global _store
    if _store is None:
        _store = LessonsMemory()
    return _store


# ── Handlers ─────────────────────────────────────────────────


async def _lesson_save_handler(args: Dict[str, Any]) -> str:
    """Guarda una leccion aprendida (error + solucion)."""
    store = _get_store()

    context = args.get("context", "")
    error = args.get("error", "")
    solution = args.get("solution", "")

    if not context or not error or not solution:
        return json.dumps({
            "error": "Se requieren context, error y solution.",
        })

    lesson_id = store.save_lesson(
        context=context,
        error=error,
        solution=solution,
        tags=args.get("tags", []),
        tool_name=args.get("tool_name", ""),
        severity=args.get("severity", "warning"),
    )

    return json.dumps({
        "status": "success",
        "lesson_id": lesson_id,
        "message": f"Leccion guardada: {lesson_id}",
    })


async def _lesson_recall_handler(args: Dict[str, Any]) -> str:
    """Busca lecciones aprendidas por query, tool o tags."""
    store = _get_store()

    results = store.recall_lessons(
        query=args.get("query", ""),
        tool_name=args.get("tool_name", ""),
        tags=args.get("tags", []),
        limit=args.get("limit", 5),
    )

    return json.dumps({
        "lessons": results,
        "count": len(results),
    })


async def _lesson_check_handler(args: Dict[str, Any]) -> str:
    """Verifica lecciones antes de ejecutar una accion."""
    store = _get_store()

    tool_name = args.get("tool_name", "")
    if not tool_name:
        return json.dumps({
            "error": "Se requiere tool_name.",
        })

    warnings = store.check_before_action(
        tool_name=tool_name,
        context=args.get("context", ""),
    )

    return json.dumps({
        "tool_name": tool_name,
        "warnings": warnings,
        "count": len(warnings),
        "has_warnings": len(warnings) > 0,
    })


# ── Registro ─────────────────────────────────────────────────


def register_lessons_tools(registry: ToolRegistry) -> None:
    """Registra las tools de lecciones aprendidas en el registry."""

    registry.register(ToolDefinition(
        id="lesson_save",
        name="lesson_save",
        description=(
            "Guarda una leccion aprendida: registra un error encontrado y su solucion/workaround. "
            "Usar cuando: algo fallo y se encontro la solucion, se descubrio un gotcha o "
            "limitacion, se encontro un workaround para un problema conocido."
        ),
        parameters={
            "type": "object",
            "properties": {
                "context": {
                    "type": "string",
                    "description": "Que se estaba intentando hacer cuando ocurrio el error.",
                },
                "error": {
                    "type": "string",
                    "description": "Que salio mal (mensaje de error, comportamiento inesperado, etc.).",
                },
                "solution": {
                    "type": "string",
                    "description": "Que funciono para resolver el problema o workaround encontrado.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Etiquetas para clasificar la leccion (e.g., deploy, networking, permisos).",
                },
                "tool_name": {
                    "type": "string",
                    "description": "Nombre de la tool que fallo (si aplica).",
                },
                "severity": {
                    "type": "string",
                    "enum": ["info", "warning", "error"],
                    "description": "Nivel de severidad (default: warning).",
                },
            },
            "required": ["context", "error", "solution"],
        },
        handler=_lesson_save_handler,
        section=ToolSection.MEMORY,
        profiles=[ToolProfile.FULL],
        timeout_secs=15.0,
    ))

    registry.register(ToolDefinition(
        id="lesson_recall",
        name="lesson_recall",
        description=(
            "Busca lecciones aprendidas por texto, tool o tags. "
            "Usar para: recordar errores pasados y sus soluciones, "
            "buscar workarounds conocidos, revisar lecciones de una tool especifica."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Texto libre para buscar en contexto, error y solucion.",
                },
                "tool_name": {
                    "type": "string",
                    "description": "Filtrar por tool especifica.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filtrar por tags.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximo de resultados (default: 5).",
                },
            },
        },
        handler=_lesson_recall_handler,
        section=ToolSection.MEMORY,
        profiles=[ToolProfile.FULL],
        timeout_secs=15.0,
    ))

    registry.register(ToolDefinition(
        id="lesson_check",
        name="lesson_check",
        description=(
            "Verifica si hay lecciones/advertencias antes de ejecutar una tool. "
            "Usar ANTES de ejecutar una accion para evitar repetir errores conocidos. "
            "Retorna advertencias relevantes si las hay."
        ),
        parameters={
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "description": "Nombre de la tool que se va a ejecutar.",
                },
                "context": {
                    "type": "string",
                    "description": "Descripcion de lo que se va a hacer (opcional, mejora la busqueda).",
                },
            },
            "required": ["tool_name"],
        },
        handler=_lesson_check_handler,
        section=ToolSection.MEMORY,
        profiles=[ToolProfile.FULL],
        timeout_secs=10.0,
    ))

    logger.info("Lessons tools registradas: 3 tools")
