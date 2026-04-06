use pyo3::prelude::*;
use rustc_hash::FxHashMap;

/// Merge BM25 and vector search results with weighted scores.
///
/// Both result lists are normalized before merging.
/// Negative vector scores are clamped to 0.
///
/// Returns:
///     Combined list of (doc_id, score) sorted by descending score.
#[pyfunction]
#[pyo3(signature = (bm25_results, vector_results, bm25_weight=0.3, vector_weight=0.7))]
pub fn hybrid_search_merge(
    bm25_results: Vec<(String, f64)>,
    vector_results: Vec<(String, f64)>,
    bm25_weight: f64,
    vector_weight: f64,
) -> Vec<(String, f64)> {
    let mut scores: FxHashMap<String, f64> = FxHashMap::default();

    // Normalize BM25
    let bm25_max = bm25_results
        .iter()
        .map(|(_, s)| *s)
        .fold(f64::NEG_INFINITY, f64::max);
    let bm25_max = if bm25_max == f64::NEG_INFINITY {
        1.0
    } else {
        bm25_max
    };

    for (doc_id, score) in &bm25_results {
        let norm_score = score / bm25_max.max(1e-10);
        *scores.entry(doc_id.clone()).or_insert(0.0) += bm25_weight * norm_score;
    }

    // Normalize vector (clamp negatives to 0)
    let vec_max = vector_results
        .iter()
        .map(|(_, s)| *s)
        .fold(f64::NEG_INFINITY, f64::max);
    let vec_max = if vec_max == f64::NEG_INFINITY {
        1.0
    } else {
        vec_max
    };

    for (doc_id, score) in &vector_results {
        let clamped = score.max(0.0);
        let norm_score = clamped / vec_max.max(1e-10);
        *scores.entry(doc_id.clone()).or_insert(0.0) += vector_weight * norm_score;
    }

    let mut ranked: Vec<(String, f64)> = scores.into_iter().collect();
    ranked.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
    ranked
}
