use pyo3::prelude::*;

mod bm25;
mod credentials;
mod hnsw;
mod merge;
mod mmr;
mod similarity;
mod tokenizer;

/// Native hybrid search module for SOMER.
#[pymodule]
fn somer_hybrid(_py: Python, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<bm25::BM25>()?;
    m.add_class::<credentials::CredentialScanner>()?;
    m.add_class::<credentials::CredentialMatch>()?;
    m.add_class::<hnsw::VectorIndex>()?;
    m.add_function(wrap_pyfunction!(similarity::cosine_similarity, m)?)?;
    m.add_function(wrap_pyfunction!(similarity::jaccard_similarity, m)?)?;
    m.add_function(wrap_pyfunction!(mmr::mmr_rerank, m)?)?;
    m.add_function(wrap_pyfunction!(mmr::mmr_rerank_text, m)?)?;
    m.add_function(wrap_pyfunction!(merge::hybrid_search_merge, m)?)?;
    m.add_function(wrap_pyfunction!(credentials::quick_scan, m)?)?;
    Ok(())
}
