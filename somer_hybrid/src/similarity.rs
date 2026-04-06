use pyo3::prelude::*;

use crate::tokenizer::tokenize_set;

/// Cosine similarity between two vectors.
#[pyfunction]
pub fn cosine_similarity(a: Vec<f64>, b: Vec<f64>) -> f64 {
    if a.len() != b.len() || a.is_empty() {
        return 0.0;
    }

    let mut dot = 0.0_f64;
    let mut norm_a = 0.0_f64;
    let mut norm_b = 0.0_f64;

    for (x, y) in a.iter().zip(b.iter()) {
        dot += x * y;
        norm_a += x * x;
        norm_b += y * y;
    }

    let na = norm_a.sqrt();
    let nb = norm_b.sqrt();

    if na == 0.0 || nb == 0.0 {
        return 0.0;
    }

    dot / (na * nb)
}

/// Cosine similarity for internal use (references, no allocation).
pub fn cosine_sim_refs(a: &[f64], b: &[f64]) -> f64 {
    if a.len() != b.len() || a.is_empty() {
        return 0.0;
    }

    let mut dot = 0.0_f64;
    let mut norm_a = 0.0_f64;
    let mut norm_b = 0.0_f64;

    for (x, y) in a.iter().zip(b.iter()) {
        dot += x * y;
        norm_a += x * x;
        norm_b += y * y;
    }

    let na = norm_a.sqrt();
    let nb = norm_b.sqrt();

    if na == 0.0 || nb == 0.0 {
        return 0.0;
    }

    dot / (na * nb)
}

/// Jaccard similarity over text tokens (lightweight, no embeddings).
#[pyfunction]
pub fn jaccard_similarity(text_a: &str, text_b: &str) -> f64 {
    let tokens_a = tokenize_set(text_a);
    let tokens_b = tokenize_set(text_b);

    if tokens_a.is_empty() || tokens_b.is_empty() {
        return 0.0;
    }

    let intersection = tokens_a.intersection(&tokens_b).count();
    let union = tokens_a.union(&tokens_b).count();

    intersection as f64 / union as f64
}
