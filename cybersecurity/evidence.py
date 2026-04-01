"""Sistema de evidencia para pentesting — captura, redacción y exportación.

EvidenceManager centraliza la gestión de evidencia: screenshots, HTTP logs,
datos extraídos (redactados), cadenas de evidencia y paquetes ZIP.
"""

from __future__ import annotations

import json
import logging
import re
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from cybersecurity.types import (
    EvidenceChain,
    EvidenceChainLink,
    ExploitResult,
    Finding,
    PentestPhase,
    RequestLog,
)

logger = logging.getLogger(__name__)


class EvidenceManager:
    """Gestiona la evidencia de un engagement de pentesting."""

    def __init__(self, workspace_path: Path) -> None:
        self._ws = workspace_path
        self._evidence_dir = workspace_path / "evidence"
        self._screenshots_dir = self._evidence_dir / "screenshots"
        self._http_logs_dir = self._evidence_dir / "http_logs"
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        """Crea los subdirectorios necesarios."""
        self._evidence_dir.mkdir(parents=True, exist_ok=True)
        self._screenshots_dir.mkdir(exist_ok=True)
        self._http_logs_dir.mkdir(exist_ok=True)

    async def capture_screenshot(
        self, url: str, browser: Any, name: str = "page"
    ) -> Optional[str]:
        """Captura screenshot full-page y lo guarda en el workspace.

        Args:
            url: URL a capturar.
            browser: Instancia de BrowserManager.
            name: Nombre base del archivo.

        Returns:
            Path al screenshot guardado o None si falla.
        """
        if browser is None:
            return None

        try:
            await browser.navigate(url)
            import asyncio
            await asyncio.sleep(1)
            ss_path = await browser.screenshot(full_page=True)
            if ss_path:
                # Copiar al directorio de evidencia
                src = Path(str(ss_path))
                dst = self._screenshots_dir / f"{name}.png"
                if src.exists():
                    import shutil
                    shutil.copy2(str(src), str(dst))
                    return str(dst)
        except Exception as exc:
            logger.warning("Error capturando screenshot de %s: %s", url, exc)
        return None

    def log_http_exchange(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        body: Optional[str] = None,
        response_status: int = 0,
        response_headers: Optional[Dict[str, str]] = None,
        response_body: Optional[str] = None,
    ) -> RequestLog:
        """Registra un intercambio HTTP y lo guarda.

        Returns:
            RequestLog con los datos registrados.
        """
        log = RequestLog(
            method=method,
            url=url,
            request_headers=headers or {},
            request_body=body,
            response_status=response_status,
            response_headers=response_headers or {},
            response_body=response_body[:2000] if response_body else None,
        )

        # Guardar en archivo
        safe_name = re.sub(r"[^\w\-.]", "_", url)[:80]
        log_path = self._http_logs_dir / f"{safe_name}.json"
        try:
            log_path.write_text(log.model_dump_json(indent=2), encoding="utf-8")
        except Exception as exc:
            logger.debug("Error guardando HTTP log: %s", exc)

        return log

    @staticmethod
    def extract_and_redact(
        data: str,
        patterns: Optional[List[str]] = None,
    ) -> Tuple[str, str]:
        """Extrae datos sensibles y los redacta.

        Args:
            data: Texto con datos potencialmente sensibles.
            patterns: Patrones regex adicionales a redactar.

        Returns:
            Tupla (datos_redactados, resumen).
        """
        # Patrones por defecto de datos sensibles
        default_patterns = [
            (r'(?i)(password|passwd|pwd|secret|key|token|api_key|apikey)\s*[=:]\s*["\']?([^"\';\s\n]+)',
             r'\1=****'),
            (r'(?i)(authorization:\s*bearer\s+)\S+', r'\1****'),
            (r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL]'),
            (r'\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b', '[CARD_NUMBER]'),
            (r'\b\d{3}-\d{2}-\d{4}\b', '[SSN]'),
            (r'(?i)(ssh-rsa|ssh-ed25519)\s+\S+', r'\1 ****'),
        ]

        redacted = data
        findings_summary: List[str] = []

        for pattern, replacement in default_patterns:
            matches = re.findall(pattern, redacted)
            if matches:
                findings_summary.append(
                    f"{len(matches)} coincidencia(s) de {pattern[:30]}..."
                )
                redacted = re.sub(pattern, replacement, redacted)

        # Patrones adicionales
        if patterns:
            for p in patterns:
                matches = re.findall(p, redacted)
                if matches:
                    findings_summary.append(f"{len(matches)} coincidencia(s) de patrón personalizado")
                    redacted = re.sub(p, "[REDACTED]", redacted)

        summary = (
            f"Datos redactados: {len(findings_summary)} tipos de información sensible encontrada. "
            + "; ".join(findings_summary)
            if findings_summary
            else "No se encontró información sensible."
        )

        return redacted, summary

    def build_chain(
        self,
        findings: List[Finding],
        exploit_results: List[ExploitResult],
        target_url: str = "",
    ) -> EvidenceChain:
        """Construye cadena de evidencia conectando findings con exploits.

        Args:
            findings: Findings del escaneo.
            exploit_results: Resultados de exploits ejecutados.
            target_url: URL del target.

        Returns:
            EvidenceChain con links conectados.
        """
        chain = EvidenceChain(target_url=target_url)

        # Links de fase scan (findings)
        for finding in findings:
            chain.links.append(EvidenceChainLink(
                phase=PentestPhase.SCAN,
                source_id=finding.check_id,
                description=f"[{finding.severity.value.upper()}] {finding.title}",
            ))

        # Links de fase exploit
        for exploit in exploit_results:
            if exploit.success:
                chain.links.append(EvidenceChainLink(
                    phase=PentestPhase.EXPLOIT,
                    source_id=exploit.exploit_id,
                    description=f"[EXPLOTADO] {exploit.title}: {exploit.impact_description[:100]}",
                    data_ref=exploit.exploit_id,
                ))

        # Guardar chain
        chain_path = self._evidence_dir / "chain.json"
        try:
            chain_path.write_text(chain.model_dump_json(indent=2), encoding="utf-8")
        except Exception as exc:
            logger.debug("Error guardando evidence chain: %s", exc)

        return chain

    def export_package(self) -> Optional[str]:
        """Exporta toda la evidencia como paquete ZIP.

        Returns:
            Path al archivo ZIP o None si falla.
        """
        zip_path = self._ws / "evidence_package.zip"
        try:
            with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
                # Incluir todo el workspace
                for file_path in self._ws.rglob("*"):
                    if file_path.is_file() and file_path != zip_path:
                        arcname = file_path.relative_to(self._ws)
                        zf.write(str(file_path), str(arcname))

            logger.info("Evidence package exportado: %s (%d bytes)", zip_path, zip_path.stat().st_size)
            return str(zip_path)
        except Exception as exc:
            logger.error("Error exportando evidence package: %s", exc)
            return None
