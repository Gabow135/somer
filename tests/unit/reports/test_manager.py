"""Tests para reports/manager.py."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from reports.manager import ReportManager
from reports.types import ReportFormat, ReportRequest, ReportSection


class TestReportManager:
    @pytest.fixture()
    def manager(self, tmp_path: Path) -> ReportManager:
        return ReportManager(reports_dir=tmp_path / "reports")

    @pytest.mark.asyncio
    async def test_generate_md(self, manager: ReportManager) -> None:
        req = ReportRequest(
            title="Test MD",
            format=ReportFormat.MD,
            sections=[ReportSection(heading="Sec1", content="Contenido")],
        )
        result = await manager.generate(req)
        assert result.format == ReportFormat.MD
        assert result.filename.endswith(".md")
        assert Path(result.file_path).exists()
        assert result.size_bytes > 0
        assert result.download_token is not None

    @pytest.mark.asyncio
    async def test_generate_xlsx(self, manager: ReportManager) -> None:
        try:
            import openpyxl  # noqa: F401
        except ImportError:
            pytest.skip("openpyxl no disponible")

        req = ReportRequest(
            title="Test XLSX",
            format=ReportFormat.XLSX,
            sections=[ReportSection(heading="Datos", content="Info")],
        )
        result = await manager.generate(req)
        assert result.format == ReportFormat.XLSX
        assert result.filename.endswith(".xlsx")
        assert Path(result.file_path).exists()

    def test_download_token_roundtrip(self, manager: ReportManager) -> None:
        # Crear un archivo temporal
        test_file = manager._dir / "test.txt"
        test_file.write_text("hello")

        token = manager.register_download(test_file)
        assert token
        assert len(token) == 32  # uuid4().hex

        resolved = manager.resolve_download(token)
        assert resolved is not None
        assert resolved == test_file

    def test_resolve_invalid_token(self, manager: ReportManager) -> None:
        result = manager.resolve_download("nonexistent_token")
        assert result is None

    def test_resolve_deleted_file(self, manager: ReportManager) -> None:
        test_file = manager._dir / "deleted.txt"
        test_file.write_text("temp")
        token = manager.register_download(test_file)
        test_file.unlink()

        result = manager.resolve_download(token)
        assert result is None

    def test_cleanup_old(self, manager: ReportManager) -> None:
        # Crear archivo "viejo"
        old_file = manager._dir / "old_report.md"
        old_file.write_text("viejo")
        # Hacer que parezca viejo (modificar mtime)
        import os
        old_mtime = time.time() - (25 * 3600)  # 25 horas atrás
        os.utime(str(old_file), (old_mtime, old_mtime))

        # Crear archivo "nuevo"
        new_file = manager._dir / "new_report.md"
        new_file.write_text("nuevo")

        removed = manager.cleanup(max_age_hours=24)
        assert removed == 1
        assert not old_file.exists()
        assert new_file.exists()

    def test_cleanup_no_old_files(self, manager: ReportManager) -> None:
        new_file = manager._dir / "recent.md"
        new_file.write_text("reciente")
        removed = manager.cleanup(max_age_hours=24)
        assert removed == 0
        assert new_file.exists()
