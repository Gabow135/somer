//! HNSW (Hierarchical Navigable Small World) index for approximate nearest neighbor search.
//!
//! Implements the HNSW algorithm (Malkov & Yashunin, 2018) with cosine distance.
//! Exposed to Python via PyO3 as `VectorIndex`.

use pyo3::prelude::*;
use pyo3::types::PyBytes;
use std::collections::{BinaryHeap, HashMap, HashSet};
use std::cmp::Ordering;

// ---------------------------------------------------------------------------
// Distance helpers
// ---------------------------------------------------------------------------

/// Cosine distance = 1.0 - cosine_similarity.  Range [0, 2].
#[inline]
fn cosine_distance(a: &[f32], b: &[f32]) -> f32 {
    debug_assert_eq!(a.len(), b.len());
    let mut dot = 0.0_f32;
    let mut na = 0.0_f32;
    let mut nb = 0.0_f32;
    for (x, y) in a.iter().zip(b.iter()) {
        dot += x * y;
        na += x * x;
        nb += y * y;
    }
    let denom = na.sqrt() * nb.sqrt();
    if denom == 0.0 {
        return 1.0;
    }
    1.0 - dot / denom
}

/// Cosine similarity (for returning to Python — users expect similarity, not distance).
#[inline]
fn cosine_similarity(a: &[f32], b: &[f32]) -> f32 {
    1.0 - cosine_distance(a, b)
}

// ---------------------------------------------------------------------------
// Min-heap / max-heap wrappers
// ---------------------------------------------------------------------------

#[derive(Clone)]
struct Candidate {
    dist: f32,
    id: usize,  // internal node index
}

impl PartialEq for Candidate {
    fn eq(&self, other: &Self) -> bool {
        self.dist == other.dist && self.id == other.id
    }
}
impl Eq for Candidate {}

/// BinaryHeap is a max-heap; for a min-heap we reverse the ordering.
impl PartialOrd for Candidate {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}
impl Ord for Candidate {
    fn cmp(&self, other: &Self) -> Ordering {
        // Reverse so BinaryHeap acts as min-heap (smallest distance first).
        other.dist.partial_cmp(&self.dist).unwrap_or(Ordering::Equal)
    }
}

/// Max-heap wrapper (largest distance first for eviction).
#[derive(Clone)]
struct MaxCandidate {
    dist: f32,
    id: usize,
}

impl PartialEq for MaxCandidate {
    fn eq(&self, other: &Self) -> bool {
        self.dist == other.dist && self.id == other.id
    }
}
impl Eq for MaxCandidate {}
impl PartialOrd for MaxCandidate {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}
impl Ord for MaxCandidate {
    fn cmp(&self, other: &Self) -> Ordering {
        self.dist.partial_cmp(&other.dist).unwrap_or(Ordering::Equal)
    }
}

// ---------------------------------------------------------------------------
// HNSW core data structures
// ---------------------------------------------------------------------------

struct Node {
    /// The vector data.
    vector: Vec<f32>,
    /// Neighbors per layer: layers[l] = Vec<usize> (internal ids).
    layers: Vec<Vec<usize>>,
}

/// HNSW parameters.
const M: usize = 16;          // max neighbors per node per layer
const M_MAX0: usize = 32;     // max neighbors at layer 0
const EF_CONSTRUCTION: usize = 200; // search width during construction

/// The HNSW graph.
struct HnswGraph {
    nodes: Vec<Node>,
    entry_point: Option<usize>,
    max_layer: usize,
    ml: f64, // normalization factor: 1 / ln(M)
    dim: usize,
    /// Map from external string ID to internal index.
    id_to_idx: HashMap<String, usize>,
    /// Map from internal index to external string ID.
    idx_to_id: Vec<String>,
}

impl HnswGraph {
    fn new(dim: usize) -> Self {
        let ml = 1.0 / (M as f64).ln();
        Self {
            nodes: Vec::new(),
            entry_point: None,
            max_layer: 0,
            ml,
            dim,
            id_to_idx: HashMap::new(),
            idx_to_id: Vec::new(),
        }
    }

    /// Assign a random layer for a new node.
    fn random_level(&self) -> usize {
        // Use a simple deterministic-ish approach based on node count for reproducibility,
        // but add randomness via a quick xorshift.
        let mut rng = self.nodes.len() as u64;
        rng ^= rng << 13;
        rng ^= rng >> 7;
        rng ^= rng << 17;
        let r = (rng as f64) / (u64::MAX as f64);
        let level = (-r.ln() * self.ml).floor() as usize;
        level.min(16) // cap at 16 layers
    }

    fn insert(&mut self, ext_id: String, vector: Vec<f32>) {
        assert_eq!(vector.len(), self.dim);

        if self.id_to_idx.contains_key(&ext_id) {
            // Update: replace vector, rebuild connections.
            let idx = self.id_to_idx[&ext_id];
            self.nodes[idx].vector = vector;
            // TODO: reconnect neighbors. For now just update vector.
            return;
        }

        let level = self.random_level();
        let idx = self.nodes.len();

        self.id_to_idx.insert(ext_id.clone(), idx);
        self.idx_to_id.push(ext_id);

        let mut layers = Vec::with_capacity(level + 1);
        for _ in 0..=level {
            layers.push(Vec::new());
        }

        self.nodes.push(Node {
            vector,
            layers,
        });

        if self.entry_point.is_none() {
            self.entry_point = Some(idx);
            self.max_layer = level;
            return;
        }

        let ep = self.entry_point.unwrap();
        let mut current_ep = ep;

        // Phase 1: Greedily descend from top layer to level+1
        let start_layer = self.max_layer;
        for l in ((level + 1)..=start_layer).rev() {
            current_ep = self.search_layer_greedy(idx, current_ep, l);
        }

        // Phase 2: Insert at each layer from min(level, max_layer) down to 0
        let bottom = level.min(self.max_layer);
        for l in (0..=bottom).rev() {
            let max_neighbors = if l == 0 { M_MAX0 } else { M };
            let neighbors = self.search_layer(idx, current_ep, EF_CONSTRUCTION, l);

            // Select best neighbors (simple: take closest M)
            let selected: Vec<usize> = neighbors.iter()
                .take(max_neighbors)
                .map(|c| c.id)
                .collect();

            // Add bidirectional connections
            self.nodes[idx].layers[l] = selected.clone();
            for &neighbor_id in &selected {
                if neighbor_id < self.nodes.len() && l < self.nodes[neighbor_id].layers.len() {
                    self.nodes[neighbor_id].layers[l].push(idx);
                    // Shrink if over capacity
                    if self.nodes[neighbor_id].layers[l].len() > max_neighbors {
                        self.shrink_connections(neighbor_id, l, max_neighbors);
                    }
                }
            }

            if !neighbors.is_empty() {
                current_ep = neighbors[0].id;
            }
        }

        // Update entry point if new node has higher layer
        if level > self.max_layer {
            self.entry_point = Some(idx);
            self.max_layer = level;
        }
    }

    /// Greedy search in a single layer — returns single closest node.
    fn search_layer_greedy(&self, query_idx: usize, ep: usize, layer: usize) -> usize {
        let query = &self.nodes[query_idx].vector;
        let mut current = ep;
        let mut current_dist = cosine_distance(query, &self.nodes[ep].vector);

        loop {
            let mut changed = false;
            if layer < self.nodes[current].layers.len() {
                for &neighbor in &self.nodes[current].layers[layer] {
                    let d = cosine_distance(query, &self.nodes[neighbor].vector);
                    if d < current_dist {
                        current_dist = d;
                        current = neighbor;
                        changed = true;
                    }
                }
            }
            if !changed {
                break;
            }
        }
        current
    }

    /// Greedy search for an external query vector.
    fn search_layer_greedy_vec(&self, query: &[f32], ep: usize, layer: usize) -> usize {
        let mut current = ep;
        let mut current_dist = cosine_distance(query, &self.nodes[ep].vector);

        loop {
            let mut changed = false;
            if layer < self.nodes[current].layers.len() {
                for &neighbor in &self.nodes[current].layers[layer] {
                    let d = cosine_distance(query, &self.nodes[neighbor].vector);
                    if d < current_dist {
                        current_dist = d;
                        current = neighbor;
                        changed = true;
                    }
                }
            }
            if !changed {
                break;
            }
        }
        current
    }

    /// Search layer with ef-width beam — returns candidates sorted by distance (closest first).
    fn search_layer(&self, query_idx: usize, ep: usize, ef: usize, layer: usize) -> Vec<Candidate> {
        let query = &self.nodes[query_idx].vector;
        self.search_layer_vec(query, ep, ef, layer)
    }

    fn search_layer_vec(&self, query: &[f32], ep: usize, ef: usize, layer: usize) -> Vec<Candidate> {
        let ep_dist = cosine_distance(query, &self.nodes[ep].vector);

        let mut visited: HashSet<usize> = HashSet::new();
        visited.insert(ep);

        // Min-heap of candidates to explore
        let mut candidates: BinaryHeap<Candidate> = BinaryHeap::new();
        candidates.push(Candidate { dist: ep_dist, id: ep });

        // Max-heap of current best results (for eviction)
        let mut results: BinaryHeap<MaxCandidate> = BinaryHeap::new();
        results.push(MaxCandidate { dist: ep_dist, id: ep });

        while let Some(closest) = candidates.pop() {
            // If the closest candidate is farther than the farthest result, stop
            if let Some(farthest) = results.peek() {
                if closest.dist > farthest.dist && results.len() >= ef {
                    break;
                }
            }

            let node_idx = closest.id;
            if layer >= self.nodes[node_idx].layers.len() {
                continue;
            }

            for &neighbor in &self.nodes[node_idx].layers[layer] {
                if visited.contains(&neighbor) {
                    continue;
                }
                visited.insert(neighbor);

                let d = cosine_distance(query, &self.nodes[neighbor].vector);

                let should_add = if results.len() < ef {
                    true
                } else if let Some(farthest) = results.peek() {
                    d < farthest.dist
                } else {
                    true
                };

                if should_add {
                    candidates.push(Candidate { dist: d, id: neighbor });
                    results.push(MaxCandidate { dist: d, id: neighbor });
                    if results.len() > ef {
                        results.pop(); // remove farthest
                    }
                }
            }
        }

        // Collect and sort by distance
        let mut result_vec: Vec<Candidate> = results
            .into_iter()
            .map(|mc| Candidate { dist: mc.dist, id: mc.id })
            .collect();
        result_vec.sort_by(|a, b| a.dist.partial_cmp(&b.dist).unwrap_or(Ordering::Equal));
        result_vec
    }

    /// Shrink connections for a node at a given layer to max_neighbors.
    fn shrink_connections(&mut self, node_idx: usize, layer: usize, max_neighbors: usize) {
        let node_vec = self.nodes[node_idx].vector.clone();
        let neighbors = &self.nodes[node_idx].layers[layer];
        let mut scored: Vec<(usize, f32)> = neighbors
            .iter()
            .map(|&n| (n, cosine_distance(&node_vec, &self.nodes[n].vector)))
            .collect();
        scored.sort_by(|a, b| a.1.partial_cmp(&b.1).unwrap_or(Ordering::Equal));
        scored.truncate(max_neighbors);
        self.nodes[node_idx].layers[layer] = scored.into_iter().map(|(id, _)| id).collect();
    }

    /// Query the index — returns (external_id, cosine_similarity) pairs, sorted descending.
    fn search(&self, query: &[f32], k: usize, ef_search: usize) -> Vec<(String, f32)> {
        if self.nodes.is_empty() || self.entry_point.is_none() {
            return Vec::new();
        }
        assert_eq!(query.len(), self.dim);

        let ep = self.entry_point.unwrap();

        // Descend from top layer
        let mut current_ep = ep;
        for l in (1..=self.max_layer).rev() {
            current_ep = self.search_layer_greedy_vec(query, current_ep, l);
        }

        // Search at layer 0 with ef width
        let ef = ef_search.max(k);
        let candidates = self.search_layer_vec(query, current_ep, ef, 0);

        // Return top-k as (id, similarity)
        candidates.iter()
            .take(k)
            .map(|c| {
                let ext_id = self.idx_to_id[c.id].clone();
                let sim = cosine_similarity(query, &self.nodes[c.id].vector);
                (ext_id, sim)
            })
            .collect()
    }

    /// Serialize the graph to bytes for persistence.
    fn serialize(&self) -> Vec<u8> {
        let mut buf: Vec<u8> = Vec::new();

        // Header: magic + version
        buf.extend_from_slice(b"HNSW");
        buf.extend_from_slice(&1u32.to_le_bytes()); // version

        // Dimensions
        buf.extend_from_slice(&(self.dim as u32).to_le_bytes());

        // Number of nodes
        let n = self.nodes.len() as u32;
        buf.extend_from_slice(&n.to_le_bytes());

        // Entry point
        let ep = self.entry_point.unwrap_or(0) as u32;
        buf.extend_from_slice(&ep.to_le_bytes());
        buf.push(if self.entry_point.is_some() { 1 } else { 0 });

        // Max layer
        buf.extend_from_slice(&(self.max_layer as u32).to_le_bytes());

        // Nodes
        for i in 0..self.nodes.len() {
            let node = &self.nodes[i];
            let ext_id = &self.idx_to_id[i];

            // External ID (length-prefixed)
            let id_bytes = ext_id.as_bytes();
            buf.extend_from_slice(&(id_bytes.len() as u32).to_le_bytes());
            buf.extend_from_slice(id_bytes);

            // Vector data (f32 LE)
            for &v in &node.vector {
                buf.extend_from_slice(&v.to_le_bytes());
            }

            // Number of layers
            buf.extend_from_slice(&(node.layers.len() as u32).to_le_bytes());

            // Each layer's neighbor list
            for layer in &node.layers {
                buf.extend_from_slice(&(layer.len() as u32).to_le_bytes());
                for &neighbor in layer {
                    buf.extend_from_slice(&(neighbor as u32).to_le_bytes());
                }
            }
        }

        buf
    }

    /// Deserialize from bytes.
    fn deserialize(data: &[u8]) -> Result<Self, String> {
        let mut pos = 0;

        macro_rules! read_u32 {
            () => {{
                if pos + 4 > data.len() {
                    return Err("Unexpected end of data".to_string());
                }
                let val = u32::from_le_bytes([data[pos], data[pos+1], data[pos+2], data[pos+3]]);
                pos += 4;
                val
            }};
        }

        macro_rules! read_f32 {
            () => {{
                if pos + 4 > data.len() {
                    return Err("Unexpected end of data".to_string());
                }
                let val = f32::from_le_bytes([data[pos], data[pos+1], data[pos+2], data[pos+3]]);
                pos += 4;
                val
            }};
        }

        // Header
        if data.len() < 4 || &data[0..4] != b"HNSW" {
            return Err("Invalid magic header".to_string());
        }
        pos = 4;
        let version = read_u32!();
        if version != 1 {
            return Err(format!("Unsupported version: {}", version));
        }

        let dim = read_u32!() as usize;
        let n = read_u32!() as usize;
        let ep_idx = read_u32!() as usize;
        if pos >= data.len() {
            return Err("Unexpected end of data".to_string());
        }
        let has_ep = data[pos] == 1;
        pos += 1;
        let max_layer = read_u32!() as usize;

        let ml = 1.0 / (M as f64).ln();
        let mut graph = HnswGraph {
            nodes: Vec::with_capacity(n),
            entry_point: if has_ep { Some(ep_idx) } else { None },
            max_layer,
            ml,
            dim,
            id_to_idx: HashMap::with_capacity(n),
            idx_to_id: Vec::with_capacity(n),
        };

        for i in 0..n {
            // External ID
            let id_len = read_u32!() as usize;
            if pos + id_len > data.len() {
                return Err("Unexpected end of data".to_string());
            }
            let ext_id = String::from_utf8(data[pos..pos+id_len].to_vec())
                .map_err(|e| format!("Invalid UTF-8 in ID: {}", e))?;
            pos += id_len;

            // Vector
            let mut vector = Vec::with_capacity(dim);
            for _ in 0..dim {
                vector.push(read_f32!());
            }

            // Layers
            let num_layers = read_u32!() as usize;
            let mut layers = Vec::with_capacity(num_layers);
            for _ in 0..num_layers {
                let num_neighbors = read_u32!() as usize;
                let mut neighbors = Vec::with_capacity(num_neighbors);
                for _ in 0..num_neighbors {
                    neighbors.push(read_u32!() as usize);
                }
                layers.push(neighbors);
            }

            graph.id_to_idx.insert(ext_id.clone(), i);
            graph.idx_to_id.push(ext_id);
            graph.nodes.push(Node { vector, layers });
        }

        Ok(graph)
    }

    fn len(&self) -> usize {
        self.nodes.len()
    }

    fn contains(&self, ext_id: &str) -> bool {
        self.id_to_idx.contains_key(ext_id)
    }
}

// ---------------------------------------------------------------------------
// PyO3 wrapper
// ---------------------------------------------------------------------------

/// HNSW-based vector index for fast approximate nearest neighbor search.
///
/// Uses cosine similarity as the distance metric.
/// Supports add/search/batch operations and serialization.
#[pyclass]
pub struct VectorIndex {
    graph: HnswGraph,
    ef_search: usize,
}

#[pymethods]
impl VectorIndex {
    /// Create a new VectorIndex.
    ///
    /// Args:
    ///     dim: Dimensionality of vectors.
    ///     ef_search: Search beam width (higher = more accurate, slower). Default: 50.
    #[new]
    #[pyo3(signature = (dim, ef_search=50))]
    fn new(dim: usize, ef_search: usize) -> Self {
        VectorIndex {
            graph: HnswGraph::new(dim),
            ef_search,
        }
    }

    /// Add a single vector to the index.
    ///
    /// Args:
    ///     id: External string identifier.
    ///     vector: List of f32 values (must match dim).
    fn add_vector(&mut self, id: String, vector: Vec<f32>) -> PyResult<()> {
        if vector.len() != self.graph.dim {
            return Err(pyo3::exceptions::PyValueError::new_err(
                format!("Expected vector of dimension {}, got {}", self.graph.dim, vector.len()),
            ));
        }
        self.graph.insert(id, vector);
        Ok(())
    }

    /// Add multiple vectors in batch.
    ///
    /// Args:
    ///     ids: List of string identifiers.
    ///     vectors: List of vectors (each a list of f32).
    fn add_vectors(&mut self, ids: Vec<String>, vectors: Vec<Vec<f32>>) -> PyResult<()> {
        if ids.len() != vectors.len() {
            return Err(pyo3::exceptions::PyValueError::new_err(
                format!("ids length ({}) != vectors length ({})", ids.len(), vectors.len()),
            ));
        }
        for (id, vec) in ids.into_iter().zip(vectors.into_iter()) {
            if vec.len() != self.graph.dim {
                return Err(pyo3::exceptions::PyValueError::new_err(
                    format!("Expected vector of dimension {}, got {} for id", self.graph.dim, vec.len()),
                ));
            }
            self.graph.insert(id, vec);
        }
        Ok(())
    }

    /// Search for the k nearest neighbors.
    ///
    /// Args:
    ///     query_vector: Query vector (list of f32).
    ///     k: Number of results. Default: 10.
    ///
    /// Returns:
    ///     List of (id, cosine_similarity) tuples, sorted descending by similarity.
    #[pyo3(signature = (query_vector, k=10))]
    fn search(&self, query_vector: Vec<f32>, k: usize) -> PyResult<Vec<(String, f32)>> {
        if query_vector.len() != self.graph.dim {
            return Err(pyo3::exceptions::PyValueError::new_err(
                format!("Expected query of dimension {}, got {}", self.graph.dim, query_vector.len()),
            ));
        }
        Ok(self.graph.search(&query_vector, k, self.ef_search))
    }

    /// Search for multiple queries in batch.
    ///
    /// Args:
    ///     query_vectors: List of query vectors.
    ///     k: Number of results per query.
    ///
    /// Returns:
    ///     List of result lists, one per query.
    #[pyo3(signature = (query_vectors, k=10))]
    fn search_batch(&self, query_vectors: Vec<Vec<f32>>, k: usize) -> PyResult<Vec<Vec<(String, f32)>>> {
        let mut results = Vec::with_capacity(query_vectors.len());
        for qv in query_vectors {
            if qv.len() != self.graph.dim {
                return Err(pyo3::exceptions::PyValueError::new_err(
                    format!("Expected query of dimension {}, got {}", self.graph.dim, qv.len()),
                ));
            }
            results.push(self.graph.search(&qv, k, self.ef_search));
        }
        Ok(results)
    }

    /// Serialize the index to bytes for persistence.
    fn serialize<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyBytes>> {
        let data = self.graph.serialize();
        Ok(PyBytes::new_bound(py, &data))
    }

    /// Load an index from serialized bytes.
    ///
    /// Args:
    ///     data: Bytes from a previous serialize() call.
    ///     ef_search: Search beam width. Default: 50.
    #[staticmethod]
    #[pyo3(signature = (data, ef_search=50))]
    fn deserialize(data: &[u8], ef_search: usize) -> PyResult<Self> {
        let graph = HnswGraph::deserialize(data)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e))?;
        Ok(VectorIndex { graph, ef_search })
    }

    /// Number of vectors in the index.
    #[getter]
    fn count(&self) -> usize {
        self.graph.len()
    }

    /// Dimensionality of the vectors.
    #[getter]
    fn dim(&self) -> usize {
        self.graph.dim
    }

    /// Check if an ID exists in the index.
    fn contains(&self, id: &str) -> bool {
        self.graph.contains(id)
    }

    /// Remove a vector by ID.
    /// Note: This is a soft-remove — the vector remains in the graph but is excluded from results.
    /// For full removal, rebuild the index.
    fn remove_vector(&mut self, id: &str) -> PyResult<bool> {
        if let Some(&idx) = self.graph.id_to_idx.get(id) {
            // Zero out the vector so it doesn't match anything well
            let dim = self.graph.dim;
            self.graph.nodes[idx].vector = vec![0.0; dim];
            // Clear its connections
            for layer in &mut self.graph.nodes[idx].layers {
                layer.clear();
            }
            // Remove from id map
            self.graph.id_to_idx.remove(id);
            Ok(true)
        } else {
            Ok(false)
        }
    }

    /// Get the ef_search parameter.
    #[getter]
    fn ef_search(&self) -> usize {
        self.ef_search
    }

    /// Set the ef_search parameter.
    #[setter]
    fn set_ef_search(&mut self, value: usize) {
        self.ef_search = value;
    }
}
