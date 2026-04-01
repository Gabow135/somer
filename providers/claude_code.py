"""Provider que usa Claude Code CLI como backend LLM.

Ejecuta `claude -p` en modo programático, sin necesidad de API key.
Usa la suscripción existente de Claude Code del usuario.
"""

from __future__ import annotations

import asyncio
import errno
import json
import logging
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from providers.base import BaseProvider
from shared.errors import ProviderError
from shared.types import ModelDefinition

logger = logging.getLogger(__name__)

# Modelos disponibles vía Claude Code CLI
CLAUDE_CODE_MODELS = [
    ModelDefinition(
        id="claude-code/opus",
        name="Claude Opus (via CLI)",
        provider="claude-code",
        api="anthropic-messages",
        context_window=200_000,
        max_output_tokens=64_000,
    ),
    ModelDefinition(
        id="claude-code/sonnet",
        name="Claude Sonnet (via CLI)",
        provider="claude-code",
        api="anthropic-messages",
        context_window=200_000,
        max_output_tokens=64_000,
    ),
    ModelDefinition(
        id="claude-code/haiku",
        name="Claude Haiku (via CLI)",
        provider="claude-code",
        api="anthropic-messages",
        context_window=200_000,
        max_output_tokens=64_000,
    ),
]

# Mapeo de model_id a flag --model del CLI
_MODEL_MAP = {
    "claude-code/opus": "opus",
    "claude-code/sonnet": "sonnet",
    "claude-code/haiku": "haiku",
}


class ClaudeCodeProvider(BaseProvider):
    """Provider que usa el CLI `claude` en modo programático."""

    def __init__(
        self,
        provider_id: str = "claude-code",
        models: Optional[List[ModelDefinition]] = None,
        max_budget_usd: Optional[float] = None,
    ):
        super().__init__(
            provider_id=provider_id,
            api="anthropic-messages",
            api_key="cli",  # No se necesita API key real
            models=models or CLAUDE_CODE_MODELS,
        )
        self._max_budget = max_budget_usd

    async def complete(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        *,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: Optional[List[Dict[str, Any]]] = None,
        stream: bool = False,
    ) -> Dict[str, Any]:
        """Ejecuta completion via `claude -p`."""

        # Construir el prompt a partir de los mensajes
        system_prompt = ""
        user_parts: List[str] = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "system":
                system_prompt = content
            elif role == "user":
                user_parts.append(content)
            elif role == "assistant" and content:
                user_parts.append(f"[Respuesta anterior del asistente]: {content}")

        # El último mensaje de usuario es el prompt principal
        prompt = "\n\n".join(user_parts) if user_parts else ""

        # Construir comando (prompt vía stdin para evitar E2BIG)
        cli_model = _MODEL_MAP.get(model, "sonnet")
        cmd = [
            "claude",
            "-p",
            "--model", cli_model,
            "--output-format", "json",
            "--no-session-persistence",
        ]

        effective_system = system_prompt

        if self._max_budget:
            cmd.extend(["--max-budget-usd", str(self._max_budget)])

        # Agregar tools como allowedTools si las hay
        if tools:
            tool_names = [t.get("function", {}).get("name", t.get("name", ""))
                          for t in tools if t.get("function", {}).get("name") or t.get("name")]
            if tool_names:
                # Informar al modelo sobre las tools disponibles via system prompt
                tools_desc = self._format_tools_for_prompt(tools)
                if tools_desc:
                    tool_instruction = (
                        "\n\n## Herramientas disponibles\n"
                        "Tienes acceso a las siguientes herramientas. "
                        "Para usarlas, incluye un bloque JSON con el formato:\n"
                        '```tool_call\n{"name": "tool_name", "arguments": {...}}\n```\n\n'
                        f"{tools_desc}"
                    )
                    effective_system = (effective_system + tool_instruction) if effective_system else tool_instruction

        # Usar archivo temporal para system prompt largo y evitar E2BIG
        system_prompt_file = None
        if effective_system:
            # Límite conservador: Linux MAX_ARG_STRLEN ≈ 128 KiB por argumento
            if len(effective_system) > 100_000:
                system_prompt_file = tempfile.NamedTemporaryFile(
                    mode="w", suffix=".txt", delete=False, encoding="utf-8",
                )
                system_prompt_file.write(effective_system)
                system_prompt_file.close()
                cmd.extend(["--system-prompt-file", system_prompt_file.name])
                logger.info(
                    "[PROVIDER:claude-code] System prompt escrito a archivo temporal "
                    "(%d chars): %s", len(effective_system), system_prompt_file.name,
                )
            else:
                cmd.extend(["--system-prompt", effective_system])

        logger.info(
            "[PROVIDER:claude-code] Ejecutando: model=%s, prompt_len=%d, tools=%d",
            cli_model, len(prompt), len(tools) if tools else 0,
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate(
                input=prompt.encode("utf-8"),
            )

            if proc.returncode != 0:
                error_msg = stderr.decode("utf-8", errors="replace")[:500]
                logger.error("[PROVIDER:claude-code] Error: %s", error_msg)
                raise ProviderError(f"claude CLI falló (code {proc.returncode}): {error_msg}")

            # Parsear respuesta JSON
            raw = stdout.decode("utf-8", errors="replace")
            data = json.loads(raw)

            if data.get("is_error"):
                raise ProviderError(f"claude CLI error: {data.get('result', 'unknown')}")

            result_text = data.get("result", "")
            usage = data.get("usage", {})

            self.auth.record_success()

            result: Dict[str, Any] = {
                "content": result_text,
                "model": model,
                "usage": {
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                },
                "stop_reason": data.get("stop_reason", "end_turn"),
            }

            # Extraer tool_calls del texto si el modelo los incluyó
            tool_calls = self._extract_tool_calls(result_text)
            if tool_calls:
                result["tool_calls"] = tool_calls
                result["stop_reason"] = "tool_use"
                # Limpiar el contenido de los bloques de tool_call
                import re
                result["content"] = re.sub(
                    r"```tool_call\s*\n.*?\n```", "", result_text, flags=re.DOTALL
                ).strip()

            logger.info(
                "[PROVIDER:claude-code] Respuesta: %d chars, %d tool_calls, cost=$%.4f",
                len(result_text),
                len(tool_calls),
                data.get("total_cost_usd", 0),
            )

            return result

        except json.JSONDecodeError as exc:
            raise ProviderError(f"claude CLI respuesta inválida: {exc}") from exc
        except FileNotFoundError:
            raise ProviderError(
                "claude CLI no encontrado. Instala Claude Code: "
                "https://claude.ai/code"
            )
        except OSError as exc:
            if exc.errno == errno.E2BIG:
                raise ProviderError(
                    "context_length_exceeded: prompt is too long for CLI args "
                    f"({len(effective_system)} chars system + {len(prompt)} chars prompt)"
                ) from exc
            raise ProviderError(f"claude CLI error: {exc}") from exc
        except Exception as exc:
            if isinstance(exc, ProviderError):
                raise
            raise ProviderError(f"claude CLI error: {exc}") from exc
        finally:
            if system_prompt_file is not None:
                try:
                    Path(system_prompt_file.name).unlink(missing_ok=True)
                except OSError:
                    pass

    async def health_check(self) -> bool:
        """Verifica que claude CLI está disponible."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "claude", "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            return proc.returncode == 0
        except Exception:
            return False

    @staticmethod
    def _format_tools_for_prompt(tools: List[Dict[str, Any]]) -> str:
        """Formatea las definiciones de tools para incluir en el prompt."""
        parts = []
        for tool in tools:
            func = tool.get("function", tool)
            name = func.get("name", "")
            desc = func.get("description", "")
            params = func.get("parameters", func.get("input_schema", {}))
            if not name:
                continue
            props = params.get("properties", {})
            required = params.get("required", [])
            param_lines = []
            for pname, pinfo in props.items():
                req = " (requerido)" if pname in required else ""
                param_lines.append(
                    f"    - {pname}: {pinfo.get('type', 'any')} — {pinfo.get('description', '')}{req}"
                )
            params_str = "\n".join(param_lines) if param_lines else "    (sin parámetros)"
            parts.append(f"### {name}\n{desc}\n  Parámetros:\n{params_str}")

        return "\n\n".join(parts)

    @staticmethod
    def _extract_tool_calls(text: str) -> List[Dict[str, Any]]:
        """Extrae tool_calls del texto si el modelo los incluyó."""
        import re
        tool_calls = []
        pattern = r"```tool_call\s*\n(.*?)\n```"
        matches = re.findall(pattern, text, re.DOTALL)
        for i, match in enumerate(matches):
            try:
                data = json.loads(match.strip())
                name = data.get("name", "")
                args = data.get("arguments", data.get("args", {}))
                if name:
                    tool_calls.append({
                        "id": f"claude_code_{i}",
                        "name": name,
                        "arguments": args if isinstance(args, dict) else {},
                    })
            except json.JSONDecodeError:
                continue
        return tool_calls
