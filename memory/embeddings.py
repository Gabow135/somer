"""Abstracción multi-provider de embeddings."""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from shared.errors import EmbeddingError

logger = logging.getLogger(__name__)


class EmbeddingProvider(ABC):
    """Interface para providers de embeddings."""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Dimensión de los vectores generados."""
        ...

    @abstractmethod
    async def embed(self, texts: List[str]) -> List[List[float]]:
        """Genera embeddings para una lista de textos."""
        ...

    async def embed_single(self, text: str) -> List[float]:
        """Genera embedding para un solo texto."""
        results = await self.embed([text])
        return results[0]


class OpenAIEmbeddings(EmbeddingProvider):
    """Embeddings vía OpenAI API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "text-embedding-3-small",
        dim: int = 1536,
    ):
        self._api_key = api_key
        self._model = model
        self._dim = dim
        self._client: Any = None

    @property
    def dimension(self) -> int:
        return self._dim

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import openai
            except ImportError:
                raise EmbeddingError("openai no instalado")
            self._client = openai.AsyncOpenAI(api_key=self._api_key)
        return self._client

    async def embed(self, texts: List[str]) -> List[List[float]]:
        client = self._get_client()
        try:
            response = await client.embeddings.create(
                model=self._model, input=texts
            )
            return [item.embedding for item in response.data]
        except Exception as exc:
            raise EmbeddingError(f"Error generando embeddings: {exc}") from exc


class OllamaEmbeddings(EmbeddingProvider):
    """Embeddings vía Ollama (local)."""

    def __init__(
        self,
        model: str = "nomic-embed-text",
        base_url: str = "http://localhost:11434",
        dim: int = 768,
    ):
        self._model = model
        self._base_url = base_url
        self._dim = dim

    @property
    def dimension(self) -> int:
        return self._dim

    async def embed(self, texts: List[str]) -> List[List[float]]:
        import httpx
        results = []
        async with httpx.AsyncClient(timeout=60) as client:
            for text in texts:
                try:
                    resp = await client.post(
                        f"{self._base_url}/api/embeddings",
                        json={"model": self._model, "prompt": text},
                    )
                    resp.raise_for_status()
                    results.append(resp.json()["embedding"])
                except Exception as exc:
                    raise EmbeddingError(f"Error con Ollama embeddings: {exc}") from exc
        return results


class DummyEmbeddings(EmbeddingProvider):
    """Embeddings dummy para testing (vectores aleatorios)."""

    def __init__(self, dim: int = 1536):
        self._dim = dim

    @property
    def dimension(self) -> int:
        return self._dim

    async def embed(self, texts: List[str]) -> List[List[float]]:
        import hashlib
        results = []
        for text in texts:
            # Determinístico basado en hash del texto
            h = hashlib.sha256(text.encode()).digest()
            vec = []
            for i in range(self._dim):
                byte_idx = i % len(h)
                vec.append((h[byte_idx] - 128) / 128.0)
            results.append(vec)
        return results


# ── Nuevos providers ─────────────────────────────────────────


class GeminiEmbeddings(EmbeddingProvider):
    """Embeddings vía Google Gemini API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gemini-embedding-001",
        dim: int = 768,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
    ):
        self._api_key = api_key
        self._model = model
        self._dim = dim
        self._base_url = base_url

    @property
    def dimension(self) -> int:
        return self._dim

    async def embed(self, texts: List[str]) -> List[List[float]]:
        import httpx

        api_key = self._api_key or os.environ.get("GOOGLE_API_KEY", "")
        if not api_key:
            raise EmbeddingError("GOOGLE_API_KEY no configurada")

        url = f"{self._base_url}/models/{self._model}:batchEmbedContents"
        requests_body = [
            {"model": f"models/{self._model}", "content": {"parts": [{"text": t}]},
             "taskType": "RETRIEVAL_DOCUMENT"}
            for t in texts
        ]

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    url,
                    params={"key": api_key},
                    json={"requests": requests_body},
                )
                resp.raise_for_status()
                data = resp.json()
                return [e["values"] for e in data["embeddings"]]
        except Exception as exc:
            raise EmbeddingError(f"Error con Gemini embeddings: {exc}") from exc


class VoyageEmbeddings(EmbeddingProvider):
    """Embeddings vía Voyage AI API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "voyage-3",
        dim: int = 1024,
        base_url: str = "https://api.voyageai.com/v1",
    ):
        self._api_key = api_key
        self._model = model
        self._dim = dim
        self._base_url = base_url

    @property
    def dimension(self) -> int:
        return self._dim

    async def embed(self, texts: List[str]) -> List[List[float]]:
        import httpx

        api_key = self._api_key or os.environ.get("VOYAGE_API_KEY", "")
        if not api_key:
            raise EmbeddingError("VOYAGE_API_KEY no configurada")

        url = f"{self._base_url}/embeddings"
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": self._model,
                        "input": texts,
                        "input_type": "document",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                return [item["embedding"] for item in data["data"]]
        except Exception as exc:
            raise EmbeddingError(f"Error con Voyage embeddings: {exc}") from exc


class MistralEmbeddings(EmbeddingProvider):
    """Embeddings vía Mistral AI API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "mistral-embed",
        dim: int = 1024,
        base_url: str = "https://api.mistral.ai/v1",
    ):
        self._api_key = api_key
        self._model = model
        self._dim = dim
        self._base_url = base_url

    @property
    def dimension(self) -> int:
        return self._dim

    async def embed(self, texts: List[str]) -> List[List[float]]:
        import httpx

        api_key = self._api_key or os.environ.get("MISTRAL_API_KEY", "")
        if not api_key:
            raise EmbeddingError("MISTRAL_API_KEY no configurada")

        url = f"{self._base_url}/embeddings"
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={"model": self._model, "input": texts},
                )
                resp.raise_for_status()
                data = resp.json()
                return [item["embedding"] for item in data["data"]]
        except Exception as exc:
            raise EmbeddingError(f"Error con Mistral embeddings: {exc}") from exc


class SentenceTransformerEmbeddings(EmbeddingProvider):
    """Embeddings locales vía sentence-transformers (sin API externa)."""

    def __init__(
        self,
        model: str = "all-MiniLM-L6-v2",
        dim: int = 384,
    ):
        self._model_name = model
        self._dim = dim
        self._model: Any = None

    @property
    def dimension(self) -> int:
        return self._dim

    def _get_model(self) -> Any:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError:
                raise EmbeddingError("sentence-transformers no instalado")
            self._model = SentenceTransformer(self._model_name)
        return self._model

    async def embed(self, texts: List[str]) -> List[List[float]]:
        model = self._get_model()
        try:
            embeddings = model.encode(texts, convert_to_numpy=True)
            return [vec.tolist() for vec in embeddings]
        except Exception as exc:
            raise EmbeddingError(
                f"Error con SentenceTransformer embeddings: {exc}"
            ) from exc


# ── Fallback wrapper ─────────────────────────────────────────


class FallbackEmbeddingProvider(EmbeddingProvider):
    """Wrapper que intenta un provider primario y cae a un fallback."""

    def __init__(
        self, primary: EmbeddingProvider, fallback: EmbeddingProvider
    ):
        self._primary = primary
        self._fallback = fallback

    @property
    def dimension(self) -> int:
        return self._primary.dimension

    async def embed(self, texts: List[str]) -> List[List[float]]:
        try:
            return await self._primary.embed(texts)
        except EmbeddingError:
            logger.warning(
                "Provider primario falló, usando fallback: %s → %s",
                type(self._primary).__name__,
                type(self._fallback).__name__,
            )
            return await self._fallback.embed(texts)


# ── Factory ──────────────────────────────────────────────────

_PROVIDER_MAP: Dict[str, type] = {
    "openai": OpenAIEmbeddings,
    "ollama": OllamaEmbeddings,
    "gemini": GeminiEmbeddings,
    "voyage": VoyageEmbeddings,
    "mistral": MistralEmbeddings,
    "local": SentenceTransformerEmbeddings,
    "sentence-transformers": SentenceTransformerEmbeddings,
    "dummy": DummyEmbeddings,
}


def _try_auto_select(
    model: str,
    dim: int,
    api_key: Optional[str],
) -> EmbeddingProvider:
    """Auto-selecciona el mejor provider disponible."""
    # 1. sentence-transformers local (offline)
    try:
        import sentence_transformers  # noqa: F401
        return SentenceTransformerEmbeddings(
            model=model or "all-MiniLM-L6-v2",
            dim=dim or 384,
        )
    except ImportError:
        pass

    # 2. OpenAI si hay API key
    key = api_key or os.environ.get("OPENAI_API_KEY")
    if key:
        return OpenAIEmbeddings(
            api_key=key,
            model=model or "text-embedding-3-small",
            dim=dim or 1536,
        )

    # 3. Ollama local (check rápido)
    try:
        import httpx  # noqa: F401
        logger.info("Auto-selección: intentando Ollama en localhost:11434")
        return OllamaEmbeddings(
            model=model or "nomic-embed-text",
            dim=dim or 768,
        )
    except ImportError:
        pass

    # 4. Dummy como último recurso
    logger.warning(
        "Auto-selección: ningún provider de embeddings disponible, usando DummyEmbeddings"
    )
    return DummyEmbeddings(dim=dim or 1536)


def create_embedding_provider(
    provider: str,
    model: str = "",
    dim: int = 0,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    fallback_provider: Optional[str] = None,
) -> EmbeddingProvider:
    """Crea un provider de embeddings por nombre de config.

    Args:
        provider: Nombre del provider ("openai", "ollama", "gemini",
            "voyage", "mistral", "local", "dummy", "auto").
        model: Nombre del modelo (usa default del provider si vacío).
        dim: Dimensión de embedding (usa default del provider si 0).
        api_key: API key (override de env var).
        base_url: Base URL custom.
        fallback_provider: Nombre del provider de fallback.

    Returns:
        EmbeddingProvider configurado.
    """
    if provider == "auto":
        primary = _try_auto_select(model, dim, api_key)
    else:
        cls = _PROVIDER_MAP.get(provider)
        if cls is None:
            raise EmbeddingError(f"Provider de embeddings desconocido: {provider!r}")

        kwargs: Dict[str, Any] = {}
        if model:
            kwargs["model"] = model
        if dim:
            kwargs["dim"] = dim
        if api_key and provider not in ("dummy",):
            kwargs["api_key"] = api_key
        if base_url and provider not in ("dummy", "local", "sentence-transformers"):
            kwargs["base_url"] = base_url

        primary = cls(**kwargs)

    if fallback_provider:
        fallback_cls = _PROVIDER_MAP.get(fallback_provider)
        if fallback_cls is None:
            raise EmbeddingError(
                f"Provider de fallback desconocido: {fallback_provider!r}"
            )
        fallback = fallback_cls()
        return FallbackEmbeddingProvider(primary, fallback)

    return primary
