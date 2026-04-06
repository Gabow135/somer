use pyo3::prelude::*;

use crate::similarity::{cosine_sim_refs, jaccard_similarity};
use crate::tokenizer::tokenize_set;

/// Maximal Marginal Relevance reranking using embeddings.
///
/// Args:
///     query_embedding: Query embedding vector.
///     doc_embeddings: List of (doc_id, embedding, base_score).
///     lambda_: Balance between relevance and diversity (0-1).
///     limit: Maximum results.
///
/// Returns:
///     List of (doc_id, mmr_score) reranked.
#[pyfunction]
#[pyo3(signature = (query_embedding, doc_embeddings, lambda_=0.7, limit=10))]
pub fn mmr_rerank(
    query_embedding: Vec<f64>,
    doc_embeddings: Vec<(String, Vec<f64>, f64)>,
    lambda_: f64,
    limit: usize,
) -> Vec<(String, f64)> {
    if doc_embeddings.is_empty() {
        return Vec::new();
    }

    let n = doc_embeddings.len().min(limit);
    let mut selected_embs: Vec<&[f64]> = Vec::with_capacity(n);
    let mut remaining: Vec<usize> = (0..doc_embeddings.len()).collect();
    let mut results: Vec<(String, f64)> = Vec::with_capacity(n);

    for _ in 0..n {
        if remaining.is_empty() {
            break;
        }

        let mut best_idx_in_remaining = 0;
        let mut best_mmr = f64::NEG_INFINITY;

        for (ri, &doc_idx) in remaining.iter().enumerate() {
            let (_, ref emb, _) = doc_embeddings[doc_idx];

            let relevance = cosine_sim_refs(&query_embedding, emb);
            let diversity = if selected_embs.is_empty() {
                0.0
            } else {
                selected_embs
                    .iter()
                    .map(|s| cosine_sim_refs(emb, s))
                    .fold(f64::NEG_INFINITY, f64::max)
            };

            let mmr = lambda_ * relevance - (1.0 - lambda_) * diversity;
            if mmr > best_mmr {
                best_mmr = mmr;
                best_idx_in_remaining = ri;
            }
        }

        let doc_idx = remaining.swap_remove(best_idx_in_remaining);
        let (ref doc_id, ref emb, _) = doc_embeddings[doc_idx];
        results.push((doc_id.clone(), best_mmr));
        selected_embs.push(emb);
    }

    results
}

/// MMR reranking using Jaccard text similarity (no embeddings).
///
/// Args:
///     query: Query text.
///     documents: List of (doc_id, content, base_score).
///     lambda_: Balance between relevance and diversity (0-1).
///     limit: Maximum results.
///
/// Returns:
///     List of (doc_id, mmr_score) reranked.
#[pyfunction]
#[pyo3(signature = (query, documents, lambda_=0.7, limit=10))]
pub fn mmr_rerank_text(
    query: &str,
    documents: Vec<(String, String, f64)>,
    lambda_: f64,
    limit: usize,
) -> Vec<(String, f64)> {
    if documents.is_empty() {
        return Vec::new();
    }

    let n = documents.len().min(limit);
    let mut selected_texts: Vec<String> = Vec::with_capacity(n);
    let mut remaining: Vec<usize> = (0..documents.len()).collect();
    let mut results: Vec<(String, f64)> = Vec::with_capacity(n);

    // Pre-tokenize query
    let _query_tokens = tokenize_set(query);

    for _ in 0..n {
        if remaining.is_empty() {
            break;
        }

        let mut best_idx_in_remaining = 0;
        let mut best_mmr = f64::NEG_INFINITY;

        for (ri, &doc_idx) in remaining.iter().enumerate() {
            let (_, ref content, _) = documents[doc_idx];

            let relevance = jaccard_similarity(query, content);
            let diversity = if selected_texts.is_empty() {
                0.0
            } else {
                selected_texts
                    .iter()
                    .map(|s| jaccard_similarity(content, s))
                    .fold(f64::NEG_INFINITY, f64::max)
            };

            let mmr = lambda_ * relevance - (1.0 - lambda_) * diversity;
            if mmr > best_mmr {
                best_mmr = mmr;
                best_idx_in_remaining = ri;
            }
        }

        let doc_idx = remaining.swap_remove(best_idx_in_remaining);
        let (ref doc_id, ref content, _) = documents[doc_idx];
        results.push((doc_id.clone(), best_mmr));
        selected_texts.push(content.clone());
    }

    results
}
