"""Tests para cybersecurity/utils.py."""

from __future__ import annotations

from cybersecurity.utils import (
    extract_hostname,
    is_same_origin,
    normalize_url,
    parse_html_forms,
    parse_html_links,
    parse_set_cookie,
    sanitize_for_display,
)


class TestNormalizeUrl:
    def test_adds_https(self) -> None:
        assert normalize_url("example.com") == "https://example.com"

    def test_keeps_https(self) -> None:
        assert normalize_url("https://example.com") == "https://example.com"

    def test_keeps_http(self) -> None:
        assert normalize_url("http://example.com") == "http://example.com"

    def test_strips_whitespace(self) -> None:
        assert normalize_url("  example.com  ") == "https://example.com"

    def test_empty_string(self) -> None:
        assert normalize_url("") == ""

    def test_with_path(self) -> None:
        assert normalize_url("example.com/path") == "https://example.com/path"


class TestExtractHostname:
    def test_simple(self) -> None:
        assert extract_hostname("https://example.com/path") == "example.com"

    def test_with_port(self) -> None:
        assert extract_hostname("https://example.com:8080") == "example.com"

    def test_bare_domain(self) -> None:
        assert extract_hostname("example.com") == "example.com"

    def test_subdomain(self) -> None:
        assert extract_hostname("https://sub.example.com") == "sub.example.com"


class TestIsSameOrigin:
    def test_same(self) -> None:
        assert is_same_origin("https://example.com/a", "https://example.com/b") is True

    def test_different_host(self) -> None:
        assert is_same_origin("https://a.com", "https://b.com") is False

    def test_different_scheme(self) -> None:
        assert is_same_origin("http://example.com", "https://example.com") is False

    def test_different_port(self) -> None:
        assert is_same_origin("https://example.com:443", "https://example.com:8080") is False


class TestParseHtmlForms:
    def test_simple_form(self) -> None:
        html = '<form action="/login" method="POST"><input name="user"><input name="pass"></form>'
        forms = parse_html_forms(html)
        assert len(forms) == 1
        assert forms[0]["action"] == "/login"
        assert forms[0]["method"] == "POST"
        assert "user" in forms[0]["inputs"]
        assert "pass" in forms[0]["inputs"]

    def test_no_forms(self) -> None:
        assert parse_html_forms("<div>no forms</div>") == []

    def test_multiple_forms(self) -> None:
        html = '<form action="/a" method="GET"></form><form action="/b" method="POST"></form>'
        forms = parse_html_forms(html)
        assert len(forms) == 2

    def test_default_method(self) -> None:
        html = '<form action="/search"></form>'
        forms = parse_html_forms(html)
        assert forms[0]["method"] == "GET"


class TestParseHtmlLinks:
    def test_absolute_links(self) -> None:
        html = '<a href="https://example.com/page">Link</a>'
        links = parse_html_links(html, "https://example.com")
        assert "https://example.com/page" in links

    def test_relative_links(self) -> None:
        html = '<a href="/about">About</a>'
        links = parse_html_links(html, "https://example.com")
        assert "https://example.com/about" in links

    def test_skips_anchors(self) -> None:
        html = '<a href="#section">Section</a><a href="javascript:void(0)">JS</a>'
        links = parse_html_links(html, "https://example.com")
        assert links == []

    def test_skips_mailto(self) -> None:
        html = '<a href="mailto:a@b.com">Email</a>'
        links = parse_html_links(html, "https://example.com")
        assert links == []

    def test_multiple_links(self) -> None:
        html = '<a href="/a">A</a><a href="/b">B</a>'
        links = parse_html_links(html, "https://example.com")
        assert len(links) == 2


class TestSanitizeForDisplay:
    def test_truncation(self) -> None:
        text = "a" * 300
        result = sanitize_for_display(text, max_len=100)
        assert len(result) == 103  # 100 + "..."
        assert result.endswith("...")

    def test_no_truncation(self) -> None:
        assert sanitize_for_display("short") == "short"

    def test_strips_newlines(self) -> None:
        assert sanitize_for_display("line1\nline2\r") == "line1 line2"

    def test_empty(self) -> None:
        assert sanitize_for_display("") == ""


class TestParseSetCookie:
    def test_simple(self) -> None:
        name, attrs = parse_set_cookie("session=abc123; Secure; HttpOnly; SameSite=Lax")
        assert name == "session"
        assert "secure" in attrs
        assert "httponly" in attrs
        assert attrs["samesite"] == "Lax"

    def test_path(self) -> None:
        name, attrs = parse_set_cookie("id=xyz; Path=/; Secure")
        assert name == "id"
        assert attrs["path"] == "/"

    def test_empty(self) -> None:
        name, attrs = parse_set_cookie("")
        assert name == ""
