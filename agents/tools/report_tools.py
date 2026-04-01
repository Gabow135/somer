"""Tools de generación y entrega de reportes para agentes.

Arquitectura:
- ``generate_report`` genera el archivo y retorna file_path.
- El orquestador (bootstrap) detecta el file_path en tool_results
  y envía el archivo automáticamente por el canal del usuario.
- ``get_download_link`` genera un link HTTP de descarga temporal
  para casos donde el usuario lo solicita explícitamente.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from agents.tools.registry import ToolDefinition, ToolRegistry, ToolSection

logger = logging.getLogger(__name__)


def register_report_tools(
    registry: ToolRegistry,
    channel_plugins: Any,
    report_manager: Any,
    base_url: str,
) -> None:
    """Registra las tools de reportes en el registry."""

    async def _generate_report_handler(args: Dict[str, Any]) -> str:
        """Genera un reporte en el formato solicitado.

        El orquestador se encarga de enviar el archivo al canal
        automáticamente — el agente solo necesita llamar esta tool.
        """
        from reports.types import ReportFormat, ReportRequest, ReportSection, TableData

        title = args.get("title", "")
        if not title:
            return json.dumps({"error": "title es requerido"})

        fmt = args.get("format", "md")
        try:
            report_format = ReportFormat(fmt)
        except ValueError:
            return json.dumps({"error": f"Formato no soportado: {fmt}. Usa md, xlsx o pdf"})

        raw_sections = args.get("sections", [])
        sections = []
        for s in raw_sections:
            table = None
            if s.get("table"):
                table = TableData(
                    headers=s["table"].get("headers", []),
                    rows=s["table"].get("rows", []),
                )
            sections.append(ReportSection(
                heading=s.get("heading", ""),
                content=s.get("content", ""),
                table=table,
            ))

        request = ReportRequest(
            title=title,
            sections=sections,
            format=report_format,
            markdown=args.get("markdown"),
        )

        result = await report_manager.generate(request)

        download_url = ""
        if result.download_token:
            download_url = f"{base_url}/reports/{result.download_token}/{result.filename}"

        return json.dumps({
            "file_path": result.file_path,
            "filename": result.filename,
            "format": result.format.value,
            "size_bytes": result.size_bytes,
            "download_url": download_url,
        })

    async def _get_download_link_handler(args: Dict[str, Any]) -> str:
        """Genera un link de descarga HTTP temporal para un archivo."""
        from pathlib import Path

        file_path = args.get("file_path", "")
        if not file_path:
            return json.dumps({"error": "file_path es requerido"})

        path = Path(file_path)
        if not path.exists():
            return json.dumps({"error": f"Archivo no encontrado: {file_path}"})

        token = report_manager.register_download(path)
        filename = path.name
        url = f"{base_url}/reports/{token}/{filename}"
        return json.dumps({"download_url": url, "filename": filename})

    # ── generate_report ───────────────────────────────────────
    registry.register(ToolDefinition(
        id="generate_report",
        name="generate_report",
        description=(
            "Genera un reporte profesional en Markdown, Excel o PDF. "
            "Estructura el contenido en secciones con texto y tablas opcionales. "
            "El archivo se envía automáticamente al usuario por el canal actual. "
            "Solo necesitas llamar esta tool una vez — no necesitas enviar el archivo manualmente."
        ),
        parameters={
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Título del reporte",
                },
                "format": {
                    "type": "string",
                    "enum": ["md", "xlsx", "pdf"],
                    "description": "Formato del reporte (default: md)",
                },
                "sections": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "heading": {
                                "type": "string",
                                "description": "Título de la sección",
                            },
                            "content": {
                                "type": "string",
                                "description": "Texto de la sección",
                            },
                            "table": {
                                "type": "object",
                                "properties": {
                                    "headers": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "rows": {
                                        "type": "array",
                                        "items": {
                                            "type": "array",
                                            "items": {},
                                        },
                                    },
                                },
                                "description": "Datos tabulares opcionales",
                            },
                        },
                    },
                    "description": "Secciones del reporte",
                },
                "markdown": {
                    "type": "string",
                    "description": "Markdown crudo como fallback si no hay sections",
                },
            },
            "required": ["title"],
        },
        handler=_generate_report_handler,
        section=ToolSection.RUNTIME,
        timeout_secs=60.0,
    ))

    # ── get_download_link ─────────────────────────────────────
    registry.register(ToolDefinition(
        id="get_download_link",
        name="get_download_link",
        description=(
            "Genera un link de descarga HTTP temporal para un archivo ya generado. "
            "Usa esta tool solo cuando el usuario pida explícitamente un link de descarga "
            "en vez de recibir el archivo directamente."
        ),
        parameters={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Ruta al archivo generado por generate_report",
                },
            },
            "required": ["file_path"],
        },
        handler=_get_download_link_handler,
        section=ToolSection.RUNTIME,
        timeout_secs=10.0,
    ))

    logger.debug("Report tools registradas: generate_report, get_download_link")
