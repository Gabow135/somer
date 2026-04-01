"""Tests para el sistema de memoria.

Cubre: BM25, cosine similarity, hybrid merge, SQLite backend,
embeddings, MemoryManager con ciclo de vida completo, categorías,
tags, importancia, compactación, batch, export/import, deduplicación.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Dict, List

import pytest

from memory.embeddings import DummyEmbeddings
from memory.hybrid import BM25, cosine_similarity, hybrid_search_merge, mmr_rerank
from memory.manager import MemoryManager, _calculate_temporal_decay
from memory.sqlite_backend import SQLiteMemoryBackend, _content_hash
from shared.types import (
    MemoryCategory,
    MemoryEntry,
    MemorySource,
    MemoryStats,
    MemoryStatus,
)


# ── BM25 ────────────────────────────────────────────────────────

class TestBM25:
    """Tests de BM25."""

    def test_add_and_search(self) -> None:
        bm25 = BM25()
        bm25.add_document("d1", "the quick brown fox")
        bm25.add_document("d2", "the lazy brown dog")
        bm25.add_document("d3", "quick fox jumps over")
        results = bm25.search("quick fox")
        assert len(results) > 0
        ids = [r[0] for r in results]
        assert "d1" in ids
        assert "d3" in ids

    def test_remove_document(self) -> None:
        bm25 = BM25()
        bm25.add_document("d1", "hello world")
        assert bm25.document_count == 1
        bm25.remove_document("d1")
        assert bm25.document_count == 0

    def test_empty_search(self) -> None:
        bm25 = BM25()
        results = bm25.search("anything")
        assert results == []

    def test_remove_nonexistent(self) -> None:
        bm25 = BM25()
        bm25.remove_document("nonexistent")
        assert bm25.document_count == 0


# ── Cosine Similarity ───────────────────────────────────────────

class TestCosineSimilarity:
    """Tests de similitud coseno."""

    def test_identical_vectors(self) -> None:
        a = [1.0, 2.0, 3.0]
        assert abs(cosine_similarity(a, a) - 1.0) < 1e-6

    def test_orthogonal_vectors(self) -> None:
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert abs(cosine_similarity(a, b)) < 1e-6

    def test_opposite_vectors(self) -> None:
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert abs(cosine_similarity(a, b) + 1.0) < 1e-6

    def test_different_length(self) -> None:
        assert cosine_similarity([1.0], [1.0, 2.0]) == 0.0

    def test_zero_vector(self) -> None:
        assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


# ── Hybrid Merge ────────────────────────────────────────────────

class TestHybridMerge:
    """Tests del merge híbrido."""

    def test_merge_with_overlap(self) -> None:
        bm25 = [("d1", 1.0), ("d2", 0.5)]
        vector = [("d2", 1.0), ("d3", 0.5)]
        merged = hybrid_search_merge(bm25, vector)
        ids = [r[0] for r in merged]
        assert "d2" in ids
        assert "d1" in ids
        assert "d3" in ids

    def test_empty_inputs(self) -> None:
        result = hybrid_search_merge([], [])
        assert result == []

    def test_weights_affect_ranking(self) -> None:
        bm25 = [("d1", 1.0)]
        vector = [("d2", 1.0)]
        # Con peso alto en BM25
        merged_bm25 = hybrid_search_merge(bm25, vector, bm25_weight=0.9, vector_weight=0.1)
        # d1 debería tener score más alto
        scores = {doc_id: score for doc_id, score in merged_bm25}
        assert scores["d1"] > scores["d2"]


# ── MMR Rerank ──────────────────────────────────────────────────

class TestMMRRerank:
    """Tests de Maximal Marginal Relevance reranking."""

    def test_mmr_rerank_basic(self) -> None:
        query = [1.0, 0.0]
        docs = [
            ("d1", [1.0, 0.0], 0.9),
            ("d2", [0.9, 0.1], 0.8),
            ("d3", [0.0, 1.0], 0.5),
        ]
        results = mmr_rerank(query, docs, lambda_=0.7, limit=3)
        assert len(results) == 3
        assert results[0][0] == "d1"

    def test_mmr_empty(self) -> None:
        results = mmr_rerank([1.0], [], lambda_=0.7, limit=5)
        assert results == []


# ── Temporal Decay ──────────────────────────────────────────────

class TestTemporalDecay:
    """Tests del decay temporal exponencial."""

    def test_no_decay_for_recent(self) -> None:
        multiplier = _calculate_temporal_decay(0.0, 30.0)
        assert abs(multiplier - 1.0) < 1e-6

    def test_half_life_decay(self) -> None:
        """A la mitad de vida, el multiplier debería ser ~0.5."""
        age_secs = 30 * 86400  # 30 días
        multiplier = _calculate_temporal_decay(age_secs, 30.0)
        assert abs(multiplier - 0.5) < 0.01

    def test_decay_increases_with_age(self) -> None:
        young = _calculate_temporal_decay(1 * 86400, 30.0)
        old = _calculate_temporal_decay(60 * 86400, 30.0)
        assert young > old

    def test_zero_half_life(self) -> None:
        multiplier = _calculate_temporal_decay(100.0, 0.0)
        assert multiplier == 1.0


# ── Content Hash ────────────────────────────────────────────────

class TestContentHash:
    """Tests del hash de contenido."""

    def test_deterministic(self) -> None:
        assert _content_hash("hello") == _content_hash("hello")

    def test_different_content(self) -> None:
        assert _content_hash("hello") != _content_hash("world")


# ── SQLite Backend ──────────────────────────────────────────────

class TestSQLiteBackend:
    """Tests del backend SQLite con funcionalidades extendidas."""

    def test_store_and_get(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "test.db"))
        entry = MemoryEntry(content="test content", metadata={"key": "value"})
        entry_id = backend.store(entry)
        retrieved = backend.get(entry_id)
        assert retrieved is not None
        assert retrieved.content == "test content"
        assert retrieved.metadata["key"] == "value"
        backend.close()

    def test_delete(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "test.db"))
        entry = MemoryEntry(content="delete me")
        entry_id = backend.store(entry)
        assert backend.delete(entry_id)
        assert backend.get(entry_id) is None
        backend.close()

    def test_count(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "test.db"))
        assert backend.count() == 0
        backend.store(MemoryEntry(content="one"))
        backend.store(MemoryEntry(content="two"))
        assert backend.count() == 2
        backend.close()

    def test_search_by_text(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "test.db"))
        backend.store(MemoryEntry(content="python programming"))
        backend.store(MemoryEntry(content="java programming"))
        backend.store(MemoryEntry(content="cooking recipes"))
        results = backend.search_by_text("programming")
        assert len(results) == 2
        backend.close()

    def test_search_recent(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "test.db"))
        backend.store(MemoryEntry(content="first"))
        backend.store(MemoryEntry(content="second"))
        results = backend.search_recent(limit=1)
        assert len(results) == 1
        backend.close()

    def test_access_count_increment(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "test.db"))
        entry = MemoryEntry(content="access me")
        entry_id = backend.store(entry)
        backend.get(entry_id)
        backend.get(entry_id)
        result = backend.get(entry_id)
        assert result is not None
        assert result.access_count >= 2
        backend.close()

    # ── Tests de categorías y tags ───────────────────────────────

    def test_store_with_category_and_tags(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "test.db"))
        entry = MemoryEntry(
            content="categorized entry",
            category=MemoryCategory.TASK,
            tags=["urgent", "review"],
            importance=0.9,
        )
        entry_id = backend.store(entry)
        retrieved = backend.get(entry_id)
        assert retrieved is not None
        assert retrieved.category == MemoryCategory.TASK
        assert "urgent" in retrieved.tags
        assert retrieved.importance == 0.9
        backend.close()

    def test_search_by_category(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "test.db"))
        backend.store(MemoryEntry(content="task 1", category=MemoryCategory.TASK))
        backend.store(MemoryEntry(content="knowledge 1", category=MemoryCategory.KNOWLEDGE))
        backend.store(MemoryEntry(content="task 2", category=MemoryCategory.TASK))
        results = backend.search_by_category("task")
        assert len(results) == 2
        backend.close()

    def test_search_by_tags(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "test.db"))
        backend.store(MemoryEntry(content="e1", tags=["python", "code"]))
        backend.store(MemoryEntry(content="e2", tags=["java", "code"]))
        backend.store(MemoryEntry(content="e3", tags=["cooking"]))
        results = backend.search_by_tags(["python"])
        assert len(results) == 1
        assert results[0].content == "e1"
        backend.close()

    def test_search_by_importance(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "test.db"))
        backend.store(MemoryEntry(content="low", importance=0.2))
        backend.store(MemoryEntry(content="high", importance=0.9))
        backend.store(MemoryEntry(content="medium", importance=0.5))
        results = backend.search_by_importance(min_importance=0.8)
        assert len(results) == 1
        assert results[0].content == "high"
        backend.close()

    # ── Tests de archival ────────────────────────────────────────

    def test_archive_and_unarchive(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "test.db"))
        entry = MemoryEntry(content="archive me")
        entry_id = backend.store(entry)
        assert backend.archive(entry_id)
        # Archivada no aparece en count normal
        assert backend.count(include_archived=False) == 0
        assert backend.count(include_archived=True) == 1
        # Restaurar
        assert backend.unarchive(entry_id)
        assert backend.count(include_archived=False) == 1
        backend.close()

    def test_archive_old_entries(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "test.db"))
        old_time = time.time() - (100 * 86400)
        entry = MemoryEntry(
            content="old entry",
            accessed_at=old_time,
            created_at=old_time,
        )
        backend.store(entry)
        backend.store(MemoryEntry(content="new entry"))  # Reciente
        archived = backend.archive_old_entries(max_age_days=90)
        assert archived == 1
        assert backend.count() == 1
        backend.close()

    # ── Tests de update ──────────────────────────────────────────

    def test_update(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "test.db"))
        entry = MemoryEntry(content="original", importance=0.5)
        entry_id = backend.store(entry)
        entry.content = "updated"
        entry.importance = 0.9
        assert backend.update(entry)
        updated = backend.get(entry_id)
        assert updated is not None
        assert updated.content == "updated"
        assert updated.importance == 0.9
        assert updated.version == 2
        backend.close()

    # ── Tests de batch operations ────────────────────────────────

    def test_store_batch(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "test.db"))
        entries = [
            MemoryEntry(content=f"batch entry {i}")
            for i in range(10)
        ]
        ids = backend.store_batch(entries)
        assert len(ids) == 10
        assert backend.count() == 10
        backend.close()

    def test_delete_batch(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "test.db"))
        entries = [MemoryEntry(content=f"entry {i}") for i in range(5)]
        ids = backend.store_batch(entries)
        deleted = backend.delete_batch(ids[:3])
        assert deleted == 3
        assert backend.count() == 2
        backend.close()

    def test_update_importance_batch(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "test.db"))
        e1 = MemoryEntry(content="e1", importance=0.5)
        e2 = MemoryEntry(content="e2", importance=0.3)
        backend.store(e1)
        backend.store(e2)
        updated = backend.update_importance_batch([
            (e1.id, 0.9),
            (e2.id, 0.1),
        ])
        assert updated == 2
        r1 = backend.get_without_access_update(e1.id)
        r2 = backend.get_without_access_update(e2.id)
        assert r1 is not None and abs(r1.importance - 0.9) < 0.01
        assert r2 is not None and abs(r2.importance - 0.1) < 0.01
        backend.close()

    # ── Tests de deduplicación ───────────────────────────────────

    def test_find_duplicates(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "test.db"))
        c_hash = _content_hash("duplicate content")
        backend.store(MemoryEntry(content="duplicate content", content_hash=c_hash))
        backend.store(MemoryEntry(content="duplicate content", content_hash=c_hash))
        dups = backend.find_duplicates(c_hash)
        assert len(dups) == 2
        backend.close()

    # ── Tests de estadísticas ────────────────────────────────────

    def test_stats(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "test.db"))
        backend.store(MemoryEntry(content="t1", category=MemoryCategory.TASK))
        backend.store(MemoryEntry(content="k1", category=MemoryCategory.KNOWLEDGE))
        backend.store(MemoryEntry(content="t2", category=MemoryCategory.TASK))
        s = backend.stats()
        assert s.total_entries == 3
        assert s.active_entries == 3
        assert s.total_by_category.get("task") == 2
        assert s.total_by_category.get("knowledge") == 1
        backend.close()

    # ── Tests de export / import ─────────────────────────────────

    def test_export_entries(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "test.db"))
        backend.store(MemoryEntry(content="export me"))
        data = backend.export_entries()
        assert len(data) == 1
        assert data[0]["content"] == "export me"
        backend.close()

    def test_import_entries(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "test.db"))
        data = [
            {"content": "imported 1", "importance": 0.8},
            {"content": "imported 2"},
        ]
        count = backend.import_entries(data)
        assert count == 2
        assert backend.count() == 2
        backend.close()

    # ── Tests de meta key-value ──────────────────────────────────

    def test_meta_get_set(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "test.db"))
        assert backend.get_meta("test_key") is None
        backend.set_meta("test_key", "test_value")
        assert backend.get_meta("test_key") == "test_value"
        backend.set_meta("test_key", "updated")
        assert backend.get_meta("test_key") == "updated"
        backend.close()

    # ── Tests de migración de esquema ────────────────────────────

    def test_schema_migration(self, tmp_path: Path) -> None:
        """Verifica que el backend maneja bases de datos con esquema legacy."""
        db_path = str(tmp_path / "legacy.db")
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE memory_entries (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                embedding TEXT,
                metadata TEXT DEFAULT '{}',
                session_id TEXT,
                created_at REAL NOT NULL,
                accessed_at REAL NOT NULL,
                access_count INTEGER DEFAULT 0
            )
        """)
        conn.execute(
            "INSERT INTO memory_entries VALUES (?, ?, NULL, '{}', NULL, ?, ?, 0)",
            ("legacy1", "legacy content", time.time(), time.time()),
        )
        conn.commit()
        conn.close()

        # Abrir con el nuevo backend debería migrar
        backend = SQLiteMemoryBackend(db_path)
        entry = backend.get("legacy1")
        assert entry is not None
        assert entry.content == "legacy content"
        assert entry.category == MemoryCategory.KNOWLEDGE  # default
        assert entry.tags == []  # default
        backend.close()


# ── Dummy Embeddings ────────────────────────────────────────────

class TestDummyEmbeddings:
    """Tests de embeddings dummy."""

    @pytest.mark.asyncio
    async def test_embed_single(self) -> None:
        emb = DummyEmbeddings(dim=128)
        result = await emb.embed_single("hello world")
        assert len(result) == 128

    @pytest.mark.asyncio
    async def test_embed_batch(self) -> None:
        emb = DummyEmbeddings(dim=64)
        results = await emb.embed(["hello", "world"])
        assert len(results) == 2
        assert len(results[0]) == 64

    @pytest.mark.asyncio
    async def test_deterministic(self) -> None:
        emb = DummyEmbeddings(dim=32)
        a = await emb.embed_single("test")
        b = await emb.embed_single("test")
        assert a == b

    def test_dimension_property(self) -> None:
        emb = DummyEmbeddings(dim=256)
        assert emb.dimension == 256


# ── MemoryManager ───────────────────────────────────────────────

class TestMemoryManager:
    """Tests del MemoryManager con funcionalidades extendidas."""

    @pytest.mark.asyncio
    async def test_store_and_search(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
        mgr = MemoryManager(backend=backend, embedding_provider=DummyEmbeddings(dim=64))
        await mgr.store("Python is a programming language")
        await mgr.store("JavaScript runs in browsers")
        await mgr.store("Cooking is an art form")
        results = await mgr.search("programming language", limit=2)
        assert len(results) <= 2
        mgr.close()

    @pytest.mark.asyncio
    async def test_delete(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
        mgr = MemoryManager(backend=backend, embedding_provider=DummyEmbeddings(dim=64))
        entry_id = await mgr.store("delete this")
        assert mgr.count() == 1
        await mgr.delete(entry_id)
        assert mgr.count() == 0
        mgr.close()

    @pytest.mark.asyncio
    async def test_rebuild_index(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
        mgr = MemoryManager(backend=backend, embedding_provider=DummyEmbeddings(dim=64))
        await mgr.store("entry one")
        await mgr.store("entry two")
        count = await mgr.rebuild_index()
        assert count == 2
        mgr.close()

    # ── Tests de categorías y tags ───────────────────────────────

    @pytest.mark.asyncio
    async def test_store_with_category_and_tags(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
        mgr = MemoryManager(backend=backend, embedding_provider=DummyEmbeddings(dim=64))
        entry_id = await mgr.store(
            "important task",
            category=MemoryCategory.TASK,
            tags=["urgent"],
            importance=0.95,
        )
        entry = await mgr.get(entry_id)
        assert entry is not None
        assert entry.category == MemoryCategory.TASK
        assert "urgent" in entry.tags
        assert entry.importance == 0.95
        mgr.close()

    @pytest.mark.asyncio
    async def test_search_by_category(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
        mgr = MemoryManager(backend=backend, embedding_provider=DummyEmbeddings(dim=64))
        await mgr.store("task 1", category=MemoryCategory.TASK)
        await mgr.store("knowledge 1", category=MemoryCategory.KNOWLEDGE)
        results = await mgr.search_by_category(MemoryCategory.TASK)
        assert len(results) == 1
        assert results[0].content == "task 1"
        mgr.close()

    @pytest.mark.asyncio
    async def test_search_by_tags(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
        mgr = MemoryManager(backend=backend, embedding_provider=DummyEmbeddings(dim=64))
        await mgr.store("py stuff", tags=["python"])
        await mgr.store("js stuff", tags=["javascript"])
        results = await mgr.search_by_tags(["python"])
        assert len(results) == 1
        mgr.close()

    @pytest.mark.asyncio
    async def test_search_with_filters(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
        mgr = MemoryManager(backend=backend, embedding_provider=DummyEmbeddings(dim=64))
        await mgr.store("python programming", category=MemoryCategory.KNOWLEDGE, importance=0.9)
        await mgr.store("python cooking", category=MemoryCategory.PREFERENCE, importance=0.3)
        results = await mgr.search(
            "python",
            category=MemoryCategory.KNOWLEDGE,
            min_importance=0.5,
        )
        assert len(results) == 1
        assert results[0].category == MemoryCategory.KNOWLEDGE
        mgr.close()

    # ── Tests de update ──────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_update(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
        mgr = MemoryManager(backend=backend, embedding_provider=DummyEmbeddings(dim=64))
        entry_id = await mgr.store("original content")
        assert await mgr.update(entry_id, content="updated content", importance=0.8)
        entry = await mgr.get(entry_id)
        assert entry is not None
        assert entry.content == "updated content"
        assert entry.importance == 0.8
        mgr.close()

    @pytest.mark.asyncio
    async def test_update_nonexistent(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
        mgr = MemoryManager(backend=backend, embedding_provider=DummyEmbeddings(dim=64))
        result = await mgr.update("nonexistent", content="new")
        assert result is False
        mgr.close()

    # ── Tests de importancia ─────────────────────────────────────

    @pytest.mark.asyncio
    async def test_boost_importance(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
        mgr = MemoryManager(backend=backend, embedding_provider=DummyEmbeddings(dim=64))
        entry_id = await mgr.store("test", importance=0.5)
        assert await mgr.boost_importance(entry_id, boost=0.3)
        entry = await mgr.get(entry_id)
        assert entry is not None
        assert abs(entry.importance - 0.8) < 0.01
        mgr.close()

    @pytest.mark.asyncio
    async def test_search_by_importance(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
        mgr = MemoryManager(backend=backend, embedding_provider=DummyEmbeddings(dim=64))
        await mgr.store("low", importance=0.1)
        await mgr.store("high", importance=0.9)
        results = await mgr.search_by_importance(min_importance=0.7)
        assert len(results) == 1
        assert results[0].content == "high"
        mgr.close()

    # ── Tests de archival ────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_archive_and_unarchive(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
        mgr = MemoryManager(backend=backend, embedding_provider=DummyEmbeddings(dim=64))
        entry_id = await mgr.store("archive me")
        assert mgr.count() == 1
        assert await mgr.archive(entry_id)
        assert mgr.count() == 0  # Archivada no aparece
        assert await mgr.unarchive(entry_id)
        assert mgr.count() == 1
        mgr.close()

    # ── Tests de deduplicación ───────────────────────────────────

    @pytest.mark.asyncio
    async def test_deduplication_on_store(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
        mgr = MemoryManager(backend=backend, embedding_provider=DummyEmbeddings(dim=64))
        id1 = await mgr.store("same content")
        id2 = await mgr.store("same content")
        assert id1 == id2  # Debe reutilizar
        assert mgr.count() == 1
        mgr.close()

    @pytest.mark.asyncio
    async def test_deduplication_disabled(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
        mgr = MemoryManager(backend=backend, embedding_provider=DummyEmbeddings(dim=64))
        id1 = await mgr.store("same content", deduplicate=False)
        id2 = await mgr.store("same content", deduplicate=False)
        assert id1 != id2
        assert mgr.count() == 2
        mgr.close()

    @pytest.mark.asyncio
    async def test_deduplicate_existing(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
        mgr = MemoryManager(backend=backend, embedding_provider=DummyEmbeddings(dim=64))
        await mgr.store("dup1", deduplicate=False)
        await mgr.store("dup1", deduplicate=False)
        await mgr.store("unique")
        assert mgr.count() == 3
        removed = await mgr.deduplicate()
        assert removed == 1
        assert mgr.count() == 2
        mgr.close()

    # ── Tests de batch operations ────────────────────────────────

    @pytest.mark.asyncio
    async def test_store_batch(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
        mgr = MemoryManager(backend=backend, embedding_provider=DummyEmbeddings(dim=64))
        items = [{"content": f"batch item {i}"} for i in range(5)]
        ids = await mgr.store_batch(items)
        assert len(ids) == 5
        assert mgr.count() == 5
        mgr.close()

    @pytest.mark.asyncio
    async def test_store_batch_deduplication(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
        mgr = MemoryManager(backend=backend, embedding_provider=DummyEmbeddings(dim=64))
        items = [
            {"content": "duplicate"},
            {"content": "duplicate"},
            {"content": "unique"},
        ]
        ids = await mgr.store_batch(items)
        assert len(ids) == 2  # Uno se deduplica
        mgr.close()

    @pytest.mark.asyncio
    async def test_delete_batch(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
        mgr = MemoryManager(backend=backend, embedding_provider=DummyEmbeddings(dim=64))
        ids = []
        for i in range(5):
            ids.append(await mgr.store(f"entry {i}", deduplicate=False))
        deleted = await mgr.delete_batch(ids[:3])
        assert deleted == 3
        assert mgr.count() == 2
        mgr.close()

    # ── Tests de compactación ────────────────────────────────────

    @pytest.mark.asyncio
    async def test_compact(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
        # Embeddings similares para contenidos similares
        mgr = MemoryManager(
            backend=backend,
            embedding_provider=DummyEmbeddings(dim=64),
            compaction_similarity=0.99,  # Solo casi idénticos
        )
        # Almacenar contenido idéntico (embeddings serán iguales)
        id1 = await mgr.store("exact same text here", deduplicate=False)
        id2 = await mgr.store("exact same text here", deduplicate=False)
        compacted = await mgr.compact()
        assert compacted >= 1
        mgr.close()

    # ── Tests de export / import ─────────────────────────────────

    @pytest.mark.asyncio
    async def test_export_and_import(self, tmp_path: Path) -> None:
        backend1 = SQLiteMemoryBackend(str(tmp_path / "mem1.db"))
        mgr1 = MemoryManager(backend=backend1, embedding_provider=DummyEmbeddings(dim=64))
        await mgr1.store("export me 1", tags=["test"], importance=0.8)
        await mgr1.store("export me 2", category=MemoryCategory.TASK)

        json_data = await mgr1.export_to_json()
        mgr1.close()

        # Importar en otro manager
        backend2 = SQLiteMemoryBackend(str(tmp_path / "mem2.db"))
        mgr2 = MemoryManager(backend=backend2, embedding_provider=DummyEmbeddings(dim=64))
        count = await mgr2.import_from_json(json_data)
        assert count == 2
        assert mgr2.count() == 2
        mgr2.close()

    @pytest.mark.asyncio
    async def test_export_format(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
        mgr = MemoryManager(backend=backend, embedding_provider=DummyEmbeddings(dim=64))
        await mgr.store("test entry")
        json_data = await mgr.export_to_json()
        parsed = json.loads(json_data)
        assert parsed["version"] == "2.0"
        assert parsed["count"] == 1
        assert "entries" in parsed
        assert parsed["entries"][0]["content"] == "test entry"
        mgr.close()

    @pytest.mark.asyncio
    async def test_import_invalid_json(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
        mgr = MemoryManager(backend=backend, embedding_provider=DummyEmbeddings(dim=64))
        from shared.errors import MemoryExportError
        with pytest.raises(MemoryExportError):
            await mgr.import_from_json("not json")
        mgr.close()

    # ── Tests de sync ────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_sync(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
        mgr = MemoryManager(
            backend=backend,
            embedding_provider=DummyEmbeddings(dim=64),
            archive_after_days=0.0001,  # ~8.6 segundos
            compaction_threshold=10000,  # No compactar
        )
        await mgr.store("sync test")
        assert mgr.is_dirty
        await mgr.sync(reason="test")
        assert not mgr.is_dirty
        assert mgr.last_sync_at is not None
        mgr.close()

    # ── Tests de estadísticas ────────────────────────────────────

    @pytest.mark.asyncio
    async def test_stats(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
        mgr = MemoryManager(backend=backend, embedding_provider=DummyEmbeddings(dim=64))
        await mgr.store("t1", category=MemoryCategory.TASK, importance=0.8)
        await mgr.store("k1", category=MemoryCategory.KNOWLEDGE, importance=0.4)
        s = mgr.stats()
        assert s.total_entries == 2
        assert s.active_entries == 2
        assert s.total_by_category.get("task") == 1
        assert s.total_by_category.get("knowledge") == 1
        mgr.close()

    # ── Tests de MMR search ──────────────────────────────────────

    @pytest.mark.asyncio
    async def test_search_with_mmr(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
        mgr = MemoryManager(backend=backend, embedding_provider=DummyEmbeddings(dim=64))
        await mgr.store("Python programming language")
        await mgr.store("Python data science")
        await mgr.store("Cooking recipes for dinner")
        results = await mgr.search("Python", limit=3, use_mmr=True)
        assert len(results) >= 1
        mgr.close()

    # ── Tests de source ──────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_store_with_source(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
        mgr = MemoryManager(backend=backend, embedding_provider=DummyEmbeddings(dim=64))
        entry_id = await mgr.store(
            "session memory",
            source=MemorySource.SESSIONS,
        )
        entry = await mgr.get(entry_id)
        assert entry is not None
        assert entry.source == MemorySource.SESSIONS
        mgr.close()

    # ── Tests de cierre ──────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_close_idempotent(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
        mgr = MemoryManager(backend=backend, embedding_provider=DummyEmbeddings(dim=64))
        mgr.close()
        mgr.close()  # No debería fallar

    @pytest.mark.asyncio
    async def test_empty_search(self, tmp_path: Path) -> None:
        backend = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
        mgr = MemoryManager(backend=backend, embedding_provider=DummyEmbeddings(dim=64))
        results = await mgr.search("", limit=10)
        assert results == []
        mgr.close()
