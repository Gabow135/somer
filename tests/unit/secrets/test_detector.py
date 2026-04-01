"""Tests para secrets.detector — detección automática de credenciales."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from secrets.detector import CredentialDetector, DetectionReport


class TestPrefixDetection:
    """Detección por prefijo conocido de API keys."""

    def test_detect_anthropic_key(self):
        d = CredentialDetector()
        r = d.scan("aqui va mi key: sk-ant-abcdefghij1234567890xyz")
        assert r.total == 1
        assert r.credentials[0].env_var == "ANTHROPIC_API_KEY"
        assert r.credentials[0].confidence == "high"
        assert r.credentials[0].source == "prefix"

    def test_detect_openai_key(self):
        d = CredentialDetector()
        r = d.scan("mi openai key sk-proj-abcdefghij1234567890abcd")
        assert r.total == 1
        assert r.credentials[0].env_var == "OPENAI_API_KEY"

    def test_detect_github_token(self):
        d = CredentialDetector()
        r = d.scan("github token: ghp_abcdefghij1234567890abcdefghij123456")
        assert r.total == 1
        assert r.credentials[0].env_var == "GITHUB_TOKEN"
        assert r.credentials[0].kind == "token"

    def test_detect_telegram_token(self):
        d = CredentialDetector()
        r = d.scan("bot token: 12345678901:ABCdefGHIjklMNOpqrSTUvwxYZ_abcdefg")
        assert r.total == 1
        assert r.credentials[0].env_var == "TELEGRAM_BOT_TOKEN"

    def test_detect_multiple_prefixes(self):
        d = CredentialDetector()
        text = (
            "anthropic: sk-ant-abcdefghij1234567890xyz "
            "github: ghp_abcdefghij1234567890abcdefghij123456"
        )
        r = d.scan(text)
        assert r.total == 2
        env_vars = {c.env_var for c in r.credentials}
        assert "ANTHROPIC_API_KEY" in env_vars
        assert "GITHUB_TOKEN" in env_vars

    def test_no_false_positive_short_string(self):
        d = CredentialDetector()
        r = d.scan("sk-ant es un prefijo pero sin nada mas")
        assert r.total == 0

    def test_detect_groq_key(self):
        d = CredentialDetector()
        r = d.scan("groq api: gsk_abcdefghijklmnopqrstuvwx")
        assert r.total == 1
        assert r.credentials[0].env_var == "GROQ_API_KEY"

    def test_detect_notion_secret(self):
        d = CredentialDetector()
        r = d.scan("notion: secret_AbcdefghijklmnopqrstuvwxYz0123456789ABCDEF")
        assert r.total == 1
        assert r.credentials[0].env_var == "NOTION_API_KEY"


class TestContextDetection:
    """Detección por contexto (keyword + valor)."""

    def test_trello_api_key_es(self):
        d = CredentialDetector()
        r = d.scan("mi trello api key es abc123def456ghi789")
        found = [c for c in r.credentials if c.env_var == "TRELLO_API_KEY"]
        assert len(found) == 1
        assert found[0].confidence == "medium"
        assert found[0].source == "context"

    def test_trello_token(self):
        d = CredentialDetector()
        r = d.scan("el trello token es ATTA_mytoken123456789abcdef")
        found = [c for c in r.credentials if c.env_var == "TRELLO_TOKEN"]
        assert len(found) == 1

    def test_trello_board_id(self):
        d = CredentialDetector()
        r = d.scan("trello board id es 6abc123def456ghi789012")
        found = [c for c in r.credentials if c.env_var == "TRELLO_BOARD_ID"]
        assert len(found) == 1

    def test_notion_api_key_colon(self):
        d = CredentialDetector()
        r = d.scan("notion api key: ntn_abcdefghij1234567890")
        found = [c for c in r.credentials if c.env_var == "NOTION_API_KEY"]
        assert len(found) == 1

    def test_deepseek_key(self):
        d = CredentialDetector()
        r = d.scan("mi deepseek api key es sk-abc123def456ghi789xyz")
        # Puede detectar por contexto O por prefijo (sk-)
        assert r.total >= 1

    def test_discord_token_context(self):
        d = CredentialDetector()
        r = d.scan("discord bot token: MTIzNDU2Nzg5.abcdef.abcdefghijklmnopqrstuvwxyz0")
        found = [c for c in r.credentials if c.env_var == "DISCORD_TOKEN"]
        assert len(found) >= 1


class TestDirectDetection:
    """Detección directa VARIABLE=valor."""

    def test_direct_equals(self):
        d = CredentialDetector()
        r = d.scan("TRELLO_API_KEY=myapikey12345678")
        found = [c for c in r.credentials if c.env_var == "TRELLO_API_KEY"]
        assert len(found) == 1

    def test_direct_colon(self):
        d = CredentialDetector()
        r = d.scan("TRELLO_TOKEN: mytoken987654321abc")
        found = [c for c in r.credentials if c.env_var == "TRELLO_TOKEN"]
        assert len(found) == 1

    def test_direct_multiple(self):
        d = CredentialDetector()
        text = "TRELLO_API_KEY=key123456789 TRELLO_TOKEN=tok987654321"
        r = d.scan(text)
        env_vars = {c.env_var for c in r.credentials}
        assert "TRELLO_API_KEY" in env_vars
        assert "TRELLO_TOKEN" in env_vars

    def test_direct_with_quotes(self):
        d = CredentialDetector()
        r = d.scan('GITHUB_TOKEN="ghp_abcdefghij1234567890abcdefghij123456"')
        assert r.total >= 1


class TestReport:
    """Tests del DetectionReport."""

    def test_empty_report(self):
        r = DetectionReport()
        assert r.total == 0
        assert r.new_credentials == []
        assert r.existing_credentials == []

    def test_summary_format(self):
        d = CredentialDetector()
        r = d.scan("sk-ant-abcdefghij1234567890xyz")
        summary = r.summary()
        assert "1 credencial(es)" in summary

    def test_masked_value(self):
        d = CredentialDetector()
        r = d.scan("sk-ant-abcdefghij1234567890xyz")
        assert r.credentials[0].masked_value != r.credentials[0].value
        assert "****" in r.credentials[0].masked_value


class TestSkillRequirements:
    """Tests de verificación de requisitos de skills."""

    def test_missing_all(self):
        d = CredentialDetector()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TRELLO_API_KEY", None)
            os.environ.pop("TRELLO_TOKEN", None)
            missing = d.check_skill_requirements(
                ["TRELLO_API_KEY", "TRELLO_TOKEN"]
            )
        assert "TRELLO_API_KEY" in missing
        assert "TRELLO_TOKEN" in missing

    def test_partial_missing(self):
        d = CredentialDetector()
        with patch.dict(os.environ, {"TRELLO_API_KEY": "test123"}, clear=False):
            os.environ.pop("TRELLO_TOKEN", None)
            missing = d.check_skill_requirements(
                ["TRELLO_API_KEY", "TRELLO_TOKEN"]
            )
        assert "TRELLO_API_KEY" not in missing
        assert "TRELLO_TOKEN" in missing


class TestNoDuplicates:
    """Verifica que no se detecten duplicados."""

    def test_no_duplicate_env_var(self):
        d = CredentialDetector()
        # Un texto con el mismo token mencionado dos veces
        text = (
            "TRELLO_API_KEY=abc123def456 y mi trello api key es abc123def456"
        )
        r = d.scan(text)
        trello_keys = [c for c in r.credentials if c.env_var == "TRELLO_API_KEY"]
        assert len(trello_keys) == 1

    def test_prefix_takes_priority_over_context(self):
        d = CredentialDetector()
        text = "mi github token es ghp_abcdefghij1234567890abcdefghij123456"
        r = d.scan(text)
        gh_tokens = [c for c in r.credentials if c.env_var == "GITHUB_TOKEN"]
        assert len(gh_tokens) == 1
        # Prefix detection should fire first (high confidence)
        assert gh_tokens[0].confidence == "high"
