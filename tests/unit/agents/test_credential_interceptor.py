"""Tests para agents/credential_interceptor.py."""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.credential_interceptor import (
    CredentialInterceptor,
    InterceptResult,
    ServiceDefinition,
)


# ── Helpers ───────────────────────────────────────────────────────


def _make_httpx_response(status_code: int = 200, json_data: Any = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    return resp


# ── TestKeyDetection ──────────────────────────────────────────────


class TestKeyDetection:
    """Detecta keys por patrón y contexto."""

    def setup_method(self) -> None:
        self.interceptor = CredentialInterceptor()

    def test_detect_notion_key(self) -> None:
        result = self.interceptor._detect_key(
            "mi api de notion es ntn_4315abcdefghijklmnopqrstuv",
            "mi api de notion es ntn_4315abcdefghijklmnopqrstuv",
        )
        assert result is not None
        svc, key = result
        assert svc.service_id == "notion"
        assert key.startswith("ntn_")

    def test_detect_anthropic_key(self) -> None:
        result = self.interceptor._detect_key(
            "sk-ant-api03-abcdefghijklmnopqrstuv",
            "sk-ant-api03-abcdefghijklmnopqrstuv",
        )
        assert result is not None
        svc, key = result
        assert svc.service_id == "anthropic"

    def test_detect_openai_key(self) -> None:
        result = self.interceptor._detect_key(
            "usa esta key: sk-proj-abcdefghijklmnopqrstuv",
            "usa esta key: sk-proj-abcdefghijklmnopqrstuv",
        )
        assert result is not None
        svc, key = result
        assert svc.service_id == "openai"

    def test_detect_groq_key(self) -> None:
        result = self.interceptor._detect_key(
            "gsk_abcdefghijklmnopqrstuv12345",
            "gsk_abcdefghijklmnopqrstuv12345",
        )
        assert result is not None
        svc, key = result
        assert svc.service_id == "groq"

    def test_detect_telegram_token(self) -> None:
        result = self.interceptor._detect_key(
            "12345678:ABCdefGHIjklMNOpqrsTUVwxyz012345678",
            "12345678:abcdefghijklmnopqrstuvwxyz012345678",
        )
        assert result is not None
        svc, key = result
        assert svc.service_id == "telegram"

    def test_detect_hf_token(self) -> None:
        result = self.interceptor._detect_key(
            "hf_abcdefghijklmnopqrstuv12345",
            "hf_abcdefghijklmnopqrstuv12345",
        )
        assert result is not None
        svc, key = result
        assert svc.service_id == "huggingface"

    def test_detect_deepseek_with_context(self) -> None:
        text = "uso deepseek y la api es sk-abcdef0123456789abcdef0123456789"
        result = self.interceptor._detect_key(text, text.lower())
        assert result is not None
        svc, key = result
        assert svc.service_id == "deepseek"

    def test_no_key_in_text(self) -> None:
        result = self.interceptor._detect_key(
            "hola, quiero hablar contigo",
            "hola, quiero hablar contigo",
        )
        assert result is None

    def test_no_false_positive_short_string(self) -> None:
        result = self.interceptor._detect_key("sk-abc", "sk-abc")
        assert result is None


# ── TestServiceIntent ─────────────────────────────────────────────


class TestServiceIntent:
    """Detecta intención de configurar un servicio sin key."""

    def setup_method(self) -> None:
        self.interceptor = CredentialInterceptor()

    def test_intent_notion(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            result = self.interceptor._detect_intent("quiero usar notion")
            assert result is not None
            assert result.service_id == "notion"

    def test_intent_openai(self) -> None:
        result = self.interceptor._detect_intent("configurar openai")
        assert result is not None
        assert result.service_id == "openai"

    def test_no_intent_without_phrase(self) -> None:
        result = self.interceptor._detect_intent("notion es genial")
        assert result is None

    def test_no_intent_random_text(self) -> None:
        result = self.interceptor._detect_intent("que hora es")
        assert result is None

    def test_intent_skipped_when_key_already_configured(self) -> None:
        """Si NOTION_API_KEY ya está en env, no intercepta 'quiero usar notion'."""
        with patch.dict(os.environ, {"NOTION_API_KEY": "ntn_already_set"}):
            result = self.interceptor._detect_intent("quiero usar notion")
            assert result is None

    def test_intent_detected_when_key_not_configured(self) -> None:
        """Sin NOTION_API_KEY en env, sí intercepta."""
        with patch.dict(os.environ, {}, clear=True):
            result = self.interceptor._detect_intent("quiero usar notion")
            assert result is not None
            assert result.service_id == "notion"

    def test_intent_skipped_for_empty_key(self) -> None:
        """Key vacía o solo espacios no cuenta como configurada."""
        with patch.dict(os.environ, {"NOTION_API_KEY": "  "}, clear=True):
            result = self.interceptor._detect_intent("quiero usar notion")
            assert result is not None
            assert result.service_id == "notion"


# ── TestIntercept (async) ─────────────────────────────────────────


class TestIntercept:
    """Flujo completo async del interceptor."""

    def setup_method(self) -> None:
        self.interceptor = CredentialInterceptor()

    @pytest.mark.asyncio
    async def test_key_found_and_verified(self) -> None:
        with patch("infra.env.save_env_var"), \
             patch.object(
                 CredentialInterceptor, "_verify_service",
                 new_callable=AsyncMock,
                 return_value=(True, "Bot: SOMER"),
             ):
            result = await self.interceptor.intercept(
                "mi notion key: ntn_4315abcdefghijklmnopqrstuv"
            )
        assert result.intercepted is True
        assert result.key_saved is True
        assert result.key_verified is True
        assert result.service_id == "notion"
        assert "Listo" in result.response

    @pytest.mark.asyncio
    async def test_key_found_verify_fails(self) -> None:
        with patch("infra.env.save_env_var"), \
             patch.object(
                 CredentialInterceptor, "_verify_service",
                 new_callable=AsyncMock,
                 return_value=(False, "HTTP 401"),
             ):
            result = await self.interceptor.intercept(
                "ntn_4315abcdefghijklmnopqrstuv"
            )
        assert result.intercepted is True
        assert result.key_saved is True
        assert result.key_verified is False
        assert "no pude verificar" in result.response

    @pytest.mark.asyncio
    async def test_intent_without_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            result = await self.interceptor.intercept("quiero usar notion")
            assert result.intercepted is True
            assert result.service_id == "notion"
            assert "necesito tu API key" in result.response

    @pytest.mark.asyncio
    async def test_no_match(self) -> None:
        result = await self.interceptor.intercept("hola, como estas?")
        assert result.intercepted is False

    @pytest.mark.asyncio
    async def test_intent_not_intercepted_when_key_configured(self) -> None:
        """Flujo completo: 'quiero usar notion' no se intercepta si key ya está."""
        with patch.dict(os.environ, {"NOTION_API_KEY": "ntn_already_configured"}):
            result = await self.interceptor.intercept("quiero usar notion para listar tareas")
        assert result.intercepted is False

    @pytest.mark.asyncio
    async def test_verify_exception_still_saves(self) -> None:
        with patch("infra.env.save_env_var") as mock_save, \
             patch.object(
                 CredentialInterceptor, "_verify_service",
                 new_callable=AsyncMock,
                 side_effect=Exception("network error"),
             ):
            result = await self.interceptor.intercept(
                "ntn_4315abcdefghijklmnopqrstuv"
            )
        assert result.intercepted is True
        assert result.key_saved is True
        assert result.key_verified is False
        mock_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_text(self) -> None:
        result = await self.interceptor.intercept("")
        assert result.intercepted is False

    @pytest.mark.asyncio
    async def test_short_text(self) -> None:
        result = await self.interceptor.intercept("hola")
        assert result.intercepted is False


# ── TestVerification (mocked httpx) ──────────────────────────────


class TestVerification:
    """Verificación de servicios con httpx mockeado."""

    def setup_method(self) -> None:
        self.interceptor = CredentialInterceptor()

    @pytest.mark.asyncio
    async def test_verify_notion_ok(self) -> None:
        user_resp = _make_httpx_response(200, {
            "name": "SOMER",
            "bot": {"owner": {"user": {"name": "Gabriel"}}},
        })
        search_resp = _make_httpx_response(200, {
            "results": [
                {"title": [{"plain_text": "Tareas"}]},
                {"title": [{"plain_text": "Notas"}]},
            ],
        })

        mock_client = AsyncMock()
        mock_client.get.return_value = user_resp
        mock_client.post.return_value = search_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            ok, details = await self.interceptor._verify_notion(
                "ntn_test", "https://api.notion.com", MagicMock()
            )
        assert ok is True
        assert "SOMER" in details
        assert "Gabriel" in details
        assert "2 base(s)" in details

    @pytest.mark.asyncio
    async def test_verify_notion_401(self) -> None:
        mock_client = AsyncMock()
        mock_client.get.return_value = _make_httpx_response(401)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            ok, details = await self.interceptor._verify_notion(
                "ntn_bad", "https://api.notion.com", MagicMock()
            )
        assert ok is False
        assert "401" in details

    @pytest.mark.asyncio
    async def test_verify_openai_compat_ok(self) -> None:
        mock_client = AsyncMock()
        mock_client.get.return_value = _make_httpx_response(200, {
            "data": [{"id": "gpt-4o"}, {"id": "gpt-4o-mini"}],
        })
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            ok, details = await self.interceptor._verify_openai_compat(
                "sk-test", "https://api.openai.com", MagicMock()
            )
        assert ok is True
        assert "2 modelo(s)" in details

    @pytest.mark.asyncio
    async def test_verify_telegram_ok(self) -> None:
        mock_client = AsyncMock()
        mock_client.get.return_value = _make_httpx_response(200, {
            "ok": True,
            "result": {"first_name": "SOMER", "username": "somer_bot"},
        })
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            ok, details = await self.interceptor._verify_telegram(
                "123456789:ABCdef", MagicMock()
            )
        assert ok is True
        assert "SOMER" in details
        assert "@somer_bot" in details


# ── TestResponseFormatting ────────────────────────────────────────


class TestResponseFormatting:
    """Formato de respuestas en español."""

    def setup_method(self) -> None:
        self.interceptor = CredentialInterceptor()
        self.svc = ServiceDefinition(
            service_id="notion",
            display_name="Notion",
            env_var="NOTION_API_KEY",
            key_pattern=r"ntn_[A-Za-z0-9]{20,}",
            verify_url="https://api.notion.com",
            verify_type="notion",
            context_clues=["notion"],
        )

    def test_format_key_verified_ok(self) -> None:
        resp = self.interceptor._format_key_response(
            self.svc, "ntn_4315abcdefghijklmnopqrstuv",
            saved=True, verified=True, details="Bot: SOMER",
        )
        assert "Listo" in resp
        assert "configurado" in resp
        assert "Bot: SOMER" in resp
        assert "Puedes pedirme" in resp

    def test_format_key_verify_failed(self) -> None:
        resp = self.interceptor._format_key_response(
            self.svc, "ntn_4315abcdefghijklmnopqrstuv",
            saved=True, verified=False, details="HTTP 401",
        )
        assert "no pude verificar" in resp

    def test_format_key_save_failed(self) -> None:
        resp = self.interceptor._format_key_response(
            self.svc, "ntn_4315abcdefghijklmnopqrstuv",
            saved=False, verified=False, details="",
        )
        assert "No pude guardar" in resp

    def test_format_intent_response(self) -> None:
        resp = self.interceptor._format_intent_response(self.svc)
        assert "necesito tu API key" in resp
        assert "ntn_" in resp

    def test_mask_key_long(self) -> None:
        masked = self.interceptor._mask_key("ntn_4315abcdefghijklmnopqrstuv")
        assert masked.startswith("ntn_4315")
        assert masked.endswith("stuv")
        assert "..." in masked

    def test_mask_key_short(self) -> None:
        masked = self.interceptor._mask_key("ntn_abc")
        assert masked == "ntn_..."
