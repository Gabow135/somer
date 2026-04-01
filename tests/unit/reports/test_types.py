"""Tests para reports/types.py."""

from __future__ import annotations

import pytest

from reports.types import (
    ReportFormat,
    ReportRequest,
    ReportResult,
    ReportSection,
    TableData,
)


class TestReportFormat:
    def test_enum_values(self) -> None:
        assert ReportFormat.MD == "md"
        assert ReportFormat.XLSX == "xlsx"
        assert ReportFormat.PDF == "pdf"

    def test_enum_from_string(self) -> None:
        assert ReportFormat("md") == ReportFormat.MD
        assert ReportFormat("xlsx") == ReportFormat.XLSX
        assert ReportFormat("pdf") == ReportFormat.PDF

    def test_invalid_format(self) -> None:
        with pytest.raises(ValueError):
            ReportFormat("docx")


class TestTableData:
    def test_basic_table(self) -> None:
        table = TableData(headers=["A", "B"], rows=[[1, 2], [3, 4]])
        assert table.headers == ["A", "B"]
        assert len(table.rows) == 2

    def test_empty_table(self) -> None:
        table = TableData(headers=[], rows=[])
        assert table.headers == []
        assert table.rows == []


class TestReportSection:
    def test_minimal(self) -> None:
        s = ReportSection(heading="Titulo")
        assert s.heading == "Titulo"
        assert s.content == ""
        assert s.table is None

    def test_with_table(self) -> None:
        s = ReportSection(
            heading="Datos",
            content="Resumen",
            table=TableData(headers=["X"], rows=[[1]]),
        )
        assert s.table is not None
        assert s.table.headers == ["X"]


class TestReportRequest:
    def test_defaults(self) -> None:
        req = ReportRequest(title="Test")
        assert req.title == "Test"
        assert req.format == ReportFormat.MD
        assert req.sections == []
        assert req.markdown is None

    def test_with_sections(self) -> None:
        req = ReportRequest(
            title="Reporte",
            format=ReportFormat.PDF,
            sections=[
                ReportSection(heading="Intro", content="Texto"),
            ],
        )
        assert req.format == ReportFormat.PDF
        assert len(req.sections) == 1

    def test_with_raw_markdown(self) -> None:
        req = ReportRequest(title="MD", markdown="# Hola\nMundo")
        assert req.markdown == "# Hola\nMundo"


class TestReportResult:
    def test_fields(self) -> None:
        r = ReportResult(
            file_path="/tmp/report.md",
            filename="report.md",
            format=ReportFormat.MD,
            size_bytes=123,
        )
        assert r.file_path == "/tmp/report.md"
        assert r.download_token is None

    def test_with_token(self) -> None:
        r = ReportResult(
            file_path="/tmp/report.pdf",
            filename="report.pdf",
            format=ReportFormat.PDF,
            size_bytes=456,
            download_token="abc123",
        )
        assert r.download_token == "abc123"
