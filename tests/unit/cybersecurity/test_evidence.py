"""Tests para cybersecurity/evidence.py."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cybersecurity.evidence import EvidenceManager
from cybersecurity.types import (
    EvidenceChain,
    ExploitCategory,
    ExploitResult,
    Finding,
    PentestPhase,
    RequestLog,
    Severity,
)


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "test_workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def evidence_manager(tmp_workspace: Path) -> EvidenceManager:
    return EvidenceManager(tmp_workspace)


class TestEvidenceManagerInit:
    def test_creates_dirs(self, tmp_workspace: Path) -> None:
        em = EvidenceManager(tmp_workspace)
        assert (tmp_workspace / "evidence").exists()
        assert (tmp_workspace / "evidence" / "screenshots").exists()
        assert (tmp_workspace / "evidence" / "http_logs").exists()


class TestLogHttpExchange:
    def test_creates_log(self, evidence_manager: EvidenceManager) -> None:
        log = evidence_manager.log_http_exchange(
            method="GET",
            url="https://example.com/test",
            response_status=200,
            response_body="OK",
        )
        assert isinstance(log, RequestLog)
        assert log.method == "GET"
        assert log.url == "https://example.com/test"
        assert log.response_status == 200

    def test_saves_to_file(self, evidence_manager: EvidenceManager, tmp_workspace: Path) -> None:
        evidence_manager.log_http_exchange(
            method="POST",
            url="https://example.com/api",
            headers={"Content-Type": "application/json"},
            body='{"key": "value"}',
            response_status=201,
        )
        log_dir = tmp_workspace / "evidence" / "http_logs"
        log_files = list(log_dir.glob("*.json"))
        assert len(log_files) > 0

    def test_truncates_long_body(self, evidence_manager: EvidenceManager) -> None:
        long_body = "x" * 5000
        log = evidence_manager.log_http_exchange(
            method="GET",
            url="https://example.com",
            response_body=long_body,
        )
        assert log.response_body is not None
        assert len(log.response_body) == 2000


class TestExtractAndRedact:
    def test_redacts_passwords(self) -> None:
        data = "DB_PASSWORD=supersecret123\nAPI_KEY=abcdef123456"
        redacted, summary = EvidenceManager.extract_and_redact(data)
        assert "supersecret123" not in redacted
        assert "abcdef123456" not in redacted
        assert "****" in redacted
        assert "sensible" in summary.lower() or "coincidencia" in summary.lower()

    def test_redacts_emails(self) -> None:
        data = "Contact: admin@example.com for support"
        redacted, summary = EvidenceManager.extract_and_redact(data)
        assert "[EMAIL]" in redacted
        assert "admin@example.com" not in redacted

    def test_redacts_card_numbers(self) -> None:
        data = "Card: 4111-1111-1111-1111"
        redacted, summary = EvidenceManager.extract_and_redact(data)
        assert "[CARD_NUMBER]" in redacted

    def test_redacts_ssn(self) -> None:
        data = "SSN: 123-45-6789"
        redacted, summary = EvidenceManager.extract_and_redact(data)
        assert "[SSN]" in redacted

    def test_no_sensitive_data(self) -> None:
        data = "Normal text without anything sensitive"
        redacted, summary = EvidenceManager.extract_and_redact(data)
        assert redacted == data
        assert "No se encontró" in summary

    def test_custom_patterns(self) -> None:
        data = "Custom ID: ABC-12345-XYZ"
        redacted, summary = EvidenceManager.extract_and_redact(
            data, patterns=[r"ABC-\d+-XYZ"]
        )
        assert "[REDACTED]" in redacted


class TestBuildChain:
    def test_empty_chain(self, evidence_manager: EvidenceManager) -> None:
        chain = evidence_manager.build_chain([], [], "https://example.com")
        assert isinstance(chain, EvidenceChain)
        assert chain.target_url == "https://example.com"
        assert len(chain.links) == 0

    def test_chain_with_findings(self, evidence_manager: EvidenceManager) -> None:
        findings = [
            Finding(
                check_id="header-missing-csp",
                severity=Severity.HIGH,
                title="CSP Missing",
                detail="No CSP",
                remediation="Add CSP",
            ),
        ]
        chain = evidence_manager.build_chain(findings, [], "https://example.com")
        assert len(chain.links) == 1
        assert chain.links[0].phase == PentestPhase.SCAN

    def test_chain_with_exploits(self, evidence_manager: EvidenceManager) -> None:
        exploits = [
            ExploitResult(
                exploit_id="poc-test",
                finding_check_id="test-1",
                title="Test PoC",
                success=True,
                impact_description="Impact described",
            ),
        ]
        chain = evidence_manager.build_chain([], exploits, "https://example.com")
        assert len(chain.links) == 1
        assert chain.links[0].phase == PentestPhase.EXPLOIT
        assert chain.links[0].data_ref == "poc-test"

    def test_chain_saved_to_file(
        self, evidence_manager: EvidenceManager, tmp_workspace: Path
    ) -> None:
        evidence_manager.build_chain([], [], "https://example.com")
        chain_path = tmp_workspace / "evidence" / "chain.json"
        assert chain_path.exists()
        data = json.loads(chain_path.read_text())
        assert data["target_url"] == "https://example.com"


class TestExportPackage:
    def test_creates_zip(self, evidence_manager: EvidenceManager, tmp_workspace: Path) -> None:
        # Create some files
        (tmp_workspace / "test.json").write_text('{"key": "value"}')
        (tmp_workspace / "evidence" / "chain.json").write_text('{"links": []}')

        zip_path = evidence_manager.export_package()
        assert zip_path is not None
        assert Path(zip_path).exists()
        assert zip_path.endswith(".zip")

    def test_zip_contains_files(
        self, evidence_manager: EvidenceManager, tmp_workspace: Path
    ) -> None:
        (tmp_workspace / "plan.json").write_text('{"target": "test"}')
        zip_path = evidence_manager.export_package()

        import zipfile
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            assert "plan.json" in names


class TestCaptureScreenshot:
    @pytest.mark.asyncio
    async def test_no_browser(self, evidence_manager: EvidenceManager) -> None:
        result = await evidence_manager.capture_screenshot("https://example.com", None)
        assert result is None

    @pytest.mark.asyncio
    async def test_browser_error(self, evidence_manager: EvidenceManager) -> None:
        browser = AsyncMock()
        browser.navigate = AsyncMock(side_effect=Exception("Browser error"))
        result = await evidence_manager.capture_screenshot("https://example.com", browser)
        assert result is None
