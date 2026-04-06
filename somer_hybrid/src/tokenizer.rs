use regex::Regex;
use std::sync::OnceLock;

static WORD_RE: OnceLock<Regex> = OnceLock::new();

fn word_regex() -> &'static Regex {
    WORD_RE.get_or_init(|| Regex::new(r"\w+").unwrap())
}

/// Tokenize text into lowercase word tokens (matching Python `re.findall(r"\w+", text.lower())`).
pub fn tokenize(text: &str) -> Vec<String> {
    let lower = text.to_lowercase();
    word_regex()
        .find_iter(&lower)
        .map(|m| m.as_str().to_owned())
        .collect()
}

/// Tokenize into a set of unique tokens.
pub fn tokenize_set(text: &str) -> rustc_hash::FxHashSet<String> {
    let lower = text.to_lowercase();
    word_regex()
        .find_iter(&lower)
        .map(|m| m.as_str().to_owned())
        .collect()
}
