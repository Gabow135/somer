"""Búsqueda híbrida BM25 + vector similarity."""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Dict, List, Optional, Tuple


class BM25:
    """Implementación simple de BM25 para búsqueda de texto."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._docs: List[List[str]] = []
        self._doc_ids: List[str] = []
        self._df: Counter = Counter()  # document frequency
        self._avg_dl: float = 0.0
        self._n: int = 0

    def add_document(self, doc_id: str, text: str) -> None:
        """Añade un documento al índice."""
        tokens = self._tokenize(text)
        self._docs.append(tokens)
        self._doc_ids.append(doc_id)
        for token in set(tokens):
            self._df[token] += 1
        self._n += 1
        total = sum(len(d) for d in self._docs)
        self._avg_dl = total / self._n if self._n else 0

    def remove_document(self, doc_id: str) -> None:
        """Elimina un documento del índice."""
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
        """Busca documentos relevantes.

        Returns:
            Lista de (doc_id, score) ordenados por relevancia.
        """
        query_tokens = self._tokenize(query)
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

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """Tokenización simple."""
        return re.findall(r"\w+", text.lower())


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Calcula la similitud coseno entre dos vectores (numpy-accelerated)."""
    if len(a) != len(b) or not a:
        return 0.0
    try:
        import numpy as np
        va = np.asarray(a, dtype=np.float32)
        vb = np.asarray(b, dtype=np.float32)
        norm_a = float(np.linalg.norm(va))
        norm_b = float(np.linalg.norm(vb))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return float(np.dot(va, vb) / (norm_a * norm_b))
    except ImportError:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)


def mmr_rerank(
    query_embedding: List[float],
    doc_embeddings: List[Tuple[str, List[float], float]],
    lambda_: float = 0.7,
    limit: int = 10,
) -> List[Tuple[str, float]]:
    """Maximal Marginal Relevance reranking.

    Args:
        query_embedding: Embedding de la query.
        doc_embeddings: Lista de (doc_id, embedding, base_score).
        lambda_: Balance entre relevancia y diversidad (0-1).
        limit: Máximo de resultados.

    Returns:
        Lista de (doc_id, score) rerankeada.
    """
    if not doc_embeddings:
        return []

    selected: List[Tuple[str, List[float], float]] = []
    remaining = list(doc_embeddings)
    results: List[Tuple[str, float]] = []

    for _ in range(min(limit, len(remaining))):
        best_idx = -1
        best_mmr = -float("inf")

        for i, (doc_id, emb, base_score) in enumerate(remaining):
            relevance = cosine_similarity(query_embedding, emb)
            diversity = 0.0
            if selected:
                diversity = max(
                    cosine_similarity(emb, s[1]) for s in selected
                )
            mmr = lambda_ * relevance - (1 - lambda_) * diversity
            if mmr > best_mmr:
                best_mmr = mmr
                best_idx = i

        if best_idx >= 0:
            item = remaining.pop(best_idx)
            selected.append(item)
            results.append((item[0], best_mmr))

    return results


def jaccard_similarity(text_a: str, text_b: str) -> float:
    """Similitud Jaccard sobre tokens de texto (ligera, sin embeddings)."""
    tokens_a = set(re.findall(r"\w+", text_a.lower()))
    tokens_b = set(re.findall(r"\w+", text_b.lower()))
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


def mmr_rerank_text(
    query: str,
    documents: List[Tuple[str, str, float]],
    lambda_: float = 0.7,
    limit: int = 10,
) -> List[Tuple[str, float]]:
    """MMR reranking usando Jaccard text similarity (sin embeddings).

    Args:
        query: Texto de la query.
        documents: Lista de (doc_id, content, base_score).
        lambda_: Balance entre relevancia y diversidad (0-1).
        limit: Máximo de resultados.

    Returns:
        Lista de (doc_id, score) rerankeada.
    """
    if not documents:
        return []

    selected_texts: List[str] = []
    remaining = list(documents)
    results: List[Tuple[str, float]] = []

    for _ in range(min(limit, len(remaining))):
        best_idx = -1
        best_mmr = -float("inf")

        for i, (doc_id, content, base_score) in enumerate(remaining):
            relevance = jaccard_similarity(query, content)
            diversity = 0.0
            if selected_texts:
                diversity = max(
                    jaccard_similarity(content, s) for s in selected_texts
                )
            mmr = lambda_ * relevance - (1 - lambda_) * diversity
            if mmr > best_mmr:
                best_mmr = mmr
                best_idx = i

        if best_idx >= 0:
            item = remaining.pop(best_idx)
            selected_texts.append(item[1])
            results.append((item[0], best_mmr))

    return results


def hybrid_search_merge(
    bm25_results: List[Tuple[str, float]],
    vector_results: List[Tuple[str, float]],
    bm25_weight: float = 0.3,
    vector_weight: float = 0.7,
) -> List[Tuple[str, float]]:
    """Merge de resultados BM25 y vector con pesos.

    Returns:
        Lista combinada de (doc_id, score) ordenada por score.
    """
    scores: Dict[str, float] = {}

    # Normalizar BM25
    bm25_max = max((s for _, s in bm25_results), default=1.0)
    for doc_id, score in bm25_results:
        norm_score = score / max(bm25_max, 1e-10)
        scores[doc_id] = scores.get(doc_id, 0) + bm25_weight * norm_score

    # Normalizar vector (clamping scores negativos a 0)
    vec_max = max((s for _, s in vector_results), default=1.0)
    for doc_id, score in vector_results:
        clamped = max(0.0, score)
        norm_score = clamped / max(vec_max, 1e-10)
        scores[doc_id] = scores.get(doc_id, 0) + vector_weight * norm_score

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return ranked
