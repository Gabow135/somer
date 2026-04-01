"""Sistema de memoria de SOMER 2.0.

Portado y extendido desde OpenClaw:
- Búsqueda híbrida BM25 + vector con SQLite
- Categorización y tags de entradas
- Scoring de importancia con decay automático
- Compactación y merge de entradas similares
- Archival automático por antigüedad
- Operaciones batch
- Export/import para backup y restauración
- Deduplicación por hash de contenido
"""

from memory.embedding_models import (
    EMBEDDING_MODEL_LIMITS,
    EmbeddingModelInfo,
    get_default_dim,
    get_model_info,
)
from memory.embeddings import (
    DummyEmbeddings,
    EmbeddingProvider,
    FallbackEmbeddingProvider,
    GeminiEmbeddings,
    MistralEmbeddings,
    OllamaEmbeddings,
    OpenAIEmbeddings,
    SentenceTransformerEmbeddings,
    VoyageEmbeddings,
    create_embedding_provider,
)
from memory.hybrid import (
    BM25,
    cosine_similarity,
    hybrid_search_merge,
    jaccard_similarity,
    mmr_rerank,
    mmr_rerank_text,
)
from memory.manager import MemoryManager
from memory.sqlite_backend import SQLiteMemoryBackend

__all__ = [
    "BM25",
    "DummyEmbeddings",
    "EMBEDDING_MODEL_LIMITS",
    "EmbeddingModelInfo",
    "EmbeddingProvider",
    "FallbackEmbeddingProvider",
    "GeminiEmbeddings",
    "MemoryManager",
    "MistralEmbeddings",
    "OllamaEmbeddings",
    "OpenAIEmbeddings",
    "SQLiteMemoryBackend",
    "SentenceTransformerEmbeddings",
    "VoyageEmbeddings",
    "cosine_similarity",
    "create_embedding_provider",
    "get_default_dim",
    "get_model_info",
    "hybrid_search_merge",
    "jaccard_similarity",
    "mmr_rerank",
    "mmr_rerank_text",
]
