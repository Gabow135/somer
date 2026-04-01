"""Catálogo de modelos de embedding con metadatos de token limits y dimensiones."""

from __future__ import annotations

from typing import Dict, NamedTuple


class EmbeddingModelInfo(NamedTuple):
    """Metadatos de un modelo de embedding."""

    max_tokens: int
    dim: int


EMBEDDING_MODEL_LIMITS: Dict[str, EmbeddingModelInfo] = {
    "openai:text-embedding-3-small": EmbeddingModelInfo(max_tokens=8192, dim=1536),
    "openai:text-embedding-3-large": EmbeddingModelInfo(max_tokens=8192, dim=3072),
    "openai:text-embedding-ada-002": EmbeddingModelInfo(max_tokens=8191, dim=1536),
    "gemini:gemini-embedding-001": EmbeddingModelInfo(max_tokens=2048, dim=768),
    "voyage:voyage-3": EmbeddingModelInfo(max_tokens=32000, dim=1024),
    "mistral:mistral-embed": EmbeddingModelInfo(max_tokens=8192, dim=1024),
    "local:all-MiniLM-L6-v2": EmbeddingModelInfo(max_tokens=512, dim=384),
    "ollama:nomic-embed-text": EmbeddingModelInfo(max_tokens=8192, dim=768),
}

# Defaults conservadores para modelos desconocidos
_DEFAULT_INFO = EmbeddingModelInfo(max_tokens=512, dim=768)


def get_model_info(provider: str, model: str) -> EmbeddingModelInfo:
    """Retorna info del modelo, con defaults conservadores si no se conoce."""
    key = f"{provider}:{model}"
    return EMBEDDING_MODEL_LIMITS.get(key, _DEFAULT_INFO)


def get_default_dim(provider: str, model: str) -> int:
    """Dimensión por defecto para un provider:model."""
    return get_model_info(provider, model).dim
