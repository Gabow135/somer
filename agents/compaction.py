"""Compactación de contexto para agentes.

Portado de OpenClaw: compaction.ts, pi-embedded-runner/compact.ts.
Divide el historial de mensajes en chunks y genera resúmenes
para reducir tokens manteniendo información crítica.

Python 3.9+ — ``from __future__ import annotations``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from agents.context_window import estimate_messages_tokens, estimate_tokens
from config.schema import AgentCompactionConfig
from shared.errors import AgentError, ContextWindowExceededError
from shared.types import AgentMessage, Role

logger = logging.getLogger(__name__)


# ── Constantes (portado de OpenClaw: compaction.ts) ───────────

BASE_CHUNK_RATIO = 0.4
MIN_CHUNK_RATIO = 0.15
SAFETY_MARGIN = 1.2  # 20% buffer para inexactitud de estimación
SUMMARIZATION_OVERHEAD_TOKENS = 4096
DEFAULT_SUMMARY_FALLBACK = "No prior history."
DEFAULT_PARTS = 2

MERGE_SUMMARIES_INSTRUCTIONS = (
    "Merge these partial summaries into a single cohesive summary.\n"
    "\n"
    "MUST PRESERVE:\n"
    "- Active tasks and their current status (in-progress, blocked, pending)\n"
    "- Batch operation progress (e.g., '5/17 items completed')\n"
    "- The last thing the user requested and what was being done about it\n"
    "- Decisions made and their rationale\n"
    "- TODOs, open questions, and constraints\n"
    "- Any commitments or follow-ups promised\n"
    "\n"
    "PRIORITIZE recent context over older history. The agent needs to know\n"
    "what it was doing, not just what was discussed."
)

IDENTIFIER_PRESERVATION_INSTRUCTIONS = (
    "Preserve all opaque identifiers exactly as written (no shortening "
    "or reconstruction), including UUIDs, hashes, IDs, tokens, API keys, "
    "hostnames, IPs, ports, URLs, and file names."
)


# ── Tipos ─────────────────────────────────────────────────────


@dataclass
class CompactionResult:
    """Resultado de una compactación.

    Portado de OpenClaw: pi-embedded-runner/types.ts → EmbeddedPiCompactResult.
    """

    compacted: bool = False
    summary: str = ""
    tokens_before: int = 0
    tokens_after: int = 0
    chunks_processed: int = 0
    duration_ms: float = 0.0
    error: Optional[str] = None


@dataclass
class CompactionConfig:
    """Configuración de compactación del runtime.

    Derivado del AgentCompactionConfig de config/schema.py con
    parámetros adicionales de runtime.
    """

    mode: str = "safeguard"  # "safeguard" | "aggressive" | "off"
    threshold_ratio: float = 0.85
    context_window: int = 128_000
    max_output_tokens: int = 8_192
    custom_instructions: Optional[str] = None
    identifier_policy: str = "strict"  # "strict" | "custom" | "off"


# ── Funciones auxiliares ──────────────────────────────────────


def _estimate_agent_message_tokens(msg: AgentMessage) -> int:
    """Estima tokens de un AgentMessage."""
    total = estimate_tokens(msg.content)
    for tc in msg.tool_calls:
        total += estimate_tokens(tc.name)
        total += estimate_tokens(str(tc.arguments))
    for tr in msg.tool_results:
        total += estimate_tokens(tr.content)
    total += 4  # overhead por mensaje
    return total


def estimate_agent_messages_tokens(messages: List[AgentMessage]) -> int:
    """Estima tokens de una lista de AgentMessages.

    Portado de OpenClaw: compaction.ts → estimateMessagesTokens.
    """
    return sum(_estimate_agent_message_tokens(m) for m in messages)


def should_compact(
    messages: List[AgentMessage],
    config: CompactionConfig,
) -> bool:
    """Determina si la conversación necesita compactación.

    Portado de OpenClaw: pi-extensions/compaction-safeguard.ts.
    """
    if config.mode == "off":
        return False

    tokens = estimate_agent_messages_tokens(messages)
    effective_limit = config.context_window - config.max_output_tokens
    threshold = effective_limit * config.threshold_ratio

    return tokens > threshold


# ── Chunking ──────────────────────────────────────────────────


def split_messages_by_token_share(
    messages: List[AgentMessage],
    parts: int = DEFAULT_PARTS,
) -> List[List[AgentMessage]]:
    """Divide mensajes en chunks por peso de tokens.

    Portado de OpenClaw: compaction.ts → splitMessagesByTokenShare.
    Distribuye mensajes en ``parts`` chunks intentando equilibrar
    la cantidad de tokens por chunk.
    """
    if not messages:
        return []

    actual_parts = max(1, min(parts, len(messages)))
    if actual_parts <= 1:
        return [messages]

    total_tokens = estimate_agent_messages_tokens(messages)
    target = total_tokens / actual_parts
    chunks: List[List[AgentMessage]] = []
    current: List[AgentMessage] = []
    current_tokens = 0

    for msg in messages:
        msg_tokens = _estimate_agent_message_tokens(msg)
        if (
            len(chunks) < actual_parts - 1
            and current
            and current_tokens + msg_tokens > target
        ):
            chunks.append(current)
            current = []
            current_tokens = 0

        current.append(msg)
        current_tokens += msg_tokens

    if current:
        chunks.append(current)

    return chunks


def chunk_messages_by_max_tokens(
    messages: List[AgentMessage],
    max_tokens: int,
) -> List[List[AgentMessage]]:
    """Divide mensajes en chunks con un máximo de tokens por chunk.

    Portado de OpenClaw: compaction.ts → chunkMessagesByMaxTokens.
    Aplica SAFETY_MARGIN para compensar inexactitud de estimación.
    """
    if not messages:
        return []

    effective_max = max(1, int(max_tokens / SAFETY_MARGIN))
    chunks: List[List[AgentMessage]] = []
    current: List[AgentMessage] = []
    current_tokens = 0

    for msg in messages:
        msg_tokens = _estimate_agent_message_tokens(msg)
        if current and current_tokens + msg_tokens > effective_max:
            chunks.append(current)
            current = []
            current_tokens = 0

        current.append(msg)
        current_tokens += msg_tokens

        # Mensajes oversized: forzar nuevo chunk
        if msg_tokens > effective_max:
            chunks.append(current)
            current = []
            current_tokens = 0

    if current:
        chunks.append(current)

    return chunks


def compute_adaptive_chunk_ratio(
    messages: List[AgentMessage],
    context_window: int,
) -> float:
    """Calcula ratio adaptativo de chunk basado en tamaño promedio de mensajes.

    Portado de OpenClaw: compaction.ts → computeAdaptiveChunkRatio.
    """
    if not messages:
        return BASE_CHUNK_RATIO

    total = estimate_agent_messages_tokens(messages)
    avg = total / len(messages)
    safe_avg = avg * SAFETY_MARGIN
    avg_ratio = safe_avg / context_window

    if avg_ratio > 0.1:
        reduction = min(avg_ratio * 2, BASE_CHUNK_RATIO - MIN_CHUNK_RATIO)
        return max(MIN_CHUNK_RATIO, BASE_CHUNK_RATIO - reduction)

    return BASE_CHUNK_RATIO


# ── Instrucciones de summarización ────────────────────────────


def build_summarization_instructions(
    custom_instructions: Optional[str] = None,
    identifier_policy: str = "strict",
) -> Optional[str]:
    """Construye instrucciones para el modelo de summarización.

    Portado de OpenClaw: compaction.ts → buildCompactionSummarizationInstructions.
    """
    id_instructions: Optional[str] = None
    if identifier_policy == "strict":
        id_instructions = IDENTIFIER_PRESERVATION_INSTRUCTIONS
    elif identifier_policy == "custom" and custom_instructions:
        id_instructions = custom_instructions

    custom = custom_instructions.strip() if custom_instructions else None
    if not id_instructions and not custom:
        return None
    if not custom:
        return id_instructions
    if not id_instructions:
        return f"Additional focus:\n{custom}"
    return f"{id_instructions}\n\nAdditional focus:\n{custom}"


# ── Serialización de mensajes ─────────────────────────────────


def _serialize_message_for_summary(msg: AgentMessage) -> str:
    """Serializa un AgentMessage para incluirlo en el prompt de summarización."""
    parts = [f"[{msg.role.value}]"]
    if msg.content:
        parts.append(msg.content)
    for tc in msg.tool_calls:
        parts.append(f"  → tool_call: {tc.name}({tc.arguments})")
    for tr in msg.tool_results:
        prefix = "ERROR" if tr.is_error else "OK"
        parts.append(f"  ← tool_result [{prefix}]: {tr.content[:500]}")
    return "\n".join(parts)


def serialize_messages_for_summary(messages: List[AgentMessage]) -> str:
    """Serializa una lista de mensajes para el prompt de summarización."""
    return "\n\n".join(
        _serialize_message_for_summary(m) for m in messages
    )


# ── Compactación principal ────────────────────────────────────

# Tipo para la función de summarización (delegada al provider)
SummarizeFn = Callable[[str, Optional[str]], Awaitable[str]]


async def compact_messages(
    messages: List[AgentMessage],
    summarize: SummarizeFn,
    config: CompactionConfig,
    *,
    previous_summary: Optional[str] = None,
) -> CompactionResult:
    """Compacta una lista de mensajes generando un resumen.

    Portado de OpenClaw: pi-embedded-runner/compact.ts → compactEmbeddedPiSession.

    Divide los mensajes en chunks, genera resúmenes parciales de cada uno
    y los fusiona en un resumen final. Preserva los últimos mensajes
    recientes que quepan en el presupuesto.

    Args:
        messages: Lista de mensajes a compactar.
        summarize: Función async(text, instructions) → summary.
        config: Configuración de compactación.
        previous_summary: Resumen anterior para preservar contexto.

    Returns:
        CompactionResult con el resumen y estadísticas.
    """
    if config.mode == "off":
        return CompactionResult(compacted=False, summary="")

    start = time.monotonic()
    tokens_before = estimate_agent_messages_tokens(messages)

    if not messages:
        return CompactionResult(
            compacted=False,
            tokens_before=0,
            tokens_after=0,
        )

    effective_limit = config.context_window - config.max_output_tokens
    threshold = effective_limit * config.threshold_ratio

    if tokens_before <= threshold:
        return CompactionResult(
            compacted=False,
            tokens_before=tokens_before,
            tokens_after=tokens_before,
        )

    # Determinar cuántos mensajes recientes preservar
    recent_budget = int(effective_limit * 0.3)  # 30% para recientes
    preserved: List[AgentMessage] = []
    preserved_tokens = 0

    for msg in reversed(messages):
        msg_tokens = _estimate_agent_message_tokens(msg)
        if preserved_tokens + msg_tokens > recent_budget:
            break
        preserved.insert(0, msg)
        preserved_tokens += msg_tokens

    # Los mensajes a compactar son los anteriores
    to_compact = messages[: len(messages) - len(preserved)]
    if not to_compact:
        return CompactionResult(
            compacted=False,
            tokens_before=tokens_before,
            tokens_after=tokens_before,
        )

    # Calcular budget para summarización
    summary_budget = int(
        effective_limit * compute_adaptive_chunk_ratio(to_compact, config.context_window)
    )
    summary_budget -= SUMMARIZATION_OVERHEAD_TOKENS

    # Chunk y resumir
    instructions = build_summarization_instructions(
        config.custom_instructions,
        config.identifier_policy,
    )

    try:
        chunks = chunk_messages_by_max_tokens(to_compact, summary_budget)
        summaries: List[str] = []

        for chunk in chunks:
            text = serialize_messages_for_summary(chunk)
            if previous_summary and not summaries:
                text = f"Previous context summary:\n{previous_summary}\n\n{text}"
            summary = await summarize(text, instructions)
            summaries.append(summary)

        # Fusionar resúmenes si hay más de uno
        if len(summaries) > 1:
            merge_text = "\n\n---\n\n".join(
                f"Part {i + 1}:\n{s}" for i, s in enumerate(summaries)
            )
            merge_prompt = f"{MERGE_SUMMARIES_INSTRUCTIONS}\n\n{merge_text}"
            final_summary = await summarize(merge_prompt, instructions)
        elif summaries:
            final_summary = summaries[0]
        else:
            final_summary = DEFAULT_SUMMARY_FALLBACK

    except Exception as exc:
        logger.error("Error durante compactación: %s", exc)
        return CompactionResult(
            compacted=False,
            tokens_before=tokens_before,
            tokens_after=tokens_before,
            error=str(exc),
        )

    tokens_after = estimate_tokens(final_summary) + preserved_tokens
    duration = (time.monotonic() - start) * 1000

    logger.info(
        "Compactación completada: %d → %d tokens (%.0f%% reducción, %d chunks, %.0fms)",
        tokens_before,
        tokens_after,
        (1 - tokens_after / tokens_before) * 100 if tokens_before > 0 else 0,
        len(chunks),
        duration,
    )

    return CompactionResult(
        compacted=True,
        summary=final_summary,
        tokens_before=tokens_before,
        tokens_after=tokens_after,
        chunks_processed=len(chunks),
        duration_ms=duration,
    )
