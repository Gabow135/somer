"""Memory Manager — coordina BM25 + vector + SQLite con ciclo de vida completo.

Portado y extendido desde OpenClaw:
- qmd-manager.ts: Gestor principal de memoria con CRUD, búsqueda, sync
- manager-sync-ops.ts: Sincronización, deduplicación, reindexación
- manager.ts: MemoryIndexManager con hybrid search, fallback, batch
- temporal-decay.ts: Decay temporal exponencial
- internal.ts: Hash, chunking, cosine similarity

Características portadas:
- CRUD completo con versionado
- Búsqueda híbrida BM25 + vector con temporal decay y MMR
- Categorización y tags de entradas
- Scoring de importancia con decay automático
- Compactación y merge de entradas similares
- Archival automático por antigüedad
- Operaciones batch (insert, update, delete)
- Export/import para backup y restauración
- Sincronización y reindexación
- Deduplicación por hash de contenido
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import time
from collections import OrderedDict
from typing import Any, Callable, Dict, ItemsView, List, Optional, Tuple

from memory.embeddings import DummyEmbeddings, EmbeddingProvider
from memory.hybrid import (
    BM25,
    cosine_similarity,
    hybrid_search_merge,
    mmr_rerank,
    mmr_rerank_text,
)

# Try to import native HNSW vector index (Rust via PyO3)
try:
    from memory.hybrid import VectorIndex, _HAS_VECTOR_INDEX
except ImportError:
    _HAS_VECTOR_INDEX = False
from memory.sqlite_backend import SQLiteMemoryBackend, _content_hash
from shared.constants import (
    MEMORY_ARCHIVE_AFTER_DAYS,
    MEMORY_BATCH_SIZE,
    MEMORY_COMPACTION_SIMILARITY,
    MEMORY_COMPACTION_THRESHOLD,
    MEMORY_IMPORTANCE_DECAY_FACTOR,
    MEMORY_MAX_EXPORT_ENTRIES,
    MEMORY_TEMPORAL_DECAY_DAYS,
)
from shared.errors import (
    MemoryBatchError,
    MemoryCompactionError,
    MemoryExportError,
    MemoryNotFoundError,
    MemorySyncError,
)
from shared.types import (
    MemoryCategory,
    MemoryEntry,
    MemorySource,
    MemoryStats,
    MemoryStatus,
    MemorySyncProgress,
)

logger = logging.getLogger(__name__)


class LRUEmbeddingCache:
    """Cache LRU de embeddings con tamaño máximo para evitar memory leaks.

    Almacena vectores como numpy arrays (float32) en lugar de listas Python.
    Ahorro de RAM: 14x menos por embedding (4 bytes vs ~56 bytes por float).
    Límite: maxsize × dimensión × 4 bytes (ej: 2000 × 1536 × 4 = ~12MB máx).
    """

    def __init__(self, maxsize: int = 2000):
        self._maxsize = maxsize
        self._cache: "OrderedDict[str, Any]" = OrderedDict()

    def __setitem__(self, key: str, value: "List[float]") -> None:
        if key in self._cache:
            self._cache.move_to_end(key)
        else:
            if len(self._cache) >= self._maxsize:
                self._cache.popitem(last=False)
        try:
            import numpy as np
            self._cache[key] = np.asarray(value, dtype=np.float32)
        except ImportError:
            self._cache[key] = value

    def __getitem__(self, key: str) -> "Any":
        if key in self._cache:
            self._cache.move_to_end(key)
        return self._cache[key]

    def __contains__(self, key: object) -> bool:
        return key in self._cache

    def get(self, key: str, default: "Any" = None) -> "Any":
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return default

    def pop(self, key: str, *args: "Any") -> "Any":
        return self._cache.pop(key, *args)

    def items(self) -> "ItemsView":
        return self._cache.items()

    def clear(self) -> None:
        self._cache.clear()

    def __len__(self) -> int:
        return len(self._cache)

    def __bool__(self) -> bool:
        return bool(self._cache)

    def to_list(self, key: str) -> "List[float]":
        """Retorna como lista Python (para compatibilidad)."""
        val = self._cache.get(key)
        if val is None:
            return []
        try:
            import numpy as np
            if isinstance(val, np.ndarray):
                return val.tolist()
        except ImportError:
            pass
        return list(val)


def _calculate_temporal_decay(
    age_seconds: float,
    half_life_days: float,
) -> float:
    """Calcula el multiplicador de decay temporal exponencial.

    Portado de OpenClaw: temporal-decay.ts calculateTemporalDecayMultiplier.
    Usa decaimiento exponencial: multiplier = exp(-lambda * age_days)
    donde lambda = ln(2) / half_life_days.
    """
    if half_life_days <= 0:
        return 1.0
    age_days = age_seconds / 86400.0
    lam = math.log(2) / half_life_days
    return math.exp(-lam * max(0.0, age_days))


class MemoryManager:
    """Coordina búsqueda híbrida BM25 + vector con backend SQLite.

    Portado de OpenClaw: MemoryIndexManager + QmdMemoryManager.

    Funcionalidades:
    - Almacenamiento y búsqueda híbrida BM25 + vector
    - Categorización y tags
    - Scoring de importancia con decay automático
    - Compactación de entradas similares
    - Archival y ciclo de vida
    - Operaciones batch
    - Export/import
    - Sincronización y reindexación
    - Deduplicación por hash
    """

    def __init__(
        self,
        backend: Optional[SQLiteMemoryBackend] = None,
        embedding_provider: Optional[EmbeddingProvider] = None,
        temporal_decay_days: int = MEMORY_TEMPORAL_DECAY_DAYS,
        compaction_threshold: int = MEMORY_COMPACTION_THRESHOLD,
        compaction_similarity: float = MEMORY_COMPACTION_SIMILARITY,
        archive_after_days: float = MEMORY_ARCHIVE_AFTER_DAYS,
        importance_decay_factor: float = MEMORY_IMPORTANCE_DECAY_FACTOR,
        temporal_decay_enabled: bool = True,
        evergreen_categories: Optional[List[str]] = None,
        bm25_weight: float = 0.3,
        vector_weight: float = 0.7,
        mmr_enabled: bool = False,
        mmr_lambda: float = 0.7,
        min_score: float = 0.0,
    ):
        self._backend = backend or SQLiteMemoryBackend()
        self._embeddings = embedding_provider or DummyEmbeddings()
        self._bm25 = BM25()
        self._temporal_decay_days = temporal_decay_days
        self._compaction_threshold = compaction_threshold
        self._compaction_similarity = compaction_similarity
        self._archive_after_days = archive_after_days
        self._importance_decay_factor = importance_decay_factor
        self._temporal_decay_enabled = temporal_decay_enabled
        self._evergreen_categories: List[str] = (
            evergreen_categories if evergreen_categories is not None else ["system"]
        )
        self._bm25_weight = bm25_weight
        self._vector_weight = vector_weight
        self._mmr_enabled = mmr_enabled
        self._mmr_lambda = mmr_lambda
        self._min_score = min_score
        self._embedding_cache: LRUEmbeddingCache = LRUEmbeddingCache(maxsize=2000)
        self._vector_index: "Any" = None  # VectorIndex (Rust HNSW) or None
        self._vector_index_dim: int = 0   # Track dimension for lazy init
        self._dirty = False
        self._last_sync_at: Optional[float] = None
        self._closed = False

    # ── CRUD ─────────────────────────────────────────────────────

    async def store(
        self,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        category: MemoryCategory = MemoryCategory.KNOWLEDGE,
        tags: Optional[List[str]] = None,
        source: MemorySource = MemorySource.MEMORY,
        importance: float = 0.5,
        deduplicate: bool = True,
    ) -> str:
        """Almacena contenido en memoria con embedding.

        Portado de OpenClaw: almacenamiento con deduplicación por hash
        y embeddings opcionales.

        Args:
            content: Texto a almacenar.
            metadata: Metadata adicional.
            session_id: ID de sesión asociada.
            category: Categoría de la entrada.
            tags: Tags para clasificación.
            source: Origen de la entrada.
            importance: Importancia (0.0 - 1.0).
            deduplicate: Si es True, no crea duplicados por hash.

        Returns:
            ID de la entrada creada o existente si es duplicada.
        """
        c_hash = _content_hash(content)

        # Deduplicación por hash (portado de OpenClaw: manager-sync-ops.ts)
        if deduplicate:
            duplicates = self._backend.find_duplicates(c_hash)
            if duplicates:
                existing = duplicates[0]
                logger.debug(
                    "Contenido duplicado detectado (hash=%s), reutilizando id=%s",
                    c_hash[:12], existing.id,
                )
                return existing.id

        embedding = await self._embeddings.embed_single(content)
        now = time.time()
        entry = MemoryEntry(
            content=content,
            content_hash=c_hash,
            embedding=embedding,
            metadata=metadata or {},
            session_id=session_id,
            category=category,
            tags=tags or [],
            source=source,
            importance=max(0.0, min(1.0, importance)),
            created_at=now,
            updated_at=now,
            accessed_at=now,
        )
        entry_id = self._backend.store(entry)
        self._bm25.add_document(entry_id, content)
        self._embedding_cache[entry_id] = embedding
        self._add_to_vector_index(entry_id, embedding)
        self._dirty = True
        return entry_id

    async def get(self, entry_id: str) -> Optional[MemoryEntry]:
        """Recupera una entrada por ID."""
        return self._backend.get(entry_id)

    async def update(
        self,
        entry_id: str,
        content: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        category: Optional[MemoryCategory] = None,
        tags: Optional[List[str]] = None,
        importance: Optional[float] = None,
    ) -> bool:
        """Actualiza una entrada existente.

        Portado de OpenClaw: actualización incremental con versionado
        automático y reindexación de BM25/vector.

        Returns:
            True si se actualizó correctamente.
        """
        existing = self._backend.get_without_access_update(entry_id)
        if not existing:
            return False

        # Construir entrada actualizada
        updated = existing.model_copy()
        if content is not None:
            updated.content = content
            updated.content_hash = _content_hash(content)
        if metadata is not None:
            updated.metadata = metadata
        if category is not None:
            updated.category = category
        if tags is not None:
            updated.tags = tags
        if importance is not None:
            updated.importance = max(0.0, min(1.0, importance))

        result = self._backend.update(updated)
        if result and content is not None:
            # Reindexar BM25 y embeddings
            self._bm25.remove_document(entry_id)
            self._bm25.add_document(entry_id, content)
            new_embedding = await self._embeddings.embed_single(content)
            self._embedding_cache[entry_id] = new_embedding
            self._add_to_vector_index(entry_id, new_embedding)
            self._dirty = True
        return result

    async def delete(self, entry_id: str) -> bool:
        """Elimina una entrada permanentemente."""
        self._bm25.remove_document(entry_id)
        self._remove_from_vector_index(entry_id)
        self._embedding_cache.pop(entry_id, None)
        result = self._backend.delete(entry_id)
        if result:
            self._dirty = True
        return result

    # ── Archival (portado de OpenClaw) ───────────────────────────

    async def archive(self, entry_id: str) -> bool:
        """Archiva una entrada (soft delete).

        Portado de OpenClaw: ciclo de vida con archival.
        """
        result = self._backend.archive(entry_id)
        if result:
            self._bm25.remove_document(entry_id)
            self._remove_from_vector_index(entry_id)
            self._embedding_cache.pop(entry_id, None)
            self._dirty = True
        return result

    async def unarchive(self, entry_id: str) -> bool:
        """Restaura una entrada archivada."""
        result = self._backend.unarchive(entry_id)
        if result:
            entry = self._backend.get_without_access_update(entry_id)
            if entry:
                self._bm25.add_document(entry_id, entry.content)
                if entry.embedding:
                    self._embedding_cache[entry_id] = entry.embedding
                    self._add_to_vector_index(entry_id, entry.embedding)
            self._dirty = True
        return result

    async def archive_old_entries(
        self, max_age_days: Optional[float] = None
    ) -> int:
        """Archiva entradas antiguas basándose en última fecha de acceso.

        Portado de OpenClaw: retención temporal con retentionMs/retentionDays.
        """
        days = max_age_days if max_age_days is not None else self._archive_after_days
        count = self._backend.archive_old_entries(days)
        if count > 0:
            # Reconstruir índices ya que se archivaron entries
            await self.rebuild_index()
        return count

    # ── Búsqueda ─────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        limit: int = 10,
        bm25_weight: Optional[float] = None,
        vector_weight: Optional[float] = None,
        session_id: Optional[str] = None,
        category: Optional[MemoryCategory] = None,
        tags: Optional[List[str]] = None,
        min_importance: float = 0.0,
        min_score: Optional[float] = None,
        use_mmr: Optional[bool] = None,
        mmr_lambda: Optional[float] = None,
    ) -> List[MemoryEntry]:
        """Búsqueda híbrida BM25 + vector con filtros avanzados.

        Portado de OpenClaw: MemoryIndexManager.search() con hybrid merge,
        temporal decay, MMR reranking y filtros por categoría/tags.

        Los parámetros de búsqueda usan los valores de config como default
        cuando no se especifican explícitamente.

        Args:
            query: Texto de búsqueda.
            limit: Máximo de resultados.
            bm25_weight: Peso del componente BM25 (default: config).
            vector_weight: Peso del componente vector (default: config).
            session_id: Filtrar por sesión.
            category: Filtrar por categoría.
            tags: Filtrar por tags.
            min_importance: Importancia mínima.
            min_score: Score mínimo del resultado (default: config).
            use_mmr: Aplicar MMR reranking (default: config).
            mmr_lambda: Balance relevancia/diversidad (default: config).

        Returns:
            Lista de MemoryEntry ordenados por relevancia.
        """
        if not query.strip():
            return []

        # Usar defaults de config cuando no se pasan explícitamente
        eff_bm25_weight = bm25_weight if bm25_weight is not None else self._bm25_weight
        eff_vector_weight = vector_weight if vector_weight is not None else self._vector_weight
        eff_min_score = min_score if min_score is not None else self._min_score
        eff_use_mmr = use_mmr if use_mmr is not None else self._mmr_enabled
        eff_mmr_lambda = mmr_lambda if mmr_lambda is not None else self._mmr_lambda

        # BM25 search
        bm25_results = self._bm25.search(query, limit=limit * 3)

        # Vector search
        query_embedding = await self._embeddings.embed_single(query)
        vector_results = await self._vector_search(query_embedding, limit * 3)

        # MMR reranking (portado de OpenClaw: mmr.ts)
        if eff_use_mmr and vector_results:
            doc_embeddings: List[Tuple[str, List[float], float]] = []
            for doc_id, score in vector_results:
                emb = self._embedding_cache.get(doc_id)
                if emb is not None and (not hasattr(emb, '__len__') or len(emb) > 0):
                    doc_embeddings.append((doc_id, list(emb) if hasattr(emb, 'tolist') else emb, score))
            if doc_embeddings:
                mmr_results = mmr_rerank(
                    query_embedding, doc_embeddings,
                    lambda_=eff_mmr_lambda, limit=limit * 3,
                )
                vector_results = mmr_results
            elif bm25_results:
                # Fallback: MMR texto con Jaccard (sin embeddings)
                text_docs: List[Tuple[str, str, float]] = []
                for doc_id, score in bm25_results:
                    entry = self._backend.get_without_access_update(doc_id)
                    if entry:
                        text_docs.append((doc_id, entry.content, score))
                if text_docs:
                    bm25_results = mmr_rerank_text(
                        query, text_docs,
                        lambda_=eff_mmr_lambda, limit=limit * 3,
                    )

        # Merge híbrido (portado de OpenClaw: hybrid.ts mergeHybridResults)
        merged = hybrid_search_merge(
            bm25_results, vector_results,
            bm25_weight=eff_bm25_weight,
            vector_weight=eff_vector_weight,
        )

        # Aplicar temporal decay (portado de OpenClaw: temporal-decay.ts)
        decayed = self._apply_temporal_decay(merged)

        # Recuperar entries completas y aplicar filtros
        results: List[MemoryEntry] = []
        for doc_id, score in decayed:
            if score < eff_min_score:
                continue
            entry = self._backend.get_without_access_update(doc_id)
            if not entry:
                continue
            if entry.status != MemoryStatus.ACTIVE:
                continue
            if entry.importance < min_importance:
                continue
            if category is not None and entry.category != category:
                continue
            if tags and not any(t in entry.tags for t in tags):
                continue
            entry.score = score
            results.append(entry)
            if len(results) >= limit:
                break

        return results

    async def search_by_category(
        self, category: MemoryCategory, limit: int = 50
    ) -> List[MemoryEntry]:
        """Busca entradas por categoría."""
        return self._backend.search_by_category(category.value, limit)

    async def search_by_tags(
        self, tags: List[str], limit: int = 50
    ) -> List[MemoryEntry]:
        """Busca entradas que contengan alguno de los tags dados."""
        return self._backend.search_by_tags(tags, limit)

    async def search_by_importance(
        self, min_importance: float = 0.7, limit: int = 50
    ) -> List[MemoryEntry]:
        """Busca entradas con importancia mínima."""
        return self._backend.search_by_importance(min_importance, limit)

    # ── Importancia (portado de OpenClaw) ────────────────────────

    async def boost_importance(
        self, entry_id: str, boost: float = 0.1
    ) -> bool:
        """Incrementa la importancia de una entrada.

        Portado de OpenClaw: scoring de relevancia con ajuste manual.
        """
        entry = self._backend.get_without_access_update(entry_id)
        if not entry:
            return False
        new_importance = min(1.0, entry.importance + boost)
        return await self.update(entry_id, importance=new_importance)

    async def decay_importance(self) -> int:
        """Aplica decay de importancia a todas las entradas activas.

        Portado de OpenClaw: decay progresivo de importancia basado en
        antigüedad y frecuencia de acceso.

        Returns:
            Número de entradas actualizadas.
        """
        entries = self._backend.get_all_active()
        updates: List[Tuple[str, float]] = []
        now = time.time()
        for entry in entries:
            age_days = (now - entry.accessed_at) / 86400.0
            if age_days < 1.0:
                continue
            # Factor de decay basado en antigüedad de acceso
            decay = self._importance_decay_factor ** age_days
            new_importance = max(0.01, entry.importance * decay)
            if abs(new_importance - entry.importance) > 0.001:
                updates.append((entry.id, new_importance))

        if updates:
            count = self._backend.update_importance_batch(updates)
            logger.info("Decay de importancia aplicado a %d entradas", count)
            return count
        return 0

    # ── Compactación (portado de OpenClaw) ───────────────────────

    async def compact(
        self,
        similarity_threshold: Optional[float] = None,
        merge_fn: Optional[Callable[[str, str], str]] = None,
        progress_fn: Optional[Callable[[MemorySyncProgress], None]] = None,
    ) -> int:
        """Compacta la memoria fusionando entradas similares.

        Portado de OpenClaw: resetIndex + syncMemoryFiles + syncSessionFiles
        con deduplicación y merge de chunks similares.

        Encuentra pares de entradas cuya similitud vectorial supera
        el umbral y las fusiona en una sola entrada.

        Args:
            similarity_threshold: Umbral de similitud (0.0-1.0).
            merge_fn: Función para combinar contenido de dos entradas.
            progress_fn: Callback de progreso.

        Returns:
            Número de entradas compactadas (eliminadas por merge).
        """
        threshold = similarity_threshold or self._compaction_similarity
        entries = self._backend.get_all_active()

        if len(entries) < 2:
            return 0

        if progress_fn:
            progress_fn(MemorySyncProgress(
                completed=0, total=len(entries), label="Compactando memoria..."
            ))

        merged_count = 0
        merged_ids: set = set()

        try:
            for i, entry_a in enumerate(entries):
                if entry_a.id in merged_ids:
                    continue
                emb_a = self._embedding_cache.get(entry_a.id)
                if emb_a is None and entry_a.embedding is not None:
                    emb_a = entry_a.embedding
                if emb_a is None:
                    continue

                for entry_b in entries[i + 1:]:
                    if entry_b.id in merged_ids:
                        continue
                    emb_b = self._embedding_cache.get(entry_b.id)
                    if emb_b is None and entry_b.embedding is not None:
                        emb_b = entry_b.embedding
                    if emb_b is None:
                        continue

                    sim = cosine_similarity(emb_a, emb_b)
                    if sim >= threshold:
                        # Merge: conservar la más importante/reciente
                        if merge_fn:
                            merged_content = merge_fn(entry_a.content, entry_b.content)
                        else:
                            merged_content = self._default_merge(
                                entry_a.content, entry_b.content
                            )
                        # Mantener entry_a, eliminar entry_b
                        new_importance = max(entry_a.importance, entry_b.importance)
                        merged_tags = list(set(entry_a.tags + entry_b.tags))
                        await self.update(
                            entry_a.id,
                            content=merged_content,
                            importance=new_importance,
                            tags=merged_tags,
                        )
                        await self.delete(entry_b.id)
                        merged_ids.add(entry_b.id)
                        merged_count += 1

                if progress_fn:
                    progress_fn(MemorySyncProgress(
                        completed=i + 1, total=len(entries),
                        label=f"Compactadas {merged_count} entradas"
                    ))

        except Exception as exc:
            raise MemoryCompactionError(
                f"Error durante compactación: {exc}"
            ) from exc

        if merged_count > 0:
            logger.info("Compactación completada: %d entradas fusionadas", merged_count)
        return merged_count

    # ── Deduplicación (portado de OpenClaw) ──────────────────────

    async def deduplicate(self) -> int:
        """Elimina entradas duplicadas por hash de contenido.

        Portado de OpenClaw: deduplicación en manager-sync-ops.ts
        usando hash de contenido para identificar duplicados exactos.

        Returns:
            Número de duplicados eliminados.
        """
        entries = self._backend.get_all_active()
        seen_hashes: Dict[str, str] = {}  # hash -> id
        duplicates: List[str] = []

        for entry in entries:
            c_hash = entry.content_hash or _content_hash(entry.content)
            if c_hash in seen_hashes:
                # Conservar el más antiguo (primero visto)
                duplicates.append(entry.id)
            else:
                seen_hashes[c_hash] = entry.id

        if duplicates:
            count = self._backend.delete_batch(duplicates)
            # Limpiar índices
            for entry_id in duplicates:
                self._bm25.remove_document(entry_id)
                self._embedding_cache.pop(entry_id, None)
            logger.info("Deduplicación: %d entradas duplicadas eliminadas", count)
            self._dirty = True
            return count
        return 0

    # ── Batch operations (portado de OpenClaw) ───────────────────

    async def store_batch(
        self,
        items: List[Dict[str, Any]],
        deduplicate: bool = True,
    ) -> List[str]:
        """Almacena un lote de entradas.

        Portado de OpenClaw: batch indexing con runWithConcurrency
        y transacciones atómicas.

        Args:
            items: Lista de dicts con 'content' y campos opcionales.
            deduplicate: Deduplicar por hash.

        Returns:
            Lista de IDs creados.

        Raises:
            MemoryBatchError: Si hay un error en el batch.
        """
        try:
            entries: List[MemoryEntry] = []
            seen_hashes: set = set()

            for item in items:
                content = item.get("content", "")
                if not content:
                    continue

                c_hash = _content_hash(content)
                if deduplicate:
                    if c_hash in seen_hashes:
                        continue
                    existing = self._backend.find_duplicates(c_hash)
                    if existing:
                        continue
                    seen_hashes.add(c_hash)

                embedding = await self._embeddings.embed_single(content)
                now = time.time()
                entry = MemoryEntry(
                    content=content,
                    content_hash=c_hash,
                    embedding=embedding,
                    metadata=item.get("metadata", {}),
                    session_id=item.get("session_id"),
                    category=item.get("category", MemoryCategory.KNOWLEDGE),
                    tags=item.get("tags", []),
                    source=item.get("source", MemorySource.MEMORY),
                    importance=item.get("importance", 0.5),
                    created_at=now,
                    updated_at=now,
                    accessed_at=now,
                )
                entries.append(entry)

            if not entries:
                return []

            # Batch en trozos para evitar transacciones enormes
            all_ids: List[str] = []
            for i in range(0, len(entries), MEMORY_BATCH_SIZE):
                batch = entries[i:i + MEMORY_BATCH_SIZE]
                ids = self._backend.store_batch(batch)
                # Indexar en BM25 y cache de embeddings
                for entry in batch:
                    self._bm25.add_document(entry.id, entry.content)
                    if entry.embedding:
                        self._embedding_cache[entry.id] = entry.embedding
                all_ids.extend(ids)

            self._dirty = True
            logger.info("Batch store: %d entradas almacenadas", len(all_ids))
            return all_ids

        except Exception as exc:
            raise MemoryBatchError(
                f"Error en batch store: {exc}"
            ) from exc

    async def delete_batch(self, entry_ids: List[str]) -> int:
        """Elimina un lote de entradas.

        Returns:
            Número de entradas eliminadas.
        """
        for entry_id in entry_ids:
            self._bm25.remove_document(entry_id)
            self._embedding_cache.pop(entry_id, None)
        count = self._backend.delete_batch(entry_ids)
        if count > 0:
            self._dirty = True
        return count

    # ── Export / Import (portado de OpenClaw) ────────────────────

    async def export_to_json(
        self, include_archived: bool = False
    ) -> str:
        """Exporta la memoria a formato JSON.

        Portado de OpenClaw: exportación de sesiones a Markdown
        adaptada a JSON para SOMER.

        Returns:
            String JSON con todas las entradas.
        """
        try:
            data = self._backend.export_entries(
                include_archived=include_archived,
                max_entries=MEMORY_MAX_EXPORT_ENTRIES,
            )
            return json.dumps({
                "version": "2.0",
                "exported_at": time.time(),
                "count": len(data),
                "entries": data,
            }, ensure_ascii=False, indent=2)
        except Exception as exc:
            raise MemoryExportError(f"Error al exportar: {exc}") from exc

    async def import_from_json(self, json_data: str) -> int:
        """Importa memoria desde formato JSON.

        Portado de OpenClaw: importación con deduplicación.

        Returns:
            Número de entradas importadas.
        """
        try:
            parsed = json.loads(json_data)
            entries = parsed.get("entries", [])
            if not entries:
                return 0
            count = self._backend.import_entries(entries)
            if count > 0:
                await self.rebuild_index()
            return count
        except json.JSONDecodeError as exc:
            raise MemoryExportError(f"JSON inválido: {exc}") from exc
        except Exception as exc:
            raise MemoryExportError(f"Error al importar: {exc}") from exc

    # ── Sincronización (portado de OpenClaw) ─────────────────────

    async def sync(
        self,
        reason: str = "manual",
        force: bool = False,
        progress_fn: Optional[Callable[[MemorySyncProgress], None]] = None,
    ) -> None:
        """Sincroniza los índices de memoria.

        Portado de OpenClaw: QmdMemoryManager.sync() y
        MemoryIndexManager.sync() con update, embed y reindex.

        Args:
            reason: Motivo de la sincronización.
            force: Forzar reindexación completa.
            progress_fn: Callback de progreso.
        """
        if self._closed:
            return

        try:
            if progress_fn:
                progress_fn(MemorySyncProgress(
                    completed=0, total=3,
                    label=f"Sincronizando memoria ({reason})..."
                ))

            if force or self._dirty:
                await self.rebuild_index()
                if progress_fn:
                    progress_fn(MemorySyncProgress(
                        completed=1, total=3,
                        label="Índices reconstruidos"
                    ))

            # Archival automático
            archived = self._backend.archive_old_entries(self._archive_after_days)
            if archived > 0 and progress_fn:
                progress_fn(MemorySyncProgress(
                    completed=2, total=3,
                    label=f"{archived} entradas archivadas"
                ))

            # Auto-compactación si supera umbral
            active_count = self._backend.count()
            if active_count > self._compaction_threshold:
                await self.compact(progress_fn=progress_fn)

            self._dirty = False
            self._last_sync_at = time.time()

            if progress_fn:
                progress_fn(MemorySyncProgress(
                    completed=3, total=3,
                    label="Sincronización completada"
                ))

            logger.info("Sync completado (reason=%s)", reason)

        except Exception as exc:
            raise MemorySyncError(
                f"Error en sync ({reason}): {exc}"
            ) from exc

    # ── Reindexación ─────────────────────────────────────────────

    async def rebuild_index(self) -> int:
        """Reconstruye los índices BM25, vector HNSW y embeddings desde SQLite.

        Portado de OpenClaw: runSafeReindex / runUnsafeReindex en
        manager-sync-ops.ts.
        """
        self._bm25 = BM25()
        self._embedding_cache.clear()
        self._vector_index = None
        self._vector_index_dim = 0
        entries = self._backend.search_recent(limit=100000, include_archived=False)
        for entry in entries:
            self._bm25.add_document(entry.id, entry.content)
            if entry.embedding:
                self._embedding_cache[entry.id] = entry.embedding
                self._add_to_vector_index(entry.id, entry.embedding)
        logger.info("Índice reconstruido: %d entries", len(entries))
        return len(entries)

    # ── Estadísticas ─────────────────────────────────────────────

    def count(self) -> int:
        """Número de entradas activas."""
        return self._backend.count()

    def stats(self) -> MemoryStats:
        """Estadísticas completas del sistema de memoria.

        Portado de OpenClaw: MemoryIndexManager.status() y
        QmdMemoryManager.status().
        """
        return self._backend.stats()

    @property
    def is_dirty(self) -> bool:
        """Indica si hay cambios pendientes de sincronizar."""
        return self._dirty

    @property
    def last_sync_at(self) -> Optional[float]:
        """Timestamp de la última sincronización."""
        return self._last_sync_at

    # ── Cierre ───────────────────────────────────────────────────

    def close(self) -> None:
        """Cierra recursos.

        Portado de OpenClaw: MemoryIndexManager.close() y
        QmdMemoryManager.close().
        """
        if self._closed:
            return
        self._closed = True
        self._backend.close()

    # ── Métodos privados ─────────────────────────────────────────

    def _add_to_vector_index(self, entry_id: str, embedding: "Any") -> None:
        """Agrega un vector al índice HNSW nativo (si disponible)."""
        if not _HAS_VECTOR_INDEX:
            return
        try:
            # Convert embedding to list of floats
            if hasattr(embedding, 'tolist'):
                vec = embedding.tolist()
            else:
                vec = list(embedding)
            if not vec:
                return
            # Convert to f32
            vec_f32 = [float(v) for v in vec]
            dim = len(vec_f32)
            # Lazy init of VectorIndex on first embedding
            if self._vector_index is None or self._vector_index_dim != dim:
                self._vector_index = VectorIndex(dim=dim)
                self._vector_index_dim = dim
                # Re-add existing cached embeddings to new index
                for eid, emb in self._embedding_cache.items():
                    if eid == entry_id:
                        continue
                    if hasattr(emb, 'tolist'):
                        ev = emb.tolist()
                    else:
                        ev = list(emb)
                    if len(ev) == dim:
                        self._vector_index.add_vector(eid, [float(v) for v in ev])
            self._vector_index.add_vector(entry_id, vec_f32)
        except Exception:
            # Non-critical: fall back to numpy/brute-force search
            logger.debug("No se pudo agregar al índice HNSW: %s", entry_id, exc_info=True)

    def _remove_from_vector_index(self, entry_id: str) -> None:
        """Elimina un vector del índice HNSW nativo (si disponible)."""
        if self._vector_index is not None:
            try:
                self._vector_index.remove_vector(entry_id)
            except Exception:
                logger.debug("No se pudo eliminar del índice HNSW: %s", entry_id, exc_info=True)

    async def _vector_search(
        self, query_embedding: List[float], limit: int
    ) -> List[Tuple[str, float]]:
        """Búsqueda por similitud vectorial — HNSW nativo > numpy batch > Python puro."""
        if not self._embedding_cache:
            return []

        # Fase 2: Usar HNSW nativo de Rust (O(log n) vs O(n) brute-force)
        if self._vector_index is not None and self._vector_index.count > 0:
            try:
                qvec = [float(v) for v in query_embedding]
                if len(qvec) == self._vector_index_dim:
                    results = self._vector_index.search(qvec, k=limit)
                    return [(doc_id, float(sim)) for doc_id, sim in results]
            except Exception:
                logger.debug("HNSW search falló, fallback a numpy", exc_info=True)

        # Fallback: numpy brute-force (Fase 1)
        try:
            import numpy as np
            doc_ids = list(self._embedding_cache._cache.keys())
            embeddings_list = list(self._embedding_cache._cache.values())
            # Construye matriz de embeddings: (N, D) float32
            matrix = np.stack(
                [e if isinstance(e, np.ndarray) else np.asarray(e, dtype=np.float32)
                 for e in embeddings_list]
            )  # shape: (N, D)
            query_vec = np.asarray(query_embedding, dtype=np.float32)
            query_norm = float(np.linalg.norm(query_vec))
            if query_norm == 0.0:
                return []
            # Similitudes coseno vectorizadas: (N,)
            dots = matrix @ query_vec
            norms = np.linalg.norm(matrix, axis=1)
            similarities = dots / (norms * query_norm + 1e-8)
            # Top-k eficiente
            n = len(similarities)
            k = min(limit, n)
            if k < n:
                top_indices = np.argpartition(similarities, -k)[-k:]
                top_indices = top_indices[np.argsort(similarities[top_indices])[::-1]]
            else:
                top_indices = np.argsort(similarities)[::-1]
            return [(doc_ids[i], float(similarities[i])) for i in top_indices]
        except (ImportError, ValueError):
            # Fallback a Python puro si numpy falla
            results: List[Tuple[str, float]] = []
            for doc_id, embedding in self._embedding_cache.items():
                sim = cosine_similarity(query_embedding, list(embedding) if hasattr(embedding, 'tolist') else embedding)
                results.append((doc_id, sim))
            results.sort(key=lambda x: x[1], reverse=True)
            return results[:limit]

    def _apply_temporal_decay(
        self, results: List[Tuple[str, float]]
    ) -> List[Tuple[str, float]]:
        """Aplica decay temporal exponencial a los scores.

        Portado de OpenClaw: temporal-decay.ts applyTemporalDecayToScore.
        Mejorado con:
        - Uso de accessed_at en vez de created_at (memorias accedidas recientemente
          se mantienen relevantes más tiempo).
        - Categorías evergreen (sin decay).
        - Importancia como factor de decay (entradas importantes decaen menos).
        """
        if not self._temporal_decay_enabled:
            return list(results)

        now = time.time()
        decayed: List[Tuple[str, float]] = []
        for doc_id, score in results:
            entry = self._backend.get_without_access_update(doc_id)
            if not entry:
                continue

            # Categorías evergreen: sin decay
            if entry.category and entry.category.value in self._evergreen_categories:
                decayed.append((doc_id, score))
                continue

            # Usar accessed_at para calcular edad (más alineado con memoria humana)
            age = now - entry.accessed_at
            decay_multiplier = _calculate_temporal_decay(age, self._temporal_decay_days)

            # Importancia como factor: entries importantes decaen menos
            effective_multiplier = decay_multiplier * (0.5 + 0.5 * entry.importance)

            decayed.append((doc_id, score * effective_multiplier))
        decayed.sort(key=lambda x: x[1], reverse=True)
        return decayed

    @staticmethod
    def _default_merge(content_a: str, content_b: str) -> str:
        """Merge por defecto: combina contenidos eliminando duplicados de líneas."""
        lines_a = set(content_a.strip().splitlines())
        lines_b = content_b.strip().splitlines()
        merged_lines = list(content_a.strip().splitlines())
        for line in lines_b:
            if line not in lines_a:
                merged_lines.append(line)
        return "\n".join(merged_lines)
