"""Tools de delegación automática a agentes de código.

Permite al orquestador delegar tareas de programación a agentes
especializados (claude-code, codex, etc.) sin escribir código él mismo.

Python 3.9+ — ``from __future__ import annotations``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from typing import Any, Dict, Optional

from agents.tools.registry import (
    ToolDefinition,
    ToolProfile,
    ToolRegistry,
    ToolSection,
)

logger = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────

_MAX_OUTPUT_LENGTH = 12_000
_DEFAULT_TIMEOUT = 600  # 10 minutos


# ── Handlers ─────────────────────────────────────────────────


async def _delegate_coding_handler(args: Dict[str, Any]) -> str:
    """Delega una tarea de código a Claude Code CLI.

    El orquestador describe QUÉ hacer; Claude Code ejecuta el código.
    """
    task = args.get("task", "").strip()
    if not task:
        return "Error: 'task' es requerido — describe la tarea de código a delegar."

    workdir = args.get("workdir") or os.getcwd()
    context = args.get("context", "")
    constraints = args.get("constraints", "")
    timeout = min(args.get("timeout", _DEFAULT_TIMEOUT), 900)

    # Verificar que claude CLI está disponible
    claude_bin = shutil.which("claude")
    if not claude_bin:
        return (
            "Error: Claude Code CLI no encontrado. "
            "Instala con: npm install -g @anthropic-ai/claude-code"
        )

    # Construir prompt completo para Claude Code
    prompt_parts = [task]
    if context:
        prompt_parts.insert(0, f"CONTEXTO: {context}")
    if constraints:
        prompt_parts.append(f"\nRESTRICCIONES: {constraints}")

    full_prompt = "\n\n".join(prompt_parts)

    # Ejecutar Claude Code como subproceso (prompt vía stdin para evitar E2BIG)
    cmd = [
        claude_bin,
        "--permission-mode", "bypassPermissions",
        "--print",
    ]

    logger.info(
        "Delegando tarea a Claude Code en %s: %s",
        workdir,
        task[:100],
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=workdir,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(input=full_prompt.encode("utf-8")),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return f"Error: Claude Code excedió el timeout de {timeout}s. La tarea puede ser demasiado grande — intenta dividirla."
    except Exception as exc:
        return f"Error ejecutando Claude Code: {exc}"

    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")

    if proc.returncode != 0:
        error_msg = stderr[:2000] if stderr else "Sin detalle de error"
        return f"Claude Code terminó con error (código {proc.returncode}):\n{error_msg}"

    # Truncar salida si es muy larga
    output = stdout.strip()
    if len(output) > _MAX_OUTPUT_LENGTH:
        output = output[:_MAX_OUTPUT_LENGTH] + "\n\n[... salida truncada ...]"

    return output if output else "Claude Code completó la tarea sin salida visible."


async def _delegate_review_handler(args: Dict[str, Any]) -> str:
    """Delega revisión de código a Claude Code — modo solo lectura."""
    target = args.get("target", "").strip()
    focus = args.get("focus", "")
    workdir = args.get("workdir") or os.getcwd()
    timeout = min(args.get("timeout", _DEFAULT_TIMEOUT), 900)

    if not target:
        return "Error: 'target' es requerido — qué revisar (archivo, directorio, rama, PR)."

    claude_bin = shutil.which("claude")
    if not claude_bin:
        return (
            "Error: Claude Code CLI no encontrado. "
            "Instala con: npm install -g @anthropic-ai/claude-code"
        )

    # Construir prompt de revisión
    review_prompt = (
        f"TAREA: Revisa el código en {target}. "
        "Analiza y reporta pero NO modifiques ningún archivo.\n\n"
        "Busca:\n"
        "- Bugs y errores lógicos\n"
        "- Vulnerabilidades de seguridad\n"
        "- Código comentado que debería eliminarse\n"
        "- TODOs/FIXMEs pendientes\n"
        "- Problemas de rendimiento\n"
        "- Code smells y mejoras sugeridas\n"
    )
    if focus:
        review_prompt += f"\nENFOQUE ESPECIAL: {focus}\n"

    review_prompt += (
        "\nFormato de respuesta:\n"
        "## Resumen\n"
        "[1-2 líneas]\n\n"
        "## Issues Encontrados\n"
        "[Lista con severidad: 🔴 crítico, 🟠 alto, 🟡 medio, 🔵 bajo]\n\n"
        "## Sugerencias\n"
        "[Mejoras opcionales]"
    )

    cmd = [
        claude_bin,
        "--permission-mode", "bypassPermissions",
        "--print",
    ]

    logger.info("Delegando revisión a Claude Code: %s", target[:100])

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=workdir,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(input=review_prompt.encode("utf-8")),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return f"Error: revisión excedió el timeout de {timeout}s."
    except Exception as exc:
        return f"Error ejecutando revisión: {exc}"

    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")

    if proc.returncode != 0:
        return f"Error en revisión (código {proc.returncode}):\n{stderr[:2000]}"

    output = stdout.strip()
    if len(output) > _MAX_OUTPUT_LENGTH:
        output = output[:_MAX_OUTPUT_LENGTH] + "\n\n[... salida truncada ...]"

    return output if output else "Revisión completada sin hallazgos."


async def _delegate_debug_handler(args: Dict[str, Any]) -> str:
    """Delega debugging a Claude Code — analiza y corrige un error."""
    error = args.get("error", "").strip()
    file_path = args.get("file", "")
    test_cmd = args.get("test_command", "")
    workdir = args.get("workdir") or os.getcwd()
    timeout = min(args.get("timeout", _DEFAULT_TIMEOUT), 900)

    if not error:
        return "Error: 'error' es requerido — describe el error o pega el traceback."

    claude_bin = shutil.which("claude")
    if not claude_bin:
        return "Error: Claude Code CLI no encontrado."

    debug_prompt = f"DEBUG: {error}\n"
    if file_path:
        debug_prompt += f"\nArchivo relevante: {file_path}\n"
    debug_prompt += (
        "\nInstrucciones:\n"
        "1. Investiga la causa raíz del error\n"
        "2. Lee los archivos relevantes\n"
        "3. Aplica el fix mínimo necesario\n"
        "4. Explica qué causaba el error y qué cambiaste\n"
    )
    if test_cmd:
        debug_prompt += f"5. Verifica ejecutando: {test_cmd}\n"

    cmd = [
        claude_bin,
        "--permission-mode", "bypassPermissions",
        "--print",
    ]

    logger.info("Delegando debug a Claude Code: %s", error[:100])

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=workdir,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(input=debug_prompt.encode("utf-8")),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return f"Error: debugging excedió el timeout de {timeout}s."
    except Exception as exc:
        return f"Error ejecutando debug: {exc}"

    stdout = stdout_bytes.decode("utf-8", errors="replace")

    if proc.returncode != 0:
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        return f"Error en debug (código {proc.returncode}):\n{stderr[:2000]}"

    output = stdout.strip()
    if len(output) > _MAX_OUTPUT_LENGTH:
        output = output[:_MAX_OUTPUT_LENGTH] + "\n\n[... salida truncada ...]"

    return output if output else "Debug completado."


async def _delegate_test_gen_handler(args: Dict[str, Any]) -> str:
    """Delega generación de tests a Claude Code."""
    target = args.get("target", "").strip()
    framework = args.get("framework", "pytest")
    workdir = args.get("workdir") or os.getcwd()
    timeout = min(args.get("timeout", _DEFAULT_TIMEOUT), 900)

    if not target:
        return "Error: 'target' es requerido — módulo o archivo para el que generar tests."

    claude_bin = shutil.which("claude")
    if not claude_bin:
        return "Error: Claude Code CLI no encontrado."

    test_prompt = (
        f"Genera tests unitarios para: {target}\n\n"
        f"Framework: {framework}\n"
        "Instrucciones:\n"
        "- Lee el módulo target para entender su API\n"
        "- Cubre happy path, edge cases y manejo de errores\n"
        "- Mockea dependencias externas (DB, APIs, filesystem)\n"
        "- Apunta a >85% de coverage del módulo\n"
        "- Sigue las convenciones de tests existentes en el proyecto\n"
        "- Escribe los tests en el directorio tests/ correspondiente\n"
    )

    cmd = [
        claude_bin,
        "--permission-mode", "bypassPermissions",
        "--print",
    ]

    logger.info("Delegando generación de tests a Claude Code: %s", target)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=workdir,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(input=test_prompt.encode("utf-8")),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return f"Error: generación de tests excedió el timeout de {timeout}s."
    except Exception as exc:
        return f"Error generando tests: {exc}"

    stdout = stdout_bytes.decode("utf-8", errors="replace")

    if proc.returncode != 0:
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        return f"Error generando tests (código {proc.returncode}):\n{stderr[:2000]}"

    output = stdout.strip()
    if len(output) > _MAX_OUTPUT_LENGTH:
        output = output[:_MAX_OUTPUT_LENGTH] + "\n\n[... salida truncada ...]"

    return output if output else "Tests generados."


# ── Registro ─────────────────────────────────────────────────


def register_delegation_tools(registry: ToolRegistry) -> None:
    """Registra las tools de delegación a agentes de código."""

    registry.register(ToolDefinition(
        id="delegate_coding",
        name="delegate_coding",
        description=(
            "Delega una tarea de programación a Claude Code. "
            "Usar para: implementar features, refactorizar, crear archivos, "
            "modificar código existente, migraciones. "
            "El orquestador describe QUÉ hacer; Claude Code lo ejecuta."
        ),
        parameters={
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": (
                        "Descripción clara y completa de la tarea de código. "
                        "Incluye: qué hacer, dónde, restricciones, formato esperado."
                    ),
                },
                "context": {
                    "type": "string",
                    "description": (
                        "Contexto adicional: tecnologías, convenciones del proyecto, "
                        "archivos relevantes, dependencias."
                    ),
                },
                "constraints": {
                    "type": "string",
                    "description": (
                        "Restricciones: no modificar X, mantener compatibilidad, "
                        "seguir patrón Y, etc."
                    ),
                },
                "workdir": {
                    "type": "string",
                    "description": "Directorio de trabajo (default: directorio actual).",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout en segundos (default: 600, max: 900).",
                },
            },
            "required": ["task"],
        },
        handler=_delegate_coding_handler,
        section=ToolSection.AGENTS,
        profiles=[ToolProfile.CODING, ToolProfile.FULL],
        timeout_secs=900.0,
    ))

    registry.register(ToolDefinition(
        id="delegate_review",
        name="delegate_review",
        description=(
            "Delega revisión de código a Claude Code (modo solo lectura). "
            "Usar para: code review, buscar bugs, analizar seguridad, "
            "detectar código comentado, evaluar calidad. "
            "NO modifica archivos — solo analiza y reporta."
        ),
        parameters={
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": (
                        "Qué revisar: archivo, directorio, rama, 'git diff main...HEAD', etc."
                    ),
                },
                "focus": {
                    "type": "string",
                    "description": (
                        "Enfoque especial: seguridad, rendimiento, bugs, "
                        "código comentado, convenciones, etc."
                    ),
                },
                "workdir": {
                    "type": "string",
                    "description": "Directorio de trabajo.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout en segundos (default: 600, max: 900).",
                },
            },
            "required": ["target"],
        },
        handler=_delegate_review_handler,
        section=ToolSection.AGENTS,
        profiles=[ToolProfile.CODING, ToolProfile.FULL],
        timeout_secs=900.0,
    ))

    registry.register(ToolDefinition(
        id="delegate_debug",
        name="delegate_debug",
        description=(
            "Delega debugging a Claude Code — investiga y corrige un error. "
            "Usar para: traceback errors, tests fallando, comportamiento inesperado. "
            "Lee el código, encuentra la causa raíz y aplica el fix mínimo."
        ),
        parameters={
            "type": "object",
            "properties": {
                "error": {
                    "type": "string",
                    "description": "Descripción del error, traceback, o mensaje de fallo.",
                },
                "file": {
                    "type": "string",
                    "description": "Archivo donde ocurre el error (opcional).",
                },
                "test_command": {
                    "type": "string",
                    "description": "Comando para verificar el fix (e.g. pytest tests/test_x.py).",
                },
                "workdir": {
                    "type": "string",
                    "description": "Directorio de trabajo.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout en segundos (default: 600, max: 900).",
                },
            },
            "required": ["error"],
        },
        handler=_delegate_debug_handler,
        section=ToolSection.AGENTS,
        profiles=[ToolProfile.CODING, ToolProfile.FULL],
        timeout_secs=900.0,
    ))

    registry.register(ToolDefinition(
        id="delegate_test_gen",
        name="delegate_test_gen",
        description=(
            "Delega generación de tests a Claude Code. "
            "Usar para: crear tests unitarios, de integración, o e2e. "
            "Lee el módulo target, genera tests con buena cobertura."
        ),
        parameters={
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Módulo o archivo para el que generar tests.",
                },
                "framework": {
                    "type": "string",
                    "description": "Framework de testing (default: pytest).",
                },
                "workdir": {
                    "type": "string",
                    "description": "Directorio de trabajo.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout en segundos (default: 600, max: 900).",
                },
            },
            "required": ["target"],
        },
        handler=_delegate_test_gen_handler,
        section=ToolSection.AGENTS,
        profiles=[ToolProfile.CODING, ToolProfile.FULL],
        timeout_secs=900.0,
    ))

    logger.info("Delegation tools registradas: 4 tools")
