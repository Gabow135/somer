"""Tests para cybersecurity/scanners.py — con mocks de httpx y ssl."""

from __future__ import annotations

import asyncio
import ssl as real_ssl
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cybersecurity.scanners import (
    analyze_csp,
    check_cookies,
    check_cors,
    check_directory_listing,
    check_email_security,
    check_forms,
    check_headers,
    check_html_leaks,
    check_http_methods,
    check_https_redirect,
    check_mixed_content,
    check_open_redirects,
    check_sri,
    check_ssl,
    check_xss_reflection,
    crawl_links,
    discover_paths,
    discover_tech,
    dns_lookup,
    scan_ports,
)
from cybersecurity.types import Severity


# ── Helpers para mocking httpx ───────────────────────────────


class MockResponse:
    """Mock de httpx.Response."""

    def __init__(
        self,
        status_code: int = 200,
        headers: Optional[Dict[str, str]] = None,
        text: str = "",
        cookies_jar: Optional[Any] = None,
    ) -> None:
        self.status_code = status_code
        self.headers = _MockHeaders(headers or {})
        self.text = text
        self.content = text.encode()
        self.cookies = cookies_jar or _MockCookieJar([])


class _MockHeaders:
    """Mock de httpx.Headers."""

    def __init__(self, data: Dict[str, str]) -> None:
        self._data = {k.lower(): v for k, v in data.items()}
        self._original = data

    def get(self, key: str, default: str = "") -> str:
        return self._data.get(key.lower(), default)

    def get_list(self, key: str) -> List[str]:
        val = self._data.get(key.lower())
        return [val] if val else []

    def items(self) -> List[tuple]:
        return list(self._original.items())

    def __contains__(self, key: str) -> bool:
        return key.lower() in self._data

    def __getitem__(self, key: str) -> str:
        return self._data[key.lower()]


class _MockCookie:
    def __init__(self, name: str, secure: bool = False, path: str = "/") -> None:
        self.name = name
        self.secure = secure
        self.path = path


class _MockCookieJar:
    def __init__(self, cookies: List[_MockCookie]) -> None:
        self.jar = cookies


class MockAsyncClient:
    """Mock de httpx.AsyncClient como context manager."""

    def __init__(
        self,
        responses: Optional[Dict[str, MockResponse]] = None,
        default_response: Optional[MockResponse] = None,
    ) -> None:
        self._responses = responses or {}
        self._default = default_response or MockResponse()

    async def get(self, url: str, **kwargs: Any) -> MockResponse:
        return self._responses.get(url, self._default)

    async def __aenter__(self) -> "MockAsyncClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass


def _patch_httpx(client: MockAsyncClient):
    """Creates a patch that replaces httpx.AsyncClient with a factory returning client."""
    mock_httpx = MagicMock()
    mock_httpx.AsyncClient.return_value = client
    mock_httpx.Timeout = MagicMock()
    return patch("cybersecurity.scanners.httpx", mock_httpx)


# ── Tests ────────────────────────────────────────────────────


class TestCheckHeaders:
    @pytest.mark.asyncio
    async def test_missing_headers(self) -> None:
        resp = MockResponse(
            headers={"Server": "nginx/1.18"},
        )
        client = MockAsyncClient(default_response=resp)

        with _patch_httpx(client):
            result = await check_headers("https://example.com")

        assert len(result.missing) > 0
        assert "Content-Security-Policy" in result.missing
        assert len(result.findings) > 0

    @pytest.mark.asyncio
    async def test_present_headers(self) -> None:
        resp = MockResponse(
            headers={
                "Content-Security-Policy": "default-src 'self'",
                "Strict-Transport-Security": "max-age=31536000",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "X-XSS-Protection": "1; mode=block",
                "Referrer-Policy": "strict-origin",
                "Permissions-Policy": "geolocation=()",
                "Cross-Origin-Opener-Policy": "same-origin",
                "Cross-Origin-Resource-Policy": "same-origin",
                "Cross-Origin-Embedder-Policy": "require-corp",
            },
        )
        client = MockAsyncClient(default_response=resp)

        with _patch_httpx(client):
            result = await check_headers("https://example.com")

        assert len(result.present) == 10
        assert result.missing == []

    @pytest.mark.asyncio
    async def test_info_disclosure(self) -> None:
        resp = MockResponse(
            headers={
                "Server": "Apache/2.4.41",
                "X-Powered-By": "PHP/7.4.3",
            },
        )
        client = MockAsyncClient(default_response=resp)

        with _patch_httpx(client):
            result = await check_headers("https://example.com")

        disclosure = [f for f in result.findings if "disclosure" in f.check_id]
        assert len(disclosure) == 2


class TestCheckSSL:
    @pytest.mark.asyncio
    async def test_valid_cert(self) -> None:
        mock_cert = {
            "issuer": ((("commonName", "Let's Encrypt"),),),
            "subject": ((("commonName", "example.com"),),),
            "notAfter": "Dec 31 23:59:59 2027 GMT",
            "subjectAltName": (("DNS", "example.com"), ("DNS", "*.example.com")),
        }

        with patch("cybersecurity.scanners.ssl") as mock_ssl, \
             patch("cybersecurity.scanners.socket") as mock_socket:
            mock_ssl.SSLCertVerificationError = real_ssl.SSLCertVerificationError
            mock_ctx = MagicMock()
            mock_ssl.create_default_context.return_value = mock_ctx
            mock_conn = MagicMock()
            mock_ctx.wrap_socket.return_value = mock_conn
            mock_conn.getpeercert.return_value = mock_cert
            mock_conn.cipher.return_value = ("TLS_AES_256_GCM_SHA384", "TLSv1.3", 256)
            mock_conn.version.return_value = "TLSv1.3"

            result = await check_ssl("example.com")

        assert result.valid is True
        assert "Encrypt" in result.issuer
        assert result.protocol == "TLSv1.3"
        assert len(result.san) == 2

    @pytest.mark.asyncio
    async def test_expired_cert(self) -> None:
        mock_cert = {
            "issuer": ((("commonName", "CA"),),),
            "subject": ((("commonName", "example.com"),),),
            "notAfter": "Jan 01 00:00:00 2020 GMT",
            "subjectAltName": (),
        }

        with patch("cybersecurity.scanners.ssl") as mock_ssl, \
             patch("cybersecurity.scanners.socket") as mock_socket:
            mock_ssl.SSLCertVerificationError = real_ssl.SSLCertVerificationError
            mock_ctx = MagicMock()
            mock_ssl.create_default_context.return_value = mock_ctx
            mock_conn = MagicMock()
            mock_ctx.wrap_socket.return_value = mock_conn
            mock_conn.getpeercert.return_value = mock_cert
            mock_conn.cipher.return_value = ("CIPHER", "TLSv1.2", 128)
            mock_conn.version.return_value = "TLSv1.2"

            result = await check_ssl("example.com")

        assert result.valid is False
        expired = [f for f in result.findings if f.check_id == "ssl-expired"]
        assert len(expired) == 1
        assert expired[0].severity == Severity.CRITICAL

    @pytest.mark.asyncio
    async def test_connection_error(self) -> None:
        import socket as real_socket

        with patch("cybersecurity.scanners.ssl") as mock_ssl, \
             patch("cybersecurity.scanners.socket") as mock_socket:
            mock_ssl.SSLCertVerificationError = real_ssl.SSLCertVerificationError
            # Preserve real socket exception classes
            mock_socket.timeout = real_socket.timeout
            mock_socket.gaierror = real_socket.gaierror
            mock_socket.AF_INET = real_socket.AF_INET
            mock_socket.SOCK_STREAM = real_socket.SOCK_STREAM

            mock_ctx = MagicMock()
            mock_ssl.create_default_context.return_value = mock_ctx
            mock_conn = MagicMock()
            mock_ctx.wrap_socket.return_value = mock_conn
            mock_conn.connect.side_effect = ConnectionRefusedError("refused")

            result = await check_ssl("example.com")

        assert result.valid is False
        assert any("connection" in f.check_id for f in result.findings)


class TestCheckCookies:
    @pytest.mark.asyncio
    async def test_insecure_session_cookie(self) -> None:
        cookie = _MockCookie("session_id", secure=False)
        jar = _MockCookieJar([cookie])
        resp = MockResponse(
            headers={"set-cookie": "session_id=abc; Path=/"},
            cookies_jar=jar,
        )
        client = MockAsyncClient(default_response=resp)

        with _patch_httpx(client):
            result = await check_cookies("https://example.com")

        assert len(result.cookies) == 1
        secure_findings = [f for f in result.findings if "no-secure" in f.check_id]
        assert len(secure_findings) == 1


class TestDiscoverTech:
    @pytest.mark.asyncio
    async def test_detects_technologies(self) -> None:
        resp = MockResponse(
            headers={"Server": "nginx/1.18"},
            text='<html><script src="/wp-content/themes/test.js"></script></html>',
        )
        client = MockAsyncClient(default_response=resp)

        with _patch_httpx(client):
            result = await discover_tech("https://example.com")

        tech_names = [t["name"] for t in result.technologies]
        assert "nginx" in tech_names
        assert "WordPress" in tech_names


class TestDnsLookup:
    @pytest.mark.asyncio
    async def test_socket_fallback(self) -> None:
        """Test DNS lookup con fallback a socket (sin dnspython)."""
        with patch.dict("sys.modules", {"dns": None, "dns.resolver": None}):
            with patch("cybersecurity.scanners.socket") as mock_socket:
                mock_socket.AF_INET = 2
                mock_socket.AF_INET6 = 10
                mock_socket.getaddrinfo.return_value = [
                    (2, 1, 6, "", ("93.184.216.34", 0)),
                ]

                result = await dns_lookup("example.com")

        assert "A" in result.records
        assert "93.184.216.34" in result.records["A"]

    @pytest.mark.asyncio
    async def test_no_spf_finding(self) -> None:
        """Test que se genera finding cuando no hay SPF."""
        with patch.dict("sys.modules", {"dns": None, "dns.resolver": None}):
            with patch("cybersecurity.scanners.socket") as mock_socket:
                mock_socket.AF_INET = 2
                mock_socket.AF_INET6 = 10
                mock_socket.getaddrinfo.return_value = [
                    (2, 1, 6, "", ("1.2.3.4", 0)),
                ]

                result = await dns_lookup("example.com")

        spf_findings = [f for f in result.findings if "spf" in f.check_id]
        assert len(spf_findings) == 1


class TestDiscoverPaths:
    @pytest.mark.asyncio
    async def test_finds_robots_txt(self) -> None:
        responses = {
            "https://example.com/robots.txt": MockResponse(status_code=200, text="User-agent: *"),
        }
        client = MockAsyncClient(responses=responses, default_response=MockResponse(status_code=404))

        with _patch_httpx(client):
            result = await discover_paths("https://example.com")

        found_paths = [p.path for p in result.found]
        assert "/robots.txt" in found_paths

    @pytest.mark.asyncio
    async def test_sensitive_env_file(self) -> None:
        responses = {
            "https://example.com/.env": MockResponse(status_code=200, text="SECRET=key"),
        }
        client = MockAsyncClient(responses=responses, default_response=MockResponse(status_code=404))

        with _patch_httpx(client):
            result = await discover_paths("https://example.com")

        env_findings = [f for f in result.findings if ".env" in f.check_id]
        assert len(env_findings) == 1
        assert env_findings[0].severity == Severity.CRITICAL


class TestCheckCORS:
    @pytest.mark.asyncio
    async def test_reflected_origin(self) -> None:
        resp = MockResponse(
            headers={
                "Access-Control-Allow-Origin": "https://evil-attacker.example.com",
                "Access-Control-Allow-Credentials": "true",
            },
        )
        client = MockAsyncClient(default_response=resp)

        with _patch_httpx(client):
            result = await check_cors("https://example.com")

        assert result.origin_reflected is True
        assert result.allows_credentials is True
        assert len(result.findings) > 0
        assert result.findings[0].severity == Severity.HIGH

    @pytest.mark.asyncio
    async def test_safe_cors(self) -> None:
        resp = MockResponse(headers={})
        client = MockAsyncClient(default_response=resp)

        with _patch_httpx(client):
            result = await check_cors("https://example.com")

        assert result.origin_reflected is False
        assert result.findings == []


class TestCheckForms:
    @pytest.mark.asyncio
    async def test_form_without_csrf(self) -> None:
        html = '<form action="/login" method="POST"><input name="user"><input name="pass"></form>'
        resp = MockResponse(text=html)
        client = MockAsyncClient(default_response=resp)

        with _patch_httpx(client):
            result = await check_forms("https://example.com")

        assert len(result.forms) == 1
        csrf_findings = [f for f in result.findings if "csrf" in f.check_id]
        assert len(csrf_findings) == 1


class TestCheckXSSReflection:
    @pytest.mark.asyncio
    async def test_no_params(self) -> None:
        """Sin query params no se testea."""
        result = await check_xss_reflection("https://example.com")
        assert result.tested_params == 0

    @pytest.mark.asyncio
    async def test_reflected_param(self) -> None:
        resp = MockResponse(text="Result: <somer7x5s3q9>")
        client = MockAsyncClient(default_response=resp)

        with _patch_httpx(client):
            result = await check_xss_reflection("https://example.com/search?q=test")

        assert result.tested_params == 1
        assert "q" in result.reflected_params
        assert len(result.findings) == 1
        assert result.findings[0].severity == Severity.HIGH


class TestScanPorts:
    @pytest.mark.asyncio
    async def test_open_ports(self) -> None:
        async def mock_open_connection(host: str, port: int) -> tuple:
            mock_writer = MagicMock()
            mock_writer.close = MagicMock()
            mock_writer.wait_closed = AsyncMock()
            if port in (80, 443):
                return (MagicMock(), mock_writer)
            raise ConnectionRefusedError()

        with patch("cybersecurity.scanners.asyncio.open_connection", side_effect=mock_open_connection):
            result = await scan_ports("example.com", ports=[80, 443, 3306])

        port_nums = [p.port for p in result.open_ports]
        assert 80 in port_nums
        assert 443 in port_nums
        assert 3306 not in port_nums

    @pytest.mark.asyncio
    async def test_database_port_finding(self) -> None:
        async def mock_open_connection(host: str, port: int) -> tuple:
            mock_writer = MagicMock()
            mock_writer.close = MagicMock()
            mock_writer.wait_closed = AsyncMock()
            return (MagicMock(), mock_writer)

        with patch("cybersecurity.scanners.asyncio.open_connection", side_effect=mock_open_connection):
            result = await scan_ports("example.com", ports=[80, 3306])

        db_findings = [f for f in result.findings if "database" in f.check_id]
        assert len(db_findings) == 1
        assert db_findings[0].severity == Severity.CRITICAL


# ── Nuevos scanners ──────────────────────────────────────────


class TestCheckHttpMethods:
    @pytest.mark.asyncio
    async def test_detects_unsafe_methods(self) -> None:
        """Detecta PUT/DELETE en header Allow."""

        class _OptionsClient(MockAsyncClient):
            async def options(self, url: str, **kwargs: Any) -> MockResponse:
                return MockResponse(headers={"Allow": "GET, POST, PUT, DELETE, OPTIONS"})

        client = _OptionsClient()
        with _patch_httpx(client):
            result = await check_http_methods("https://example.com")

        assert "PUT" in result.unsafe_methods
        assert "DELETE" in result.unsafe_methods
        assert len(result.findings) == 1
        assert result.findings[0].check_id == "unsafe-http-methods"


class TestCheckHttpsRedirect:
    @pytest.mark.asyncio
    async def test_redirect_ok(self) -> None:
        """Detecta redirección HTTP → HTTPS correcta."""
        resp_redirect = MockResponse(
            status_code=301,
            headers={"Location": "https://example.com/"},
        )
        client = MockAsyncClient(default_response=resp_redirect)
        with _patch_httpx(client):
            result = await check_https_redirect("https://example.com")

        assert result.redirects_to_https is True
        assert len(result.findings) == 0


class TestCheckSRI:
    @pytest.mark.asyncio
    async def test_missing_sri(self) -> None:
        """Detecta scripts externos sin integrity."""
        html = (
            '<html><head>'
            '<script src="https://cdn.example.com/lib.js"></script>'
            '<script src="https://cdn.example.com/app.js" integrity="sha384-abc"></script>'
            '</head></html>'
        )
        resp = MockResponse(text=html)
        client = MockAsyncClient(default_response=resp)
        with _patch_httpx(client):
            result = await check_sri("https://example.com")

        assert result.external_scripts == 2
        assert result.scripts_with_sri == 1
        assert len(result.scripts_without_sri) == 1
        assert len(result.findings) == 1
        assert result.findings[0].check_id == "missing-sri"


class TestCheckMixedContent:
    @pytest.mark.asyncio
    async def test_mixed_content_found(self) -> None:
        """Detecta recursos HTTP en página HTTPS."""
        html = (
            '<html>'
            '<script src="http://cdn.example.com/bad.js"></script>'
            '<img src="http://images.example.com/pic.png">'
            '</html>'
        )
        resp = MockResponse(text=html)
        client = MockAsyncClient(default_response=resp)
        with _patch_httpx(client):
            result = await check_mixed_content("https://example.com")

        assert len(result.mixed_scripts) == 1
        assert len(result.mixed_images) == 1
        assert len(result.findings) == 1
        assert result.findings[0].check_id == "mixed-content"


class TestCheckDirectoryListing:
    @pytest.mark.asyncio
    async def test_listing_found(self) -> None:
        """Detecta directory listing habilitado."""
        listing_html = "<html><title>Index of /images/</title><body>Parent Directory</body></html>"
        responses = {
            "https://example.com/images/": MockResponse(text=listing_html),
        }
        client = MockAsyncClient(responses=responses, default_response=MockResponse(status_code=404))
        with _patch_httpx(client):
            result = await check_directory_listing("https://example.com")

        assert "/images/" in result.listings_found
        assert len(result.findings) == 1
        assert result.findings[0].check_id == "directory-listing"


class TestCheckHtmlLeaks:
    @pytest.mark.asyncio
    async def test_versions_found(self) -> None:
        """Detecta versiones expuestas en HTML."""
        html = '<html><head><meta name="generator" content="WordPress 6.4.2"></head></html>'
        resp = MockResponse(text=html)
        client = MockAsyncClient(default_response=resp)
        with _patch_httpx(client):
            result = await check_html_leaks("https://example.com")

        assert len(result.versions_found) > 0
        version_findings = [f for f in result.findings if "version" in f.check_id]
        assert len(version_findings) >= 1


class TestAnalyzeCSP:
    @pytest.mark.asyncio
    async def test_unsafe_inline(self) -> None:
        """Detecta unsafe-inline en CSP."""
        resp = MockResponse(
            headers={
                "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'",
            },
        )
        client = MockAsyncClient(default_response=resp)
        with _patch_httpx(client):
            result = await analyze_csp("https://example.com")

        assert result.has_unsafe_inline is True
        assert result.has_unsafe_eval is True
        unsafe_findings = [f for f in result.findings if "unsafe" in f.check_id]
        assert len(unsafe_findings) == 2


class TestCheckEmailSecurity:
    @pytest.mark.asyncio
    async def test_missing_records(self) -> None:
        """Detecta SPF/DMARC/DKIM faltantes cuando dnspython no está."""
        with patch.dict("sys.modules", {"dns": None, "dns.resolver": None}):
            with patch("cybersecurity.scanners.socket") as mock_socket:
                mock_socket.getaddrinfo.return_value = [
                    (2, 1, 6, "", ("1.2.3.4", 0)),
                ]
                result = await check_email_security("example.com")

        # Sin dnspython retorna finding informativo
        assert len(result.findings) >= 1
