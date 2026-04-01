"""Tests para agents/tools/report_tools.py."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock

import pytest

from agents.tools.registry import ToolRegistry
from agents.tools.report_tools import register_report_tools
from reports.manager import ReportManager


class _FakeChannelRegistry:
    """Simula un ChannelRegistry con plugins falsos."""

    def __init__(self) -> None:
        self._plugins: Dict[str, Any] = {}

    def add(self, plugin_id: str, plugin: Any) -> None:
        self._plugins[plugin_id] = plugin

    def get(self, plugin_id: str) -> Optional[Any]:
        return self._plugins.get(plugin_id)


class _FakePlugin:
    """Simula un ChannelPlugin con send_file."""

    def __init__(self, succeeds: bool = True) -> None:
        self.send_file = AsyncMock(return_value=succeeds)


@pytest.fixture()
def setup(tmp_path: Path):
    """Setup compartido: registry + manager + report tools."""
    registry = ToolRegistry()
    manager = ReportManager(reports_dir=tmp_path / "reports")
    channels = _FakeChannelRegistry()
    base_url = "http://localhost:18789"
    register_report_tools(registry, channels, manager, base_url)
    return registry, manager, channels, base_url


class TestGenerateReportTool:
    @pytest.mark.asyncio
    async def test_generate_md(self, setup) -> None:
        registry, manager, _, _ = setup
        tool = registry.get("generate_report")
        assert tool is not None
        assert tool.handler is not None

        result_str = await tool.handler({
            "title": "Test Report",
            "format": "md",
            "sections": [
                {"heading": "Intro", "content": "Hello world"},
            ],
        })
        result = json.loads(result_str)
        assert "file_path" in result
        assert result["format"] == "md"
        assert result["size_bytes"] > 0
        assert "download_url" in result
        assert Path(result["file_path"]).exists()

    @pytest.mark.asyncio
    async def test_missing_title(self, setup) -> None:
        registry, _, _, _ = setup
        tool = registry.get("generate_report")
        assert tool is not None and tool.handler is not None

        result_str = await tool.handler({"format": "md"})
        result = json.loads(result_str)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_invalid_format(self, setup) -> None:
        registry, _, _, _ = setup
        tool = registry.get("generate_report")
        assert tool is not None and tool.handler is not None

        result_str = await tool.handler({"title": "X", "format": "docx"})
        result = json.loads(result_str)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_with_table(self, setup) -> None:
        registry, _, _, _ = setup
        tool = registry.get("generate_report")
        assert tool is not None and tool.handler is not None

        result_str = await tool.handler({
            "title": "Tabla Test",
            "format": "md",
            "sections": [{
                "heading": "Data",
                "content": "Numbers:",
                "table": {
                    "headers": ["A", "B"],
                    "rows": [[1, 2], [3, 4]],
                },
            }],
        })
        result = json.loads(result_str)
        assert result["format"] == "md"
        content = Path(result["file_path"]).read_text()
        assert "| A | B |" in content

    @pytest.mark.asyncio
    async def test_auto_delivery_metadata(self, setup) -> None:
        """Verifica que generate_report retorna file_path para auto-delivery."""
        registry, _, _, _ = setup
        tool = registry.get("generate_report")
        assert tool is not None and tool.handler is not None

        result_str = await tool.handler({
            "title": "Auto Delivery",
            "format": "md",
            "sections": [{"heading": "Test", "content": "Content"}],
        })
        result = json.loads(result_str)
        # El orquestador usa file_path para auto-enviar
        assert "file_path" in result
        assert Path(result["file_path"]).exists()
        assert "filename" in result


class TestGetDownloadLinkTool:
    @pytest.mark.asyncio
    async def test_get_link(self, setup) -> None:
        registry, manager, _, base_url = setup
        tool = registry.get("get_download_link")
        assert tool is not None and tool.handler is not None

        test_file = manager._dir / "test.txt"
        test_file.write_text("contenido")

        result_str = await tool.handler({"file_path": str(test_file)})
        result = json.loads(result_str)
        assert "download_url" in result
        assert base_url in result["download_url"]
        assert "test.txt" in result["download_url"]

    @pytest.mark.asyncio
    async def test_missing_file_path(self, setup) -> None:
        registry, _, _, _ = setup
        tool = registry.get("get_download_link")
        assert tool is not None and tool.handler is not None

        result_str = await tool.handler({})
        result = json.loads(result_str)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_nonexistent_file(self, setup) -> None:
        registry, _, _, _ = setup
        tool = registry.get("get_download_link")
        assert tool is not None and tool.handler is not None

        result_str = await tool.handler({"file_path": "/tmp/nonexistent_xyz.pdf"})
        result = json.loads(result_str)
        assert "error" in result


class TestExtractReportFiles:
    """Tests para la extracción de archivos en el orquestador."""

    def test_extract_from_tool_results(self, tmp_path: Path) -> None:
        """Verifica que _extract_report_files detecta archivos generados."""
        from gateway.bootstrap import GatewayBootstrap
        from shared.types import AgentMessage, AgentTurn, Role, ToolResult

        # Crear un archivo simulado
        test_file = tmp_path / "report_test.pdf"
        test_file.write_bytes(b"fake pdf content")

        turn = AgentTurn(model="test")
        turn.messages.append(AgentMessage(
            role=Role.TOOL,
            content="",
            tool_results=[ToolResult(
                tool_call_id="tc1",
                content=json.dumps({
                    "file_path": str(test_file),
                    "filename": "report_test.pdf",
                    "format": "pdf",
                    "size_bytes": 16,
                }),
            )],
        ))

        files = GatewayBootstrap._extract_report_files(turn)
        assert len(files) == 1
        assert files[0]["file_path"] == str(test_file)
        assert files[0]["filename"] == "report_test.pdf"

    def test_extract_ignores_errors(self) -> None:
        """Verifica que tool_results con errores se ignoran."""
        from gateway.bootstrap import GatewayBootstrap
        from shared.types import AgentMessage, AgentTurn, Role, ToolResult

        turn = AgentTurn(model="test")
        turn.messages.append(AgentMessage(
            role=Role.TOOL,
            content="",
            tool_results=[ToolResult(
                tool_call_id="tc1",
                content='{"error": "algo falló"}',
                is_error=True,
            )],
        ))

        files = GatewayBootstrap._extract_report_files(turn)
        assert len(files) == 0

    def test_extract_ignores_non_json(self) -> None:
        """Verifica que resultados no-JSON se ignoran."""
        from gateway.bootstrap import GatewayBootstrap
        from shared.types import AgentMessage, AgentTurn, Role, ToolResult

        turn = AgentTurn(model="test")
        turn.messages.append(AgentMessage(
            role=Role.TOOL,
            content="",
            tool_results=[ToolResult(
                tool_call_id="tc1",
                content="esto no es JSON",
            )],
        ))

        files = GatewayBootstrap._extract_report_files(turn)
        assert len(files) == 0

    def test_extract_ignores_missing_files(self, tmp_path: Path) -> None:
        """Verifica que file_paths inexistentes se ignoran."""
        from gateway.bootstrap import GatewayBootstrap
        from shared.types import AgentMessage, AgentTurn, Role, ToolResult

        turn = AgentTurn(model="test")
        turn.messages.append(AgentMessage(
            role=Role.TOOL,
            content="",
            tool_results=[ToolResult(
                tool_call_id="tc1",
                content=json.dumps({
                    "file_path": str(tmp_path / "no_existe.pdf"),
                    "filename": "no_existe.pdf",
                }),
            )],
        ))

        files = GatewayBootstrap._extract_report_files(turn)
        assert len(files) == 0

    def test_extract_empty_turn(self) -> None:
        """Turn sin tool_results no retorna archivos."""
        from gateway.bootstrap import GatewayBootstrap
        from shared.types import AgentMessage, AgentTurn, Role

        turn = AgentTurn(model="test")
        turn.messages.append(AgentMessage(
            role=Role.ASSISTANT,
            content="Respuesta normal",
        ))

        files = GatewayBootstrap._extract_report_files(turn)
        assert len(files) == 0
