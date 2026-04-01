"""Tests para agents/tools/builtins.py."""

from __future__ import annotations

import json
import os
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.tools.builtins import _http_request_handler, register_builtins
from agents.tools.registry import ToolRegistry


# ── register_builtins ─────────────────────────────────────────


class TestRegisterBuiltins:
    """Tests para register_builtins()."""

    def test_registers_http_request(self) -> None:
        registry = ToolRegistry()
        register_builtins(registry)
        assert "http_request" in registry.tool_names

    def test_http_request_has_handler(self) -> None:
        registry = ToolRegistry()
        register_builtins(registry)
        tool = registry.get("http_request")
        assert tool is not None
        assert tool.handler is not None

    def test_http_request_has_parameters(self) -> None:
        registry = ToolRegistry()
        register_builtins(registry)
        tool = registry.get("http_request")
        assert tool is not None
        props = tool.parameters.get("properties", {})
        assert "method" in props
        assert "url" in props
        assert "headers" in props
        assert "body" in props

    def test_registers_security_tools(self) -> None:
        registry = ToolRegistry()
        register_builtins(registry)
        security_tools = [
            "security_scan", "check_headers", "check_ssl",
            "check_cookies", "discover_tech", "dns_lookup",
            "crawl_links", "scan_ports", "generate_security_report",
            "check_http_methods", "check_https_redirect", "check_sri",
            "check_mixed_content", "check_directory_listing",
            "check_html_leaks", "analyze_csp", "check_email_security",
            "run_security_exploits",
        ]
        for name in security_tools:
            assert name in registry.tool_names, f"Tool {name} no registrada"

    def test_to_provider_format_anthropic(self) -> None:
        registry = ToolRegistry()
        register_builtins(registry)
        defs = registry.to_provider_format("anthropic")
        assert len(defs) == 41  # 1 http + 18 security + 22 pentest/advanced (incl. full_pentest)
        names = [d["name"] for d in defs]
        assert "http_request" in names
        assert "security_scan" in names
        assert "check_http_methods" in names
        assert "analyze_csp" in names
        assert "input_schema" in defs[0]

    def test_to_provider_format_openai(self) -> None:
        registry = ToolRegistry()
        register_builtins(registry)
        defs = registry.to_provider_format("default")
        assert len(defs) == 41  # 1 http + 18 security + 22 pentest/advanced (incl. full_pentest)
        assert defs[0]["type"] == "function"
        names = [d["function"]["name"] for d in defs]
        assert "http_request" in names


# ── _http_request_handler ─────────────────────────────────────


class TestHttpRequestHandler:
    """Tests para el handler HTTP."""

    @pytest.mark.asyncio
    async def test_missing_url(self) -> None:
        result = await _http_request_handler({"method": "GET"})
        assert "Error: url es requerida" in result

    @pytest.mark.asyncio
    async def test_env_var_missing(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            result = await _http_request_handler({
                "method": "GET",
                "url": "https://example.com",
                "headers": {"Authorization": "Bearer $MISSING_KEY"},
            })
            assert "Error: variable de entorno MISSING_KEY" in result

    @pytest.mark.asyncio
    async def test_env_var_resolution(self) -> None:
        """Verifica que $ENV_VAR en headers se resuelve correctamente."""
        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"ok": true}'
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {"ok": True}

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.dict(os.environ, {"TEST_KEY": "secret123"}):
            with patch.object(httpx, "AsyncClient", return_value=mock_client):
                with patch.object(httpx, "Timeout", return_value=30):
                    result = await _http_request_handler({
                        "method": "GET",
                        "url": "https://api.example.com/test",
                        "headers": {"Authorization": "Bearer $TEST_KEY"},
                    })
        assert "200" in result
        # Verificar que el header fue resuelto
        call_kwargs = mock_client.request.call_args.kwargs
        assert call_kwargs["headers"]["Authorization"] == "Bearer secret123"

    @pytest.mark.asyncio
    async def test_default_method_is_get(self) -> None:
        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "ok"
        mock_response.headers = {"content-type": "text/plain"}

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(httpx, "AsyncClient", return_value=mock_client):
            with patch.object(httpx, "Timeout", return_value=30):
                result = await _http_request_handler({"url": "https://example.com"})
        mock_client.request.assert_called_once()
        call_kwargs = mock_client.request.call_args.kwargs
        assert call_kwargs["method"] == "GET"
