"""Orquestador de generación de reportes y tokens de descarga."""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from shared.errors import ReportGenerationError
from reports.types import ReportFormat, ReportRequest, ReportResult

logger = logging.getLogger(__name__)


class ReportManager:
    """Genera reportes y gestiona tokens de descarga."""

    REPORTS_DIR = Path.home() / ".somer" / "reports"

    def __init__(self, reports_dir: Optional[Path] = None) -> None:
        self._dir = reports_dir or self.REPORTS_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._tokens: Dict[str, Path] = {}  # token -> filepath

    async def generate(self, request: ReportRequest) -> ReportResult:
        """Genera un reporte según el formato solicitado."""
        from reports.generators import generate_excel, generate_markdown, generate_pdf

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        ext_map = {
            ReportFormat.MD: "md",
            ReportFormat.XLSX: "xlsx",
            ReportFormat.PDF: "pdf",
        }
        ext = ext_map[request.format]
        filename = f"report_{timestamp}.{ext}"
        output_path = self._dir / filename

        try:
            if request.format == ReportFormat.MD:
                content = generate_markdown(request)
                output_path.write_text(content, encoding="utf-8")
            elif request.format == ReportFormat.XLSX:
                generate_excel(request, output_path)
            elif request.format == ReportFormat.PDF:
                generate_pdf(request, output_path)
        except ReportGenerationError:
            raise
        except Exception as exc:
            raise ReportGenerationError(
                f"Error generando reporte {request.format.value}: {exc}"
            ) from exc

        size = output_path.stat().st_size
        token = self.register_download(output_path)

        logger.info(
            "Reporte generado: %s (%d bytes, token=%s)",
            filename, size, token[:8],
        )

        return ReportResult(
            file_path=str(output_path),
            filename=filename,
            format=request.format,
            size_bytes=size,
            download_token=token,
        )

    def register_download(self, file_path: Path) -> str:
        """Registra un archivo para descarga y retorna un token."""
        token = uuid.uuid4().hex
        self._tokens[token] = file_path
        return token

    def resolve_download(self, token: str) -> Optional[Path]:
        """Resuelve un token de descarga a una ruta de archivo."""
        path = self._tokens.get(token)
        if path and path.exists():
            return path
        return None

    def cleanup(self, max_age_hours: int = 24) -> int:
        """Elimina archivos de reportes antiguos."""
        cutoff = time.time() - (max_age_hours * 3600)
        removed = 0
        for file in self._dir.iterdir():
            if file.is_file() and file.stat().st_mtime < cutoff:
                file.unlink()
                # Limpiar tokens asociados
                self._tokens = {
                    t: p for t, p in self._tokens.items() if p != file
                }
                removed += 1
        if removed:
            logger.info("Limpiados %d reportes antiguos", removed)
        return removed
