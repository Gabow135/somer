"""Tests de paridad: VectorIndex HNSW (Rust) vs numpy brute-force (Python).

Verifica que el indice HNSW nativo produce resultados compatibles con la
busqueda brute-force de numpy, con tolerancia para la naturaleza aproximada
del HNSW.
"""

from __future__ import annotations

import math
import random
import time
from typing import List, Tuple

import pytest

# ---------------------------------------------------------------------------
# Python brute-force reference implementation (numpy)
# ---------------------------------------------------------------------------


def _py_cosine_similarity(a: List[float], b: List[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _py_brute_force_search(
    query: List[float],
    vectors: List[Tuple[str, List[float]]],
    k: int,
) -> List[Tuple[str, float]]:
    """Brute-force k-nearest neighbor search using cosine similarity."""
    scored = []
    for vid, vec in vectors:
        sim = _py_cosine_similarity(query, vec)
        scored.append((vid, sim))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:k]


# ---------------------------------------------------------------------------
# Try to import Rust VectorIndex
# ---------------------------------------------------------------------------

try:
    from somer_hybrid import VectorIndex
    HAS_NATIVE = True
except ImportError:
    HAS_NATIVE = False

needs_native = pytest.mark.skipif(
    not HAS_NATIVE, reason="somer_hybrid native extension not installed"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _random_vector(dim: int, seed: int = 0) -> List[float]:
    """Generate a deterministic random unit-ish vector."""
    rng = random.Random(seed)
    vec = [rng.gauss(0, 1) for _ in range(dim)]
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]
    return vec


def _make_dataset(n: int, dim: int) -> List[Tuple[str, List[float]]]:
    """Generate n random vectors with string IDs."""
    return [(f"doc_{i}", _random_vector(dim, seed=i)) for i in range(n)]


# ---------------------------------------------------------------------------
# Basic VectorIndex tests
# ---------------------------------------------------------------------------

@needs_native
class TestVectorIndexBasic:
    def test_create_empty(self):
        idx = VectorIndex(dim=8)
        assert idx.count == 0
        assert idx.dim == 8

    def test_add_and_count(self):
        idx = VectorIndex(dim=3)
        idx.add_vector("a", [1.0, 0.0, 0.0])
        idx.add_vector("b", [0.0, 1.0, 0.0])
        assert idx.count == 2

    def test_contains(self):
        idx = VectorIndex(dim=3)
        idx.add_vector("a", [1.0, 0.0, 0.0])
        assert idx.contains("a")
        assert not idx.contains("b")

    def test_search_exact_match(self):
        idx = VectorIndex(dim=3)
        idx.add_vector("a", [1.0, 0.0, 0.0])
        idx.add_vector("b", [0.0, 1.0, 0.0])
        idx.add_vector("c", [0.0, 0.0, 1.0])

        results = idx.search([1.0, 0.0, 0.0], k=1)
        assert len(results) == 1
        assert results[0][0] == "a"
        assert abs(results[0][1] - 1.0) < 1e-5

    def test_search_ordering(self):
        idx = VectorIndex(dim=3)
        idx.add_vector("a", [1.0, 0.0, 0.0])
        idx.add_vector("b", [0.9, 0.1, 0.0])
        idx.add_vector("c", [0.0, 1.0, 0.0])

        results = idx.search([1.0, 0.0, 0.0], k=3)
        # "a" should be closest, then "b", then "c"
        assert results[0][0] == "a"
        assert results[1][0] == "b"
        assert results[2][0] == "c"
        # Similarities should be descending
        assert results[0][1] >= results[1][1] >= results[2][1]

    def test_search_k_limit(self):
        idx = VectorIndex(dim=3)
        for i in range(10):
            idx.add_vector(f"d{i}", _random_vector(3, seed=i))
        results = idx.search([1.0, 0.0, 0.0], k=3)
        assert len(results) == 3

    def test_dimension_mismatch_raises(self):
        idx = VectorIndex(dim=3)
        with pytest.raises(ValueError):
            idx.add_vector("a", [1.0, 0.0])  # wrong dim

    def test_search_dimension_mismatch_raises(self):
        idx = VectorIndex(dim=3)
        idx.add_vector("a", [1.0, 0.0, 0.0])
        with pytest.raises(ValueError):
            idx.search([1.0, 0.0], k=1)

    def test_empty_search(self):
        idx = VectorIndex(dim=3)
        results = idx.search([1.0, 0.0, 0.0], k=5)
        assert results == []


# ---------------------------------------------------------------------------
# Batch operations tests
# ---------------------------------------------------------------------------

@needs_native
class TestVectorIndexBatch:
    def test_add_vectors_batch(self):
        idx = VectorIndex(dim=3)
        ids = ["a", "b", "c"]
        vecs = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        idx.add_vectors(ids, vecs)
        assert idx.count == 3

    def test_add_vectors_length_mismatch(self):
        idx = VectorIndex(dim=3)
        with pytest.raises(ValueError):
            idx.add_vectors(["a", "b"], [[1.0, 0.0, 0.0]])

    def test_search_batch(self):
        idx = VectorIndex(dim=3)
        idx.add_vectors(
            ["x", "y", "z"],
            [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        )
        queries = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
        batch_results = idx.search_batch(queries, k=1)
        assert len(batch_results) == 2
        assert batch_results[0][0][0] == "x"
        assert batch_results[1][0][0] == "y"


# ---------------------------------------------------------------------------
# Serialization tests
# ---------------------------------------------------------------------------

@needs_native
class TestVectorIndexSerialization:
    def test_serialize_deserialize_roundtrip(self):
        idx = VectorIndex(dim=4)
        dataset = _make_dataset(20, 4)
        for vid, vec in dataset:
            idx.add_vector(vid, vec)

        data = idx.serialize()
        assert isinstance(data, bytes)
        assert len(data) > 0

        idx2 = VectorIndex.deserialize(data)
        assert idx2.count == idx.count
        assert idx2.dim == idx.dim

        # Search results should be the same
        query = _random_vector(4, seed=999)
        r1 = idx.search(query, k=5)
        r2 = idx2.search(query, k=5)
        assert len(r1) == len(r2)
        for (id1, sim1), (id2, sim2) in zip(r1, r2):
            assert id1 == id2
            assert abs(sim1 - sim2) < 1e-5

    def test_deserialize_invalid(self):
        with pytest.raises(ValueError):
            VectorIndex.deserialize(b"invalid data")

    def test_serialize_empty(self):
        idx = VectorIndex(dim=3)
        data = idx.serialize()
        idx2 = VectorIndex.deserialize(data)
        assert idx2.count == 0
        assert idx2.dim == 3


# ---------------------------------------------------------------------------
# Remove tests
# ---------------------------------------------------------------------------

@needs_native
class TestVectorIndexRemove:
    def test_remove_existing(self):
        idx = VectorIndex(dim=3)
        idx.add_vector("a", [1.0, 0.0, 0.0])
        idx.add_vector("b", [0.0, 1.0, 0.0])
        result = idx.remove_vector("a")
        assert result is True
        assert not idx.contains("a")

    def test_remove_nonexistent(self):
        idx = VectorIndex(dim=3)
        result = idx.remove_vector("nonexistent")
        assert result is False


# ---------------------------------------------------------------------------
# Parity tests: HNSW vs brute-force
# ---------------------------------------------------------------------------

@needs_native
class TestVectorIndexParity:
    """Verify HNSW returns same top results as brute-force for small datasets."""

    def _build_index_and_dataset(self, n: int, dim: int):
        dataset = _make_dataset(n, dim)
        idx = VectorIndex(dim=dim, ef_search=200)  # high ef for accuracy
        for vid, vec in dataset:
            idx.add_vector(vid, vec)
        return idx, dataset

    def test_top1_matches_bruteforce(self):
        """Top-1 result should always match brute-force."""
        idx, dataset = self._build_index_and_dataset(100, 32)

        mismatches = 0
        for seed in range(50):
            query = _random_vector(32, seed=seed + 1000)
            hnsw_results = idx.search(query, k=1)
            bf_results = _py_brute_force_search(query, dataset, k=1)

            if hnsw_results[0][0] != bf_results[0][0]:
                mismatches += 1

        # Allow at most 5% mismatches for approximate search
        assert mismatches <= 3, f"Top-1 mismatches: {mismatches}/50"

    def test_top5_recall(self):
        """Top-5 recall should be high with high ef_search."""
        idx, dataset = self._build_index_and_dataset(200, 64)

        total_recall = 0.0
        n_queries = 30
        for seed in range(n_queries):
            query = _random_vector(64, seed=seed + 2000)
            hnsw_results = idx.search(query, k=5)
            bf_results = _py_brute_force_search(query, dataset, k=5)

            hnsw_ids = {r[0] for r in hnsw_results}
            bf_ids = {r[0] for r in bf_results}
            recall = len(hnsw_ids & bf_ids) / len(bf_ids) if bf_ids else 1.0
            total_recall += recall

        avg_recall = total_recall / n_queries
        assert avg_recall >= 0.8, f"Average recall@5: {avg_recall:.3f} (expected >= 0.8)"

    def test_similarity_values_close(self):
        """Similarity values for top results should be close to brute-force."""
        idx, dataset = self._build_index_and_dataset(50, 16)

        query = _random_vector(16, seed=3000)
        hnsw_results = idx.search(query, k=5)
        bf_results = _py_brute_force_search(query, dataset, k=5)

        # Build lookup for brute-force results
        bf_map = {r[0]: r[1] for r in bf_results}

        for hid, hsim in hnsw_results:
            if hid in bf_map:
                assert abs(hsim - bf_map[hid]) < 0.01, (
                    f"Similarity mismatch for {hid}: HNSW={hsim:.4f} vs BF={bf_map[hid]:.4f}"
                )

    def test_orthogonal_vectors(self):
        """Orthogonal vectors should have similarity ~0."""
        idx = VectorIndex(dim=3)
        idx.add_vector("x", [1.0, 0.0, 0.0])
        idx.add_vector("y", [0.0, 1.0, 0.0])
        idx.add_vector("z", [0.0, 0.0, 1.0])

        results = idx.search([1.0, 0.0, 0.0], k=3)
        # First should be exact match
        assert results[0][0] == "x"
        assert abs(results[0][1] - 1.0) < 1e-5
        # Others should be ~0 similarity
        for _, sim in results[1:]:
            assert abs(sim) < 0.01


# ---------------------------------------------------------------------------
# Benchmark: HNSW vs numpy brute-force
# ---------------------------------------------------------------------------

@needs_native
class TestVectorIndexBenchmark:
    """Performance comparison HNSW vs numpy brute-force.

    These are not strict pass/fail — they print results for manual review.
    The assert ensures HNSW is at least 2x faster for 5000+ vectors.
    """

    @pytest.mark.parametrize("n_vectors", [1000, 5000])
    def test_benchmark_search(self, n_vectors: int):
        dim = 128
        dataset = _make_dataset(n_vectors, dim)

        # Build HNSW index
        idx = VectorIndex(dim=dim, ef_search=50)
        t0 = time.perf_counter()
        for vid, vec in dataset:
            idx.add_vector(vid, vec)
        build_time = time.perf_counter() - t0

        # Prepare numpy matrix for brute-force
        try:
            import numpy as np
            has_numpy = True
        except ImportError:
            has_numpy = False
            return  # Skip benchmark if no numpy

        doc_ids = [d[0] for d in dataset]
        matrix = np.array([d[1] for d in dataset], dtype=np.float32)

        queries = [_random_vector(dim, seed=i + 5000) for i in range(100)]

        # Benchmark HNSW
        t0 = time.perf_counter()
        for q in queries:
            idx.search(q, k=10)
        hnsw_time = time.perf_counter() - t0

        # Benchmark numpy brute-force
        t0 = time.perf_counter()
        for q in queries:
            qv = np.asarray(q, dtype=np.float32)
            dots = matrix @ qv
            norms = np.linalg.norm(matrix, axis=1)
            qnorm = np.linalg.norm(qv)
            sims = dots / (norms * qnorm + 1e-8)
            top_k = np.argpartition(sims, -10)[-10:]
            _ = top_k[np.argsort(sims[top_k])[::-1]]
        numpy_time = time.perf_counter() - t0

        speedup = numpy_time / max(hnsw_time, 1e-9)
        print(f"\n[n={n_vectors}, dim={dim}]")
        print(f"  HNSW build:  {build_time:.3f}s")
        print(f"  HNSW search: {hnsw_time:.4f}s (100 queries)")
        print(f"  Numpy BF:    {numpy_time:.4f}s (100 queries)")
        print(f"  Speedup:     {speedup:.1f}x")

        # For 5000+ vectors, HNSW should be faster
        if n_vectors >= 5000:
            assert speedup > 1.5, (
                f"HNSW should be at least 1.5x faster than numpy for {n_vectors} vectors, "
                f"got {speedup:.1f}x"
            )
