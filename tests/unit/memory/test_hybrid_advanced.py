"""Tests avanzados para hybrid search: Jaccard similarity y MMR texto.

Cubre: jaccard_similarity, mmr_rerank_text con diversidad y relevancia.
"""

from __future__ import annotations

import pytest

from memory.hybrid import jaccard_similarity, mmr_rerank_text


# ── Jaccard Similarity ───────────────────────────────────────────


class TestJaccardSimilarity:
    """Tests de jaccard_similarity."""

    def test_identical_texts(self) -> None:
        assert jaccard_similarity("hello world", "hello world") == 1.0

    def test_no_overlap(self) -> None:
        assert jaccard_similarity("hello world", "foo bar") == 0.0

    def test_partial_overlap(self) -> None:
        sim = jaccard_similarity("the quick brown fox", "the lazy brown dog")
        # Tokens: {the, quick, brown, fox} ∩ {the, lazy, brown, dog} = {the, brown}
        # Union = {the, quick, brown, fox, lazy, dog} = 6
        # Jaccard = 2/6 = 0.333...
        assert abs(sim - 2.0 / 6.0) < 1e-6

    def test_empty_text_a(self) -> None:
        assert jaccard_similarity("", "hello world") == 0.0

    def test_empty_text_b(self) -> None:
        assert jaccard_similarity("hello world", "") == 0.0

    def test_both_empty(self) -> None:
        assert jaccard_similarity("", "") == 0.0

    def test_case_insensitive(self) -> None:
        assert jaccard_similarity("Hello World", "hello world") == 1.0

    def test_special_characters_ignored(self) -> None:
        # \w+ solo captura word characters
        sim = jaccard_similarity("hello, world!", "hello world")
        assert sim == 1.0


# ── MMR Rerank Text ──────────────────────────────────────────────


class TestMmrRerankText:
    """Tests de mmr_rerank_text."""

    def test_basic_reranking(self) -> None:
        docs = [
            ("d1", "the quick brown fox jumps", 0.9),
            ("d2", "lazy dog sleeps all day", 0.5),
            ("d3", "quick fox runs fast", 0.7),
        ]
        results = mmr_rerank_text("quick fox", docs, lambda_=0.7, limit=3)
        assert len(results) == 3
        ids = [r[0] for r in results]
        assert "d1" in ids
        assert "d3" in ids

    def test_empty_documents(self) -> None:
        results = mmr_rerank_text("query", [], lambda_=0.7, limit=10)
        assert results == []

    def test_lambda_one_pure_relevance(self) -> None:
        # Con lambda=1.0, solo importa relevancia (Jaccard con query)
        docs = [
            ("d1", "apple banana", 0.9),
            ("d2", "apple cherry", 0.5),
            ("d3", "apple banana cherry", 0.3),
        ]
        results = mmr_rerank_text("apple banana", docs, lambda_=1.0, limit=3)
        # d1 tiene Jaccard=1.0 con query, d3 tiene Jaccard=2/3
        assert results[0][0] == "d1"

    def test_diversity_separates_similar(self) -> None:
        # Con lambda bajo, textos similares deberían estar más separados
        docs = [
            ("d1", "machine learning models", 0.9),
            ("d2", "machine learning algorithms", 0.8),
            ("d3", "cooking recipes delicious", 0.4),
        ]
        results = mmr_rerank_text(
            "machine learning", docs, lambda_=0.3, limit=3
        )
        ids = [r[0] for r in results]
        # d1 y d2 son muy similares; con diversidad, d3 debería
        # intercalarse entre ellos
        assert ids[0] == "d1" or ids[0] == "d2"  # Uno de los relevantes primero
        # d3 debería aparecer antes que el segundo similar
        if ids[0] == "d1":
            assert ids.index("d3") < ids.index("d2")
        else:
            assert ids.index("d3") < ids.index("d1")

    def test_respects_limit(self) -> None:
        docs = [
            ("d1", "hello world", 0.9),
            ("d2", "foo bar", 0.5),
            ("d3", "baz qux", 0.3),
        ]
        results = mmr_rerank_text("hello", docs, lambda_=0.7, limit=2)
        assert len(results) == 2

    def test_single_document(self) -> None:
        docs = [("d1", "hello world", 0.9)]
        results = mmr_rerank_text("hello", docs, lambda_=0.7, limit=5)
        assert len(results) == 1
        assert results[0][0] == "d1"
