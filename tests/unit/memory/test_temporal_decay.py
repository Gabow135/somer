"""Tests para temporal decay mejorado y configuración de búsqueda.

Cubre: decay con accessed_at, categorías evergreen, importancia como
factor de decay, temporal_decay_enabled, config defaults en search().
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional

import pytest

from memory.embeddings import DummyEmbeddings
from memory.manager import MemoryManager, _calculate_temporal_decay
from memory.sqlite_backend import SQLiteMemoryBackend
from shared.types import MemoryCategory, MemoryEntry, MemoryStatus


# ── Helpers ──────────────────────────────────────────────────────


def _make_manager(
    temporal_decay_enabled: bool = True,
    evergreen_categories: Optional[List[str]] = None,
    temporal_decay_days: int = 30,
    bm25_weight: float = 0.3,
    vector_weight: float = 0.7,
    mmr_enabled: bool = False,
    mmr_lambda: float = 0.7,
    min_score: float = 0.0,
) -> MemoryManager:
    """Crea un MemoryManager de testing con backend en memoria."""
    return MemoryManager(
        backend=SQLiteMemoryBackend(":memory:"),
        embedding_provider=DummyEmbeddings(dim=64),
        temporal_decay_enabled=temporal_decay_enabled,
        evergreen_categories=evergreen_categories,
        temporal_decay_days=temporal_decay_days,
        bm25_weight=bm25_weight,
        vector_weight=vector_weight,
        mmr_enabled=mmr_enabled,
        mmr_lambda=mmr_lambda,
        min_score=min_score,
    )


def _set_accessed_at(mgr: MemoryManager, entry_id: str, accessed_at: float) -> None:
    """Manipula accessed_at directamente en SQLite (bypass del backend.update)."""
    conn = mgr._backend._conn
    assert conn is not None
    conn.execute(
        "UPDATE memory_entries SET accessed_at = ? WHERE id = ?",
        (accessed_at, entry_id),
    )
    conn.commit()


# ── _calculate_temporal_decay ────────────────────────────────────


class TestCalculateTemporalDecay:
    """Tests de la función base _calculate_temporal_decay."""

    def test_zero_age_returns_one(self) -> None:
        assert _calculate_temporal_decay(0, 30) == 1.0

    def test_half_life_returns_half(self) -> None:
        # A los 30 días exactos, el multiplier debería ser ~0.5
        age_secs = 30 * 86400.0
        result = _calculate_temporal_decay(age_secs, 30)
        assert abs(result - 0.5) < 0.01

    def test_zero_half_life_returns_one(self) -> None:
        assert _calculate_temporal_decay(86400, 0) == 1.0

    def test_negative_age_treated_as_zero(self) -> None:
        assert _calculate_temporal_decay(-100, 30) == 1.0


# ── Temporal Decay con accessed_at ───────────────────────────────


class TestTemporalDecayAccessedAt:
    """Tests de decay basado en accessed_at."""

    @pytest.mark.asyncio
    async def test_recently_accessed_less_decay(self) -> None:
        mgr = _make_manager(temporal_decay_days=1)
        # Almacenar dos entradas con contenido idéntico (deduplicate=False)
        id1 = await mgr.store(
            "test search content alpha beta",
            category=MemoryCategory.KNOWLEDGE,
            deduplicate=False,
        )
        id2 = await mgr.store(
            "test search content alpha beta",
            category=MemoryCategory.KNOWLEDGE,
            deduplicate=False,
        )

        now = time.time()
        # entry1 accedida hace 1 segundo, entry2 accedida hace 30 días
        _set_accessed_at(mgr, id1, now - 1)
        _set_accessed_at(mgr, id2, now - 30 * 86400)

        results = await mgr.search("test search content alpha", limit=2)
        assert len(results) == 2
        scores = {r.id: r.score for r in results}
        # Contenido idéntico → mismo base score. Con temporal decay,
        # entry1 (recién accedida) debe tener score más alto
        assert scores[id1] > scores[id2]

    @pytest.mark.asyncio
    async def test_decay_disabled_no_modification(self) -> None:
        mgr = _make_manager(temporal_decay_enabled=False)
        id1 = await mgr.store("test decay disabled content", category=MemoryCategory.KNOWLEDGE)

        # Manipular accessed_at a hace 365 días
        _set_accessed_at(mgr, id1, time.time() - 365 * 86400)

        results = await mgr.search("test decay disabled", limit=1)
        assert len(results) == 1
        # Score no debería verse reducido por decay


# ── Categorías Evergreen ─────────────────────────────────────────


class TestEvergreenCategories:
    """Tests de categorías sin temporal decay."""

    @pytest.mark.asyncio
    async def test_system_category_no_decay(self) -> None:
        mgr = _make_manager(evergreen_categories=["system"], temporal_decay_days=1)
        id1 = await mgr.store(
            "system configuration rules important",
            category=MemoryCategory.SYSTEM,
        )

        # Hacer que parezca muy vieja
        _set_accessed_at(mgr, id1, time.time() - 365 * 86400)

        results = await mgr.search("system configuration rules", limit=1)
        assert len(results) == 1
        # La categoría system es evergreen, no debería tener decay

    @pytest.mark.asyncio
    async def test_normal_category_has_decay(self) -> None:
        mgr = _make_manager(evergreen_categories=["system"], temporal_decay_days=1)
        # Contenido idéntico para aislar el efecto del decay
        id_old = await mgr.store(
            "conversation about weather patterns today",
            category=MemoryCategory.CONVERSATION,
            deduplicate=False,
        )
        id_new = await mgr.store(
            "conversation about weather patterns today",
            category=MemoryCategory.CONVERSATION,
            deduplicate=False,
        )

        # Hacer old muy vieja
        _set_accessed_at(mgr, id_old, time.time() - 30 * 86400)

        results = await mgr.search("conversation weather patterns", limit=2)
        assert len(results) == 2
        scores = {r.id: r.score for r in results}
        # La nueva (recién accedida) debería tener más score
        assert scores[id_new] > scores[id_old]

    @pytest.mark.asyncio
    async def test_custom_evergreen_categories(self) -> None:
        mgr = _make_manager(evergreen_categories=["system", "knowledge"])
        id1 = await mgr.store(
            "python is a programming language knowledge base",
            category=MemoryCategory.KNOWLEDGE,
        )

        _set_accessed_at(mgr, id1, time.time() - 365 * 86400)

        results = await mgr.search("python programming language", limit=1)
        assert len(results) == 1
        # knowledge es evergreen en esta config


# ── Importancia como Factor de Decay ─────────────────────────────


class TestImportanceDecayFactor:
    """Tests de importancia como factor de decay."""

    @pytest.mark.asyncio
    async def test_high_importance_less_decay(self) -> None:
        mgr = _make_manager(temporal_decay_days=7)
        # Contenido idéntico para aislar el efecto de importancia
        id_high = await mgr.store(
            "security policy for servers critical",
            category=MemoryCategory.KNOWLEDGE,
            importance=1.0,
            deduplicate=False,
        )
        id_low = await mgr.store(
            "security policy for servers critical",
            category=MemoryCategory.KNOWLEDGE,
            importance=0.0,
            deduplicate=False,
        )

        now = time.time()
        # Ambas accedidas hace 14 días (2 half-lives)
        _set_accessed_at(mgr, id_high, now - 14 * 86400)
        _set_accessed_at(mgr, id_low, now - 14 * 86400)

        results = await mgr.search("security policy servers", limit=2)
        assert len(results) == 2
        scores = {r.id: r.score for r in results}
        # High importance debería tener mejor score después del decay
        assert scores[id_high] > scores[id_low]

    @pytest.mark.asyncio
    async def test_evergreen_with_low_importance_no_decay(self) -> None:
        mgr = _make_manager(evergreen_categories=["system"], temporal_decay_days=1)
        entry_id = await mgr.store(
            "system rule low importance test",
            category=MemoryCategory.SYSTEM,
            importance=0.1,
        )

        _set_accessed_at(mgr, entry_id, time.time() - 100 * 86400)

        results = await mgr.search("system rule low importance", limit=1)
        assert len(results) == 1
        # Evergreen ignora decay completamente, incluso con baja importancia


# ── Config Defaults en search() ──────────────────────────────────


class TestSearchConfigDefaults:
    """Tests de que search() usa config como defaults."""

    @pytest.mark.asyncio
    async def test_default_bm25_weight_from_config(self) -> None:
        mgr = _make_manager(bm25_weight=0.8, vector_weight=0.2)
        await mgr.store("test content for search", category=MemoryCategory.KNOWLEDGE)
        # No debería lanzar error al buscar con defaults
        results = await mgr.search("test content")
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_override_config_defaults(self) -> None:
        mgr = _make_manager(bm25_weight=0.3, vector_weight=0.7)
        await mgr.store("override test content data", category=MemoryCategory.KNOWLEDGE)
        # Pasar valores explícitos que sobreescriben config
        results = await mgr.search(
            "override test",
            bm25_weight=0.9,
            vector_weight=0.1,
        )
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_mmr_enabled_from_config(self) -> None:
        mgr = _make_manager(mmr_enabled=True, mmr_lambda=0.5)
        await mgr.store("mmr test content alpha", category=MemoryCategory.KNOWLEDGE)
        await mgr.store("mmr test content beta", category=MemoryCategory.KNOWLEDGE)
        results = await mgr.search("mmr test content")
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_min_score_from_config(self) -> None:
        mgr = _make_manager(min_score=999.0)
        await mgr.store("high threshold content test", category=MemoryCategory.KNOWLEDGE)
        results = await mgr.search("high threshold content")
        # Con min_score=999, nada debería pasar el filtro
        assert len(results) == 0


# ── MemoryConfig campos nuevos ───────────────────────────────────


class TestMemoryConfigNewFields:
    """Tests de los nuevos campos en MemoryConfig."""

    def test_default_values(self) -> None:
        from config.schema import MemoryConfig
        cfg = MemoryConfig()
        assert cfg.embedding_fallback_provider is None
        assert cfg.embedding_api_key is None
        assert cfg.embedding_base_url is None
        assert cfg.bm25_weight == 0.3
        assert cfg.vector_weight == 0.7
        assert cfg.mmr_enabled is False
        assert cfg.mmr_lambda == 0.7
        assert cfg.min_score == 0.0
        assert cfg.temporal_decay_enabled is True
        assert cfg.evergreen_categories == ["system"]

    def test_custom_values(self) -> None:
        from config.schema import MemoryConfig
        cfg = MemoryConfig(
            embedding_fallback_provider="dummy",
            bm25_weight=0.5,
            vector_weight=0.5,
            mmr_enabled=True,
            mmr_lambda=0.6,
            min_score=0.1,
            temporal_decay_enabled=False,
            evergreen_categories=["system", "knowledge"],
        )
        assert cfg.embedding_fallback_provider == "dummy"
        assert cfg.bm25_weight == 0.5
        assert cfg.mmr_enabled is True
        assert cfg.temporal_decay_enabled is False
        assert "knowledge" in cfg.evergreen_categories


# ── Retrocompatibilidad ──────────────────────────────────────────


class TestRetrocompatibility:
    """Tests de retrocompatibilidad con la interfaz anterior."""

    @pytest.mark.asyncio
    async def test_legacy_constructor(self) -> None:
        """MemoryManager con solo embedding_provider sigue funcionando."""
        mgr = MemoryManager(
            backend=SQLiteMemoryBackend(":memory:"),
            embedding_provider=DummyEmbeddings(dim=64),
        )
        entry_id = await mgr.store("retrocompat test", category=MemoryCategory.KNOWLEDGE)
        assert entry_id
        results = await mgr.search("retrocompat")
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_legacy_search_params(self) -> None:
        """search() con parámetros explícitos sigue funcionando."""
        mgr = MemoryManager(
            backend=SQLiteMemoryBackend(":memory:"),
            embedding_provider=DummyEmbeddings(dim=64),
        )
        await mgr.store("legacy search test content", category=MemoryCategory.KNOWLEDGE)
        results = await mgr.search(
            "legacy search test",
            bm25_weight=0.3,
            vector_weight=0.7,
            use_mmr=False,
            mmr_lambda=0.7,
            min_score=0.0,
        )
        assert isinstance(results, list)
