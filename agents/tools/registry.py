"""Registro y ejecución de tools para agentes.

Portado de OpenClaw: tool-catalog.ts, pi-tools.ts, pi-tools.types.ts,
tools/common.ts, openclaw-tools.ts.

Implementa:
- Definición de tools con schema JSON
- Registro global y por agente
- Ejecución con timeout y error handling
- Perfiles de tools (minimal, coding, messaging, full)
- Loop detection para evitar tool-call infinitos

Python 3.9+ — ``from __future__ import annotations``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set

from shared.errors import AgentError
from shared.types import ToolCall, ToolResult

logger = logging.getLogger(__name__)


# ── Tipos ─────────────────────────────────────────────────────


class ToolProfile(str, Enum):
    """Perfiles de herramientas disponibles.

    Portado de OpenClaw: tool-catalog.ts → ToolProfileId.
    """

    MINIMAL = "minimal"
    CODING = "coding"
    MESSAGING = "messaging"
    FULL = "full"


class ToolSection(str, Enum):
    """Secciones de herramientas.

    Portado de OpenClaw: tool-catalog.ts → CoreToolSection.
    """

    FS = "fs"
    RUNTIME = "runtime"
    WEB = "web"
    MEMORY = "memory"
    SESSIONS = "sessions"
    MESSAGING = "messaging"
    AGENTS = "agents"
    MEDIA = "media"
    SECURITY = "security"
    BUSINESS = "business"
    PERSONAL = "personal"
    MONITORING = "monitoring"


# Tipo para handler de tool
ToolHandler = Callable[[Dict[str, Any]], Awaitable[str]]


@dataclass
class ToolDefinition:
    """Definición de una herramienta registrada.

    Portado de OpenClaw: pi-tools.types.ts + tool-catalog.ts.
    """

    id: str
    name: str
    description: str
    parameters: Dict[str, Any] = field(default_factory=lambda: {
        "type": "object",
        "properties": {},
    })
    handler: Optional[ToolHandler] = None
    section: ToolSection = ToolSection.RUNTIME
    profiles: List[ToolProfile] = field(default_factory=lambda: [ToolProfile.FULL])
    timeout_secs: float = 120.0
    requires_approval: bool = False
    dangerous: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_provider_format(self, provider_family: str = "default") -> Dict[str, Any]:
        """Convierte a formato de tool para el provider.

        Soporta formato OpenAI (function calling) y Anthropic.
        """
        if provider_family == "anthropic":
            return {
                "name": self.name,
                "description": self.description,
                "input_schema": self.parameters,
            }

        # Formato OpenAI / default
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# ── Loop detection ────────────────────────────────────────────


@dataclass
class LoopDetectionConfig:
    """Configuración para detección de loops de tool calls.

    Portado de OpenClaw: tool-loop-detection.ts.
    Adaptado para arquitectura single-tool (http_request).
    """

    max_identical_consecutive: int = 3  # Máx calls idénticos consecutivos (misma tool + mismos args)
    max_same_name_in_window: int = 15  # Máx calls con mismo nombre en ventana
    window_size: int = 20  # Número de calls recientes a analizar
    max_total_calls: int = 50  # Máx calls totales por turno


class ToolLoopDetector:
    """Detecta loops en las llamadas a tools.

    Portado de OpenClaw: tool-loop-detection.ts.
    Detecta dos tipos de loops:
    1. Llamadas IDÉNTICAS consecutivas (misma tool + mismos argumentos) → loop real
    2. Demasiadas llamadas a la misma tool en una ventana → posible loop
    3. Demasiadas llamadas totales en un turno → safety limit
    """

    def __init__(self, config: Optional[LoopDetectionConfig] = None) -> None:
        self._config = config or LoopDetectionConfig()
        self._recent_calls: List[str] = []  # "name|args_hash" entries
        self._recent_names: List[str] = []  # tool names only
        self._total_calls: int = 0

    def record(self, tool_name: str, args_signature: str = "") -> None:
        """Registra una llamada a tool.

        Args:
            tool_name: Nombre de la tool.
            args_signature: Firma de los argumentos (para detectar calls idénticos).
        """
        call_sig = f"{tool_name}|{args_signature}"
        self._recent_calls.append(call_sig)
        self._recent_names.append(tool_name)
        self._total_calls += 1

        # Mantener ventana
        if len(self._recent_calls) > self._config.window_size * 2:
            self._recent_calls = self._recent_calls[-self._config.window_size:]
            self._recent_names = self._recent_names[-self._config.window_size:]

    def is_looping(self) -> bool:
        """Verifica si se detecta un loop."""
        # 1. Total excedido (safety limit)
        if self._total_calls >= self._config.max_total_calls:
            return True

        # 2. Llamadas IDÉNTICAS consecutivas (misma tool + mismos args)
        if len(self._recent_calls) >= self._config.max_identical_consecutive:
            tail = self._recent_calls[-self._config.max_identical_consecutive:]
            if len(set(tail)) == 1:
                return True

        # 3. Demasiadas llamadas al mismo nombre en ventana
        window = self._recent_names[-self._config.window_size:]
        if window:
            counts: Dict[str, int] = {}
            for name in window:
                counts[name] = counts.get(name, 0) + 1
            if any(c >= self._config.max_same_name_in_window for c in counts.values()):
                return True

        return False

    def reset(self) -> None:
        """Resetea el detector."""
        self._recent_calls.clear()
        self._recent_names.clear()
        self._total_calls = 0


# ── Registry de tools ─────────────────────────────────────────


class ToolRegistry:
    """Registro de herramientas para agentes.

    Portado de OpenClaw: pi-tools.ts, tool-catalog.ts.
    Mantiene las definiciones de tools y ejecuta llamadas con
    timeout y error handling.
    """

    def __init__(self) -> None:
        self._tools: Dict[str, ToolDefinition] = {}
        self._loop_detector = ToolLoopDetector()

    # ── Registro ──────────────────────────────────────────────

    def register(self, tool: ToolDefinition) -> None:
        """Registra una herramienta."""
        self._tools[tool.name] = tool
        logger.debug("Tool registrada: %s (%s)", tool.name, tool.section.value)

    def register_simple(
        self,
        name: str,
        description: str,
        handler: ToolHandler,
        *,
        parameters: Optional[Dict[str, Any]] = None,
        timeout_secs: float = 120.0,
    ) -> None:
        """Registra una herramienta simple con handler."""
        tool = ToolDefinition(
            id=name,
            name=name,
            description=description,
            parameters=parameters or {"type": "object", "properties": {}},
            handler=handler,
            timeout_secs=timeout_secs,
        )
        self.register(tool)

    def unregister(self, name: str) -> None:
        """Desregistra una herramienta."""
        self._tools.pop(name, None)

    def get(self, name: str) -> Optional[ToolDefinition]:
        """Obtiene una herramienta por nombre."""
        return self._tools.get(name)

    # ── Listado ───────────────────────────────────────────────

    @property
    def tool_names(self) -> List[str]:
        """Lista de nombres de tools registradas."""
        return list(self._tools.keys())

    def list_tools(
        self,
        *,
        profile: Optional[ToolProfile] = None,
        section: Optional[ToolSection] = None,
    ) -> List[ToolDefinition]:
        """Lista tools filtradas por perfil y/o sección."""
        result: List[ToolDefinition] = []
        for tool in self._tools.values():
            if profile and profile not in tool.profiles:
                continue
            if section and tool.section != section:
                continue
            result.append(tool)
        return result

    def to_provider_format(
        self,
        provider_family: str = "default",
        *,
        profile: Optional[ToolProfile] = None,
        allowed_names: Optional[Set[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Convierte todas las tools a formato de provider.

        Args:
            provider_family: "anthropic", "openai", "google", "default".
            profile: Si se provee, filtra por perfil.
            allowed_names: Si se provee, solo incluye estas tools.

        Returns:
            Lista de definiciones de tools para el provider.
        """
        tools = self.list_tools(profile=profile)
        result: List[Dict[str, Any]] = []
        for tool in tools:
            if allowed_names and tool.name not in allowed_names:
                continue
            result.append(tool.to_provider_format(provider_family))
        return result

    # ── Ejecución ─────────────────────────────────────────────

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        """Ejecuta una llamada a tool.

        Args:
            tool_call: ToolCall con nombre y argumentos.

        Returns:
            ToolResult con el resultado o error.
        """
        tool = self._tools.get(tool_call.name)
        if tool is None:
            return ToolResult(
                tool_call_id=tool_call.id,
                content=f"Tool no encontrada: {tool_call.name}",
                is_error=True,
            )

        if tool.handler is None:
            return ToolResult(
                tool_call_id=tool_call.id,
                content=f"Tool sin handler: {tool_call.name}",
                is_error=True,
            )

        # Loop detection — firma incluye args para distinguir calls legítimos
        import json as _json
        try:
            args_sig = _json.dumps(tool_call.arguments, sort_keys=True)
        except (TypeError, ValueError):
            args_sig = str(tool_call.arguments)
        self._loop_detector.record(tool_call.name, args_sig)
        if self._loop_detector.is_looping():
            logger.warning("Loop de tool calls detectado para: %s", tool_call.name)
            return ToolResult(
                tool_call_id=tool_call.id,
                content=(
                    f"Loop detectado: la tool '{tool_call.name}' se llamó "
                    f"demasiadas veces. Deteniéndose para evitar bucle infinito."
                ),
                is_error=True,
            )

        # Ejecutar con timeout
        start = time.monotonic()
        try:
            if tool.timeout_secs > 0:
                result_content = await asyncio.wait_for(
                    tool.handler(tool_call.arguments),
                    timeout=tool.timeout_secs,
                )
            else:
                # timeout_secs=0 → sin límite de tiempo
                result_content = await tool.handler(tool_call.arguments)
            duration = time.monotonic() - start
            logger.debug(
                "Tool %s ejecutada en %.1fms",
                tool_call.name,
                duration * 1000,
            )
            return ToolResult(
                tool_call_id=tool_call.id,
                content=result_content,
            )
        except asyncio.TimeoutError:
            duration = time.monotonic() - start
            logger.warning(
                "Tool %s timeout después de %.1fs",
                tool_call.name,
                duration,
            )
            return ToolResult(
                tool_call_id=tool_call.id,
                content=f"Tool '{tool_call.name}' timeout después de {tool.timeout_secs}s",
                is_error=True,
            )
        except Exception as exc:
            duration = time.monotonic() - start
            logger.error(
                "Tool %s error después de %.1fms: %s",
                tool_call.name,
                duration * 1000,
                exc,
            )
            return ToolResult(
                tool_call_id=tool_call.id,
                content=f"Error en tool '{tool_call.name}': {str(exc)[:500]}",
                is_error=True,
            )

    async def execute_batch(
        self, tool_calls: List[ToolCall]
    ) -> List[ToolResult]:
        """Ejecuta múltiples tool calls secuencialmente.

        Args:
            tool_calls: Lista de ToolCall a ejecutar.

        Returns:
            Lista de ToolResult correspondientes.
        """
        results: List[ToolResult] = []
        for tc in tool_calls:
            result = await self.execute(tc)
            results.append(result)
        return results

    def reset_loop_detector(self) -> None:
        """Resetea el detector de loops (inicio de nuevo turno)."""
        self._loop_detector.reset()
