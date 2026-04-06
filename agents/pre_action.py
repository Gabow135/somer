"""Pre-Action Validator — piensa antes de actuar.

Intercepta tool calls antes de su ejecucion para consultar
la memoria de lecciones y episodica. Si hay advertencias
conocidas, las inyecta como contexto para que el LLM pueda
reconsiderar.

Python 3.9+ — ``from __future__ import annotations``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from shared.types import ToolCall

logger = logging.getLogger(__name__)


# ── Modelos ──────────────────────────────────────────────────


class PreActionWarning(BaseModel):
    """Advertencia individual de pre-accion."""
    tool_name: str
    message: str
    source: str = "lessons"          # "lessons" | "episodic"
    severity: str = "warning"        # "info" | "warning" | "error"
    suggestion: str = ""


class PreActionResult(BaseModel):
    """Resultado de la validacion pre-accion."""
    warnings: List[PreActionWarning] = Field(default_factory=list)
    suggestions: List[PreActionWarning] = Field(default_factory=list)
    should_proceed: bool = True

    def has_warnings(self) -> bool:
        return len(self.warnings) > 0

    def format_for_context(self) -> str:
        """Formatea advertencias y sugerencias como texto para inyectar en contexto."""
        parts: List[str] = []

        if self.warnings:
            parts.append("[Pre-Action Warnings]")
            for w in self.warnings:
                line = f"- [{w.severity.upper()}] Tool '{w.tool_name}': {w.message}"
                if w.suggestion:
                    line += f" | Sugerencia: {w.suggestion}"
                parts.append(line)

        if self.suggestions:
            parts.append("[Pre-Action Suggestions]")
            for s in self.suggestions:
                parts.append(f"- Tool '{s.tool_name}': {s.message}")

        return "\n".join(parts)


# ── Validator ────────────────────────────────────────────────


class PreActionValidator:
    """Verifica lecciones y memoria episodica antes de ejecutar tools.

    Ambos backends de memoria son opcionales. Si no estan disponibles,
    la validacion se salta silenciosamente.
    """

    def __init__(
        self,
        lessons_memory: Any = None,
        episodic_memory: Any = None,
    ) -> None:
        self.lessons = lessons_memory
        self.episodic = episodic_memory

    async def validate(
        self,
        tool_calls: List[ToolCall],
        context: str = "",
    ) -> PreActionResult:
        """Valida una lista de tool calls contra la memoria.

        Args:
            tool_calls: Lista de ToolCall que el LLM quiere ejecutar.
            context: Contexto textual (mensaje del usuario, etc.).

        Returns:
            PreActionResult con advertencias y sugerencias.
        """
        warnings: List[PreActionWarning] = []
        suggestions: List[PreActionWarning] = []

        for tc in tool_calls:
            # 1. Consultar lecciones aprendidas
            if self.lessons:
                try:
                    lessons = self.lessons.check_before_action(
                        tool_name=tc.name,
                        context=context,
                    )
                    for lesson in lessons:
                        severity = lesson.get("severity", "warning")
                        warnings.append(PreActionWarning(
                            tool_name=tc.name,
                            message=f"{lesson.get('error', 'Problema conocido')}",
                            source="lessons",
                            severity=severity,
                            suggestion=lesson.get("solution", ""),
                        ))
                except Exception as exc:
                    logger.debug(
                        "Error consultando lecciones para tool '%s': %s",
                        tc.name, exc,
                    )

            # 2. Consultar memoria episodica
            if self.episodic:
                try:
                    episodes = self.episodic.recall(
                        query=f"{tc.name} {context}",
                        limit=2,
                    )
                    for ep in episodes:
                        outcome = (
                            ep.outcome.value
                            if hasattr(ep.outcome, "value")
                            else str(ep.outcome)
                        )
                        title = getattr(ep, "title", str(ep))

                        if outcome == "failure":
                            warnings.append(PreActionWarning(
                                tool_name=tc.name,
                                message=f"Accion similar fallo antes: {title}",
                                source="episodic",
                                severity="warning",
                            ))
                        elif outcome == "success":
                            suggestions.append(PreActionWarning(
                                tool_name=tc.name,
                                message=f"Accion similar exitosa: {title}",
                                source="episodic",
                                severity="info",
                            ))
                except Exception as exc:
                    logger.debug(
                        "Error consultando memoria episodica para tool '%s': %s",
                        tc.name, exc,
                    )

        # Solo bloquear si hay advertencias con severidad "error"
        has_blocking = any(w.severity == "error" for w in warnings)

        return PreActionResult(
            warnings=warnings,
            suggestions=suggestions,
            should_proceed=not has_blocking,
        )
