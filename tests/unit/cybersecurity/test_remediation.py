"""Tests para cybersecurity/remediation.py."""

from __future__ import annotations

import pytest

from cybersecurity.remediation import (
    REMEDIATION_DB,
    format_remediation_markdown,
    get_remediation,
    get_remediations_for_findings,
)
from cybersecurity.types import Finding, Severity


class TestGetRemediation:
    def test_get_known_remediation(self) -> None:
        """Buscar una remediación existente retorna la guía."""
        guide = get_remediation("missing_csp")
        assert guide is not None
        assert guide.check_id == "missing_csp"
        assert "CSP" in guide.title

    def test_get_unknown_remediation(self) -> None:
        """Buscar una remediación inexistente retorna None."""
        guide = get_remediation("nonexistent_check_id_xyz")
        assert guide is None


class TestGetRemediationsForFindings:
    def test_filters_by_check_ids(self) -> None:
        """Filtra correctamente remediaciones por check_ids de findings."""
        findings = [
            Finding(
                check_id="header-missing-content-security-policy",
                severity=Severity.HIGH,
                title="CSP faltante",
                detail="No CSP",
                remediation="Agregar CSP",
            ),
            Finding(
                check_id="header-missing-strict-transport-security",
                severity=Severity.HIGH,
                title="HSTS faltante",
                detail="No HSTS",
                remediation="Agregar HSTS",
            ),
            Finding(
                check_id="unknown-check-id",
                severity=Severity.LOW,
                title="Desconocido",
                detail="No mapeado",
                remediation="N/A",
            ),
        ]
        guides = get_remediations_for_findings(findings)
        check_ids = [g.check_id for g in guides]
        assert "missing_csp" in check_ids
        assert "missing_hsts" in check_ids
        # El unknown no debe estar
        assert len(guides) == 2


class TestFormatRemediationMarkdown:
    def test_has_code_blocks(self) -> None:
        """El markdown generado contiene bloques de código."""
        guide = get_remediation("missing_csp")
        assert guide is not None
        md = format_remediation_markdown(guide)
        assert "```" in md
        assert "<details>" in md
        assert guide.title in md


class TestRemediationDBIntegrity:
    def test_all_db_entries_valid(self) -> None:
        """Cada entrada tiene al menos 1 snippet."""
        for guide in REMEDIATION_DB:
            assert len(guide.snippets) >= 1, (
                f"Guía {guide.check_id} no tiene snippets"
            )

    def test_snippets_have_content(self) -> None:
        """Ningún snippet tiene código vacío."""
        for guide in REMEDIATION_DB:
            for snippet in guide.snippets:
                assert snippet.code.strip(), (
                    f"Snippet vacío en {guide.check_id}/{snippet.platform}"
                )
                assert snippet.platform.strip(), (
                    f"Platform vacía en {guide.check_id}"
                )
                assert snippet.language.strip(), (
                    f"Language vacío en {guide.check_id}/{snippet.platform}"
                )
