"""Parity tests: Rust CredentialScanner vs Python regex detector.

Verifies that the Rust/Aho-Corasick backend produces identical results
to the Python regex fallback for all credential patterns.
"""

from __future__ import annotations

import re
import time
from typing import Dict, List, Set

import pytest

from secrets.patterns import CREDENTIAL_PATTERNS, get_unique_patterns

# ── Rust backend availability ─────────────────────────────────────

try:
    from somer_hybrid import CredentialScanner, CredentialMatch, quick_scan
    RUST_AVAILABLE = True
except ImportError:
    RUST_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not RUST_AVAILABLE,
    reason="somer_hybrid Rust module not available",
)


# ── Test data: realistic credential samples ───────────────────────

SAMPLE_CREDENTIALS = {
    "anthropic": "sk-ant-abcdefghijklmnopqrstuvwxyz1234567890",
    "openrouter": "sk-or-v1-abcdefghijklmnopqrstuvwxyz12345",
    "groq": "gsk_abcdefghijklmnopqrstuvwx",
    "google": "AIzaSyAbcdefghijklmnopqrstuvwxyz123456",
    "huggingface": "hf_abcdefghijklmnopqrstuvwx",
    "xai": "xai-abcdefghijklmnopqrstuvwx",
    "perplexity": "pplx-abcdefghijklmnopqrstuvwxyz1234567890abcdef",
    "nvidia": "nvapi-abcdefghijklmnopqrstuvwx",
    "notion_ntn": "ntn_abcdefghijklmnopqrstuvwx",
    "notion_secret": "secret_AbcdefghijklmnopqrstuvwxYz0123456789ABCDEF",
    "github_pat": "ghp_abcdefghij1234567890abcdefghij123456",
    "github_oauth": "gho_abcdefghij1234567890abcdefghij123456",
    "gitlab": "glpat-abcdefghijklmnopqrstuvwx",
    "slack_bot": "xoxb-FILTERED",
    "slack_app": "xapp-FILTERED",
    "tavily": "tvly-abcdefghijklmnopqrstuvwx",
    "openai": "sk-proj-abcdefghij1234567890abcd",
}

# These are handled only by Python regex (no simple literal prefix)
PYTHON_ONLY_CREDENTIALS = {
    "telegram": "12345678901:ABCdefGHIjklMNOpqrSTUvwxYZ_abcdefg",
    "discord": "MTIzNDU2Nzg5MDEy.abcdef.abcdefghijklmnopqrstuvwxyz0",
}


def _build_rust_patterns() -> Dict[str, Dict[str, str]]:
    """Build Rust scanner patterns dict matching detector.py logic."""
    from secrets.detector import _PREFIX_MAP

    rust_patterns: Dict[str, Dict[str, str]] = {}
    for p in get_unique_patterns():
        sid = p.service_id
        if sid == "notion":
            rust_patterns["notion_ntn"] = {
                "prefix": "ntn_",
                "regex": r"ntn_[a-zA-Z0-9]{20,}",
            }
            rust_patterns["notion_secret"] = {
                "prefix": "secret_",
                "regex": r"secret_[a-zA-Z0-9]{20,}",
            }
            continue

        prefix = _PREFIX_MAP.get(sid)
        if prefix is None:
            continue

        # Rust regex crate doesn't support lookahead — use simplified pattern
        regex_str = p.pattern
        if sid == "openai":
            regex_str = r"sk-[a-zA-Z0-9_-]{20,}"

        rust_patterns[sid] = {
            "prefix": prefix,
            "regex": regex_str,
        }
    return rust_patterns


# ── Parity tests ──────────────────────────────────────────────────


class TestRustScannerBasic:
    """Basic functionality of the Rust CredentialScanner."""

    def test_scanner_creation(self):
        patterns = _build_rust_patterns()
        scanner = CredentialScanner(patterns)
        assert scanner.pattern_count() == len(patterns)

    def test_scan_empty_text(self):
        patterns = _build_rust_patterns()
        scanner = CredentialScanner(patterns)
        matches = scanner.scan("")
        assert matches == []

    def test_scan_no_credentials(self):
        patterns = _build_rust_patterns()
        scanner = CredentialScanner(patterns)
        matches = scanner.scan("this is just a normal text without any credentials")
        assert matches == []

    def test_scan_short_prefix_no_match(self):
        """Short prefix without enough chars should not match."""
        patterns = _build_rust_patterns()
        scanner = CredentialScanner(patterns)
        matches = scanner.scan("sk-ant- is a prefix but too short")
        assert matches == []

    def test_redact_no_credentials(self):
        patterns = _build_rust_patterns()
        scanner = CredentialScanner(patterns)
        text = "hello world"
        assert scanner.redact(text) == text


class TestRustScannerDetection:
    """Test that Rust scanner detects each credential type."""

    @pytest.mark.parametrize("name,value", list(SAMPLE_CREDENTIALS.items()))
    def test_detect_individual(self, name: str, value: str):
        patterns = _build_rust_patterns()
        scanner = CredentialScanner(patterns)
        text = f"here is the credential: {value}"
        matches = scanner.scan(text)
        assert len(matches) >= 1, f"Failed to detect {name}: {value}"
        found_names = {m.pattern_name for m in matches}
        assert name in found_names, f"Expected pattern '{name}' but got {found_names}"

    def test_detect_multiple_in_text(self):
        patterns = _build_rust_patterns()
        scanner = CredentialScanner(patterns)
        parts = [f"{v}" for v in SAMPLE_CREDENTIALS.values()]
        text = " ".join(parts)
        matches = scanner.scan(text)
        assert len(matches) == len(SAMPLE_CREDENTIALS)

    def test_match_positions(self):
        patterns = _build_rust_patterns()
        scanner = CredentialScanner(patterns)
        cred = SAMPLE_CREDENTIALS["anthropic"]
        prefix = "KEY: "
        text = prefix + cred
        matches = scanner.scan(text)
        assert len(matches) == 1
        m = matches[0]
        assert m.start == len(prefix)
        assert m.end == len(prefix) + len(cred)
        assert m.matched_text == cred


class TestRustScannerRedact:
    """Test redaction functionality."""

    def test_redact_single(self):
        patterns = _build_rust_patterns()
        scanner = CredentialScanner(patterns)
        cred = SAMPLE_CREDENTIALS["anthropic"]
        text = f"my key is {cred} ok?"
        redacted = scanner.redact(text)
        assert cred not in redacted
        assert "[REDACTED:anthropic]" in redacted
        assert "my key is " in redacted
        assert " ok?" in redacted

    def test_redact_multiple(self):
        patterns = _build_rust_patterns()
        scanner = CredentialScanner(patterns)
        text = f'{SAMPLE_CREDENTIALS["anthropic"]} and {SAMPLE_CREDENTIALS["groq"]}'
        redacted = scanner.redact(text)
        assert SAMPLE_CREDENTIALS["anthropic"] not in redacted
        assert SAMPLE_CREDENTIALS["groq"] not in redacted
        assert "[REDACTED:anthropic]" in redacted
        assert "[REDACTED:groq]" in redacted

    def test_redact_custom_mask(self):
        patterns = _build_rust_patterns()
        scanner = CredentialScanner(patterns)
        cred = SAMPLE_CREDENTIALS["anthropic"]
        text = f"key: {cred}"
        redacted = scanner.redact_custom(text, "*", 6)
        assert cred not in redacted
        assert redacted.startswith("key: sk-ant")
        assert "****" in redacted


class TestQuickScan:
    """Test the quick_scan standalone function."""

    def test_quick_scan_basic(self):
        patterns = _build_rust_patterns()
        cred = SAMPLE_CREDENTIALS["groq"]
        matches = quick_scan(f"api key: {cred}", patterns)
        assert len(matches) == 1
        assert matches[0].pattern_name == "groq"
        assert matches[0].matched_text == cred


class TestParityWithPython:
    """Verify Rust scanner produces same detections as Python regex."""

    def _python_scan(self, text: str) -> Set[str]:
        """Scan with Python regex and return set of matched values."""
        found = set()
        for p in get_unique_patterns():
            for m in re.finditer(p.pattern, text):
                val = m.group(0)
                if len(val) >= 10:
                    found.add(val)
        return found

    def _rust_scan(self, text: str) -> Set[str]:
        """Scan with Rust scanner and return set of matched values."""
        patterns = _build_rust_patterns()
        scanner = CredentialScanner(patterns)
        matches = scanner.scan(text)
        return {m.matched_text for m in matches}

    @pytest.mark.parametrize("name,value", list(SAMPLE_CREDENTIALS.items()))
    def test_parity_individual(self, name: str, value: str):
        text = f"credential: {value} end"
        py = self._python_scan(text)
        rs = self._rust_scan(text)
        # Rust should find at least what corresponds to this credential
        assert value in rs, f"Rust missed {name}"
        assert value in py, f"Python missed {name}"

    def test_parity_full_text(self):
        """Both backends find the same credentials in a multi-credential text."""
        parts = [f"svc={v}" for v in SAMPLE_CREDENTIALS.values()]
        text = " | ".join(parts)
        py = self._python_scan(text)
        rs = self._rust_scan(text)

        # Every Rust match should also be found by Python
        for val in rs:
            assert val in py, f"Rust found '{val[:20]}...' but Python didn't"

        # For unique-prefix patterns handled by Rust, Python should agree
        # (Some Python matches may be from patterns Rust doesn't cover)
        for val in SAMPLE_CREDENTIALS.values():
            if val in py:
                assert val in rs, f"Python found '{val[:20]}...' but Rust didn't"

    def test_parity_detector_class(self):
        """CredentialDetector (which uses Rust internally) matches pure Python."""
        from secrets.detector import CredentialDetector

        d = CredentialDetector()
        for name, value in SAMPLE_CREDENTIALS.items():
            text = f"here: {value}"
            report = d.scan(text)
            values = {c.value for c in report.credentials}
            assert value in values, f"Detector missed {name} ({value[:20]}...)"

    def test_openai_not_confused_with_anthropic(self):
        """sk-proj should match openai, not anthropic."""
        patterns = _build_rust_patterns()
        scanner = CredentialScanner(patterns)
        text = "sk-proj-abcdefghij1234567890abcd"
        matches = scanner.scan(text)
        names = {m.pattern_name for m in matches}
        assert "anthropic" not in names
        # openai uses prefix "sk-" so it should match
        assert "openai" in names


class TestBenchmark:
    """Performance comparison: Rust Aho-Corasick vs Python regex."""

    def _make_large_text(self, n_lines: int = 500) -> str:
        """Generate a large text with some credentials sprinkled in."""
        lines = []
        creds = list(SAMPLE_CREDENTIALS.values())
        for i in range(n_lines):
            if i % 50 == 0 and creds:
                cred = creds[i // 50 % len(creds)]
                lines.append(f"config line {i}: key={cred} # auto")
            else:
                lines.append(f"This is line {i} of normal text without any secrets or keys present here.")
        return "\n".join(lines)

    def test_benchmark_rust_vs_python(self):
        """Benchmark: Rust Aho-Corasick vs Python regex on large text."""
        text = self._make_large_text(1000)
        patterns_dict = _build_rust_patterns()
        scanner = CredentialScanner(patterns_dict)
        compiled_patterns = [
            (p.service_id, re.compile(p.pattern))
            for p in get_unique_patterns()
        ]

        iterations = 100

        # Rust benchmark
        t0 = time.perf_counter()
        for _ in range(iterations):
            rust_matches = scanner.scan(text)
        rust_time = time.perf_counter() - t0

        # Python benchmark
        t0 = time.perf_counter()
        for _ in range(iterations):
            py_matches = []
            for sid, pat in compiled_patterns:
                for m in pat.finditer(text):
                    if len(m.group(0)) >= 10:
                        py_matches.append((sid, m.group(0)))
        python_time = time.perf_counter() - t0

        speedup = python_time / rust_time if rust_time > 0 else float("inf")

        # Print benchmark results
        print(f"\n{'='*60}")
        print(f"Benchmark: Credential Scanner ({iterations} iterations)")
        print(f"Text size: {len(text):,} chars, {text.count(chr(10))+1} lines")
        print(f"{'='*60}")
        print(f"  Rust (Aho-Corasick):  {rust_time*1000:.1f} ms total, {rust_time/iterations*1000:.3f} ms/iter")
        print(f"  Python (regex):       {python_time*1000:.1f} ms total, {python_time/iterations*1000:.3f} ms/iter")
        print(f"  Speedup:              {speedup:.1f}x")
        print(f"  Rust matches:         {len(rust_matches)}")
        print(f"  Python matches:       {len(py_matches)}")
        print(f"{'='*60}")

        # Rust should not be slower than Python
        # (allow some margin for small texts / cold caches)
        assert rust_time <= python_time * 2, (
            f"Rust ({rust_time:.3f}s) should not be much slower than Python ({python_time:.3f}s)"
        )

    def test_benchmark_redact(self):
        """Benchmark redaction speed."""
        text = self._make_large_text(1000)
        patterns_dict = _build_rust_patterns()
        scanner = CredentialScanner(patterns_dict)

        iterations = 100

        t0 = time.perf_counter()
        for _ in range(iterations):
            redacted = scanner.redact(text)
        rust_time = time.perf_counter() - t0

        print(f"\n{'='*60}")
        print(f"Benchmark: Redaction ({iterations} iterations)")
        print(f"Text size: {len(text):,} chars")
        print(f"{'='*60}")
        print(f"  Rust redact:  {rust_time*1000:.1f} ms total, {rust_time/iterations*1000:.3f} ms/iter")
        print(f"{'='*60}")

        # Sanity: redacted text should not contain any known credentials
        for v in SAMPLE_CREDENTIALS.values():
            assert v not in redacted
