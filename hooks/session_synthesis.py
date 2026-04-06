"""Hook de sintesis post-sesion.

Al finalizar una sesion (cierre o timeout), extrae un resumen automatico
y lo guarda como episodio en la memoria episodica. Esto permite al agente
recordar conversaciones previas y aprender de ellas.

Python 3.9+ — ``from __future__ import annotations``.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from memory.episodic import (
    Episode,
    EpisodeOutcome,
    EpisodeStep,
    EpisodicMemory,
)

logger = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────

_MAX_TITLE_LEN = 120
_MAX_DESCRIPTION_LEN = 500
_MAX_TOPICS = 10
_MAX_ACTION_ITEMS = 10

# Palabras clave para detectar decisiones
_DECISION_MARKERS = (
    "decidimos", "vamos a", "la solucion es", "optamos por",
    "decided", "let's go with", "the solution is", "we'll use",
    "elegimos", "usaremos", "implementaremos",
)

# Palabras clave para detectar action items
_ACTION_MARKERS = (
    "todo", "pendiente", "falta", "hay que", "necesitamos",
    "action item", "next step", "should do", "need to",
    "recordar", "no olvidar", "importante",
)


# ── Helpers ───────────────────────────────────────────────────


def _extract_title(messages: List[Dict[str, str]]) -> str:
    """Extrae un titulo de la sesion basado en el primer mensaje del usuario."""
    for msg in messages:
        if msg.get("role") == "user":
            content = msg.get("content", "").strip()
            if content:
                # Usar primera linea, truncada
                first_line = content.split("\n")[0].strip()
                if len(first_line) > _MAX_TITLE_LEN:
                    return first_line[:_MAX_TITLE_LEN - 3] + "..."
                return first_line
    return "Sesion sin titulo"


def _extract_topics(messages: List[Dict[str, str]]) -> List[str]:
    """Extrae topics basicos de la conversacion.

    v1 simple: usa las primeras palabras significativas de los mensajes
    del usuario como aproximacion a los temas discutidos.
    """
    topics: List[str] = []
    seen: set = set()

    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "").strip().lower()
        # Tomar palabras largas como posibles temas
        words = content.split()
        for word in words:
            clean = word.strip(".,;:!?()[]{}\"'")
            if len(clean) > 5 and clean not in seen:
                seen.add(clean)
                topics.append(clean)
                if len(topics) >= _MAX_TOPICS:
                    return topics
    return topics


def _extract_decisions(messages: List[Dict[str, str]]) -> List[str]:
    """Busca marcadores de decision en los mensajes del asistente."""
    decisions: List[str] = []
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", "").lower()
        for marker in _DECISION_MARKERS:
            if marker in content:
                # Extraer la oracion que contiene el marcador
                lines = msg.get("content", "").split(".")
                for line in lines:
                    if marker in line.lower():
                        clean = line.strip()
                        if clean and len(clean) > 10:
                            decisions.append(clean[:200])
                            break
                break  # Un marcador por mensaje
    return decisions[:5]


def _extract_action_items(messages: List[Dict[str, str]]) -> List[str]:
    """Busca action items en los mensajes."""
    items: List[str] = []
    for msg in messages:
        content = msg.get("content", "").lower()
        for marker in _ACTION_MARKERS:
            if marker in content:
                lines = msg.get("content", "").split("\n")
                for line in lines:
                    if marker in line.lower():
                        clean = line.strip().lstrip("-*# ")
                        if clean and len(clean) > 5:
                            items.append(clean[:200])
                            if len(items) >= _MAX_ACTION_ITEMS:
                                return items
    return items


def _build_description(
    messages: List[Dict[str, str]],
    tools_used: List[str],
    decisions: List[str],
    action_items: List[str],
) -> str:
    """Construye una descripcion del resumen de la sesion."""
    parts: List[str] = []

    msg_count = len(messages)
    user_msgs = sum(1 for m in messages if m.get("role") == "user")
    parts.append(f"Sesion con {msg_count} mensajes ({user_msgs} del usuario).")

    if tools_used:
        parts.append(f"Tools usadas: {', '.join(tools_used[:10])}.")

    if decisions:
        parts.append(f"Decisiones: {decisions[0]}")

    if action_items:
        parts.append(f"Pendientes: {action_items[0]}")

    description = " ".join(parts)
    if len(description) > _MAX_DESCRIPTION_LEN:
        return description[:_MAX_DESCRIPTION_LEN - 3] + "..."
    return description


# ── Hook principal ────────────────────────────────────────────


async def on_session_end(session_data: Dict[str, Any]) -> None:
    """Hook que se ejecuta al finalizar una sesion.

    Extrae un resumen de la conversacion y lo guarda como episodio
    en la memoria episodica.

    Args:
        session_data: Diccionario con:
            - session_id (str): ID de la sesion.
            - messages (list): Lista de dicts con role/content.
            - tools_used (list): Lista de nombres de tools usadas.
            - duration_secs (float): Duracion de la sesion en segundos.
    """
    session_id: str = session_data.get("session_id", "")
    messages: List[Dict[str, str]] = session_data.get("messages", [])
    tools_used: List[str] = session_data.get("tools_used", [])
    duration_secs: float = session_data.get("duration_secs", 0.0)

    if not messages:
        logger.debug("Sesion %s sin mensajes, saltando sintesis.", session_id)
        return

    # Extraer informacion
    title = _extract_title(messages)
    topics = _extract_topics(messages)
    decisions = _extract_decisions(messages)
    action_items = _extract_action_items(messages)
    description = _build_description(messages, tools_used, decisions, action_items)

    # Construir tags
    tags: List[str] = ["session_synthesis"]
    tags.extend(tools_used[:5])
    tags.extend(topics[:5])

    # Construir pasos del episodio basados en las tools usadas
    steps: List[EpisodeStep] = []
    for i, tool in enumerate(tools_used):
        steps.append(EpisodeStep(
            step_index=i + 1,
            action_type="tool",
            action_name=tool,
            result_summary=f"Tool {tool} usada durante la sesion.",
            success=True,
        ))

    # Determinar outcome basado en si hubo errores
    outcome = EpisodeOutcome.SUCCESS
    for msg in messages:
        content = msg.get("content", "").lower()
        if "error" in content or "fallo" in content or "failed" in content:
            outcome = EpisodeOutcome.PARTIAL
            break

    # Crear y guardar episodio
    episode = Episode(
        episode_id=uuid.uuid4().hex[:12],
        title=title,
        description=description,
        trigger_pattern=f"session:{session_id}",
        steps=steps,
        outcome=outcome,
        tags=tags,
        success_score=1.0 if outcome == EpisodeOutcome.SUCCESS else 0.7,
        created_at=time.time(),
    )

    memory = EpisodicMemory()
    try:
        episode_id = memory.save_episode(episode)
        logger.info(
            "Sintesis de sesion guardada: %s (episodio %s, %d mensajes, %.0fs)",
            session_id, episode_id, len(messages), duration_secs,
        )
    except Exception:
        logger.exception("Error guardando sintesis de sesion %s", session_id)
    finally:
        memory.close()

    # TODO(v2): Actualizar USER.md si se aprendieron hechos nuevos del usuario.
    # Estructura preparada para futura implementacion:
    # _update_user_facts(messages, session_id)


# ── Registro ──────────────────────────────────────────────────


class SessionSynthesisHook:
    """Clase wrapper para el hook de sintesis de sesion.

    Permite registrar y acceder al hook de forma orientada a objetos.
    """

    name: str = "session_synthesis"
    event: str = "on_session_end"

    @staticmethod
    async def handle(session_data: Dict[str, Any]) -> None:
        """Ejecuta la sintesis de sesion."""
        await on_session_end(session_data)

    @staticmethod
    def register_session_hooks() -> Dict[str, Any]:
        """Retorna definiciones de hooks para el sistema de hooks."""
        return {
            "on_session_end": on_session_end,
        }


def register_session_hooks() -> Dict[str, Any]:
    """Retorna definiciones de hooks para el sistema de hooks.

    Returns:
        Diccionario con nombre_evento -> callback.
    """
    return {
        "on_session_end": on_session_end,
    }
