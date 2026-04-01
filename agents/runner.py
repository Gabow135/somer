"""Agent Runner — motor de ejecución de agentes.

Portado de OpenClaw: pi-embedded-runner/run/attempt.ts,
pi-embedded-runner/run.ts, pi-embedded.ts.

Coordina la ejecución completa de un turno de agente:
- Resolución de modelo con fallback automático
- Context window management con compactación
- Tool execution con loop detection
- Multi-turn conversation
- Streaming output
- Abort control
- Sub-agente spawning
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import (
    Any,
    AsyncIterator,
    Callable,
    Coroutine,
    Dict,
    List,
    Optional,
    Tuple,
)

from agents.compaction import (
    CompactionConfig,
    CompactionResult,
    compact_messages,
    estimate_agent_messages_tokens,
    should_compact,
)
from agents.context_window import ContextWindowGuard, estimate_messages_tokens
from agents.model_fallback import (
    FallbackResult,
    ModelCandidate,
    build_fallback_candidates,
    is_context_overflow,
    run_with_model_fallback,
)
from agents.tools.registry import ToolRegistry
from context_engine.base import ContextEngine
from context_engine.default import DefaultContextEngine
from providers.base import BaseProvider
from providers.registry import ProviderRegistry
from shared.errors import AgentError, AgentTimeoutError, ProviderError
from shared.types import AgentMessage, AgentTurn, Role, ToolCall, ToolResult

logger = logging.getLogger(__name__)

# Type alias para tools (legacy, usar ToolRegistry para nuevas tools)
ToolHandler = Callable[[str, Dict[str, Any]], Coroutine[Any, Any, Dict[str, Any]]]


# ── Abort controller ──────────────────────────────────────────


class AbortController:
    """Control de aborto para la ejecución de un agente.

    Portado de OpenClaw: pi-embedded-runner/abort.ts.
    Permite cancelar la ejecución de un turno desde el exterior.
    """

    def __init__(self) -> None:
        self._aborted = False
        self._event = asyncio.Event()

    @property
    def is_aborted(self) -> bool:
        return self._aborted

    def abort(self) -> None:
        """Señaliza que la ejecución debe abortarse."""
        self._aborted = True
        self._event.set()

    def check(self) -> None:
        """Verifica si hay abort y lanza asyncio.CancelledError si lo hay."""
        if self._aborted:
            raise asyncio.CancelledError("Ejecución abortada por el usuario")

    async def wait(self, timeout: Optional[float] = None) -> bool:
        """Espera a que se señalice abort.

        Returns:
            True si se abortó, False si expiró el timeout.
        """
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    def reset(self) -> None:
        """Resetea el controller."""
        self._aborted = False
        self._event.clear()


# ── Runner principal ──────────────────────────────────────────


class AgentRunner:
    """Motor de ejecución de agentes.

    Portado de OpenClaw: pi-embedded-runner/run/attempt.ts,
    agent-command.ts, pi-embedded.ts.

    Coordina:
    - Provider selection con fallback automático
    - Context window management con compactación
    - Tool execution con ToolRegistry y loop detection
    - Multi-turn conversation loop
    - Streaming output
    - Abort control
    """

    def __init__(
        self,
        provider_registry: ProviderRegistry,
        context_engine: Optional[ContextEngine] = None,
        default_model: str = "claude-sonnet-4-5-20250929",
        max_turns: int = 50,
        timeout_secs: float = 300.0,
        tool_registry: Optional[ToolRegistry] = None,
        compaction_config: Optional[CompactionConfig] = None,
    ):
        self._providers = provider_registry
        self._context = context_engine or DefaultContextEngine()
        self._default_model = default_model
        self._max_turns = max_turns
        self._timeout = timeout_secs
        self._tools: Dict[str, ToolHandler] = {}
        self._guard = ContextWindowGuard()
        self._tool_registry = tool_registry or ToolRegistry()
        self._compaction_config = compaction_config or CompactionConfig()
        self._abort: Optional[AbortController] = None
        self._on_stream: Optional[Callable[[str], Coroutine[Any, Any, None]]] = None
        self._on_tool_start: Optional[Callable[[ToolCall], Coroutine[Any, Any, None]]] = None
        self._on_tool_end: Optional[Callable[[ToolResult], Coroutine[Any, Any, None]]] = None

    @property
    def tool_registry(self) -> ToolRegistry:
        """Acceso al registry de tools (para prompt builder, etc.)."""
        return self._tool_registry

    # ── Legacy tool API (mantener compatibilidad) ─────────────

    def register_tool(self, name: str, handler: ToolHandler) -> None:
        """Registra una tool disponible para el agente (API legacy)."""
        self._tools[name] = handler

    def unregister_tool(self, name: str) -> None:
        self._tools.pop(name, None)

    @property
    def tool_names(self) -> List[str]:
        return list(self._tools.keys()) + self._tool_registry.tool_names

    # ── Callbacks ─────────────────────────────────────────────

    def set_stream_callback(
        self, callback: Callable[[str], Coroutine[Any, Any, None]]
    ) -> None:
        """Establece callback para streaming de tokens."""
        self._on_stream = callback

    def set_tool_callbacks(
        self,
        on_start: Optional[Callable[[ToolCall], Coroutine[Any, Any, None]]] = None,
        on_end: Optional[Callable[[ToolResult], Coroutine[Any, Any, None]]] = None,
    ) -> None:
        """Establece callbacks para inicio/fin de tool execution."""
        self._on_tool_start = on_start
        self._on_tool_end = on_end

    # ── Ejecución principal ───────────────────────────────────

    async def run(
        self,
        session_id: str,
        user_message: str,
        *,
        model: Optional[str] = None,
        system_prompt: str = "",
        extra_context: Optional[List[Dict[str, Any]]] = None,
        abort: Optional[AbortController] = None,
        fallback_models: Optional[List[Tuple[str, str]]] = None,
    ) -> AgentTurn:
        """Ejecuta un turno completo del agente.

        Portado de OpenClaw: pi-embedded-runner/run/attempt.ts.

        Args:
            session_id: ID de sesión.
            user_message: Mensaje del usuario.
            model: Modelo a usar (default: self._default_model).
            system_prompt: System prompt opcional.
            extra_context: Mensajes adicionales de contexto.
            abort: Controller de abort opcional.
            fallback_models: Lista de (provider, model) para fallback.

        Returns:
            AgentTurn con los mensajes del turno.
        """
        self._abort = abort
        model = model or self._default_model

        # Resolver provider primario
        provider = self._providers.get_provider_for_model(model)
        if not provider:
            available = self._providers.list_available_providers()
            if not available:
                raise AgentError("No hay providers disponibles")
            provider = available[0]
            models = provider.list_models()
            if models:
                model = models[0].id

        turn = AgentTurn(model=model)
        messages: List[Dict[str, Any]] = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if extra_context:
            messages.extend(extra_context)
        messages.append({"role": "user", "content": user_message})

        # Ingestar en context
        user_msg = AgentMessage(role=Role.USER, content=user_message)
        await self._context.ingest(session_id, user_msg)
        turn.messages.append(user_msg)

        # Resetear loop detector
        self._tool_registry.reset_loop_detector()

        # Loop de ejecución (para tool calls)
        start = time.monotonic()
        compaction_count = 0

        for iteration in range(self._max_turns):
            # Check abort
            if self._abort and self._abort.is_aborted:
                logger.info("Ejecución abortada en iteración %d", iteration)
                break

            if self._timeout > 0 and time.monotonic() - start > self._timeout:
                raise AgentTimeoutError(f"Timeout después de {self._timeout}s")

            # Guard de contexto
            messages = self._guard.enforce(messages)
            turn.token_count = estimate_messages_tokens(messages)

            # Compactación proactiva si el contexto supera el umbral
            check = self._guard.check(messages)
            if check["should_compact"] and compaction_count < 2:
                logger.info(
                    "[AGENT] Compactación proactiva: utilización=%.1f%%, tokens=%d",
                    check["utilization"] * 100, check["tokens"],
                )
                compacted = await self._try_compact(session_id, turn)
                if compacted:
                    compaction_count += 1
                    messages = self._rebuild_messages(
                        system_prompt, turn.messages, compacted.summary
                    )
                    turn.token_count = estimate_messages_tokens(messages)

            # Llamar al provider (con fallback si se configuró)
            try:
                response = await self._call_provider_with_fallback(
                    provider, model, messages, fallback_models
                )
            except ProviderError as exc:
                # Si es overflow de contexto, intentar compactar
                if is_context_overflow(exc) and compaction_count < 2:
                    compacted = await self._try_compact(session_id, turn)
                    if compacted:
                        compaction_count += 1
                        # Reconstruir mensajes post-compactación
                        messages = self._rebuild_messages(
                            system_prompt, turn.messages, compacted.summary
                        )
                        continue
                raise

            # Extraer datos de la respuesta
            content = response.get("content", "")
            usage = response.get("usage", {})
            tool_calls_raw = response.get("tool_calls", [])
            stop_reason = response.get("stop_reason", "end_turn")

            logger.info(
                "[AGENT] Respuesta del provider: stop=%s, content_len=%d, "
                "tool_calls=%d, input_tokens=%d, output_tokens=%d",
                stop_reason, len(content),
                len(tool_calls_raw),
                usage.get("input_tokens", 0),
                usage.get("output_tokens", 0),
            )
            if tool_calls_raw:
                for tc_raw in tool_calls_raw:
                    logger.info(
                        "[AGENT] Tool call raw: id=%s, name='%s', args_keys=%s",
                        tc_raw.get("id", "?"),
                        tc_raw.get("name", ""),
                        list(tc_raw.get("arguments", {}).keys()) if isinstance(tc_raw.get("arguments"), dict) else "?",
                    )
            if content:
                logger.info("[AGENT] Content preview: %s", content[:200])

            turn.token_count += (
                usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
            )

            # Construir ToolCalls si los hay (ignorar tool calls con nombre vacío)
            tool_calls: List[ToolCall] = []
            for tc_raw in tool_calls_raw:
                tc_name = tc_raw.get("name", "")
                if not tc_name:
                    logger.warning(
                        "[AGENT] Tool call con nombre vacío IGNORADO: id=%s, raw=%s",
                        tc_raw.get("id", "?"),
                        str(tc_raw)[:300],
                    )
                    continue
                tool_calls.append(
                    ToolCall(
                        id=tc_raw.get("id", ""),
                        name=tc_name,
                        arguments=tc_raw.get("arguments", {}),
                    )
                )

            # Añadir respuesta del asistente
            assistant_msg = AgentMessage(
                role=Role.ASSISTANT,
                content=content,
                tool_calls=tool_calls,
                metadata={"model": model, "usage": usage},
            )
            await self._context.ingest(session_id, assistant_msg)
            turn.messages.append(assistant_msg)

            # Incluir tool_calls en el mensaje para multi-turn tool use
            assistant_dict: Dict[str, Any] = {
                "role": "assistant",
                "content": content,
            }
            if tool_calls:
                assistant_dict["tool_calls"] = [
                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                    for tc in tool_calls
                ]
            messages.append(assistant_dict)

            # Si no hay tool calls, terminamos
            if stop_reason != "tool_use" or not tool_calls:
                logger.info(
                    "[AGENT] Fin del turno: stop=%s, valid_tool_calls=%d",
                    stop_reason, len(tool_calls),
                )
                break

            # Ejecutar tool calls
            logger.info("[AGENT] Ejecutando %d tool calls...", len(tool_calls))
            tool_results = await self._execute_tool_calls(tool_calls)

            for tr in tool_results:
                logger.info(
                    "[AGENT] Tool result: id=%s, is_error=%s, content_preview=%s",
                    tr.tool_call_id, tr.is_error, tr.content[:200] if tr.content else "",
                )

            # Registrar resultados
            tool_msg = AgentMessage(
                role=Role.TOOL,
                content="",
                tool_results=tool_results,
            )
            await self._context.ingest(session_id, tool_msg)
            turn.messages.append(tool_msg)

            # Añadir resultados al contexto del provider
            for tr in tool_results:
                messages.append({
                    "role": "tool",
                    "content": tr.content,
                    "tool_call_id": tr.tool_call_id,
                })

        # After turn hook
        await self._context.after_turn(session_id, [])

        return turn

    # ── Ejecución con fallback ────────────────────────────────

    async def _call_provider_with_fallback(
        self,
        provider: BaseProvider,
        model: str,
        messages: List[Dict[str, Any]],
        fallback_models: Optional[List[Tuple[str, str]]] = None,
    ) -> Dict[str, Any]:
        """Llama al provider con fallback automático.

        Portado de OpenClaw: model-fallback.ts → runWithModelFallback
        integrado en el attempt loop.
        """
        tool_defs = self._build_all_tool_definitions()

        if fallback_models:
            candidates = build_fallback_candidates(
                provider.provider_id,
                model,
                fallback_models,
            )

            async def _run(provider_id: str, model_id: str) -> Dict[str, Any]:
                p = self._providers.get_provider(provider_id)
                if not p:
                    raise ProviderError(f"Provider no encontrado: {provider_id}")
                return await p.complete(messages, model_id, tools=tool_defs)

            result = await run_with_model_fallback(
                candidates,
                _run,
                label="agent turn",
            )
            return result.result
        else:
            # Sin fallback: intento directo con failover simple del registry
            try:
                return await provider.complete(messages, model, tools=tool_defs)
            except ProviderError:
                fallback = self._providers.find_fallback(provider.provider_id)
                if fallback:
                    fallback_models_list = fallback.list_models()
                    fallback_model = (
                        fallback_models_list[0].id if fallback_models_list else model
                    )
                    return await fallback.complete(
                        messages, fallback_model, tools=tool_defs
                    )
                raise

    # ── Tool execution ────────────────────────────────────────

    async def _execute_tool_calls(
        self,
        tool_calls: List[ToolCall],
    ) -> List[ToolResult]:
        """Ejecuta una lista de tool calls.

        Intenta primero con el ToolRegistry, luego con legacy tools.
        """
        results: List[ToolResult] = []
        for tc in tool_calls:
            # Notificar inicio
            if self._on_tool_start:
                await self._on_tool_start(tc)

            # Check abort entre tools
            if self._abort and self._abort.is_aborted:
                results.append(
                    ToolResult(
                        tool_call_id=tc.id,
                        content="Ejecución abortada",
                        is_error=True,
                    )
                )
                break

            # Intentar ToolRegistry primero
            registry_tool = self._tool_registry.get(tc.name)
            if registry_tool:
                result = await self._tool_registry.execute(tc)
            elif tc.name in self._tools:
                # Legacy handler
                result = await self._execute_legacy_tool(tc)
            else:
                result = ToolResult(
                    tool_call_id=tc.id,
                    content=f"Tool no encontrada: {tc.name}",
                    is_error=True,
                )

            results.append(result)

            # Notificar fin
            if self._on_tool_end:
                await self._on_tool_end(result)

        return results

    async def _execute_legacy_tool(self, tc: ToolCall) -> ToolResult:
        """Ejecuta una tool con el handler legacy."""
        handler = self._tools.get(tc.name)
        if not handler:
            return ToolResult(
                tool_call_id=tc.id,
                content=f"Tool no encontrada: {tc.name}",
                is_error=True,
            )
        try:
            result_dict = await handler(tc.name, tc.arguments)
            return ToolResult(
                tool_call_id=tc.id,
                content=str(result_dict),
            )
        except Exception as exc:
            return ToolResult(
                tool_call_id=tc.id,
                content=f"Error: {str(exc)[:500]}",
                is_error=True,
            )

    # ── Compactación ──────────────────────────────────────────

    async def _try_compact(
        self, session_id: str, turn: AgentTurn
    ) -> Optional[CompactionResult]:
        """Intenta compactar el contexto actual.

        Portado de OpenClaw: pi-embedded-runner/compact.ts.
        """
        if self._compaction_config.mode == "off":
            return None

        agent_messages = turn.messages

        if not should_compact(agent_messages, self._compaction_config):
            return None

        logger.info(
            "Iniciando compactación para sesión %s (%d mensajes)",
            session_id,
            len(agent_messages),
        )

        async def summarize(text: str, instructions: Optional[str]) -> str:
            """Delegado de summarización al provider actual."""
            prompt = "Summarize the following conversation, preserving key details:\n\n"
            if instructions:
                prompt += f"Instructions: {instructions}\n\n"
            prompt += text

            # Usar el provider actual para resumir
            try:
                available = self._providers.list_available_providers()
                if not available:
                    return text[:2000]
                provider = available[0]
                models = provider.list_models()
                model = models[0].id if models else self._default_model
                response = await provider.complete(
                    [{"role": "user", "content": prompt}],
                    model,
                )
                return response.get("content", text[:2000])
            except Exception as exc:
                logger.error("Error en summarización: %s", exc)
                return text[:2000]

        result = await compact_messages(
            agent_messages,
            summarize,
            self._compaction_config,
        )

        if result.compacted:
            logger.info(
                "Compactación exitosa: %d → %d tokens",
                result.tokens_before,
                result.tokens_after,
            )

        return result if result.compacted else None

    def _rebuild_messages(
        self,
        system_prompt: str,
        agent_messages: List[AgentMessage],
        summary: str,
    ) -> List[Dict[str, Any]]:
        """Reconstruye los mensajes post-compactación."""
        messages: List[Dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if summary:
            messages.append({
                "role": "system",
                "content": f"[Previous conversation summary]\n{summary}",
            })
        # Mantener últimos mensajes
        recent = agent_messages[-4:] if len(agent_messages) > 4 else agent_messages
        for msg in recent:
            entry: Dict[str, Any] = {
                "role": msg.role.value,
                "content": msg.content,
            }
            # Preservar tool_calls en mensajes del asistente
            if msg.tool_calls:
                entry["tool_calls"] = [
                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                    for tc in msg.tool_calls
                ]
            # Reconstruir mensajes tool a partir de tool_results
            if msg.role.value == "tool" and msg.tool_results:
                # Cada tool_result se envía como mensaje separado
                for tr in msg.tool_results:
                    messages.append({
                        "role": "tool",
                        "content": tr.content,
                        "tool_call_id": tr.tool_call_id,
                    })
                continue
            messages.append(entry)
        return messages

    # ── Tool definitions ──────────────────────────────────────

    def _build_all_tool_definitions(self) -> Optional[List[Dict[str, Any]]]:
        """Construye definiciones de tools combinando registry + legacy."""
        # Tools del registry
        defs = self._tool_registry.to_provider_format()

        # Legacy tools
        for name in self._tools:
            defs.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": f"Tool: {name}",
                    "parameters": {"type": "object", "properties": {}},
                },
            })

        return defs if defs else None

    def _build_tool_definitions(self) -> List[Dict[str, Any]]:
        """Construye definiciones de tools para el provider (legacy)."""
        defs = []
        for name in self._tools:
            defs.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": f"Tool: {name}",
                    "parameters": {"type": "object", "properties": {}},
                },
            })
        return defs

    # ── Streaming ─────────────────────────────────────────────

    async def run_stream(
        self,
        session_id: str,
        user_message: str,
        *,
        model: Optional[str] = None,
        system_prompt: str = "",
        abort: Optional[AbortController] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Ejecuta un turno con streaming de tokens.

        Portado de OpenClaw: pi-embedded-subscribe.ts → streaming.

        Yields:
            Dicts con eventos: {"type": "token", "content": "..."} o
            {"type": "tool_call", ...} o {"type": "done", "turn": ...}.
        """
        model = model or self._default_model
        provider = self._providers.get_provider_for_model(model)
        if not provider:
            available = self._providers.list_available_providers()
            if not available:
                raise AgentError("No hay providers disponibles")
            provider = available[0]
            models = provider.list_models()
            if models:
                model = models[0].id

        messages: List[Dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_message})

        # Ingestar
        user_msg = AgentMessage(role=Role.USER, content=user_message)
        await self._context.ingest(session_id, user_msg)

        turn = AgentTurn(model=model)
        turn.messages.append(user_msg)

        tool_defs = self._build_all_tool_definitions()

        try:
            async for chunk in provider.stream(messages, model, tools=tool_defs):
                if abort and abort.is_aborted:
                    yield {"type": "abort"}
                    break

                yield {"type": "token", "content": chunk.get("content", "")}

        except Exception as exc:
            yield {"type": "error", "error": str(exc)}

        yield {"type": "done", "turn": turn}
