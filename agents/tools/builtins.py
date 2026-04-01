"""Tools built-in para agentes — HTTP requests, etc.

Proporciona herramientas básicas que el agente puede usar para
interactuar con APIs externas (Notion, etc.) según las instrucciones
de los skills cargados.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

from agents.tools.registry import ToolDefinition, ToolRegistry, ToolSection

logger = logging.getLogger(__name__)

# ── Tamaño máximo de respuesta (evitar respuestas enormes) ────
_MAX_RESPONSE_LENGTH = 8000


# ── HTTP Request Tool ─────────────────────────────────────────


async def _http_request_handler(args: Dict[str, Any]) -> str:
    """Ejecuta una petición HTTP y retorna el resultado.

    El agente usa esta tool para llamar APIs externas
    (Notion, etc.) basándose en las instrucciones del skill.
    """
    try:
        import httpx
    except ImportError:
        return "Error: httpx no instalado. Ejecuta: pip install httpx"

    method = args.get("method", "GET").upper()
    url = args.get("url", "")
    headers = args.get("headers", {})
    body = args.get("body")
    timeout_secs = min(args.get("timeout", 30), 60)

    if not url:
        return "Error: url es requerida"

    # Resolver env vars en headers (para $NOTION_API_KEY, etc.)
    # Soporta tanto "$VAR" como "Bearer $VAR"
    resolved_headers: Dict[str, str] = {}
    for key, value in headers.items():
        if not isinstance(value, str):
            resolved_headers[key] = str(value)
            continue
        # Buscar $VARIABLE patterns en el valor
        resolved = value
        import re as _re
        for match in _re.finditer(r"\$([A-Z_][A-Z0-9_]*)", value):
            env_name = match.group(1)
            env_val = os.environ.get(env_name, "")
            if not env_val:
                return f"Error: variable de entorno {env_name} no configurada"
            resolved = resolved.replace(match.group(0), env_val)
        resolved_headers[key] = resolved

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_secs)) as client:
            response = await client.request(
                method=method,
                url=url,
                headers=resolved_headers,
                json=body if body and method in ("POST", "PUT", "PATCH") else None,
            )

            # Construir resultado
            result_parts = [f"HTTP {response.status_code}"]

            content_type = response.headers.get("content-type", "")
            body_text = response.text

            if len(body_text) > _MAX_RESPONSE_LENGTH:
                body_text = body_text[:_MAX_RESPONSE_LENGTH] + "\n...(truncado)"

            # Intentar formatear JSON
            if "json" in content_type:
                try:
                    parsed = response.json()
                    body_text = json.dumps(parsed, indent=2, ensure_ascii=False)
                    if len(body_text) > _MAX_RESPONSE_LENGTH:
                        body_text = body_text[:_MAX_RESPONSE_LENGTH] + "\n...(truncado)"
                except (json.JSONDecodeError, ValueError):
                    pass

            result_parts.append(body_text)
            return "\n".join(result_parts)

    except httpx.TimeoutException:
        return f"Error: timeout después de {timeout_secs}s conectando a {url}"
    except httpx.ConnectError as exc:
        return f"Error de conexión a {url}: {exc}"
    except Exception as exc:
        return f"Error HTTP: {str(exc)[:500]}"


# ── Registro de builtins ──────────────────────────────────────


def register_builtins(registry: ToolRegistry) -> None:
    """Registra las tools built-in en el registry."""
    registry.register(ToolDefinition(
        id="http_request",
        name="http_request",
        description=(
            "Hace una petición HTTP a una URL. Usa esta herramienta para "
            "interactuar con APIs externas como Notion, GitHub, etc. "
            "Las credenciales (API keys) ya están configuradas como variables "
            "de entorno — usa $NOMBRE_VARIABLE en los headers para referenciarlas."
        ),
        parameters={
            "type": "object",
            "properties": {
                "method": {
                    "type": "string",
                    "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                    "description": "Método HTTP",
                },
                "url": {
                    "type": "string",
                    "description": "URL completa del endpoint",
                },
                "headers": {
                    "type": "object",
                    "description": (
                        "Headers HTTP. Usa $NOMBRE_VARIABLE para referenciar "
                        "env vars, ej: {\"Authorization\": \"Bearer $NOTION_API_KEY\"}"
                    ),
                    "additionalProperties": {"type": "string"},
                },
                "body": {
                    "type": "object",
                    "description": "Body JSON para POST/PUT/PATCH",
                },
                "timeout": {
                    "type": "number",
                    "description": "Timeout en segundos (max 60)",
                },
            },
            "required": ["method", "url"],
        },
        handler=_http_request_handler,
        section=ToolSection.WEB,
        timeout_secs=65.0,
    ))

    # ── Security tools ───────────────────────────────────────
    _register_security_tools(registry)

    logger.debug("Built-in tools registradas: http_request + security tools")


# ── Security tools ───────────────────────────────────────────


def _truncate(text: str, max_len: int = _MAX_RESPONSE_LENGTH) -> str:
    """Trunca texto a max_len chars."""
    if len(text) > max_len:
        return text[:max_len] + "\n...(truncado)"
    return text


async def _security_scan_handler(args: Dict[str, Any]) -> str:
    """Escaneo de seguridad completo o parcial."""
    import time as _time
    from cybersecurity.scanners import (
        analyze_csp, check_cookies, check_cors, check_directory_listing,
        check_email_security, check_forms, check_headers, check_html_leaks,
        check_http_methods, check_https_redirect, check_mixed_content,
        check_sri, check_ssl, check_xss_reflection, discover_paths,
        discover_tech, dns_lookup, scan_ports,
    )
    from cybersecurity.report import calculate_risk_score, findings_to_summary
    from cybersecurity.types import ScanReport
    from cybersecurity.utils import extract_hostname, normalize_url

    url = args.get("url", "")
    if not url:
        return "Error: url es requerida"

    url = normalize_url(url)
    hostname = extract_hostname(url)

    # Pre-flight DNS check — abortar rápido si el dominio no resuelve
    import socket as _socket
    try:
        _socket.getaddrinfo(hostname, None, _socket.AF_UNSPEC, _socket.SOCK_STREAM)
    except _socket.gaierror as exc:
        return (
            f"Error: No se pudo resolver el dominio '{hostname}'. "
            f"Verifica que la URL es correcta y el dominio existe. ({exc})"
        )

    checks = args.get("checks") or [
        "headers", "ssl", "cookies", "tech", "dns",
        "paths", "cors", "forms", "xss", "ports",
        "http_methods", "https_redirect", "sri",
        "mixed_content", "directory_listing", "html_leaks",
        "csp", "email_security",
    ]

    report = ScanReport(target_url=url)
    start = _time.monotonic()

    if "headers" in checks:
        report.headers = await check_headers(url)
    if "ssl" in checks:
        report.ssl = await check_ssl(hostname)
    if "cookies" in checks:
        report.cookies = await check_cookies(url)
    if "tech" in checks:
        report.tech = await discover_tech(url)
    if "dns" in checks:
        report.dns = await dns_lookup(hostname)
    if "paths" in checks:
        report.paths = await discover_paths(url)
    if "cors" in checks:
        report.cors = await check_cors(url)
    if "forms" in checks:
        report.forms = await check_forms(url)
    if "xss" in checks:
        report.xss = await check_xss_reflection(url)
    if "ports" in checks:
        report.ports = await scan_ports(hostname)
    if "http_methods" in checks:
        report.http_methods = await check_http_methods(url)
    if "https_redirect" in checks:
        report.https_redirect = await check_https_redirect(url)
    if "sri" in checks:
        report.sri = await check_sri(url)
    if "mixed_content" in checks:
        report.mixed_content = await check_mixed_content(url)
    if "directory_listing" in checks:
        report.directory_listing = await check_directory_listing(url)
    if "html_leaks" in checks:
        report.html_leaks = await check_html_leaks(url)
    if "csp" in checks:
        report.csp = await analyze_csp(url)
    if "email_security" in checks:
        report.email_security = await check_email_security(hostname)

    report.scan_duration_secs = round(_time.monotonic() - start, 1)
    report.collect_findings()
    report.risk_score = calculate_risk_score(report.all_findings)

    summary = findings_to_summary(report.all_findings)
    result_json = report.model_dump_json(indent=2)
    return _truncate(
        f"Riesgo: {report.risk_score}/10 | Duración: {report.scan_duration_secs}s\n"
        f"{summary}\n\n{result_json}"
    )


async def _check_headers_handler(args: Dict[str, Any]) -> str:
    """Análisis de headers de seguridad HTTP."""
    from cybersecurity.scanners import check_headers

    url = args.get("url", "")
    if not url:
        return "Error: url es requerida"

    result = await check_headers(url)
    return _truncate(result.model_dump_json(indent=2))


async def _check_ssl_handler(args: Dict[str, Any]) -> str:
    """Análisis SSL/TLS."""
    from cybersecurity.scanners import check_ssl

    hostname = args.get("hostname", "")
    if not hostname:
        return "Error: hostname es requerido"

    port = args.get("port", 443)
    result = await check_ssl(hostname, port)
    return _truncate(result.model_dump_json(indent=2))


async def _check_cookies_handler(args: Dict[str, Any]) -> str:
    """Análisis de cookies de seguridad."""
    from cybersecurity.scanners import check_cookies

    url = args.get("url", "")
    if not url:
        return "Error: url es requerida"

    result = await check_cookies(url)
    return _truncate(result.model_dump_json(indent=2))


async def _discover_tech_handler(args: Dict[str, Any]) -> str:
    """Detección de tecnologías."""
    from cybersecurity.scanners import discover_tech

    url = args.get("url", "")
    if not url:
        return "Error: url es requerida"

    result = await discover_tech(url)
    return _truncate(result.model_dump_json(indent=2))


async def _dns_lookup_handler(args: Dict[str, Any]) -> str:
    """Consulta DNS."""
    from cybersecurity.scanners import dns_lookup

    hostname = args.get("hostname", "")
    if not hostname:
        return "Error: hostname es requerido"

    record_types = args.get("record_types")
    result = await dns_lookup(hostname, record_types)
    return _truncate(result.model_dump_json(indent=2))


async def _crawl_links_handler(args: Dict[str, Any]) -> str:
    """Descubrimiento de links."""
    from cybersecurity.scanners import crawl_links

    url = args.get("url", "")
    if not url:
        return "Error: url es requerida"

    max_pages = args.get("max_pages", 20)
    max_depth = args.get("max_depth", 2)
    result = await crawl_links(url, max_pages, max_depth)
    return _truncate(result.model_dump_json(indent=2))


async def _scan_ports_handler(args: Dict[str, Any]) -> str:
    """Escaneo de puertos TCP."""
    from cybersecurity.scanners import scan_ports

    hostname = args.get("hostname", "")
    if not hostname:
        return "Error: hostname es requerido"

    ports = args.get("ports")
    result = await scan_ports(hostname, ports)
    return _truncate(result.model_dump_json(indent=2))


async def _generate_report_handler(args: Dict[str, Any]) -> str:
    """Genera reporte Markdown de seguridad."""
    from cybersecurity.report import calculate_risk_score, generate_markdown_report
    from cybersecurity.types import ScanReport

    url = args.get("url", "")
    scan_data = args.get("scan_data")
    output_path = args.get("output_path")

    if not url:
        return "Error: url es requerida"
    if not scan_data:
        return "Error: scan_data es requerido (JSON del escaneo previo)"

    try:
        if isinstance(scan_data, str):
            scan_data = json.loads(scan_data)
        report = ScanReport.model_validate(scan_data)
    except Exception as exc:
        return f"Error parseando scan_data: {str(exc)[:200]}"

    report.collect_findings()
    report.risk_score = calculate_risk_score(report.all_findings)
    md = generate_markdown_report(report)

    if output_path:
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(md)
            return f"Reporte guardado en: {output_path}\n\n{_truncate(md)}"
        except OSError as exc:
            return f"Error guardando reporte: {exc}\n\n{_truncate(md)}"

    return _truncate(md)


async def _check_http_methods_handler(args: Dict[str, Any]) -> str:
    """Detecta métodos HTTP inseguros."""
    from cybersecurity.scanners import check_http_methods

    url = args.get("url", "")
    if not url:
        return "Error: url es requerida"

    result = await check_http_methods(url)
    return _truncate(result.model_dump_json(indent=2))


async def _check_https_redirect_handler(args: Dict[str, Any]) -> str:
    """Verifica redirección HTTP → HTTPS."""
    from cybersecurity.scanners import check_https_redirect

    url = args.get("url", "")
    if not url:
        return "Error: url es requerida"

    result = await check_https_redirect(url)
    return _truncate(result.model_dump_json(indent=2))


async def _check_sri_handler(args: Dict[str, Any]) -> str:
    """Verifica Subresource Integrity en recursos externos."""
    from cybersecurity.scanners import check_sri

    url = args.get("url", "")
    if not url:
        return "Error: url es requerida"

    result = await check_sri(url)
    return _truncate(result.model_dump_json(indent=2))


async def _check_mixed_content_handler(args: Dict[str, Any]) -> str:
    """Detecta contenido mixto (HTTP en HTTPS)."""
    from cybersecurity.scanners import check_mixed_content

    url = args.get("url", "")
    if not url:
        return "Error: url es requerida"

    result = await check_mixed_content(url)
    return _truncate(result.model_dump_json(indent=2))


async def _check_directory_listing_handler(args: Dict[str, Any]) -> str:
    """Detecta directory listing habilitado."""
    from cybersecurity.scanners import check_directory_listing

    url = args.get("url", "")
    if not url:
        return "Error: url es requerida"

    result = await check_directory_listing(url)
    return _truncate(result.model_dump_json(indent=2))


async def _check_html_leaks_handler(args: Dict[str, Any]) -> str:
    """Detecta fugas de información en HTML."""
    from cybersecurity.scanners import check_html_leaks

    url = args.get("url", "")
    if not url:
        return "Error: url es requerida"

    result = await check_html_leaks(url)
    return _truncate(result.model_dump_json(indent=2))


async def _analyze_csp_handler(args: Dict[str, Any]) -> str:
    """Análisis detallado de Content Security Policy."""
    from cybersecurity.scanners import analyze_csp

    url = args.get("url", "")
    if not url:
        return "Error: url es requerida"

    result = await analyze_csp(url)
    return _truncate(result.model_dump_json(indent=2))


async def _check_email_security_handler(args: Dict[str, Any]) -> str:
    """Verifica SPF, DMARC y DKIM en DNS."""
    from cybersecurity.scanners import check_email_security

    hostname = args.get("hostname", "")
    if not hostname:
        return "Error: hostname es requerido"

    result = await check_email_security(hostname)
    return _truncate(result.model_dump_json(indent=2))


async def _run_exploits_handler(args: Dict[str, Any]) -> str:
    """Ejecuta exploits PoC sobre findings de un escaneo previo."""
    from cybersecurity.exploits import run_exploits
    from cybersecurity.report import generate_markdown_report
    from cybersecurity.types import ScanReport
    from cybersecurity.workspace import SecurityWorkspace

    url = args.get("url", "")
    scan_data = args.get("scan_data")
    use_browser = args.get("use_browser", True)

    if not url:
        return "Error: url es requerida"
    if not scan_data:
        return "Error: scan_data es requerido (JSON del escaneo previo)"

    try:
        if isinstance(scan_data, str):
            scan_data = json.loads(scan_data)
        report = ScanReport.model_validate(scan_data)
    except Exception as exc:
        return f"Error parseando scan_data: {str(exc)[:200]}"

    report.collect_findings()

    # Crear workspace
    workspace = SecurityWorkspace()
    ws_path = workspace.create_scan_workspace(url)
    workspace.save_scan_report(ws_path, report)

    # Generar y guardar reporte MD del escaneo
    try:
        from cybersecurity.report import calculate_risk_score
        report.risk_score = calculate_risk_score(report.all_findings)
        scan_md = generate_markdown_report(report)
        workspace.save_scan_report_md(ws_path, scan_md)
    except Exception:
        pass

    # Ejecutar exploits
    exploit_report = await run_exploits(
        url=url,
        findings=report.all_findings,
        workspace_dir=ws_path,
        use_browser=use_browser,
    )
    exploit_report.workspace_path = str(ws_path)

    # Guardar resumen
    workspace.save_exploit_report(ws_path, exploit_report)

    # Generar reporte Markdown con evidencias
    md_path = _generate_exploit_markdown(ws_path, exploit_report)

    size = md_path.stat().st_size if md_path.exists() else 0
    return json.dumps({
        "file_path": str(md_path),
        "filename": md_path.name,
        "format": "md",
        "size_bytes": size,
        "workspace_path": str(ws_path),
        "total_exploits": exploit_report.total_exploits,
        "successful": exploit_report.successful,
        "failed": exploit_report.failed,
    })


def _generate_exploit_markdown(ws_path: "Path", report: Any) -> "Path":
    """Genera reporte Markdown de exploits con evidencia."""
    from pathlib import Path as _Path

    lines = [
        f"# Reporte de Exploits PoC — {report.target_url}",
        "",
        f"**Total exploits:** {report.total_exploits} | "
        f"**Exitosos:** {report.successful} | "
        f"**Fallidos:** {report.failed} | "
        f"**Duración:** {report.duration_secs}s",
        "",
        "---",
        "",
    ]

    for r in report.results:
        status = "EXITOSO" if r.success else "FALLIDO"
        lines.append(f"## {r.title} [{status}]")
        lines.append("")
        lines.append(f"- **Exploit ID:** `{r.exploit_id}`")
        lines.append(f"- **Finding:** `{r.finding_check_id}`")
        lines.append(f"- **Impacto:** {r.impact_description}")
        lines.append(f"- **Duración:** {r.duration_secs}s")
        lines.append("")

        if r.evidence:
            lines.append("### Evidencia")
            lines.append("")
            for i, ev in enumerate(r.evidence, 1):
                lines.append(f"**{i}.** {ev.description}")
                if ev.http_status:
                    lines.append(f"   - HTTP Status: {ev.http_status}")
                if ev.screenshot_path:
                    lines.append(f"   - Screenshot: `{ev.screenshot_path}`")
                if ev.response_data:
                    lines.append(f"   ```")
                    lines.append(f"   {ev.response_data[:500]}")
                    lines.append(f"   ```")
                lines.append("")

        lines.append("---")
        lines.append("")

    if report.workspace_path:
        lines.append(f"**Workspace:** `{report.workspace_path}`")

    md_content = "\n".join(lines)
    md_path = ws_path / "exploit_report.md"
    md_path.write_text(md_content, encoding="utf-8")
    return md_path


def _register_security_tools(registry: ToolRegistry) -> None:
    """Registra las tools de seguridad en el registry."""

    # Registrar tools de pentesting por fases
    try:
        from cybersecurity.tools.orchestrator_tools import register_orchestrator_tools
        register_orchestrator_tools(registry)
    except ImportError:
        logger.debug("No se pudieron cargar orchestrator tools")

    try:
        from cybersecurity.tools.scanner_tools import register_scanner_tools
        register_scanner_tools(registry)
    except ImportError:
        logger.debug("No se pudieron cargar scanner tools")

    try:
        from cybersecurity.tools.exploit_tools import register_exploit_tools
        register_exploit_tools(registry)
    except ImportError:
        logger.debug("No se pudieron cargar exploit tools")

    try:
        from cybersecurity.tools.evidence_tools import register_evidence_tools
        register_evidence_tools(registry)
    except ImportError:
        logger.debug("No se pudieron cargar evidence tools")

    # 1. security_scan — escaneo completo/parcial
    registry.register(ToolDefinition(
        id="security_scan",
        name="security_scan",
        description=(
            "Ejecuta un escaneo de seguridad web completo o parcial sobre una URL. "
            "Analiza headers, SSL, cookies, tecnologías, DNS, rutas expuestas, "
            "CORS, formularios, reflexión XSS, puertos, métodos HTTP, redirect HTTPS, "
            "SRI, contenido mixto, directory listing, leaks HTML, CSP y email security. "
            "Retorna hallazgos con severidad y puntuación de riesgo."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL del sitio web a escanear",
                },
                "checks": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "headers", "ssl", "cookies", "tech", "dns",
                            "paths", "cors", "forms", "xss", "ports",
                            "http_methods", "https_redirect", "sri",
                            "mixed_content", "directory_listing", "html_leaks",
                            "csp", "email_security",
                        ],
                    },
                    "description": (
                        "Checks específicos a ejecutar. Si se omite, "
                        "ejecuta todos los checks (18 en total)."
                    ),
                },
            },
            "required": ["url"],
        },
        handler=_security_scan_handler,
        section=ToolSection.SECURITY,
        timeout_secs=180.0,
    ))

    # 2. check_headers
    registry.register(ToolDefinition(
        id="check_headers",
        name="check_headers",
        description=(
            "Analiza los headers de seguridad HTTP de una URL. "
            "Verifica CSP, HSTS, X-Frame-Options, X-Content-Type-Options, "
            "y detecta divulgación de información (Server, X-Powered-By)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL a analizar",
                },
            },
            "required": ["url"],
        },
        handler=_check_headers_handler,
        section=ToolSection.SECURITY,
        timeout_secs=30.0,
    ))

    # 3. check_ssl
    registry.register(ToolDefinition(
        id="check_ssl",
        name="check_ssl",
        description=(
            "Analiza el certificado SSL/TLS de un hostname. "
            "Verifica validez, expiración, protocolo TLS, cipher suite y SAN."
        ),
        parameters={
            "type": "object",
            "properties": {
                "hostname": {
                    "type": "string",
                    "description": "Hostname a verificar (sin https://)",
                },
                "port": {
                    "type": "integer",
                    "description": "Puerto SSL (default: 443)",
                },
            },
            "required": ["hostname"],
        },
        handler=_check_ssl_handler,
        section=ToolSection.SECURITY,
        timeout_secs=30.0,
    ))

    # 4. check_cookies
    registry.register(ToolDefinition(
        id="check_cookies",
        name="check_cookies",
        description=(
            "Analiza las cookies de una URL. Verifica flags Secure, "
            "HttpOnly, SameSite en cookies de sesión."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL a analizar",
                },
            },
            "required": ["url"],
        },
        handler=_check_cookies_handler,
        section=ToolSection.SECURITY,
        timeout_secs=30.0,
    ))

    # 5. discover_tech
    registry.register(ToolDefinition(
        id="discover_tech",
        name="discover_tech",
        description=(
            "Detecta tecnologías usadas por un sitio web. "
            "Analiza headers, meta tags y patrones en HTML para identificar "
            "frameworks, CMSs, servidores web y librerías."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL a analizar",
                },
            },
            "required": ["url"],
        },
        handler=_discover_tech_handler,
        section=ToolSection.SECURITY,
        timeout_secs=30.0,
    ))

    # 6. dns_lookup
    registry.register(ToolDefinition(
        id="dns_lookup",
        name="dns_lookup",
        description=(
            "Consulta registros DNS de un hostname. "
            "Obtiene registros A, AAAA, MX, TXT, NS y verifica SPF/DMARC."
        ),
        parameters={
            "type": "object",
            "properties": {
                "hostname": {
                    "type": "string",
                    "description": "Hostname a consultar",
                },
                "record_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tipos de registro DNS (default: A, AAAA, MX, TXT, NS)",
                },
            },
            "required": ["hostname"],
        },
        handler=_dns_lookup_handler,
        section=ToolSection.SECURITY,
        timeout_secs=30.0,
    ))

    # 7. crawl_links
    registry.register(ToolDefinition(
        id="crawl_links",
        name="crawl_links",
        description=(
            "Descubre links internos y externos de un sitio web. "
            "BFS con profundidad máxima, cuenta formularios encontrados."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL inicial del crawl",
                },
                "max_pages": {
                    "type": "integer",
                    "description": "Máximo de páginas a visitar (default: 20)",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Profundidad máxima de BFS (default: 2)",
                },
            },
            "required": ["url"],
        },
        handler=_crawl_links_handler,
        section=ToolSection.SECURITY,
        timeout_secs=120.0,
    ))

    # 8. scan_ports
    registry.register(ToolDefinition(
        id="scan_ports",
        name="scan_ports",
        description=(
            "Escanea puertos TCP abiertos en un hostname. "
            "Prueba puertos web comunes y de bases de datos."
        ),
        parameters={
            "type": "object",
            "properties": {
                "hostname": {
                    "type": "string",
                    "description": "Hostname a escanear",
                },
                "ports": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Lista de puertos específicos (default: puertos comunes)",
                },
            },
            "required": ["hostname"],
        },
        handler=_scan_ports_handler,
        section=ToolSection.SECURITY,
        timeout_secs=60.0,
    ))

    # 9. generate_security_report
    registry.register(ToolDefinition(
        id="generate_security_report",
        name="generate_security_report",
        description=(
            "Genera un reporte de seguridad en Markdown a partir de datos "
            "de escaneo previo. Puede guardar a archivo."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL del sitio escaneado",
                },
                "scan_data": {
                    "type": "object",
                    "description": "Datos JSON del escaneo (output de security_scan)",
                },
                "output_path": {
                    "type": "string",
                    "description": "Ruta para guardar el reporte Markdown (opcional)",
                },
            },
            "required": ["url", "scan_data"],
        },
        handler=_generate_report_handler,
        section=ToolSection.SECURITY,
        timeout_secs=30.0,
    ))

    # 10. check_http_methods
    registry.register(ToolDefinition(
        id="check_http_methods",
        name="check_http_methods",
        description=(
            "Detecta métodos HTTP inseguros habilitados (PUT, DELETE, TRACE). "
            "Envía request OPTIONS para listar métodos permitidos."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL a analizar",
                },
            },
            "required": ["url"],
        },
        handler=_check_http_methods_handler,
        section=ToolSection.SECURITY,
        timeout_secs=30.0,
    ))

    # 11. check_https_redirect
    registry.register(ToolDefinition(
        id="check_https_redirect",
        name="check_https_redirect",
        description=(
            "Verifica que HTTP redirige correctamente a HTTPS. "
            "Sigue la cadena de redirects desde la versión HTTP."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL a verificar",
                },
            },
            "required": ["url"],
        },
        handler=_check_https_redirect_handler,
        section=ToolSection.SECURITY,
        timeout_secs=30.0,
    ))

    # 12. check_sri
    registry.register(ToolDefinition(
        id="check_sri",
        name="check_sri",
        description=(
            "Verifica Subresource Integrity (SRI) en scripts y stylesheets "
            "cargados desde CDNs externos."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL a analizar",
                },
            },
            "required": ["url"],
        },
        handler=_check_sri_handler,
        section=ToolSection.SECURITY,
        timeout_secs=30.0,
    ))

    # 13. check_mixed_content
    registry.register(ToolDefinition(
        id="check_mixed_content",
        name="check_mixed_content",
        description=(
            "Detecta contenido mixto: recursos HTTP cargados en páginas HTTPS "
            "(scripts, stylesheets, imágenes)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL HTTPS a analizar",
                },
            },
            "required": ["url"],
        },
        handler=_check_mixed_content_handler,
        section=ToolSection.SECURITY,
        timeout_secs=30.0,
    ))

    # 14. check_directory_listing
    registry.register(ToolDefinition(
        id="check_directory_listing",
        name="check_directory_listing",
        description=(
            "Detecta directory listing habilitado en directorios comunes "
            "(/images/, /uploads/, /css/, /js/, /assets/, etc.)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL base del sitio",
                },
            },
            "required": ["url"],
        },
        handler=_check_directory_listing_handler,
        section=ToolSection.SECURITY,
        timeout_secs=30.0,
    ))

    # 15. check_html_leaks
    registry.register(ToolDefinition(
        id="check_html_leaks",
        name="check_html_leaks",
        description=(
            "Detecta fugas de información en HTML: comentarios sensibles, "
            "versiones expuestas en meta tags, y emails."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL a analizar",
                },
            },
            "required": ["url"],
        },
        handler=_check_html_leaks_handler,
        section=ToolSection.SECURITY,
        timeout_secs=30.0,
    ))

    # 16. analyze_csp
    registry.register(ToolDefinition(
        id="analyze_csp",
        name="analyze_csp",
        description=(
            "Analiza Content-Security-Policy en profundidad. Parsea directivas, "
            "detecta unsafe-inline/eval, wildcards y directivas faltantes."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL a analizar",
                },
            },
            "required": ["url"],
        },
        handler=_analyze_csp_handler,
        section=ToolSection.SECURITY,
        timeout_secs=30.0,
    ))

    # 17. check_email_security
    registry.register(ToolDefinition(
        id="check_email_security",
        name="check_email_security",
        description=(
            "Verifica registros SPF, DMARC y DKIM en DNS para evaluar "
            "la protección contra email spoofing."
        ),
        parameters={
            "type": "object",
            "properties": {
                "hostname": {
                    "type": "string",
                    "description": "Dominio a verificar (ej: example.com)",
                },
            },
            "required": ["hostname"],
        },
        handler=_check_email_security_handler,
        section=ToolSection.SECURITY,
        timeout_secs=30.0,
    ))

    # 18. run_security_exploits
    registry.register(ToolDefinition(
        id="run_security_exploits",
        name="run_security_exploits",
        description=(
            "Ejecuta pruebas de concepto (PoC) seguras sobre vulnerabilidades "
            "descubiertas en un escaneo previo. Demuestra el impacto real de cada "
            "hallazgo con capturas de pantalla y evidencia. "
            "Guarda todo en el workspace de seguridad (~/.somer/security/). "
            "El reporte con evidencias se envía automáticamente al usuario."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL escaneada",
                },
                "scan_data": {
                    "type": "object",
                    "description": "JSON del escaneo (output de security_scan)",
                },
                "use_browser": {
                    "type": "boolean",
                    "description": "Usar Playwright para screenshots (default: true)",
                },
            },
            "required": ["url", "scan_data"],
        },
        handler=_run_exploits_handler,
        section=ToolSection.SECURITY,
        timeout_secs=180.0,
    ))
