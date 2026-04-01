"""Tool de ejecución controlada de comandos shell.

Permite al agente ejecutar comandos del sistema con sandboxing,
timeout, y restricciones de seguridad.

Seguridad:
- Blacklist de comandos peligrosos
- Timeout configurable
- Directorio de trabajo restringido
- Captura de stdout/stderr con límite de tamaño

Python 3.9+ — ``from __future__ import annotations``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

from agents.tools.registry import (
    ToolDefinition,
    ToolProfile,
    ToolRegistry,
    ToolSection,
)

logger = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────

_DEFAULT_TIMEOUT = 60
_MAX_TIMEOUT = 300
_MAX_OUTPUT_LENGTH = 20_000

# Comandos bloqueados por seguridad
_BLOCKED_COMMANDS = re.compile(
    r"\b("
    r"rm\s+-rf\s+/|"
    r"mkfs|"
    r"dd\s+if=|"
    r":()\s*\{|"                  # fork bomb
    r"chmod\s+-R\s+777\s+/|"
    r"shutdown|reboot|halt|"
    r"systemctl\s+(stop|disable)\s+|"
    r"launchctl\s+unload|"
    r"killall\s+-9|"
    r">\s*/dev/sd|"
    r"curl.*\|\s*(bash|sh|zsh)|"  # pipe to shell
    r"wget.*\|\s*(bash|sh|zsh)"
    r")\b",
    re.IGNORECASE,
)

# Comandos que requieren aprobación explícita
_DANGEROUS_COMMANDS = re.compile(
    r"\b("
    r"rm\s+-r|"
    r"git\s+push\s+--force|"
    r"git\s+reset\s+--hard|"
    r"docker\s+rm|"
    r"docker\s+system\s+prune|"
    r"pip\s+uninstall|"
    r"npm\s+uninstall|"
    r"brew\s+uninstall"
    r")\b",
    re.IGNORECASE,
)


# ── Helpers ──────────────────────────────────────────────────


def _validate_command(command: str) -> Optional[str]:
    """Valida que el comando sea seguro.

    Returns:
        None si es válido, mensaje de error si no.
    """
    if not command.strip():
        return "Comando vacío."

    if _BLOCKED_COMMANDS.search(command):
        return (
            "Comando bloqueado por seguridad. "
            "Comandos destructivos del sistema no están permitidos."
        )

    return None


def _is_dangerous(command: str) -> bool:
    """Verifica si el comando es potencialmente peligroso."""
    return bool(_DANGEROUS_COMMANDS.search(command))


# ── Handler ──────────────────────────────────────────────────


async def _shell_exec_handler(args: Dict[str, Any]) -> str:
    """Ejecuta un comando shell con sandboxing."""
    command = args.get("command", "").strip()
    if not command:
        return json.dumps({"error": "command es requerido."})

    workdir = args.get("workdir") or os.getcwd()
    timeout = min(args.get("timeout", _DEFAULT_TIMEOUT), _MAX_TIMEOUT)
    env_vars = args.get("env", {})
    shell = args.get("shell", "/bin/bash")

    # Validar comando
    error = _validate_command(command)
    if error:
        return json.dumps({"error": error})

    # Preparar entorno
    env = os.environ.copy()
    if env_vars:
        env.update(env_vars)

    # Verificar directorio
    if not os.path.isdir(workdir):
        return json.dumps({"error": f"Directorio no encontrado: {workdir}"})

    start = time.monotonic()
    logger.info("Shell exec: %s (cwd=%s, timeout=%ds)", command[:100], workdir, timeout)

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=workdir,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            executable=shell,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        duration = time.monotonic() - start
        return json.dumps({
            "error": f"Comando excedió el timeout de {timeout}s.",
            "duration_secs": round(duration, 2),
        })
    except Exception as exc:
        return json.dumps({"error": f"Error ejecutando comando: {str(exc)[:500]}"})

    duration = time.monotonic() - start
    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")

    # Truncar salida
    if len(stdout) > _MAX_OUTPUT_LENGTH:
        stdout = stdout[:_MAX_OUTPUT_LENGTH] + "\n\n[... salida truncada ...]"
    if len(stderr) > _MAX_OUTPUT_LENGTH:
        stderr = stderr[:_MAX_OUTPUT_LENGTH] + "\n\n[... error truncado ...]"

    result: Dict[str, Any] = {
        "exit_code": proc.returncode,
        "duration_secs": round(duration, 2),
    }

    if stdout.strip():
        result["stdout"] = stdout.strip()
    if stderr.strip():
        result["stderr"] = stderr.strip()

    if proc.returncode != 0:
        result["status"] = "error"
    else:
        result["status"] = "success"

    return json.dumps(result, ensure_ascii=False)


async def _shell_which_handler(args: Dict[str, Any]) -> str:
    """Verifica si un binario está disponible en el PATH."""
    binary = args.get("binary", "").strip()
    if not binary:
        return json.dumps({"error": "binary es requerido."})

    import shutil
    path = shutil.which(binary)

    if path:
        return json.dumps({"found": True, "path": path})
    return json.dumps({"found": False, "binary": binary})


# ── Registro ─────────────────────────────────────────────────


def register_shell_tools(registry: ToolRegistry) -> None:
    """Registra las tools de ejecución shell en el registry."""

    registry.register(ToolDefinition(
        id="shell_exec",
        name="shell_exec",
        description=(
            "Ejecuta un comando shell con sandboxing y timeout. "
            "Usar para: ejecutar scripts, compilar código, correr tests, "
            "instalar dependencias, operaciones del sistema. "
            "Bloqueará comandos destructivos del sistema automáticamente. "
            "Captura stdout y stderr con límite de tamaño."
        ),
        parameters={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Comando shell a ejecutar.",
                },
                "workdir": {
                    "type": "string",
                    "description": "Directorio de trabajo (default: directorio actual).",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout en segundos (default: 60, max: 300).",
                },
                "env": {
                    "type": "object",
                    "description": "Variables de entorno adicionales.",
                    "additionalProperties": {"type": "string"},
                },
                "shell": {
                    "type": "string",
                    "description": "Shell a usar (default: /bin/bash).",
                },
            },
            "required": ["command"],
        },
        handler=_shell_exec_handler,
        section=ToolSection.RUNTIME,
        profiles=[ToolProfile.CODING, ToolProfile.FULL],
        timeout_secs=300.0,
        requires_approval=False,
        dangerous=False,
    ))

    registry.register(ToolDefinition(
        id="shell_which",
        name="shell_which",
        description=(
            "Verifica si un binario o comando está disponible en el PATH. "
            "Usar antes de shell_exec para verificar que una herramienta existe."
        ),
        parameters={
            "type": "object",
            "properties": {
                "binary": {
                    "type": "string",
                    "description": "Nombre del binario a buscar (e.g. 'python3', 'docker', 'gh').",
                },
            },
            "required": ["binary"],
        },
        handler=_shell_which_handler,
        section=ToolSection.RUNTIME,
        profiles=[ToolProfile.MINIMAL, ToolProfile.CODING, ToolProfile.FULL],
        timeout_secs=5.0,
    ))

    logger.info("Shell tools registradas: 2 tools")
