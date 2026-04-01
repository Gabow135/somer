"""Workspace de seguridad — gestión de almacenamiento de escaneos y exploits.

Estructura:
~/.somer/security/
  scans/
    {domain}_{YYYYMMDD_HHMMSS}/
      scan_report.json       # ScanReport completo
      scan_report.md         # Reporte Markdown
      exploits/
        {exploit_id}/
          result.json        # ExploitResult
          screenshot_*.png   # Capturas
      summary.json           # ExploitReport
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from shared.constants import DEFAULT_HOME

logger = logging.getLogger(__name__)

SECURITY_DIR = DEFAULT_HOME / "security"


class SecurityWorkspace:
    """Gestiona el workspace de escaneos de seguridad."""

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        self._base = base_dir or SECURITY_DIR
        self._scans_dir = self._base / "scans"

    def create_scan_workspace(self, target_url: str) -> Path:
        """Crea directorio para un nuevo escaneo.

        Args:
            target_url: URL del sitio escaneado.

        Returns:
            Path al directorio creado.
        """
        domain = self._extract_domain(target_url)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        ws_name = f"{domain}_{timestamp}"

        ws_path = self._scans_dir / ws_name
        ws_path.mkdir(parents=True, exist_ok=True)
        (ws_path / "exploits").mkdir(exist_ok=True)
        (ws_path / "recon").mkdir(exist_ok=True)
        (ws_path / "evidence").mkdir(exist_ok=True)
        (ws_path / "evidence" / "screenshots").mkdir(exist_ok=True)
        (ws_path / "evidence" / "http_logs").mkdir(exist_ok=True)

        logger.info("Workspace de seguridad creado: %s", ws_path)
        return ws_path

    def save_scan_report(self, ws_path: Path, report: Any) -> Path:
        """Guarda reporte de escaneo en JSON.

        Args:
            ws_path: Directorio del workspace.
            report: ScanReport a guardar.

        Returns:
            Path al archivo JSON guardado.
        """
        json_path = ws_path / "scan_report.json"
        json_path.write_text(
            report.model_dump_json(indent=2),
            encoding="utf-8",
        )
        logger.debug("Scan report guardado en %s", json_path)
        return json_path

    def save_scan_report_md(self, ws_path: Path, markdown: str) -> Path:
        """Guarda reporte de escaneo en Markdown.

        Args:
            ws_path: Directorio del workspace.
            markdown: Contenido Markdown del reporte.

        Returns:
            Path al archivo MD guardado.
        """
        md_path = ws_path / "scan_report.md"
        md_path.write_text(markdown, encoding="utf-8")
        logger.debug("Scan report MD guardado en %s", md_path)
        return md_path

    def save_exploit_result(self, ws_path: Path, result: Any) -> Path:
        """Guarda resultado de un exploit en su subdirectorio.

        Args:
            ws_path: Directorio del workspace.
            result: ExploitResult a guardar.

        Returns:
            Path al directorio del exploit.
        """
        exploit_dir = ws_path / "exploits" / result.exploit_id
        exploit_dir.mkdir(parents=True, exist_ok=True)

        result_path = exploit_dir / "result.json"
        result_path.write_text(
            result.model_dump_json(indent=2),
            encoding="utf-8",
        )
        logger.debug("Exploit result guardado en %s", result_path)
        return exploit_dir

    def save_exploit_report(self, ws_path: Path, report: Any) -> Path:
        """Guarda reporte resumen de exploits.

        Args:
            ws_path: Directorio del workspace.
            report: ExploitReport a guardar.

        Returns:
            Path al archivo summary.json.
        """
        summary_path = ws_path / "summary.json"
        summary_path.write_text(
            report.model_dump_json(indent=2),
            encoding="utf-8",
        )
        logger.debug("Exploit report guardado en %s", summary_path)
        return summary_path

    def save_recon_data(self, ws_path: Path, filename: str, data: Any) -> Path:
        """Guarda datos de reconocimiento en subdirectorio recon/.

        Args:
            ws_path: Directorio del workspace.
            filename: Nombre del archivo (ej: 'tech.json').
            data: Datos a guardar (Pydantic model o dict).

        Returns:
            Path al archivo guardado.
        """
        recon_dir = ws_path / "recon"
        recon_dir.mkdir(exist_ok=True)
        file_path = recon_dir / filename
        if hasattr(data, "model_dump_json"):
            file_path.write_text(data.model_dump_json(indent=2), encoding="utf-8")
        else:
            file_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
        return file_path

    def save_plan(self, ws_path: Path, plan: Any) -> Path:
        """Guarda el plan de pentesting.

        Args:
            ws_path: Directorio del workspace.
            plan: PentestPlan a guardar.

        Returns:
            Path al archivo plan.json.
        """
        plan_path = ws_path / "plan.json"
        plan_path.write_text(
            plan.model_dump_json(indent=2),
            encoding="utf-8",
        )
        return plan_path

    def export_package(self, ws_path: Path) -> Optional[Path]:
        """Exporta todo el workspace como paquete ZIP.

        Args:
            ws_path: Directorio del workspace.

        Returns:
            Path al ZIP o None si falla.
        """
        import zipfile
        zip_path = ws_path / "evidence_package.zip"
        try:
            with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
                for file_path in ws_path.rglob("*"):
                    if file_path.is_file() and file_path != zip_path:
                        arcname = file_path.relative_to(ws_path)
                        zf.write(str(file_path), str(arcname))
            logger.info("Package exportado: %s", zip_path)
            return zip_path
        except Exception as exc:
            logger.error("Error exportando package: %s", exc)
            return None

    def list_scans(self) -> List[Dict[str, Any]]:
        """Lista escaneos previos guardados.

        Returns:
            Lista de dicts con info de cada escaneo.
        """
        scans: List[Dict[str, Any]] = []
        if not self._scans_dir.exists():
            return scans

        for scan_dir in sorted(self._scans_dir.iterdir(), reverse=True):
            if not scan_dir.is_dir():
                continue

            info: Dict[str, Any] = {
                "name": scan_dir.name,
                "path": str(scan_dir),
                "has_scan_report": (scan_dir / "scan_report.json").exists(),
                "has_exploits": (scan_dir / "summary.json").exists(),
            }

            # Extraer dominio y fecha del nombre
            parts = scan_dir.name.rsplit("_", 2)
            if len(parts) >= 3:
                info["domain"] = parts[0]
                try:
                    info["date"] = f"{parts[1]}_{parts[2]}"
                except (ValueError, IndexError):
                    pass

            # Contar exploits
            exploits_dir = scan_dir / "exploits"
            if exploits_dir.exists():
                info["exploit_count"] = sum(
                    1 for d in exploits_dir.iterdir() if d.is_dir()
                )
            else:
                info["exploit_count"] = 0

            scans.append(info)

        return scans

    @staticmethod
    def _extract_domain(url: str) -> str:
        """Extrae dominio limpio de una URL para nombres de directorio."""
        parsed = urlparse(url)
        domain = parsed.hostname or parsed.path or "unknown"
        # Limpiar caracteres no válidos para nombres de directorio
        domain = re.sub(r"[^\w\-.]", "_", domain)
        return domain
