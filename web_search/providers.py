"""Web search — abstracción multi-provider para búsquedas en Internet."""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from shared.errors import SomerError

logger = logging.getLogger(__name__)


class SearchError(SomerError):
    """Error en búsqueda web."""


@dataclass
class SearchResult:
    """Resultado individual de una búsqueda."""

    title: str
    url: str
    snippet: str
    source: str  # Nombre del provider que lo devolvió


class SearchProvider(ABC):
    """Interfaz base para providers de búsqueda."""

    name: str = "base"

    @abstractmethod
    async def search(self, query: str, max_results: int = 5) -> List[SearchResult]:
        """Ejecuta una búsqueda y devuelve resultados."""
        ...

    async def health_check(self) -> bool:
        """Verifica si el provider está disponible."""
        try:
            results = await self.search("test", max_results=1)
            return True
        except Exception:
            return False


class TavilyProvider(SearchProvider):
    """Provider de búsqueda usando la API de Tavily.

    Requiere TAVILY_API_KEY en variables de entorno.
    """

    name = "tavily"

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._api_key = api_key or os.environ.get("TAVILY_API_KEY", "")

    async def search(self, query: str, max_results: int = 5) -> List[SearchResult]:
        if not self._api_key:
            raise SearchError("TAVILY_API_KEY no configurada")

        try:
            import httpx
        except ImportError:
            raise SearchError("httpx no instalado: pip install httpx")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self._api_key,
                    "query": query,
                    "max_results": max_results,
                    "include_answer": False,
                },
            )
            response.raise_for_status()
            data = response.json()

        results: List[SearchResult] = []
        for item in data.get("results", [])[:max_results]:
            results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("content", ""),
                source=self.name,
            ))
        return results


class BraveProvider(SearchProvider):
    """Provider de búsqueda usando Brave Search API.

    Requiere BRAVE_API_KEY en variables de entorno.
    """

    name = "brave"

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._api_key = api_key or os.environ.get("BRAVE_API_KEY", "")

    async def search(self, query: str, max_results: int = 5) -> List[SearchResult]:
        if not self._api_key:
            raise SearchError("BRAVE_API_KEY no configurada")

        try:
            import httpx
        except ImportError:
            raise SearchError("httpx no instalado: pip install httpx")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": max_results},
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "X-Subscription-Token": self._api_key,
                },
            )
            response.raise_for_status()
            data = response.json()

        results: List[SearchResult] = []
        for item in data.get("web", {}).get("results", [])[:max_results]:
            results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("description", ""),
                source=self.name,
            ))
        return results


class DuckDuckGoProvider(SearchProvider):
    """Provider de búsqueda usando DuckDuckGo HTML (sin API key).

    Usa la API lite/html de DuckDuckGo para extraer resultados.
    No requiere autenticación.
    """

    name = "duckduckgo"

    async def search(self, query: str, max_results: int = 5) -> List[SearchResult]:
        try:
            import httpx
        except ImportError:
            raise SearchError("httpx no instalado: pip install httpx")

        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; SOMER/2.0)"},
        ) as client:
            response = await client.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"},
            )
            response.raise_for_status()
            data = response.json()

        results: List[SearchResult] = []

        # Abstract (respuesta directa)
        abstract = data.get("Abstract", "")
        abstract_url = data.get("AbstractURL", "")
        abstract_source = data.get("AbstractSource", "")
        if abstract and abstract_url:
            results.append(SearchResult(
                title=abstract_source or "DuckDuckGo Abstract",
                url=abstract_url,
                snippet=abstract,
                source=self.name,
            ))

        # Related topics
        for topic in data.get("RelatedTopics", []):
            if len(results) >= max_results:
                break
            # Los topics pueden ser dicts directos o groups
            if isinstance(topic, dict) and "FirstURL" in topic:
                results.append(SearchResult(
                    title=topic.get("Text", "")[:100],
                    url=topic.get("FirstURL", ""),
                    snippet=topic.get("Text", ""),
                    source=self.name,
                ))
            elif isinstance(topic, dict) and "Topics" in topic:
                for sub in topic["Topics"]:
                    if len(results) >= max_results:
                        break
                    if isinstance(sub, dict) and "FirstURL" in sub:
                        results.append(SearchResult(
                            title=sub.get("Text", "")[:100],
                            url=sub.get("FirstURL", ""),
                            snippet=sub.get("Text", ""),
                            source=self.name,
                        ))

        return results[:max_results]


class SearchManager:
    """Gestor de búsquedas con múltiples providers.

    Intenta providers en orden de prioridad hasta que uno devuelva
    resultados exitosamente.

    Uso::

        manager = SearchManager()
        manager.add_provider(TavilyProvider())
        manager.add_provider(BraveProvider())
        manager.add_provider(DuckDuckGoProvider())  # fallback sin key

        results = await manager.search("python asyncio tutorial")
    """

    def __init__(self) -> None:
        self._providers: List[SearchProvider] = []

    def add_provider(self, provider: SearchProvider) -> None:
        """Agrega un provider al final de la cadena."""
        self._providers.append(provider)
        logger.info("Search provider '%s' registrado", provider.name)

    def remove_provider(self, name: str) -> bool:
        """Remueve un provider por nombre."""
        before = len(self._providers)
        self._providers = [p for p in self._providers if p.name != name]
        return len(self._providers) < before

    @property
    def provider_names(self) -> List[str]:
        """Nombres de providers registrados en orden de prioridad."""
        return [p.name for p in self._providers]

    async def search(
        self,
        query: str,
        max_results: int = 5,
        *,
        provider_name: Optional[str] = None,
    ) -> List[SearchResult]:
        """Busca usando providers en orden de prioridad.

        Args:
            query: Texto de búsqueda.
            max_results: Máximo de resultados.
            provider_name: Forzar un provider específico.

        Returns:
            Lista de SearchResult.

        Raises:
            SearchError: Si ningún provider pudo ejecutar la búsqueda.
        """
        if not self._providers:
            raise SearchError("No hay providers de búsqueda registrados")

        # Si se especifica un provider, usar solo ese
        if provider_name:
            for p in self._providers:
                if p.name == provider_name:
                    return await p.search(query, max_results)
            raise SearchError(f"Provider '{provider_name}' no encontrado")

        # Intentar en orden
        errors: List[str] = []
        for provider in self._providers:
            try:
                results = await provider.search(query, max_results)
                if results:
                    logger.info(
                        "Búsqueda '%s' completada con %s (%d resultados)",
                        query[:50], provider.name, len(results),
                    )
                    return results
            except Exception as exc:
                msg = f"{provider.name}: {exc}"
                errors.append(msg)
                logger.warning("Falló búsqueda con %s: %s", provider.name, exc)

        raise SearchError(
            f"Ningún provider pudo buscar '{query}'. Errores: {'; '.join(errors)}"
        )
