"""Tests para cybersecurity/types.py."""

from __future__ import annotations

from cybersecurity.types import (
    CookieAnalysis,
    CookieInfo,
    CORSAnalysis,
    DiscoveredPath,
    DNSResult,
    Finding,
    FormAnalysis,
    FormInfo,
    HeaderAnalysis,
    OpenPort,
    PathDiscoveryResult,
    PortScanResult,
    ScanReport,
    Severity,
    SSLAnalysis,
    TechFingerprint,
    XSSResult,
    CrawlResult,
    OpenRedirectResult,
)


class TestSeverity:
    def test_values(self) -> None:
        assert Severity.CRITICAL == "critical"
        assert Severity.HIGH == "high"
        assert Severity.MEDIUM == "medium"
        assert Severity.LOW == "low"
        assert Severity.INFO == "info"


class TestFinding:
    def test_creation(self) -> None:
        f = Finding(
            check_id="test-1",
            severity=Severity.HIGH,
            title="Test finding",
            detail="Detail text",
            remediation="Fix it",
        )
        assert f.check_id == "test-1"
        assert f.severity == Severity.HIGH
        assert f.cwe is None
        assert f.evidence == ""

    def test_with_cwe(self) -> None:
        f = Finding(
            check_id="test-2",
            severity=Severity.CRITICAL,
            title="SSL issue",
            detail="Expired cert",
            remediation="Renew",
            cwe="CWE-295",
            evidence="notAfter: 2020-01-01",
        )
        assert f.cwe == "CWE-295"
        assert f.evidence == "notAfter: 2020-01-01"

    def test_serialization(self) -> None:
        f = Finding(
            check_id="ser-1",
            severity=Severity.LOW,
            title="Title",
            detail="Detail",
            remediation="Remed",
        )
        data = f.model_dump()
        assert data["check_id"] == "ser-1"
        assert data["severity"] == "low"

        # Round trip
        f2 = Finding.model_validate(data)
        assert f2.check_id == f.check_id


class TestHeaderAnalysis:
    def test_default(self) -> None:
        h = HeaderAnalysis()
        assert h.present == {}
        assert h.missing == []
        assert h.findings == []

    def test_with_data(self) -> None:
        h = HeaderAnalysis(
            present={"Content-Security-Policy": "default-src 'self'"},
            missing=["X-Frame-Options"],
        )
        assert "Content-Security-Policy" in h.present
        assert "X-Frame-Options" in h.missing


class TestSSLAnalysis:
    def test_default(self) -> None:
        s = SSLAnalysis()
        assert s.valid is False
        assert s.issuer == ""
        assert s.san == []

    def test_valid_cert(self) -> None:
        s = SSLAnalysis(
            valid=True,
            issuer="CN=Let's Encrypt",
            protocol="TLSv1.3",
            cipher="TLS_AES_256_GCM_SHA384",
        )
        assert s.valid is True
        assert "Encrypt" in s.issuer


class TestCookieAnalysis:
    def test_default(self) -> None:
        c = CookieAnalysis()
        assert c.cookies == []

    def test_with_cookies(self) -> None:
        c = CookieAnalysis(
            cookies=[
                CookieInfo(name="session_id", secure=True, httponly=True, samesite="Lax"),
                CookieInfo(name="prefs", secure=False),
            ],
        )
        assert len(c.cookies) == 2
        assert c.cookies[0].secure is True


class TestTechFingerprint:
    def test_detection(self) -> None:
        t = TechFingerprint(
            technologies=[
                {"name": "nginx", "detected_in": "header"},
                {"name": "React", "detected_in": "body"},
            ]
        )
        assert len(t.technologies) == 2


class TestDNSResult:
    def test_with_records(self) -> None:
        d = DNSResult(records={"A": ["1.2.3.4"], "MX": ["mail.example.com"]})
        assert "A" in d.records
        assert d.records["A"] == ["1.2.3.4"]


class TestPathDiscoveryResult:
    def test_with_found(self) -> None:
        p = PathDiscoveryResult(
            found=[DiscoveredPath(path="/robots.txt", status_code=200, content_length=120)]
        )
        assert len(p.found) == 1
        assert p.found[0].path == "/robots.txt"


class TestCORSAnalysis:
    def test_default(self) -> None:
        c = CORSAnalysis()
        assert c.origin_reflected is False
        assert c.allows_credentials is False


class TestFormAnalysis:
    def test_with_forms(self) -> None:
        fa = FormAnalysis(
            forms=[FormInfo(action="/login", method="POST", has_csrf_token=True)]
        )
        assert len(fa.forms) == 1
        assert fa.forms[0].has_csrf_token is True


class TestXSSResult:
    def test_default(self) -> None:
        x = XSSResult()
        assert x.tested_params == 0
        assert x.reflected_params == []


class TestPortScanResult:
    def test_with_ports(self) -> None:
        p = PortScanResult(
            open_ports=[OpenPort(port=80, service="HTTP"), OpenPort(port=443, service="HTTPS")]
        )
        assert len(p.open_ports) == 2


class TestCrawlResult:
    def test_default(self) -> None:
        c = CrawlResult()
        assert c.pages_crawled == 0
        assert c.internal_links == []


class TestOpenRedirectResult:
    def test_default(self) -> None:
        r = OpenRedirectResult()
        assert r.vulnerable_params == []


class TestScanReport:
    def test_collect_findings(self) -> None:
        finding1 = Finding(
            check_id="h1", severity=Severity.HIGH,
            title="T1", detail="D1", remediation="R1",
        )
        finding2 = Finding(
            check_id="s1", severity=Severity.LOW,
            title="T2", detail="D2", remediation="R2",
        )
        report = ScanReport(
            target_url="https://example.com",
            headers=HeaderAnalysis(findings=[finding1]),
            ssl=SSLAnalysis(findings=[finding2]),
        )
        report.collect_findings()
        assert len(report.all_findings) == 2
        assert report.all_findings[0].check_id == "h1"

    def test_empty_report(self) -> None:
        report = ScanReport(target_url="https://example.com")
        report.collect_findings()
        assert report.all_findings == []
        assert report.risk_score == 0.0

    def test_serialization(self) -> None:
        report = ScanReport(
            target_url="https://example.com",
            scan_duration_secs=5.2,
            risk_score=7.5,
        )
        data = report.model_dump()
        assert data["target_url"] == "https://example.com"
        report2 = ScanReport.model_validate(data)
        assert report2.risk_score == 7.5
