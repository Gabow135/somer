//! Credential scanner using Aho-Corasick for fast multi-pattern prefix matching
//! followed by regex validation.

use aho_corasick::{AhoCorasick, MatchKind};
use pyo3::prelude::*;
use regex::Regex;
use std::collections::HashMap;

/// A single credential match found in text.
#[pyclass]
#[derive(Clone, Debug)]
pub struct CredentialMatch {
    #[pyo3(get)]
    pub start: usize,
    #[pyo3(get)]
    pub end: usize,
    #[pyo3(get)]
    pub pattern_name: String,
    #[pyo3(get)]
    pub matched_text: String,
}

#[pymethods]
impl CredentialMatch {
    fn __repr__(&self) -> String {
        format!(
            "CredentialMatch(pattern_name='{}', start={}, end={}, matched_text='{}...{}')",
            self.pattern_name,
            self.start,
            self.end,
            &self.matched_text[..self.matched_text.len().min(8)],
            if self.matched_text.len() > 12 {
                &self.matched_text[self.matched_text.len() - 4..]
            } else {
                ""
            }
        )
    }
}

/// Internal pattern definition: prefix for Aho-Corasick + full regex for validation.
struct PatternDef {
    name: String,
    full_regex: Regex,
}

/// High-performance credential scanner using Aho-Corasick + regex.
///
/// Usage from Python:
///     scanner = CredentialScanner({"anthropic": {"prefix": "sk-ant-", "regex": r"sk-ant-[a-zA-Z0-9_-]{20,}"}})
///     matches = scanner.scan("text with sk-ant-abc123...")
///     redacted = scanner.redact("text with sk-ant-abc123...")
#[pyclass]
pub struct CredentialScanner {
    ac: AhoCorasick,
    /// Index-aligned with AC patterns: maps AC pattern index -> PatternDef
    patterns: Vec<PatternDef>,
    /// Prefix strings (index-aligned with AC)
    prefixes: Vec<String>,
}

#[pymethods]
impl CredentialScanner {
    /// Create a new scanner.
    ///
    /// Args:
    ///     patterns: Dict[str, Dict[str, str]] mapping pattern_name -> {"prefix": "...", "regex": "..."}
    #[new]
    fn new(patterns: HashMap<String, HashMap<String, String>>) -> PyResult<Self> {
        let mut prefix_list: Vec<String> = Vec::with_capacity(patterns.len());
        let mut pattern_defs: Vec<PatternDef> = Vec::with_capacity(patterns.len());

        for (name, config) in &patterns {
            let prefix = config.get("prefix").ok_or_else(|| {
                pyo3::exceptions::PyValueError::new_err(format!(
                    "Pattern '{}' missing 'prefix' key",
                    name
                ))
            })?;
            let regex_str = config.get("regex").ok_or_else(|| {
                pyo3::exceptions::PyValueError::new_err(format!(
                    "Pattern '{}' missing 'regex' key",
                    name
                ))
            })?;
            let full_regex = Regex::new(regex_str).map_err(|e| {
                pyo3::exceptions::PyValueError::new_err(format!(
                    "Invalid regex for '{}': {}",
                    name, e
                ))
            })?;

            prefix_list.push(prefix.clone());
            pattern_defs.push(PatternDef {
                name: name.clone(),
                full_regex,
            });
        }

        let ac = AhoCorasick::builder()
            .match_kind(MatchKind::Standard)
            .build(&prefix_list)
            .map_err(|e| {
                pyo3::exceptions::PyValueError::new_err(format!(
                    "Failed to build Aho-Corasick automaton: {}",
                    e
                ))
            })?;

        Ok(CredentialScanner {
            ac,
            patterns: pattern_defs,
            prefixes: prefix_list,
        })
    }

    /// Scan text for credential matches.
    ///
    /// Returns a list of CredentialMatch objects.
    /// When multiple patterns match the same region, the pattern with the
    /// longer (more specific) prefix wins.
    fn scan(&self, text: &str) -> Vec<CredentialMatch> {
        // Collect all candidate matches first
        let mut candidates: Vec<(usize, usize, usize, String)> = Vec::new(); // (start, end, prefix_len, name)

        for mat in self.ac.find_overlapping_iter(text) {
            let pattern_idx = mat.pattern().as_usize();
            let pattern_def = &self.patterns[pattern_idx];
            let prefix_len = self.prefixes[pattern_idx].len();

            let start = mat.start();
            let slice = &text[start..];

            if let Some(re_match) = pattern_def.full_regex.find(slice) {
                if re_match.start() != 0 {
                    continue;
                }
                let actual_start = start;
                let actual_end = start + re_match.end();
                let matched_text = &text[actual_start..actual_end];

                if matched_text.len() < 10 {
                    continue;
                }

                candidates.push((
                    actual_start,
                    actual_end,
                    prefix_len,
                    pattern_def.name.clone(),
                ));
            }
        }

        // Deduplicate: for overlapping ranges, keep the one with the longest prefix
        // (most specific pattern). Sort by start, then by prefix_len descending.
        candidates.sort_by(|a, b| {
            a.0.cmp(&b.0)
                .then(b.2.cmp(&a.2)) // longer prefix first
        });

        let mut results: Vec<CredentialMatch> = Vec::new();
        let mut seen_ranges: Vec<(usize, usize)> = Vec::new();

        for (actual_start, actual_end, _prefix_len, name) in &candidates {
            // Check if this range is dominated by an existing result
            let dominated = seen_ranges
                .iter()
                .any(|&(s, e)| *actual_start >= s && *actual_end <= e);
            if dominated {
                continue;
            }

            // Remove any existing results that this new one dominates
            let mut i = 0;
            while i < results.len() {
                let (s, e) = seen_ranges[i];
                if s >= *actual_start && e <= *actual_end {
                    results.remove(i);
                    seen_ranges.remove(i);
                } else {
                    i += 1;
                }
            }

            seen_ranges.push((*actual_start, *actual_end));
            results.push(CredentialMatch {
                start: *actual_start,
                end: *actual_end,
                pattern_name: name.clone(),
                matched_text: text[*actual_start..*actual_end].to_string(),
            });
        }

        results
    }

    /// Redact all detected credentials in text, replacing them with masks.
    ///
    /// The mask format is: [REDACTED:<pattern_name>]
    fn redact(&self, text: &str) -> String {
        let matches = self.scan(text);
        if matches.is_empty() {
            return text.to_string();
        }

        // Sort matches by start position (descending) so we can replace from end to start
        let mut sorted_matches = matches;
        sorted_matches.sort_by(|a, b| b.start.cmp(&a.start));

        let mut result = text.to_string();
        for m in &sorted_matches {
            let mask = format!("[REDACTED:{}]", m.pattern_name);
            result.replace_range(m.start..m.end, &mask);
        }

        result
    }

    /// Redact credentials using a custom mask format.
    ///
    /// Args:
    ///     text: Input text
    ///     mask_char: Character to use for masking (default: '*')
    ///     show_prefix: Number of prefix characters to show (default: 4)
    fn redact_custom(&self, text: &str, mask_char: char, show_prefix: usize) -> String {
        let matches = self.scan(text);
        if matches.is_empty() {
            return text.to_string();
        }

        let mut sorted_matches = matches;
        sorted_matches.sort_by(|a, b| b.start.cmp(&a.start));

        let mut result = text.to_string();
        for m in &sorted_matches {
            let visible = &m.matched_text[..m.matched_text.len().min(show_prefix)];
            let mask_len = m.matched_text.len().saturating_sub(show_prefix);
            let mask: String = std::iter::repeat(mask_char).take(mask_len).collect();
            let replacement = format!("{}{}", visible, mask);
            result.replace_range(m.start..m.end, &replacement);
        }

        result
    }

    /// Return the number of patterns loaded.
    fn pattern_count(&self) -> usize {
        self.patterns.len()
    }
}

/// Quick scan function — creates a temporary scanner with the given patterns and scans once.
///
/// Useful for one-off scans. For repeated scans, create a CredentialScanner instance.
#[pyfunction]
pub fn quick_scan(
    text: &str,
    patterns: HashMap<String, HashMap<String, String>>,
) -> PyResult<Vec<CredentialMatch>> {
    let scanner = CredentialScanner::new(patterns)?;
    Ok(scanner.scan(text))
}
