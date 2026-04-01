"""Tests para cybersecurity/report.py."""

from __future__ import annotations

from cybersecurity.report import (
    calculate_risk_score,
    findings_to_summary,
    generate_markdown_report,
)
from cybersecurity.types import (
    Finding,
    HeaderAnalysis,
    OpenPort,
    PortScanResult,
    ScanReport,
    Severity,
    SSLAnalysis,
    TechFingerprint,
)


class TestRiskScore:
    def test_empty_findings(self) -> None:
        assert calculate_risk_score([]) == 0.0

    def test_single_critical(self) -> None:
        findings = [
            Finding(
                check_id="c1", severity=Severity.CRITICAL,
                title="T", detail="D", remediation="R",
            ),
        ]
        score = calculate_risk_score(findings)
        assert score == 3.0

    def test_mixed_severities(self) -> None:
        findings = [
            Finding(check_id="c1", severity=Severity.CRITICAL, title="T", detail="D", remediation="R"),
            Finding(check_id="h1", severity=Severity.HIGH, title="T", detail="D", remediation="R"),
            Finding(check_id="m1", severity=Severity.MEDIUM, title="T", detail="D", remediation="R"),
            Finding(check_id="l1", severity=Severity.LOW, title="T", detail="D", remediation="R"),
            Finding(check_id="i1", severity=Severity.INFO, title="T", detail="D", remediation="R"),
        ]
        score = calculate_risk_score(findings)
        # 3.0 + 2.0 + 1.0 + 0.3 + 0.0 = 6.3
        assert score == 6.3

    def test_max_score_capped_at_10(self) -> None:
        findings = [
            Finding(check_id=f"c{i}", severity=Severity.CRITICAL, title="T", detail="D", remediation="R")
            for i in range(10)
        ]
        score = calculate_risk_score(findings)
        assert score == 10.0

    def test_info_only(self) -> None:
        findings = [
            Finding(check_id="i1", severity=Severity.INFO, title="T", detail="D", remediation="R"),
            Finding(check_id="i2", severity=Severity.INFO, title="T", detail="D", remediation="R"),
        ]
        assert calculate_risk_score(findings) == 0.0

    def test_low_only(self) -> None:
        findings = [
            Finding(check_id="l1", severity=Severity.LOW, title="T", detail="D", remediation="R"),
        ]
        assert calculate_risk_score(findings) == 0.3


class TestFindingsSummary:
    def test_empty(self) -> None:
        result = findings_to_summary([])
        assert "No se encontraron" in result

    def test_with_findings(self) -> None:
        findings = [
            Finding(check_id="c1", severity=Severity.CRITICAL, title="Critical Issue", detail="D", remediation="R"),
            Finding(check_id="h1", severity=Severity.HIGH, title="High Issue", detail="D", remediation="R"),
            Finding(check_id="l1", severity=Severity.LOW, title="Low Issue", detail="D", remediation="R"),
        ]
        result = findings_to_summary(findings)
        assert "3 hallazgos" in result
        assert "CRÍTICO" in result
        assert "ALTO" in result
        assert "Critical Issue" in result
        assert "High Issue" in result

    def test_only_info(self) -> None:
        findings = [
            Finding(check_id="i1", severity=Severity.INFO, title="Info", detail="D", remediation="R"),
        ]
        result = findings_to_summary(findings)
        assert "1 hallazgos" in result
        assert "INFO" in result


class TestMarkdownReport:
    def test_basic_report(self) -> None:
        report = ScanReport(
            target_url="https://example.com",
            scan_duration_secs=5.0,
            risk_score=3.5,
            all_findings=[
                Finding(
                    check_id="h1", severity=Severity.HIGH,
                    title="Missing CSP", detail="No CSP header",
                    remediation="Add CSP header", cwe="CWE-1021",
                ),
            ],
        )
        md = generate_markdown_report(report)
        assert "# Reporte de Seguridad Web" in md
        assert "example.com" in md
        assert "3.5/10" in md
        assert "Missing CSP" in md
        assert "CWE-1021" in md
        assert "SOMER 2.0" in md

    def test_empty_report(self) -> None:
        report = ScanReport(
            target_url="https://example.com",
            scan_duration_secs=1.0,
            risk_score=0.0,
        )
        md = generate_markdown_report(report)
        assert "0.0/10" in md
        assert "Reporte de Seguridad" in md

    def test_with_headers(self) -> None:
        report = ScanReport(
            target_url="https://example.com",
            headers=HeaderAnalysis(
                present={"CSP": "default-src 'self'"},
                missing=["HSTS"],
            ),
        )
        md = generate_markdown_report(report)
        assert "Headers de Seguridad" in md
        assert "CSP" in md
        assert "HSTS" in md

    def test_with_ssl(self) -> None:
        report = ScanReport(
            target_url="https://example.com",
            ssl=SSLAnalysis(
                valid=True,
                issuer="CN=Let's Encrypt",
                protocol="TLSv1.3",
                cipher="AES-256",
                expires="Dec 2027",
            ),
        )
        md = generate_markdown_report(report)
        assert "SSL/TLS" in md
        assert "TLSv1.3" in md

    def test_with_tech(self) -> None:
        report = ScanReport(
            target_url="https://example.com",
            tech=TechFingerprint(
                technologies=[{"name": "nginx", "detected_in": "header"}],
            ),
        )
        md = generate_markdown_report(report)
        assert "Tecnologías" in md
        assert "nginx" in md

    def test_with_ports(self) -> None:
        report = ScanReport(
            target_url="https://example.com",
            ports=PortScanResult(
                open_ports=[OpenPort(port=80, service="HTTP")],
            ),
        )
        md = generate_markdown_report(report)
        assert "Puertos" in md
        assert "80" in md

    def test_recommendations(self) -> None:
        report = ScanReport(
            target_url="https://example.com",
            all_findings=[
                Finding(
                    check_id="c1", severity=Severity.CRITICAL,
                    title="Env exposed", detail="D",
                    remediation="Block .env in web server",
                ),
                Finding(
                    check_id="h1", severity=Severity.HIGH,
                    title="No HSTS", detail="D",
                    remediation="Enable HSTS",
                ),
            ],
        )
        md = generate_markdown_report(report)
        assert "Recomendaciones Prioritarias" in md
        assert "Block .env" in md
        assert "Enable HSTS" in md
