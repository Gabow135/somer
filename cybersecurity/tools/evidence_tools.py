"""Tools para gestión de evidencia."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict

from agents.tools.registry import ToolDefinition, ToolRegistry, ToolSection

logger = logging.getLogger(__name__)

_MAX_RESPONSE = 8000


def _truncate(text: str, max_len: int = _MAX_RESPONSE) -> str:
    if len(text) > max_len:
        return text[:max_len] + "\n...(truncado)"
    return text


async def _capture_screenshot_handler(args: Dict[str, Any]) -> str:
    """Captura screenshot de una URL."""
    from cybersecurity.evidence import EvidenceManager

    url = args.get("url", "")
    workspace_path = args.get("workspace_path", "")
    name = args.get("name", "page")

    if not url or not workspace_path:
        return "Error: url y workspace_path son requeridos"

    em = EvidenceManager(Path(workspace_path))

    # Intentar usar browser
    browser = None
    try:
        from browser.automation import BrowserManager
        browser = BrowserManager(profile="security-evidence", headless=True)
        await browser.launch()
    except Exception:
        return "Error: No se pudo iniciar el browser para screenshots"

    try:
        ss_path = await em.capture_screenshot(url, browser, name)
        return json.dumps({"screenshot_path": ss_path or "failed"})
    finally:
        if browser:
            try:
                await browser.close()
            except Exception:
                pass


async def _extract_sensitive_handler(args: Dict[str, Any]) -> str:
    """Extrae y redacta datos sensibles de un texto."""
    from cybersecurity.evidence import EvidenceManager

    data = args.get("data", "")
    if not data:
        return "Error: data es requerido"

    patterns = args.get("additional_patterns")
    redacted, summary = EvidenceManager.extract_and_redact(data, patterns)
    return json.dumps({
        "redacted": redacted[:2000],
        "summary": summary,
    })


async def _build_evidence_chain_handler(args: Dict[str, Any]) -> str:
    """Construye cadena de evidencia."""
    from cybersecurity.evidence import EvidenceManager
    from cybersecurity.types import ExploitResult, Finding

    workspace_path = args.get("workspace_path", "")
    target_url = args.get("target_url", "")
    findings_data = args.get("findings", [])
    exploit_data = args.get("exploit_results", [])

    if not workspace_path:
        return "Error: workspace_path es requerido"

    findings = [Finding.model_validate(f) for f in findings_data] if findings_data else []
    exploit_results = [ExploitResult.model_validate(r) for r in exploit_data] if exploit_data else []

    em = EvidenceManager(Path(workspace_path))
    chain = em.build_chain(findings, exploit_results, target_url)
    return _truncate(chain.model_dump_json(indent=2))


def register_evidence_tools(registry: ToolRegistry) -> None:
    """Registra las tools de evidencia."""

    registry.register(ToolDefinition(
        id="capture_screenshot",
        name="capture_screenshot",
        description=(
            "Captura un screenshot full-page de una URL y lo guarda "
            "en el workspace de seguridad."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL a capturar"},
                "workspace_path": {"type": "string", "description": "Path del workspace"},
                "name": {"type": "string", "description": "Nombre base del archivo (default: page)"},
            },
            "required": ["url", "workspace_path"],
        },
        handler=_capture_screenshot_handler,
        section=ToolSection.SECURITY,
        timeout_secs=60.0,
    ))

    registry.register(ToolDefinition(
        id="extract_sensitive_data",
        name="extract_sensitive_data",
        description=(
            "Extrae y redacta datos sensibles de un texto. "
            "Detecta passwords, API keys, emails, tarjetas de crédito, SSN y SSH keys."
        ),
        parameters={
            "type": "object",
            "properties": {
                "data": {"type": "string", "description": "Texto a analizar"},
                "additional_patterns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Patrones regex adicionales a redactar",
                },
            },
            "required": ["data"],
        },
        handler=_extract_sensitive_handler,
        section=ToolSection.SECURITY,
        timeout_secs=10.0,
    ))

    registry.register(ToolDefinition(
        id="build_evidence_chain",
        name="build_evidence_chain",
        description=(
            "Construye una cadena de evidencia conectando findings "
            "con resultados de exploits. Guarda en el workspace."
        ),
        parameters={
            "type": "object",
            "properties": {
                "workspace_path": {"type": "string", "description": "Path del workspace"},
                "target_url": {"type": "string", "description": "URL del target"},
                "findings": {"type": "array", "description": "Lista de findings"},
                "exploit_results": {"type": "array", "description": "Lista de exploit results"},
            },
            "required": ["workspace_path"],
        },
        handler=_build_evidence_chain_handler,
        section=ToolSection.SECURITY,
        timeout_secs=30.0,
    ))
