"""Tipos del sistema de reportes."""

from __future__ import annotations

from enum import Enum
from typing import Any, List, Optional

from pydantic import BaseModel


class ReportFormat(str, Enum):
    """Formatos de reporte soportados."""

    MD = "md"
    XLSX = "xlsx"
    PDF = "pdf"


class TableData(BaseModel):
    """Datos tabulares para una sección de reporte."""

    headers: List[str]
    rows: List[List[Any]]


class ReportSection(BaseModel):
    """Sección individual de un reporte."""

    heading: str
    content: str = ""
    table: Optional[TableData] = None


class ReportRequest(BaseModel):
    """Solicitud de generación de reporte."""

    title: str
    sections: List[ReportSection] = []
    format: ReportFormat = ReportFormat.MD
    markdown: Optional[str] = None


class ReportResult(BaseModel):
    """Resultado de una generación de reporte."""

    file_path: str
    filename: str
    format: ReportFormat
    size_bytes: int
    download_token: Optional[str] = None
