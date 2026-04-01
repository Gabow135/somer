"""Tests para el sistema de seguridad."""

from __future__ import annotations

from pathlib import Path

import pytest

from config.schema import (
    ChannelConfig,
    ChannelsConfig,
    GatewayConfig,
    ProviderAuthConfig,
    ProviderSettings,
    SecurityConfig,
    SomerConfig,
)
from security.audit import (
    AuditFinding,
    AuditReport,
    AuditOptions,
    AuditSummary,
    FixResult,
    audit_config,
    audit_credentials_dir,
)
from security.scanner import scan_skill_file, validate_skill_safety
from shared.types import SkillMeta


class TestAuditModels:
    """Tests de modelos Pydantic de auditoría."""

    def test_finding_creation(self) -> None:
        f = AuditFinding(
            check_id="test.check",
            severity="warning",
            title="Test",
            detail="Detail",
        )
        assert f.check_id == "test.check"
        assert f.severity == "warning"
        assert f.auto_fixable is False

    def test_summary_defaults(self) -> None:
        s = AuditSummary()
        assert s.critical == 0
        assert s.warning == 0
        assert s.info == 0

    def test_report_defaults(self) -> None:
        r = AuditReport()
        assert r.findings == []
        assert r.summary.critical == 0
        assert r.deep is None

    def test_fix_result_defaults(self) -> None:
        f = FixResult()
        assert f.ok is True
        assert f.actions == []


class TestSecurityAudit:
    """Tests de auditoría de seguridad."""

    def test_clean_config(self) -> None:
        config = SomerConfig()
        report = audit_config(config)
        assert isinstance(report, AuditReport)
        # Una config limpia no debería tener hallazgos críticos
        # (puede tener warnings/info sobre filesystem)
        critical = [f for f in report.findings if f.severity == "critical"]
        # Sin providers habilitados y gateway en loopback, sin críticos
        config_criticals = [
            f for f in critical
            if not f.check_id.startswith("fs.")
        ]
        assert len(config_criticals) == 0

    def test_literal_api_key_warning(self) -> None:
        config = SomerConfig(
            providers={
                "test": ProviderSettings(
                    auth=ProviderAuthConfig(api_key="sk-literal-key")
                )
            }
        )
        report = audit_config(config)
        api_key_findings = [
            f for f in report.findings
            if "api_key" in f.check_id.lower() or "literal" in f.detail.lower()
        ]
        assert len(api_key_findings) > 0

    def test_exposed_gateway_warning(self) -> None:
        config = SomerConfig(gateway=GatewayConfig(host="0.0.0.0"))
        report = audit_config(config)
        gateway_findings = [
            f for f in report.findings
            if "gateway" in f.check_id and "bind" in f.check_id
        ]
        assert len(gateway_findings) > 0
        assert any(f.severity == "critical" for f in gateway_findings)

    def test_dangerous_skills_disabled_warning(self) -> None:
        config = SomerConfig(
            security=SecurityConfig(block_dangerous_skills=False)
        )
        report = audit_config(config)
        skill_findings = [
            f for f in report.findings
            if "dangerous_skills" in f.check_id
        ]
        assert len(skill_findings) > 0

    def test_channel_group_policy_open(self) -> None:
        config = SomerConfig(
            channels=ChannelsConfig(entries={
                "telegram": ChannelConfig(
                    enabled=True,
                    plugin="channels.telegram",
                    config={"group_policy": "open"},
                )
            })
        )
        report = audit_config(config)
        open_findings = [
            f for f in report.findings
            if "group_policy_open" in f.check_id
        ]
        assert len(open_findings) > 0
        assert open_findings[0].severity == "critical"

    def test_channel_secrets_in_config(self) -> None:
        config = SomerConfig(
            channels=ChannelsConfig(entries={
                "discord": ChannelConfig(
                    enabled=True,
                    plugin="channels.discord",
                    config={"token": "my-secret-token"},
                )
            })
        )
        report = audit_config(config)
        secret_findings = [
            f for f in report.findings
            if "secrets_in_config" in f.check_id
        ]
        assert len(secret_findings) > 0

    def test_wildcard_allowed_hosts(self) -> None:
        config = SomerConfig(
            security=SecurityConfig(allowed_hosts=["*"])
        )
        report = audit_config(config)
        wildcard_findings = [
            f for f in report.findings
            if "wildcard_allowed_host" in f.check_id
        ]
        assert len(wildcard_findings) > 0
        assert wildcard_findings[0].severity == "critical"

    def test_model_hygiene_legacy(self) -> None:
        config = SomerConfig(default_model="gpt-3.5-turbo")
        report = audit_config(config)
        legacy_findings = [
            f for f in report.findings
            if f.check_id == "models.legacy"
        ]
        assert len(legacy_findings) > 0

    def test_model_hygiene_weak_tier(self) -> None:
        config = SomerConfig(fast_model="claude-haiku-4-5-20251001")
        report = audit_config(config)
        weak_findings = [
            f for f in report.findings
            if f.check_id == "models.weak_tier"
        ]
        assert len(weak_findings) > 0

    def test_summary_counts(self) -> None:
        config = SomerConfig(
            gateway=GatewayConfig(host="0.0.0.0"),
            security=SecurityConfig(allowed_hosts=["*"]),
        )
        report = audit_config(config)
        # Debe haber al menos 2 críticos (gateway + wildcard host)
        assert report.summary.critical >= 2

    def test_non_loopback_gateway_info(self) -> None:
        config = SomerConfig(gateway=GatewayConfig(host="192.168.1.100"))
        report = audit_config(config)
        findings = [
            f for f in report.findings
            if "bind_non_loopback" in f.check_id
        ]
        assert len(findings) > 0

    def test_non_standard_port_info(self) -> None:
        config = SomerConfig(gateway=GatewayConfig(port=9999))
        report = audit_config(config)
        findings = [
            f for f in report.findings
            if "non_default_port" in f.check_id
        ]
        assert len(findings) > 0
        assert findings[0].severity == "info"


class TestCredentialsAudit:
    """Tests de auditoría de credenciales."""

    def test_nonexistent_dir(self, tmp_path: Path) -> None:
        findings = audit_credentials_dir(tmp_path / "nonexistent")
        assert len(findings) > 0
        assert any(f.check_id == "credentials.dir_missing" for f in findings)

    def test_secure_permissions(self, tmp_path: Path) -> None:
        creds_dir = tmp_path / "creds"
        creds_dir.mkdir()
        secret = creds_dir / "test.enc"
        secret.write_text("encrypted")
        secret.chmod(0o600)
        creds_dir.chmod(0o700)
        findings = audit_credentials_dir(creds_dir)
        # No debe haber warnings ni criticals
        dangerous = [f for f in findings if f.severity in ("critical", "warning")]
        assert len(dangerous) == 0

    def test_insecure_permissions(self, tmp_path: Path) -> None:
        creds_dir = tmp_path / "creds"
        creds_dir.mkdir()
        secret = creds_dir / "test.enc"
        secret.write_text("encrypted")
        secret.chmod(0o644)
        findings = audit_credentials_dir(creds_dir)
        perm_findings = [
            f for f in findings
            if "file_perms" in f.check_id
        ]
        assert len(perm_findings) > 0


class TestSkillScanner:
    """Tests del scanner de skills."""

    def test_scan_safe_skill(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "safe-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("""---
name: safe
description: A safe skill
---

# Safe Skill

Does nothing dangerous.
""")
        result = scan_skill_file(skill_dir / "SKILL.md")
        assert result.safe
        assert len(result.findings) == 0

    def test_scan_dangerous_skill(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "dangerous"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("""---
name: dangerous
---

# Dangerous Skill

Uses os.system() to execute commands.
Also uses eval() for dynamic code.
""")
        result = scan_skill_file(skill_dir / "SKILL.md")
        assert not result.safe
        assert len(result.findings) >= 2

    def test_scan_nonexistent(self, tmp_path: Path) -> None:
        result = scan_skill_file(tmp_path / "nope" / "SKILL.md")
        assert len(result.findings) > 0


class TestSkillSafetyValidation:
    """Tests de validación de seguridad de skills."""

    def test_api_skill_without_credentials(self) -> None:
        skill = SkillMeta(
            name="unsafe-api",
            tags=["api", "http"],
            required_credentials=[],
        )
        warnings = validate_skill_safety(skill)
        assert len(warnings) > 0

    def test_api_skill_with_credentials(self) -> None:
        skill = SkillMeta(
            name="safe-api",
            tags=["api"],
            required_credentials=["API_KEY"],
        )
        warnings = validate_skill_safety(skill)
        assert len(warnings) == 0

    def test_non_api_skill(self) -> None:
        skill = SkillMeta(name="local", tags=["utility"])
        warnings = validate_skill_safety(skill)
        assert len(warnings) == 0
