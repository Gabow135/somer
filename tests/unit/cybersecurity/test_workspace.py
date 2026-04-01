"""Tests para cybersecurity/workspace.py."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from cybersecurity.types import (
    ExploitEvidence,
    ExploitReport,
    ExploitResult,
    Finding,
    HeaderAnalysis,
    ScanReport,
    Severity,
)
from cybersecurity.workspace import SecurityWorkspace


def _make_scan_report() -> ScanReport:
    """Crea un ScanReport de prueba."""
    return ScanReport(
        target_url="https://example.com",
        scan_duration_secs=5.0,
        headers=HeaderAnalysis(
            present={"X-Content-Type-Options": "nosniff"},
            missing=["X-Frame-Options"],
            findings=[
                Finding(
                    check_id="header-missing-x-frame-options",
                    severity=Severity.MEDIUM,
                    title="X-Frame-Options ausente",
                    detail="El header no está presente",
                    remediation="Añadir X-Frame-Options: DENY",
                ),
            ],
        ),
        risk_score=4.5,
    )


def _make_exploit_result() -> ExploitResult:
    """Crea un ExploitResult de prueba."""
    return ExploitResult(
        exploit_id="poc-clickjacking",
        finding_check_id="header-missing-x-frame-options",
        title="Clickjacking PoC",
        success=True,
        impact_description="Sitio embebible en iframe",
        evidence=[
            ExploitEvidence(
                description="iframe embebido exitosamente",
                screenshot_path="/tmp/test.png",
            ),
        ],
        duration_secs=1.5,
    )


def _make_exploit_report() -> ExploitReport:
    """Crea un ExploitReport de prueba."""
    return ExploitReport(
        target_url="https://example.com",
        total_exploits=2,
        successful=1,
        failed=1,
        results=[_make_exploit_result()],
        workspace_path="/tmp/test",
        duration_secs=5.0,
    )


class TestSecurityWorkspace:
    def test_create_scan_workspace(self, tmp_path: Path) -> None:
        ws = SecurityWorkspace(base_dir=tmp_path)
        ws_path = ws.create_scan_workspace("https://example.com")

        assert ws_path.exists()
        assert ws_path.is_dir()
        assert (ws_path / "exploits").exists()
        assert "example.com" in ws_path.name

    def test_create_scan_workspace_with_port(self, tmp_path: Path) -> None:
        ws = SecurityWorkspace(base_dir=tmp_path)
        ws_path = ws.create_scan_workspace("https://example.com:8080/path")

        assert ws_path.exists()
        assert "example.com" in ws_path.name

    def test_create_scan_workspace_unique(self, tmp_path: Path) -> None:
        ws = SecurityWorkspace(base_dir=tmp_path)
        ws1 = ws.create_scan_workspace("https://example.com")
        # Pequeña pausa para generar timestamp diferente
        import time
        time.sleep(1.1)
        ws2 = ws.create_scan_workspace("https://example.com")
        assert ws1 != ws2

    def test_save_scan_report(self, tmp_path: Path) -> None:
        ws = SecurityWorkspace(base_dir=tmp_path)
        ws_path = ws.create_scan_workspace("https://example.com")
        report = _make_scan_report()

        json_path = ws.save_scan_report(ws_path, report)

        assert json_path.exists()
        assert json_path.name == "scan_report.json"
        data = json.loads(json_path.read_text())
        assert data["target_url"] == "https://example.com"
        assert data["risk_score"] == 4.5

    def test_save_scan_report_md(self, tmp_path: Path) -> None:
        ws = SecurityWorkspace(base_dir=tmp_path)
        ws_path = ws.create_scan_workspace("https://example.com")

        md_path = ws.save_scan_report_md(ws_path, "# Test Report\n\nContent")

        assert md_path.exists()
        assert md_path.name == "scan_report.md"
        assert "# Test Report" in md_path.read_text()

    def test_save_exploit_result(self, tmp_path: Path) -> None:
        ws = SecurityWorkspace(base_dir=tmp_path)
        ws_path = ws.create_scan_workspace("https://example.com")
        result = _make_exploit_result()

        exploit_dir = ws.save_exploit_result(ws_path, result)

        assert exploit_dir.exists()
        assert exploit_dir.is_dir()
        assert exploit_dir.name == "poc-clickjacking"
        result_path = exploit_dir / "result.json"
        assert result_path.exists()
        data = json.loads(result_path.read_text())
        assert data["exploit_id"] == "poc-clickjacking"
        assert data["success"] is True

    def test_save_exploit_report(self, tmp_path: Path) -> None:
        ws = SecurityWorkspace(base_dir=tmp_path)
        ws_path = ws.create_scan_workspace("https://example.com")
        report = _make_exploit_report()

        summary_path = ws.save_exploit_report(ws_path, report)

        assert summary_path.exists()
        assert summary_path.name == "summary.json"
        data = json.loads(summary_path.read_text())
        assert data["total_exploits"] == 2
        assert data["successful"] == 1
        assert data["failed"] == 1

    def test_list_scans_empty(self, tmp_path: Path) -> None:
        ws = SecurityWorkspace(base_dir=tmp_path)
        scans = ws.list_scans()
        assert scans == []

    def test_list_scans(self, tmp_path: Path) -> None:
        ws = SecurityWorkspace(base_dir=tmp_path)
        ws_path = ws.create_scan_workspace("https://example.com")
        report = _make_scan_report()
        ws.save_scan_report(ws_path, report)

        scans = ws.list_scans()

        assert len(scans) == 1
        assert scans[0]["has_scan_report"] is True
        assert scans[0]["has_exploits"] is False
        assert "example.com" in scans[0]["name"]

    def test_list_scans_with_exploits(self, tmp_path: Path) -> None:
        ws = SecurityWorkspace(base_dir=tmp_path)
        ws_path = ws.create_scan_workspace("https://example.com")
        ws.save_exploit_report(ws_path, _make_exploit_report())
        ws.save_exploit_result(ws_path, _make_exploit_result())

        scans = ws.list_scans()

        assert len(scans) == 1
        assert scans[0]["has_exploits"] is True
        assert scans[0]["exploit_count"] == 1

    def test_list_scans_multiple(self, tmp_path: Path) -> None:
        ws = SecurityWorkspace(base_dir=tmp_path)
        ws.create_scan_workspace("https://example.com")
        import time
        time.sleep(1.1)
        ws.create_scan_workspace("https://other.com")

        scans = ws.list_scans()
        assert len(scans) == 2

    def test_extract_domain(self) -> None:
        assert SecurityWorkspace._extract_domain("https://example.com/path") == "example.com"
        assert SecurityWorkspace._extract_domain("https://sub.example.com:8080") == "sub.example.com"
        assert SecurityWorkspace._extract_domain("http://localhost") == "localhost"

    def test_extract_domain_special_chars(self) -> None:
        domain = SecurityWorkspace._extract_domain("https://test site.com")
        # Debería limpiar caracteres no válidos
        assert " " not in domain

    def test_workspace_directory_structure(self, tmp_path: Path) -> None:
        ws = SecurityWorkspace(base_dir=tmp_path)
        ws_path = ws.create_scan_workspace("https://example.com")

        # Verificar estructura completa
        assert (ws_path / "exploits").is_dir()
        assert ws_path.parent.name == "scans"
        assert ws_path.parent.parent == tmp_path
