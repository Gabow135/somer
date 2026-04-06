"""Tests de paridad entre implementación Rust (somer_hybrid) y Python pura.

Verifica que ambas implementaciones produzcan resultados idénticos
con tolerancia numérica de 1e-6.
"""

from __future__ import annotations

import math
import re
import pytest
from collections import Counter
from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# Inline Python-pure reference implementations (copied from original hybrid.py)
# ---------------------------------------------------------------------------

class _PyBM25:
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._docs: List[List[str]] = []
        self._doc_ids: List[str] = []
        self._df: Counter = Counter()
        self._avg_dl: float = 0.0
        self._n: int = 0

    def add_document(self, doc_id: str, text: str) -> None:
        tokens = re.findall(r"\w+", text.lower())
        self._docs.append(tokens)
        self._doc_ids.append(doc_id)
        for token in set(tokens):
            self._df[token] += 1
        self._n += 1
        total = sum(len(d) for d in self._docs)
        self._avg_dl = total / self._n if self._n else 0

    def remove_document(self, doc_id: str) -> None:
        try:
            idx = self._doc_ids.index(doc_id)
        except ValueError:
            return
        tokens = self._docs[idx]
        for token in set(tokens):
            self._df[token] -= 1
            if self._df[token] <= 0:
                del self._df[token]
        self._docs.pop(idx)
        self._doc_ids.pop(idx)
        self._n -= 1
        total = sum(len(d) for d in self._docs)
        self._avg_dl = total / self._n if self._n else 0

    def search(self, query: str, limit: int = 10) -> List[Tuple[str, float]]:
        query_tokens = re.findall(r"\w+", query.lower())
        scores: Dict[int, float] = {}
        for qi in query_tokens:
            if qi not in self._df:
                continue
            idf = math.log(
                (self._n - self._df[qi] + 0.5) / (self._df[qi] + 0.5) + 1
            )
            for idx, doc in enumerate(self._docs):
                tf = doc.count(qi)
                dl = len(doc)
                denom = tf + self.k1 * (1 - self.b + self.b * dl / max(self._avg_dl, 1))
                score = idf * (tf * (self.k1 + 1)) / max(denom, 1e-10)
                scores[idx] = scores.get(idx, 0) + score
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [(self._doc_ids[idx], sc) for idx, sc in ranked[:limit]]

    @property
    def document_count(self) -> int:
        return self._n


def _py_cosine_similarity(a: List[float], b: List[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _py_jaccard_similarity(text_a: str, text_b: str) -> float:
    tokens_a = set(re.findall(r"\w+", text_a.lower()))
    tokens_b = set(re.findall(r"\w+", text_b.lower()))
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


def _py_hybrid_search_merge(
    bm25_results: List[Tuple[str, float]],
    vector_results: List[Tuple[str, float]],
    bm25_weight: float = 0.3,
    vector_weight: float = 0.7,
) -> List[Tuple[str, float]]:
    scores: Dict[str, float] = {}
    bm25_max = max((s for _, s in bm25_results), default=1.0)
    for doc_id, score in bm25_results:
        norm_score = score / max(bm25_max, 1e-10)
        scores[doc_id] = scores.get(doc_id, 0) + bm25_weight * norm_score
    vec_max = max((s for _, s in vector_results), default=1.0)
    for doc_id, score in vector_results:
        clamped = max(0.0, score)
        norm_score = clamped / max(vec_max, 1e-10)
        scores[doc_id] = scores.get(doc_id, 0) + vector_weight * norm_score
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return ranked


def _py_mmr_rerank(
    query_embedding, doc_embeddings, lambda_=0.7, limit=10,
):
    if not doc_embeddings:
        return []
    selected = []
    remaining = list(doc_embeddings)
    results = []
    for _ in range(min(limit, len(remaining))):
        best_idx = -1
        best_mmr = -float("inf")
        for i, (doc_id, emb, base_score) in enumerate(remaining):
            relevance = _py_cosine_similarity(query_embedding, emb)
            diversity = 0.0
            if selected:
                diversity = max(_py_cosine_similarity(emb, s[1]) for s in selected)
            mmr = lambda_ * relevance - (1 - lambda_) * diversity
            if mmr > best_mmr:
                best_mmr = mmr
                best_idx = i
        if best_idx >= 0:
            item = remaining.pop(best_idx)
            selected.append(item)
            results.append((item[0], best_mmr))
    return results


def _py_mmr_rerank_text(query, documents, lambda_=0.7, limit=10):
    if not documents:
        return []
    selected_texts = []
    remaining = list(documents)
    results = []
    for _ in range(min(limit, len(remaining))):
        best_idx = -1
        best_mmr = -float("inf")
        for i, (doc_id, content, base_score) in enumerate(remaining):
            relevance = _py_jaccard_similarity(query, content)
            diversity = 0.0
            if selected_texts:
                diversity = max(_py_jaccard_similarity(content, s) for s in selected_texts)
            mmr = lambda_ * relevance - (1 - lambda_) * diversity
            if mmr > best_mmr:
                best_mmr = mmr
                best_idx = i
        if best_idx >= 0:
            item = remaining.pop(best_idx)
            selected_texts.append(item[1])
            results.append((item[0], best_mmr))
    return results


# ---------------------------------------------------------------------------
# Try to import native Rust implementation
# ---------------------------------------------------------------------------

try:
    from somer_hybrid import (
        BM25 as RustBM25,
        cosine_similarity as rust_cosine_similarity,
        jaccard_similarity as rust_jaccard_similarity,
        hybrid_search_merge as rust_hybrid_search_merge,
        mmr_rerank as rust_mmr_rerank,
        mmr_rerank_text as rust_mmr_rerank_text,
    )
    HAS_NATIVE = True
except ImportError:
    HAS_NATIVE = False

TOLERANCE = 1e-6

needs_native = pytest.mark.skipif(
    not HAS_NATIVE, reason="somer_hybrid native extension not installed"
)


# ---------------------------------------------------------------------------
# Test data fixtures
# ---------------------------------------------------------------------------

DOCS = [
    ("doc1", "the quick brown fox jumps over the lazy dog"),
    ("doc2", "a fast brown fox leaps over a sleeping dog"),
    ("doc3", "the dog chased the cat around the house"),
    ("doc4", "python is a great programming language"),
    ("doc5", "rust is fast and memory safe"),
]

VEC_A = [1.0, 2.0, 3.0, 4.0, 5.0]
VEC_B = [5.0, 4.0, 3.0, 2.0, 1.0]
VEC_ZERO = [0.0, 0.0, 0.0, 0.0, 0.0]
VEC_SAME = [1.0, 2.0, 3.0, 4.0, 5.0]


# ---------------------------------------------------------------------------
# Parity tests
# ---------------------------------------------------------------------------

@needs_native
class TestBM25Parity:
    def _build_both(self):
        py = _PyBM25()
        rs = RustBM25()
        for doc_id, text in DOCS:
            py.add_document(doc_id, text)
            rs.add_document(doc_id, text)
        return py, rs

    def test_document_count(self):
        py, rs = self._build_both()
        assert py.document_count == rs.document_count

    def test_search_basic(self):
        py, rs = self._build_both()
        py_results = py.search("brown fox")
        rs_results = rs.search("brown fox")
        # Filter out zero-score results (Rust optimizes by skipping them)
        py_filtered = [(did, sc) for did, sc in py_results if sc > 0]
        assert len(py_filtered) == len(rs_results)
        for (py_id, py_sc), (rs_id, rs_sc) in zip(py_filtered, rs_results):
            assert py_id == rs_id, f"ID mismatch: {py_id} vs {rs_id}"
            assert abs(py_sc - rs_sc) < TOLERANCE, f"Score mismatch for {py_id}: {py_sc} vs {rs_sc}"

    def test_search_with_limit(self):
        py, rs = self._build_both()
        py_results = py.search("dog", limit=2)
        rs_results = rs.search("dog", limit=2)
        assert len(py_results) == len(rs_results) == 2
        for (py_id, py_sc), (rs_id, rs_sc) in zip(py_results, rs_results):
            assert py_id == rs_id
            assert abs(py_sc - rs_sc) < TOLERANCE

    def test_search_no_match(self):
        py, rs = self._build_both()
        assert py.search("xyz_nonexistent") == rs.search("xyz_nonexistent") == []

    def test_remove_document(self):
        py, rs = self._build_both()
        py.remove_document("doc1")
        rs.remove_document("doc1")
        assert py.document_count == rs.document_count
        py_results = py.search("brown fox")
        rs_results = rs.search("brown fox")
        # Filter out zero-score results (Rust optimizes by skipping them)
        py_filtered = [(did, sc) for did, sc in py_results if sc > 0]
        assert len(py_filtered) == len(rs_results)
        for (py_id, py_sc), (rs_id, rs_sc) in zip(py_filtered, rs_results):
            assert py_id == rs_id
            assert abs(py_sc - rs_sc) < TOLERANCE

    def test_remove_nonexistent(self):
        py, rs = self._build_both()
        py.remove_document("nonexistent")
        rs.remove_document("nonexistent")
        assert py.document_count == rs.document_count


@needs_native
class TestCosineSimilarityParity:
    def test_basic(self):
        py = _py_cosine_similarity(VEC_A, VEC_B)
        rs = rust_cosine_similarity(VEC_A, VEC_B)
        assert abs(py - rs) < TOLERANCE

    def test_identical(self):
        py = _py_cosine_similarity(VEC_A, VEC_SAME)
        rs = rust_cosine_similarity(VEC_A, VEC_SAME)
        assert abs(py - rs) < TOLERANCE
        assert abs(rs - 1.0) < TOLERANCE

    def test_zero_vector(self):
        py = _py_cosine_similarity(VEC_A, VEC_ZERO)
        rs = rust_cosine_similarity(VEC_A, VEC_ZERO)
        assert py == rs == 0.0

    def test_empty(self):
        py = _py_cosine_similarity([], [])
        rs = rust_cosine_similarity([], [])
        assert py == rs == 0.0

    def test_different_lengths(self):
        py = _py_cosine_similarity([1.0, 2.0], [1.0])
        rs = rust_cosine_similarity([1.0, 2.0], [1.0])
        assert py == rs == 0.0


@needs_native
class TestJaccardSimilarityParity:
    def test_basic(self):
        py = _py_jaccard_similarity("the quick brown fox", "the fast brown dog")
        rs = rust_jaccard_similarity("the quick brown fox", "the fast brown dog")
        assert abs(py - rs) < TOLERANCE

    def test_identical(self):
        py = _py_jaccard_similarity("hello world", "hello world")
        rs = rust_jaccard_similarity("hello world", "hello world")
        assert abs(py - rs) < TOLERANCE
        assert abs(rs - 1.0) < TOLERANCE

    def test_no_overlap(self):
        py = _py_jaccard_similarity("abc def", "xyz uvw")
        rs = rust_jaccard_similarity("abc def", "xyz uvw")
        assert py == rs == 0.0

    def test_empty(self):
        py = _py_jaccard_similarity("", "hello")
        rs = rust_jaccard_similarity("", "hello")
        assert py == rs == 0.0


@needs_native
class TestHybridSearchMergeParity:
    def test_basic(self):
        bm25 = [("doc1", 2.5), ("doc2", 1.8), ("doc3", 0.5)]
        vector = [("doc2", 0.95), ("doc4", 0.88), ("doc1", 0.7)]
        py = _py_hybrid_search_merge(bm25, vector)
        rs = rust_hybrid_search_merge(bm25, vector)
        assert len(py) == len(rs)
        for (py_id, py_sc), (rs_id, rs_sc) in zip(py, rs):
            assert py_id == rs_id, f"ID mismatch: {py_id} vs {rs_id}"
            assert abs(py_sc - rs_sc) < TOLERANCE

    def test_custom_weights(self):
        bm25 = [("a", 1.0), ("b", 0.5)]
        vector = [("b", 0.9), ("c", 0.8)]
        py = _py_hybrid_search_merge(bm25, vector, bm25_weight=0.5, vector_weight=0.5)
        rs = rust_hybrid_search_merge(bm25, vector, bm25_weight=0.5, vector_weight=0.5)
        assert len(py) == len(rs)
        for (py_id, py_sc), (rs_id, rs_sc) in zip(py, rs):
            assert py_id == rs_id
            assert abs(py_sc - rs_sc) < TOLERANCE

    def test_empty(self):
        py = _py_hybrid_search_merge([], [])
        rs = rust_hybrid_search_merge([], [])
        assert py == rs == []


@needs_native
class TestMMRRerankParity:
    def test_basic(self):
        query = [1.0, 0.0, 0.0]
        docs = [
            ("d1", [0.9, 0.1, 0.0], 0.9),
            ("d2", [0.0, 1.0, 0.0], 0.8),
            ("d3", [0.5, 0.5, 0.0], 0.7),
        ]
        py = _py_mmr_rerank(query, docs, lambda_=0.7, limit=3)
        rs = rust_mmr_rerank(query, docs, lambda_=0.7, limit=3)
        assert len(py) == len(rs)
        for (py_id, py_sc), (rs_id, rs_sc) in zip(py, rs):
            assert py_id == rs_id, f"ID mismatch: {py_id} vs {rs_id}"
            assert abs(py_sc - rs_sc) < TOLERANCE

    def test_empty(self):
        assert _py_mmr_rerank([], []) == rust_mmr_rerank([], []) == []


@needs_native
class TestMMRRerankTextParity:
    def test_basic(self):
        query = "brown fox jumping"
        docs = [
            ("d1", "the quick brown fox jumps", 0.9),
            ("d2", "a lazy sleeping dog", 0.7),
            ("d3", "brown dogs and foxes jumping", 0.8),
        ]
        py = _py_mmr_rerank_text(query, docs, lambda_=0.7, limit=3)
        rs = rust_mmr_rerank_text(query, docs, lambda_=0.7, limit=3)
        assert len(py) == len(rs)
        for (py_id, py_sc), (rs_id, rs_sc) in zip(py, rs):
            assert py_id == rs_id, f"ID mismatch: {py_id} vs {rs_id}"
            assert abs(py_sc - rs_sc) < TOLERANCE

    def test_empty(self):
        assert _py_mmr_rerank_text("q", []) == rust_mmr_rerank_text("q", []) == []
