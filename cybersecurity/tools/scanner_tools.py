"""Tools individuales para los 10 scanners avanzados."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from agents.tools.registry import ToolDefinition, ToolRegistry, ToolSection

logger = logging.getLogger(__name__)

_MAX_RESPONSE = 8000


def _truncate(text: str, max_len: int = _MAX_RESPONSE) -> str:
    if len(text) > max_len:
        return text[:max_len] + "\n...(truncado)"
    return text


async def _check_sqli_handler(args: Dict[str, Any]) -> str:
    from cybersecurity.scanners_advanced import check_sqli_indicators
    url = args.get("url", "")
    if not url:
        return "Error: url es requerida"
    findings = await check_sqli_indicators(url)
    return _truncate(json.dumps([f.model_dump() for f in findings], indent=2))


async def _check_admin_handler(args: Dict[str, Any]) -> str:
    from cybersecurity.scanners_advanced import check_admin_panels
    url = args.get("url", "")
    if not url:
        return "Error: url es requerida"
    findings = await check_admin_panels(url)
    return _truncate(json.dumps([f.model_dump() for f in findings], indent=2))


async def _enum_subdomains_handler(args: Dict[str, Any]) -> str:
    from cybersecurity.scanners_advanced import enumerate_subdomains
    hostname = args.get("hostname", "")
    if not hostname:
        return "Error: hostname es requerido"
    subdomains, findings = await enumerate_subdomains(hostname)
    return _truncate(json.dumps({
        "subdomains": [s.model_dump() for s in subdomains],
        "findings": [f.model_dump() for f in findings],
    }, indent=2))


async def _detect_waf_handler(args: Dict[str, Any]) -> str:
    from cybersecurity.scanners_advanced import detect_waf
    url = args.get("url", "")
    if not url:
        return "Error: url es requerida"
    result = await detect_waf(url)
    return _truncate(result.model_dump_json(indent=2))


async def _check_session_handler(args: Dict[str, Any]) -> str:
    from cybersecurity.scanners_advanced import check_session_management
    url = args.get("url", "")
    if not url:
        return "Error: url es requerida"
    findings = await check_session_management(url)
    return _truncate(json.dumps([f.model_dump() for f in findings], indent=2))


async def _check_smuggling_handler(args: Dict[str, Any]) -> str:
    from cybersecurity.scanners_advanced import check_request_smuggling
    url = args.get("url", "")
    if not url:
        return "Error: url es requerida"
    findings = await check_request_smuggling(url)
    return _truncate(json.dumps([f.model_dump() for f in findings], indent=2))


async def _check_ssti_handler(args: Dict[str, Any]) -> str:
    from cybersecurity.scanners_advanced import check_ssti
    url = args.get("url", "")
    if not url:
        return "Error: url es requerida"
    findings = await check_ssti(url)
    return _truncate(json.dumps([f.model_dump() for f in findings], indent=2))


async def _check_traversal_handler(args: Dict[str, Any]) -> str:
    from cybersecurity.scanners_advanced import check_path_traversal
    url = args.get("url", "")
    if not url:
        return "Error: url es requerida"
    findings = await check_path_traversal(url)
    return _truncate(json.dumps([f.model_dump() for f in findings], indent=2))


async def _check_info_handler(args: Dict[str, Any]) -> str:
    from cybersecurity.scanners_advanced import check_info_disclosure
    url = args.get("url", "")
    if not url:
        return "Error: url es requerida"
    findings = await check_info_disclosure(url)
    return _truncate(json.dumps([f.model_dump() for f in findings], indent=2))


async def _analyze_jwt_handler(args: Dict[str, Any]) -> str:
    from cybersecurity.scanners_advanced import analyze_jwt
    url = args.get("url", "")
    if not url:
        return "Error: url es requerida"
    result = await analyze_jwt(url)
    return _truncate(result.model_dump_json(indent=2))


def register_scanner_tools(registry: ToolRegistry) -> None:
    """Registra las tools de scanners avanzados."""

    _url_param = {
        "type": "object",
        "properties": {"url": {"type": "string", "description": "URL a escanear"}},
        "required": ["url"],
    }
    _host_param = {
        "type": "object",
        "properties": {"hostname": {"type": "string", "description": "Hostname a escanear"}},
        "required": ["hostname"],
    }

    tools = [
        ("check_sqli", "Detecta indicadores de SQL Injection con payloads de detección.", _url_param, _check_sqli_handler),
        ("check_admin_panels", "Detecta paneles de administración accesibles sin autenticación.", _url_param, _check_admin_handler),
        ("enumerate_subdomains", "Enumera subdominios via Certificate Transparency y DNS brute force.", _host_param, _enum_subdomains_handler),
        ("detect_waf", "Detecta Web Application Firewalls por fingerprinting de respuestas.", _url_param, _detect_waf_handler),
        ("check_session_management", "Verifica si session tokens rotan correctamente entre requests.", _url_param, _check_session_handler),
        ("check_request_smuggling", "Detecta vulnerabilidades de HTTP Request Smuggling (CL/TE).", _url_param, _check_smuggling_handler),
        ("check_ssti", "Detecta Server-Side Template Injection con payloads de detección.", _url_param, _check_ssti_handler),
        ("check_path_traversal", "Detecta vulnerabilidades de path traversal en parámetros.", _url_param, _check_traversal_handler),
        ("check_info_disclosure", "Detecta fugas de información en rutas de debug, backups y archivos expuestos.", _url_param, _check_info_handler),
        ("analyze_jwt", "Analiza JWTs encontrados en respuestas o cookies del sitio.", _url_param, _analyze_jwt_handler),
    ]

    for tool_id, desc, params, handler in tools:
        registry.register(ToolDefinition(
            id=tool_id,
            name=tool_id,
            description=desc,
            parameters=params,
            handler=handler,
            section=ToolSection.SECURITY,
            timeout_secs=60.0,
        ))
