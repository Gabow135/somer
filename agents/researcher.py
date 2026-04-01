"""Agente investigador especializado.

Realiza búsquedas web profundas, sintetiza información de múltiples
fuentes y produce resúmenes estructurados.

Flujo: query → multi-search → extract → synthesize → report

Python 3.9+ — ``from __future__ import annotations``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Tipos ────────────────────────────────────────────────────


class ResearchDepth(str, Enum):
    """Nivel de profundidad de investigación."""
    QUICK = "quick"        # 1-2 búsquedas, resumen rápido
    STANDARD = "standard"  # 3-5 búsquedas, síntesis moderada
    DEEP = "deep"          # 5-10 búsquedas, síntesis exhaustiva


class SourceType(str, Enum):
    """Tipo de fuente de información."""
    WEB = "web"
    MEMORY = "memory"
    FILE = "file"
    API = "api"


@dataclass
class ResearchSource:
    """Una fuente de información encontrada durante la investigación."""
    title: str = ""
    url: str = ""
    content: str = ""
    source_type: SourceType = SourceType.WEB
    relevance_score: float = 0.0
    extracted_at: float = field(default_factory=time.time)


@dataclass
class ResearchResult:
    """Resultado completo de una investigación."""
    query: str = ""
    summary: str = ""
    key_findings: List[str] = field(default_factory=list)
    sources: List[ResearchSource] = field(default_factory=list)
    follow_up_questions: List[str] = field(default_factory=list)
    depth: ResearchDepth = ResearchDepth.STANDARD
    duration_secs: float = 0.0
    search_count: int = 0

    def to_markdown(self) -> str:
        """Convierte el resultado a Markdown."""
        lines = [
            f"# Investigación: {self.query}",
            "",
            "## Resumen",
            self.summary,
            "",
        ]

        if self.key_findings:
            lines.append("## Hallazgos Clave")
            for i, finding in enumerate(self.key_findings, 1):
                lines.append(f"{i}. {finding}")
            lines.append("")

        if self.sources:
            lines.append("## Fuentes")
            for src in self.sources:
                if src.url:
                    lines.append(f"- [{src.title}]({src.url})")
                else:
                    lines.append(f"- {src.title} ({src.source_type.value})")
            lines.append("")

        if self.follow_up_questions:
            lines.append("## Preguntas de Seguimiento")
            for q in self.follow_up_questions:
                lines.append(f"- {q}")
            lines.append("")

        lines.append(f"*{self.search_count} búsquedas en {self.duration_secs:.1f}s*")
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """Convierte a diccionario serializable."""
        return {
            "query": self.query,
            "summary": self.summary,
            "key_findings": self.key_findings,
            "sources": [
                {
                    "title": s.title,
                    "url": s.url,
                    "type": s.source_type.value,
                    "relevance": s.relevance_score,
                }
                for s in self.sources
            ],
            "follow_up_questions": self.follow_up_questions,
            "depth": self.depth.value,
            "duration_secs": self.duration_secs,
            "search_count": self.search_count,
        }


# ── SearchProvider protocol ──────────────────────────────────

# Tipo para un proveedor de búsqueda externo
SearchFunc = Callable[[str, int], Awaitable[List[Dict[str, Any]]]]


# ── ResearchAgent ────────────────────────────────────────────


class ResearchAgent:
    """Agente investigador que combina múltiples fuentes.

    Uso:
        agent = ResearchAgent(search_func=my_web_search)
        result = await agent.research("¿Cómo funciona QUIC?")
    """

    def __init__(
        self,
        *,
        search_func: Optional[SearchFunc] = None,
        memory_search_func: Optional[SearchFunc] = None,
        llm_func: Optional[Callable[[str], Awaitable[str]]] = None,
        max_concurrent_searches: int = 3,
    ) -> None:
        self._search = search_func
        self._memory_search = memory_search_func
        self._llm = llm_func
        self._max_concurrent = max_concurrent_searches

    async def research(
        self,
        query: str,
        *,
        depth: ResearchDepth = ResearchDepth.STANDARD,
        context: str = "",
        max_sources: int = 10,
    ) -> ResearchResult:
        """Ejecuta una investigación completa.

        Args:
            query: Pregunta o tema a investigar.
            depth: Nivel de profundidad.
            context: Contexto adicional para refinar la búsqueda.
            max_sources: Máximo de fuentes a recopilar.
        """
        start = time.time()
        result = ResearchResult(query=query, depth=depth)

        # 1. Generar sub-queries
        sub_queries = await self._generate_sub_queries(query, context, depth)

        # 2. Ejecutar búsquedas en paralelo
        all_sources: List[ResearchSource] = []
        search_count = 0

        # Búsqueda en memoria (si disponible)
        if self._memory_search:
            memory_results = await self._search_memory(query)
            all_sources.extend(memory_results)

        # Búsquedas web en paralelo
        if self._search:
            semaphore = asyncio.Semaphore(self._max_concurrent)

            async def _bounded_search(q: str) -> List[ResearchSource]:
                async with semaphore:
                    return await self._search_web(q)

            tasks = [_bounded_search(sq) for sq in sub_queries]
            results_lists = await asyncio.gather(*tasks, return_exceptions=True)

            for res in results_lists:
                search_count += 1
                if isinstance(res, list):
                    all_sources.extend(res)

        # 3. Deduplicar y rankear fuentes
        sources = self._deduplicate_sources(all_sources)
        sources = sorted(sources, key=lambda s: s.relevance_score, reverse=True)
        sources = sources[:max_sources]
        result.sources = sources
        result.search_count = search_count

        # 4. Sintetizar hallazgos
        if self._llm and sources:
            synthesis = await self._synthesize(query, sources, depth)
            result.summary = synthesis.get("summary", "")
            result.key_findings = synthesis.get("key_findings", [])
            result.follow_up_questions = synthesis.get("follow_up_questions", [])
        else:
            # Sin LLM, compilar manualmente
            result.summary = self._compile_summary(query, sources)
            result.key_findings = [s.title for s in sources[:5] if s.title]

        result.duration_secs = round(time.time() - start, 2)
        return result

    # ── Sub-query generation ────────────────────────────────

    async def _generate_sub_queries(
        self,
        query: str,
        context: str,
        depth: ResearchDepth,
    ) -> List[str]:
        """Genera sub-queries para ampliar la búsqueda."""
        queries = [query]

        if depth == ResearchDepth.QUICK:
            return queries

        # Variaciones automáticas
        if depth in (ResearchDepth.STANDARD, ResearchDepth.DEEP):
            # Añadir variaciones básicas
            queries.append(f"{query} tutorial guía")
            queries.append(f"{query} mejores prácticas")

        if depth == ResearchDepth.DEEP:
            queries.append(f"{query} comparación alternativas")
            queries.append(f"{query} problemas comunes soluciones")
            queries.append(f"{query} ejemplos código implementación")

        # Si hay LLM, generar queries más inteligentes
        if self._llm and depth == ResearchDepth.DEEP:
            try:
                prompt = (
                    f"Genera 3 sub-preguntas de búsqueda para investigar: {query}\n"
                    f"Contexto: {context}\n"
                    "Responde solo las preguntas, una por línea."
                )
                response = await self._llm(prompt)
                for line in response.strip().split("\n"):
                    line = line.strip().lstrip("0123456789.-) ")
                    if line and len(line) > 10:
                        queries.append(line)
            except Exception as exc:
                logger.warning("Error generando sub-queries: %s", exc)

        return queries

    # ── Search implementations ──────────────────────────────

    async def _search_web(self, query: str) -> List[ResearchSource]:
        """Ejecuta búsqueda web."""
        if not self._search:
            return []

        try:
            results = await self._search(query, 5)
            sources: List[ResearchSource] = []
            for r in results:
                sources.append(ResearchSource(
                    title=r.get("title", ""),
                    url=r.get("url", r.get("link", "")),
                    content=r.get("content", r.get("snippet", "")),
                    source_type=SourceType.WEB,
                    relevance_score=r.get("score", 0.5),
                ))
            return sources
        except Exception as exc:
            logger.warning("Error en búsqueda web para '%s': %s", query[:50], exc)
            return []

    async def _search_memory(self, query: str) -> List[ResearchSource]:
        """Busca en la memoria del agente."""
        if not self._memory_search:
            return []

        try:
            results = await self._memory_search(query, 5)
            return [
                ResearchSource(
                    title=r.get("title", r.get("key", "memory")),
                    content=r.get("content", r.get("text", "")),
                    source_type=SourceType.MEMORY,
                    relevance_score=r.get("score", 0.6),
                )
                for r in results
            ]
        except Exception as exc:
            logger.warning("Error en búsqueda de memoria: %s", exc)
            return []

    # ── Synthesis ────────────────────────────────────────────

    async def _synthesize(
        self,
        query: str,
        sources: List[ResearchSource],
        depth: ResearchDepth,
    ) -> Dict[str, Any]:
        """Sintetiza fuentes en un resumen coherente usando LLM."""
        if not self._llm:
            return {}

        # Compilar contexto de fuentes
        source_texts: List[str] = []
        for i, src in enumerate(sources[:8], 1):
            text = src.content[:2000] if src.content else src.title
            source_texts.append(f"[{i}] {src.title}\n{text}")

        sources_context = "\n\n".join(source_texts)

        prompt = (
            f"Investigación: {query}\n\n"
            f"Fuentes encontradas:\n{sources_context}\n\n"
            "Genera un JSON con:\n"
            '- "summary": resumen de 2-4 párrafos sintetizando la información\n'
            '- "key_findings": lista de 3-5 hallazgos clave\n'
            '- "follow_up_questions": lista de 2-3 preguntas de seguimiento\n'
            "\nResponde SOLO el JSON."
        )

        try:
            response = await self._llm(prompt)
            # Extraer JSON
            start = response.find("{")
            end = response.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(response[start:end])
        except Exception as exc:
            logger.warning("Error sintetizando: %s", exc)

        return {"summary": self._compile_summary(query, sources)}

    def _compile_summary(
        self,
        query: str,
        sources: List[ResearchSource],
    ) -> str:
        """Compilación manual de resumen sin LLM."""
        if not sources:
            return f"No se encontraron fuentes relevantes para: {query}"

        parts = [f"Se encontraron {len(sources)} fuentes relevantes para: {query}\n"]
        for src in sources[:5]:
            if src.content:
                parts.append(f"**{src.title}**: {src.content[:300]}")
        return "\n\n".join(parts)

    # ── Deduplication ────────────────────────────────────────

    def _deduplicate_sources(
        self,
        sources: List[ResearchSource],
    ) -> List[ResearchSource]:
        """Elimina fuentes duplicadas por URL o título similar."""
        seen_urls: set = set()
        seen_titles: set = set()
        unique: List[ResearchSource] = []

        for src in sources:
            if src.url and src.url in seen_urls:
                continue
            title_key = src.title.lower().strip()[:60]
            if title_key and title_key in seen_titles:
                continue

            if src.url:
                seen_urls.add(src.url)
            if title_key:
                seen_titles.add(title_key)
            unique.append(src)

        return unique
