"""Tests para los tipos extendidos de cybersecurity/types.py."""

from __future__ import annotations

from typing import List

import pytest

from cybersecurity.types import (
    EvidenceChain,
    EvidenceChainLink,
    ExploitCategory,
    ExploitEvidence,
    ExploitResult,
    Finding,
    JWTAnalysisResult,
    PentestPhase,
    PentestPlan,
    PhaseResult,
    RequestLog,
    Severity,
    SubdomainResult,
    WAFDetectionResult,
)


class TestExploitCategory:
    def test_values(self) -> None:
        assert ExploitCategory.INJECTION == "injection"
        assert ExploitCategory.AUTH == "authentication"
        assert ExploitCategory.SESSION == "session"
        assert ExploitCategory.CRYPTO == "cryptography"
        assert ExploitCategory.DISCLOSURE == "information-disclosure"
        assert ExploitCategory.MISCONFIGURATION == "misconfiguration"
        assert ExploitCategory.INPUT_VALIDATION == "input-validation"


class TestPentestPhase:
    def test_values(self) -> None:
        assert PentestPhase.RECON == "recon"
        assert PentestPhase.SCAN == "scan"
        assert PentestPhase.EXPLOIT == "exploit"
        assert PentestPhase.EVIDENCE == "evidence"
        assert PentestPhase.REPORT == "report"


class TestRequestLog:
    def test_defaults(self) -> None:
        log = RequestLog()
        assert log.method == "GET"
        assert log.url == ""
        assert log.response_status == 0
        assert log.timestamp  # auto-generated

    def test_full(self) -> None:
        log = RequestLog(
            method="POST",
            url="https://example.com/api",
            request_headers={"Content-Type": "application/json"},
            request_body='{"key": "value"}',
            response_status=200,
            response_headers={"X-Custom": "header"},
            response_body="OK",
        )
        assert log.method == "POST"
        assert log.response_status == 200

    def test_serialization(self) -> None:
        log = RequestLog(method="GET", url="https://x.com")
        data = log.model_dump()
        restored = RequestLog.model_validate(data)
        assert restored.method == "GET"
        assert restored.url == "https://x.com"


class TestEvidenceChain:
    def test_empty_chain(self) -> None:
        chain = EvidenceChain(target_url="https://example.com")
        assert chain.target_url == "https://example.com"
        assert chain.links == []
        assert chain.created_at

    def test_chain_with_links(self) -> None:
        chain = EvidenceChain(
            target_url="https://example.com",
            links=[
                EvidenceChainLink(
                    phase=PentestPhase.SCAN,
                    source_id="header-missing-csp",
                    description="CSP ausente",
                ),
                EvidenceChainLink(
                    phase=PentestPhase.EXPLOIT,
                    source_id="poc-missing-csp",
                    description="CSP explotado",
                    data_ref="poc-missing-csp",
                ),
            ],
        )
        assert len(chain.links) == 2
        assert chain.links[0].phase == PentestPhase.SCAN
        assert chain.links[1].data_ref == "poc-missing-csp"


class TestSubdomainResult:
    def test_defaults(self) -> None:
        sub = SubdomainResult(subdomain="api.example.com")
        assert sub.subdomain == "api.example.com"
        assert sub.source == ""
        assert sub.resolves is False
        assert sub.ip is None

    def test_full(self) -> None:
        sub = SubdomainResult(
            subdomain="api.example.com",
            source="crt.sh",
            resolves=True,
            ip="1.2.3.4",
        )
        assert sub.resolves is True
        assert sub.ip == "1.2.3.4"


class TestWAFDetectionResult:
    def test_defaults(self) -> None:
        waf = WAFDetectionResult()
        assert waf.detected is False
        assert waf.waf_name == ""
        assert waf.confidence == "low"
        assert waf.bypass_suggestions == []

    def test_detected(self) -> None:
        waf = WAFDetectionResult(
            detected=True,
            waf_name="Cloudflare",
            confidence="high",
            bypass_suggestions=["Use URL encoding"],
        )
        assert waf.detected is True
        assert waf.waf_name == "Cloudflare"


class TestJWTAnalysisResult:
    def test_defaults(self) -> None:
        jwt = JWTAnalysisResult()
        assert jwt.token_found is False
        assert jwt.algorithm == ""
        assert jwt.weaknesses == []

    def test_with_weaknesses(self) -> None:
        jwt = JWTAnalysisResult(
            token_found=True,
            algorithm="none",
            weaknesses=["Algorithm 'none'"],
            findings=[Finding(
                check_id="jwt-alg-none",
                severity=Severity.CRITICAL,
                title="JWT alg none",
                detail="Alg none",
                remediation="Fix",
            )],
        )
        assert len(jwt.weaknesses) == 1
        assert len(jwt.findings) == 1


class TestPhaseResult:
    def test_defaults(self) -> None:
        pr = PhaseResult(phase=PentestPhase.RECON)
        assert pr.phase == PentestPhase.RECON
        assert pr.success is False
        assert pr.duration_secs == 0.0
        assert pr.data == {}
        assert pr.error is None

    def test_successful(self) -> None:
        pr = PhaseResult(
            phase=PentestPhase.SCAN,
            success=True,
            duration_secs=5.3,
            findings_count=15,
            data={"report": "data"},
        )
        assert pr.success is True
        assert pr.findings_count == 15


class TestPentestPlan:
    def test_defaults(self) -> None:
        plan = PentestPlan(target_url="https://example.com")
        assert plan.target_url == "https://example.com"
        assert plan.scope == "full"
        assert len(plan.phases) == 5
        assert PentestPhase.RECON in plan.phases
        assert plan.created_at

    def test_custom(self) -> None:
        plan = PentestPlan(
            target_url="https://example.com",
            hostname="example.com",
            scope="quick",
            phases=[PentestPhase.RECON, PentestPhase.SCAN],
        )
        assert plan.scope == "quick"
        assert len(plan.phases) == 2


class TestExtendedExploitEvidence:
    def test_new_fields(self) -> None:
        ev = ExploitEvidence(
            description="Test",
            request_log=RequestLog(method="GET", url="https://x.com"),
            data_extracted="sensitive data",
            redacted_data="[REDACTED]",
        )
        assert ev.request_log is not None
        assert ev.request_log.method == "GET"
        assert ev.data_extracted == "sensitive data"
        assert ev.redacted_data == "[REDACTED]"

    def test_backward_compatible(self) -> None:
        # Old-style evidence without new fields
        ev = ExploitEvidence(
            description="Old style",
            screenshot_path="/tmp/ss.png",
            response_data="data",
            http_status=200,
        )
        assert ev.request_log is None
        assert ev.data_extracted is None


class TestExtendedExploitResult:
    def test_new_fields(self) -> None:
        result = ExploitResult(
            exploit_id="poc-test",
            finding_check_id="test-1",
            title="Test",
            category=ExploitCategory.INJECTION,
            cvss_estimate=9.8,
        )
        assert result.category == ExploitCategory.INJECTION
        assert result.cvss_estimate == 9.8
        assert result.evidence_chain is None

    def test_backward_compatible(self) -> None:
        result = ExploitResult(
            exploit_id="poc-old",
            finding_check_id="old-1",
            title="Old",
        )
        assert result.category is None
        assert result.cvss_estimate is None
