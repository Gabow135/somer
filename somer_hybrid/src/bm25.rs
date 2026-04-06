use pyo3::prelude::*;
use rustc_hash::FxHashMap;

use crate::tokenizer::tokenize;

/// BM25 search index with pre-computed term frequencies.
#[pyclass]
pub struct BM25 {
    k1: f64,
    b: f64,
    /// doc_id -> index in docs
    id_to_idx: FxHashMap<String, usize>,
    /// Ordered list of doc_ids (index-aligned)
    doc_ids: Vec<String>,
    /// Pre-computed term frequencies per document: token -> count
    doc_tfs: Vec<FxHashMap<String, u32>>,
    /// Document lengths (number of tokens)
    doc_lens: Vec<u32>,
    /// Document frequency: token -> number of docs containing it
    df: FxHashMap<String, u32>,
    /// Total number of documents
    n: usize,
    /// Sum of all document lengths (for avg_dl calculation)
    total_dl: u64,
}

#[pymethods]
impl BM25 {
    #[new]
    #[pyo3(signature = (k1=1.5, b=0.75))]
    fn new(k1: f64, b: f64) -> Self {
        BM25 {
            k1,
            b,
            id_to_idx: FxHashMap::default(),
            doc_ids: Vec::new(),
            doc_tfs: Vec::new(),
            doc_lens: Vec::new(),
            df: FxHashMap::default(),
            n: 0,
            total_dl: 0,
        }
    }

    /// Add a document to the index.
    fn add_document(&mut self, doc_id: String, text: &str) {
        let tokens = tokenize(text);
        let dl = tokens.len() as u32;

        // Build term frequency map
        let mut tf: FxHashMap<String, u32> = FxHashMap::default();
        for token in &tokens {
            *tf.entry(token.clone()).or_insert(0) += 1;
        }

        // Update document frequency
        for key in tf.keys() {
            *self.df.entry(key.clone()).or_insert(0) += 1;
        }

        let idx = self.doc_ids.len();
        self.id_to_idx.insert(doc_id.clone(), idx);
        self.doc_ids.push(doc_id);
        self.doc_tfs.push(tf);
        self.doc_lens.push(dl);
        self.total_dl += dl as u64;
        self.n += 1;
    }

    /// Remove a document from the index.
    fn remove_document(&mut self, doc_id: &str) {
        let idx = match self.id_to_idx.remove(doc_id) {
            Some(i) => i,
            None => return,
        };

        // Decrease document frequency for tokens in removed doc
        let tf = &self.doc_tfs[idx];
        for key in tf.keys() {
            if let Some(count) = self.df.get_mut(key) {
                *count -= 1;
                if *count == 0 {
                    self.df.remove(key);
                }
            }
        }

        let dl = self.doc_lens[idx] as u64;
        self.total_dl -= dl;
        self.n -= 1;

        // Swap-remove for O(1)
        let last = self.doc_ids.len() - 1;
        if idx != last {
            // Update the moved element's index
            let moved_id = self.doc_ids[last].clone();
            self.id_to_idx.insert(moved_id, idx);
        }
        self.doc_ids.swap_remove(idx);
        self.doc_tfs.swap_remove(idx);
        self.doc_lens.swap_remove(idx);
    }

    /// Search for documents matching the query.
    ///
    /// Returns a list of (doc_id, score) sorted by descending relevance.
    #[pyo3(signature = (query, limit=10))]
    fn search(&self, query: &str, limit: usize) -> Vec<(String, f64)> {
        if self.n == 0 {
            return Vec::new();
        }

        let query_tokens = tokenize(query);
        let avg_dl = if self.n > 0 {
            self.total_dl as f64 / self.n as f64
        } else {
            0.0
        };

        let mut scores: FxHashMap<usize, f64> = FxHashMap::default();

        for qi in &query_tokens {
            let doc_freq = match self.df.get(qi) {
                Some(&d) => d as f64,
                None => continue,
            };

            let idf = ((self.n as f64 - doc_freq + 0.5) / (doc_freq + 0.5) + 1.0).ln();

            for (idx, tf_map) in self.doc_tfs.iter().enumerate() {
                let tf = match tf_map.get(qi) {
                    Some(&c) => c as f64,
                    None => continue,
                };
                let dl = self.doc_lens[idx] as f64;
                let denom = tf + self.k1 * (1.0 - self.b + self.b * dl / avg_dl.max(1.0));
                let score = idf * (tf * (self.k1 + 1.0)) / denom.max(1e-10);
                *scores.entry(idx).or_insert(0.0) += score;
            }
        }

        let mut ranked: Vec<(usize, f64)> = scores.into_iter().collect();
        ranked.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
        ranked.truncate(limit);

        ranked
            .into_iter()
            .map(|(idx, sc)| (self.doc_ids[idx].clone(), sc))
            .collect()
    }

    /// Number of documents in the index.
    #[getter]
    fn document_count(&self) -> usize {
        self.n
    }
}
