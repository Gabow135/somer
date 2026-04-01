"""Sistema de comandos de agente.

Portado de OpenClaw: agent-command.ts, command/types.ts, command/session.ts.
Maneja la ejecución de comandos de agente: run, override de modelo,
override de provider, reset de sesión, etc.

Python 3.9+ — ``from __future__ import annotations``.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional

from shared.errors import AgentError

logger = logging.getLogger(__name__)


# ── Tipos ─────────────────────────────────────────────────────


class CommandType(str, Enum):
    """Tipos de comandos de agente.

    Portado de OpenClaw: command/types.ts.
    """

    RUN = "run"  # Ejecutar turno con mensaje
    MODEL_OVERRIDE = "model_override"  # Cambiar modelo
    PROVIDER_OVERRIDE = "provider_override"  # Cambiar provider
    CLEAR_OVERRIDES = "clear_overrides"  # Limpiar overrides
    RESET_SESSION = "reset_session"  # Reset de sesión
    COMPACT = "compact"  # Forzar compactación
    STATUS = "status"  # Estado del agente


@dataclass
class AgentCommandOpts:
    """Opciones para ejecutar un comando de agente.

    Portado de OpenClaw: command/types.ts → AgentCommandOpts.
    """

    session_key: str
    message: str = ""
    channel: Optional[str] = None
    account_id: Optional[str] = None
    sender_id: Optional[str] = None
    thread_id: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    system_prompt: Optional[str] = None
    agent_id: str = "main"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentCommandResult:
    """Resultado de un comando de agente.

    Portado de OpenClaw: command/delivery.ts.
    """

    success: bool = True
    content: str = ""
    model: Optional[str] = None
    provider: Optional[str] = None
    tokens_used: int = 0
    duration_ms: float = 0.0
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


# ── Parsing de comandos ───────────────────────────────────────


OVERRIDE_VALUE_MAX_LENGTH = 256

# Prefijos de comando reconocidos
_COMMAND_PREFIXES = {
    "/model": CommandType.MODEL_OVERRIDE,
    "/provider": CommandType.PROVIDER_OVERRIDE,
    "/reset": CommandType.RESET_SESSION,
    "/compact": CommandType.COMPACT,
    "/status": CommandType.STATUS,
    "/clear": CommandType.CLEAR_OVERRIDES,
}


def parse_command(text: str) -> Optional[Tuple[CommandType, str]]:
    """Parsea un texto como comando de agente.

    Portado de OpenClaw: agent-command.ts → parsing logic.

    Args:
        text: Texto del usuario.

    Returns:
        (tipo_comando, argumento) o None si no es un comando.
    """
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None

    for prefix, cmd_type in _COMMAND_PREFIXES.items():
        if stripped.lower().startswith(prefix):
            arg = stripped[len(prefix):].strip()
            return (cmd_type, arg)

    return None


from typing import Tuple


def validate_override_value(value: str, kind: str = "model") -> str:
    """Valida y normaliza un valor de override.

    Portado de OpenClaw: agent-command.ts → normalizeExplicitOverrideInput.

    Args:
        value: Valor del override.
        kind: Tipo de override ("model" o "provider").

    Returns:
        Valor normalizado.

    Raises:
        AgentError: Si el valor es inválido.
    """
    trimmed = value.strip()
    label = "Provider" if kind == "provider" else "Model"

    if not trimmed:
        raise AgentError(f"{label} override no puede estar vacío.")

    if len(trimmed) > OVERRIDE_VALUE_MAX_LENGTH:
        raise AgentError(
            f"{label} override demasiado largo "
            f"(máx {OVERRIDE_VALUE_MAX_LENGTH} caracteres)."
        )

    # Verificar caracteres de control
    for char in trimmed:
        code = ord(char)
        if code <= 0x1F or (0x7F <= code <= 0x9F):
            raise AgentError(
                f"{label} override contiene caracteres de control no permitidos."
            )

    return trimmed


# ── Ejecutor de comandos ──────────────────────────────────────

# Tipo para la función de ejecución del run del agente
RunAgentFn = Callable[[AgentCommandOpts], Awaitable[AgentCommandResult]]


class AgentCommandExecutor:
    """Ejecutor de comandos de agente.

    Portado de OpenClaw: agent-command.ts → runAgentCommand.
    Procesa comandos recibidos del usuario y los delega al runner
    o aplica overrides de sesión.
    """

    def __init__(
        self,
        run_agent: RunAgentFn,
        *,
        on_model_override: Optional[Callable[[str, str], Awaitable[None]]] = None,
        on_provider_override: Optional[Callable[[str, str], Awaitable[None]]] = None,
        on_clear_overrides: Optional[Callable[[str], Awaitable[None]]] = None,
        on_reset_session: Optional[Callable[[str], Awaitable[None]]] = None,
        on_compact: Optional[Callable[[str], Awaitable[None]]] = None,
        on_status: Optional[Callable[[str], Awaitable[Dict[str, Any]]]] = None,
    ) -> None:
        self._run_agent = run_agent
        self._on_model_override = on_model_override
        self._on_provider_override = on_provider_override
        self._on_clear_overrides = on_clear_overrides
        self._on_reset_session = on_reset_session
        self._on_compact = on_compact
        self._on_status = on_status

    async def execute(self, opts: AgentCommandOpts) -> AgentCommandResult:
        """Ejecuta un comando de agente.

        Si el mensaje es un comando (empieza con /), lo procesa.
        Si no, lo envía como mensaje normal al runner.

        Args:
            opts: Opciones del comando.

        Returns:
            AgentCommandResult con el resultado.
        """
        start = time.monotonic()

        # Verificar si es un comando
        parsed = parse_command(opts.message)
        if parsed:
            cmd_type, arg = parsed
            try:
                result = await self._dispatch_command(cmd_type, arg, opts)
            except AgentError as exc:
                result = AgentCommandResult(
                    success=False,
                    error=str(exc),
                )
            result.duration_ms = (time.monotonic() - start) * 1000
            return result

        # No es comando: ejecutar como mensaje normal
        try:
            result = await self._run_agent(opts)
        except Exception as exc:
            result = AgentCommandResult(
                success=False,
                error=str(exc),
            )
        result.duration_ms = (time.monotonic() - start) * 1000
        return result

    async def _dispatch_command(
        self,
        cmd_type: CommandType,
        arg: str,
        opts: AgentCommandOpts,
    ) -> AgentCommandResult:
        """Despacha un comando al handler apropiado."""
        if cmd_type == CommandType.MODEL_OVERRIDE:
            return await self._handle_model_override(arg, opts.session_key)

        if cmd_type == CommandType.PROVIDER_OVERRIDE:
            return await self._handle_provider_override(arg, opts.session_key)

        if cmd_type == CommandType.CLEAR_OVERRIDES:
            return await self._handle_clear_overrides(opts.session_key)

        if cmd_type == CommandType.RESET_SESSION:
            return await self._handle_reset_session(opts.session_key)

        if cmd_type == CommandType.COMPACT:
            return await self._handle_compact(opts.session_key)

        if cmd_type == CommandType.STATUS:
            return await self._handle_status(opts.session_key)

        return AgentCommandResult(
            success=False,
            error=f"Comando no reconocido: {cmd_type.value}",
        )

    async def _handle_model_override(
        self, model: str, session_key: str
    ) -> AgentCommandResult:
        """Maneja override de modelo."""
        validated = validate_override_value(model, "model")
        if self._on_model_override:
            await self._on_model_override(session_key, validated)
        return AgentCommandResult(
            success=True,
            content=f"Modelo cambiado a: {validated}",
            model=validated,
        )

    async def _handle_provider_override(
        self, provider: str, session_key: str
    ) -> AgentCommandResult:
        """Maneja override de provider."""
        validated = validate_override_value(provider, "provider")
        if self._on_provider_override:
            await self._on_provider_override(session_key, validated)
        return AgentCommandResult(
            success=True,
            content=f"Provider cambiado a: {validated}",
            provider=validated,
        )

    async def _handle_clear_overrides(
        self, session_key: str
    ) -> AgentCommandResult:
        """Maneja limpieza de overrides."""
        if self._on_clear_overrides:
            await self._on_clear_overrides(session_key)
        return AgentCommandResult(
            success=True,
            content="Overrides limpiados. Usando configuración por defecto.",
        )

    async def _handle_reset_session(
        self, session_key: str
    ) -> AgentCommandResult:
        """Maneja reset de sesión."""
        if self._on_reset_session:
            await self._on_reset_session(session_key)
        return AgentCommandResult(
            success=True,
            content="Sesión reseteada.",
        )

    async def _handle_compact(
        self, session_key: str
    ) -> AgentCommandResult:
        """Maneja compactación forzada."""
        if self._on_compact:
            await self._on_compact(session_key)
        return AgentCommandResult(
            success=True,
            content="Compactación iniciada.",
        )

    async def _handle_status(
        self, session_key: str
    ) -> AgentCommandResult:
        """Maneja consulta de estado."""
        info: Dict[str, Any] = {"session_key": session_key}
        if self._on_status:
            info = await self._on_status(session_key)
        return AgentCommandResult(
            success=True,
            content=str(info),
            metadata=info,
        )
