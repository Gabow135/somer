"""Tools de monitoreo de red — ping, traceroute, cert check, HTTP check, DNS health."""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import socket
import ssl
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agents.tools.registry import ToolDefinition, ToolRegistry, ToolSection

logger = logging.getLogger(__name__)

_MAX_RESPONSE = 8000


def _truncate(text: str, max_len: int = _MAX_RESPONSE) -> str:
    if len(text) > max_len:
        return text[:max_len] + "\n...(truncado)"
    return text


# ── Handlers ─────────────────────────────────────────────────


async def _net_ping_handler(args: Dict[str, Any]) -> str:
    """Ping a host con estadísticas."""
    host = args.get("host", "").strip()
    count = min(args.get("count", 4), 20)
    if not host:
        return "Error: host es requerido"

    try:
        flag = "-c" if platform.system() != "Windows" else "-n"
        result = subprocess.run(
            ["ping", flag, str(count), host],
            capture_output=True, text=True, timeout=30,
        )

        output = result.stdout + result.stderr
        stats: Dict[str, Any] = {"host": host, "count": count, "reachable": result.returncode == 0}

        # Parse stats
        loss_match = re.search(r"(\d+(?:\.\d+)?)% packet loss", output)
        if loss_match:
            stats["packet_loss_pct"] = float(loss_match.group(1))

        rtt_match = re.search(r"min/avg/max.*?=\s*([\d.]+)/([\d.]+)/([\d.]+)", output)
        if rtt_match:
            stats["rtt_ms"] = {
                "min": float(rtt_match.group(1)),
                "avg": float(rtt_match.group(2)),
                "max": float(rtt_match.group(3)),
            }

        stats["raw_output"] = output[-500:]
        return json.dumps(stats, indent=2)
    except subprocess.TimeoutExpired:
        return json.dumps({"host": host, "reachable": False, "error": "timeout"})
    except Exception as exc:
        return json.dumps({"host": host, "reachable": False, "error": str(exc)})


async def _net_traceroute_handler(args: Dict[str, Any]) -> str:
    """Traceroute a host."""
    host = args.get("host", "").strip()
    if not host:
        return "Error: host es requerido"

    try:
        cmd = "traceroute" if platform.system() != "Windows" else "tracert"
        result = subprocess.run(
            [cmd, "-m", "20", host],
            capture_output=True, text=True, timeout=60,
        )
        return json.dumps({
            "host": host,
            "output": result.stdout[-2000:],
            "completed": result.returncode == 0,
        }, indent=2)
    except subprocess.TimeoutExpired:
        return json.dumps({"host": host, "error": "timeout (>60s)"})
    except Exception as exc:
        return json.dumps({"host": host, "error": str(exc)})


async def _net_cert_check_handler(args: Dict[str, Any]) -> str:
    """Verifica certificado SSL de un host."""
    host = args.get("host", "").strip().replace("https://", "").replace("http://", "").split("/")[0]
    port = args.get("port", 443)
    if not host:
        return "Error: host es requerido"

    try:
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(socket.socket(), server_hostname=host) as s:
            s.settimeout(10)
            s.connect((host, port))
            cert = s.getpeercert()
            proto = s.version()

        # Parse expiry
        not_after = cert.get("notAfter", "")
        not_before = cert.get("notBefore", "")

        try:
            expiry_dt = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
            days_left = (expiry_dt - datetime.now(timezone.utc)).days
        except Exception:
            days_left = -1

        san = [x[1] for x in cert.get("subjectAltName", [])]
        issuer = dict(x[0] for x in cert.get("issuer", []))
        subject = dict(x[0] for x in cert.get("subject", []))

        status = "OK"
        if days_left < 0:
            status = "EXPIRED"
        elif days_left < 7:
            status = "CRITICAL"
        elif days_left < 30:
            status = "WARNING"

        return json.dumps({
            "host": host,
            "port": port,
            "status": status,
            "valid": days_left > 0,
            "days_until_expiry": days_left,
            "not_before": not_before,
            "not_after": not_after,
            "issuer": issuer,
            "subject": subject,
            "san": san[:20],
            "protocol": proto,
        }, indent=2)
    except ssl.SSLCertVerificationError as exc:
        return json.dumps({"host": host, "status": "INVALID", "valid": False, "error": str(exc)})
    except Exception as exc:
        return json.dumps({"host": host, "status": "ERROR", "valid": False, "error": str(exc)})


async def _net_http_check_handler(args: Dict[str, Any]) -> str:
    """Verifica respuesta HTTP de un host."""
    host = args.get("host", "").strip()
    if not host:
        return "Error: host es requerido"

    url = host if host.startswith("http") else f"https://{host}"

    try:
        import aiohttp
        import time
        start = time.monotonic()
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=15),
                allow_redirects=True,
                ssl=False,
            ) as resp:
                elapsed = (time.monotonic() - start) * 1000
                headers = dict(resp.headers)
                security_headers = {
                    "Strict-Transport-Security": headers.get("Strict-Transport-Security", "MISSING"),
                    "Content-Security-Policy": headers.get("Content-Security-Policy", "MISSING"),
                    "X-Frame-Options": headers.get("X-Frame-Options", "MISSING"),
                    "X-Content-Type-Options": headers.get("X-Content-Type-Options", "MISSING"),
                    "X-XSS-Protection": headers.get("X-XSS-Protection", "MISSING"),
                }
                return json.dumps({
                    "url": str(resp.url),
                    "status": resp.status,
                    "response_time_ms": round(elapsed, 1),
                    "server": headers.get("Server", ""),
                    "security_headers": security_headers,
                    "redirect_chain": [str(h.url) for h in resp.history] if resp.history else [],
                }, indent=2)
    except ImportError:
        import urllib.request
        import time
        start = time.monotonic()
        req = urllib.request.Request(url, headers={"User-Agent": "SOMER-Monitor/1.0"})
        try:
            resp = urllib.request.urlopen(req, timeout=15)
            elapsed = (time.monotonic() - start) * 1000
            return json.dumps({
                "url": url,
                "status": resp.status,
                "response_time_ms": round(elapsed, 1),
                "server": resp.headers.get("Server", ""),
            }, indent=2)
        except Exception as exc:
            return json.dumps({"url": url, "status": "DOWN", "error": str(exc)})
    except Exception as exc:
        return json.dumps({"url": url, "status": "DOWN", "error": str(exc)})


async def _net_dns_health_handler(args: Dict[str, Any]) -> str:
    """Verifica salud DNS de un dominio."""
    domain = args.get("domain", "").strip().replace("https://", "").replace("http://", "").split("/")[0]
    if not domain:
        return "Error: domain es requerido"

    results: Dict[str, Any] = {"domain": domain, "records": {}, "health": []}

    record_types = ["A", "AAAA", "MX", "NS", "TXT", "SOA"]
    for rtype in record_types:
        try:
            result = subprocess.run(
                ["dig", "+short", rtype, domain],
                capture_output=True, text=True, timeout=10,
            )
            records = [r.strip() for r in result.stdout.strip().split("\n") if r.strip()]
            results["records"][rtype] = records
        except Exception:
            results["records"][rtype] = []

    # Health checks
    if not results["records"].get("A"):
        results["health"].append({"check": "A record", "status": "FAIL", "detail": "No A record found"})
    else:
        results["health"].append({"check": "A record", "status": "OK", "detail": f"{len(results['records']['A'])} records"})

    if not results["records"].get("NS"):
        results["health"].append({"check": "NS records", "status": "WARN", "detail": "No NS records found"})
    else:
        results["health"].append({"check": "NS records", "status": "OK", "detail": f"{len(results['records']['NS'])} nameservers"})

    # SPF check
    txt_records = results["records"].get("TXT", [])
    has_spf = any("v=spf1" in t for t in txt_records)
    has_dmarc = False

    try:
        dmarc_result = subprocess.run(
            ["dig", "+short", "TXT", f"_dmarc.{domain}"],
            capture_output=True, text=True, timeout=10,
        )
        has_dmarc = "v=DMARC1" in dmarc_result.stdout
    except Exception:
        pass

    results["health"].append({
        "check": "SPF", "status": "OK" if has_spf else "WARN",
        "detail": "SPF record present" if has_spf else "No SPF record — email spoofing risk",
    })
    results["health"].append({
        "check": "DMARC", "status": "OK" if has_dmarc else "WARN",
        "detail": "DMARC record present" if has_dmarc else "No DMARC record — email spoofing risk",
    })

    return _truncate(json.dumps(results, indent=2, ensure_ascii=False))


async def _net_full_check_handler(args: Dict[str, Any]) -> str:
    """Pipeline completo de monitoreo: ping + HTTP + cert + DNS."""
    host = args.get("host", "").strip().replace("https://", "").replace("http://", "").split("/")[0]
    if not host:
        return "Error: host es requerido"

    results: Dict[str, Any] = {"host": host, "checked_at": datetime.now().isoformat(), "checks": {}}

    # Ping
    ping_result = await _net_ping_handler({"host": host, "count": 3})
    results["checks"]["ping"] = json.loads(ping_result)

    # HTTP
    http_result = await _net_http_check_handler({"host": host})
    results["checks"]["http"] = json.loads(http_result)

    # Cert
    cert_result = await _net_cert_check_handler({"host": host})
    results["checks"]["cert"] = json.loads(cert_result)

    # DNS
    dns_result = await _net_dns_health_handler({"domain": host})
    results["checks"]["dns"] = json.loads(dns_result)

    # Overall status
    statuses = []
    if results["checks"]["ping"].get("reachable"):
        statuses.append("OK")
    else:
        statuses.append("DOWN")
    if results["checks"]["cert"].get("status") in ("OK",):
        statuses.append("OK")
    elif results["checks"]["cert"].get("status") in ("WARNING", "CRITICAL"):
        statuses.append(results["checks"]["cert"]["status"])

    if "DOWN" in statuses:
        results["overall"] = "DOWN"
    elif "CRITICAL" in statuses:
        results["overall"] = "CRITICAL"
    elif "WARNING" in statuses:
        results["overall"] = "WARNING"
    else:
        results["overall"] = "OK"

    return _truncate(json.dumps(results, indent=2, ensure_ascii=False), 12000)


# ── Registro ─────────────────────────────────────────────────


def register_network_tools(registry: ToolRegistry) -> None:
    """Registra las tools de monitoreo de red en el registry."""

    registry.register(ToolDefinition(
        id="net_full_check",
        name="net_full_check",
        description=(
            "Verificación COMPLETA de un host: ping + HTTP + certificado SSL + DNS. "
            "USA ESTA HERRAMIENTA cuando el usuario pregunte si un sitio está online, "
            "quiera verificar un servidor, o pida monitoreo."
        ),
        parameters={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Dominio o IP a verificar"},
            },
            "required": ["host"],
        },
        handler=_net_full_check_handler,
        section=ToolSection.MONITORING,
        timeout_secs=120,
    ))

    registry.register(ToolDefinition(
        id="net_ping",
        name="net_ping",
        description="Ping a un host con estadísticas (RTT, packet loss).",
        parameters={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Host o IP"},
                "count": {"type": "integer", "description": "Número de pings (max 20)", "default": 4},
            },
            "required": ["host"],
        },
        handler=_net_ping_handler,
        section=ToolSection.MONITORING,
        timeout_secs=30,
    ))

    registry.register(ToolDefinition(
        id="net_traceroute",
        name="net_traceroute",
        description="Traceroute a un host — muestra la ruta de red.",
        parameters={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Host o IP destino"},
            },
            "required": ["host"],
        },
        handler=_net_traceroute_handler,
        section=ToolSection.MONITORING,
        timeout_secs=60,
    ))

    registry.register(ToolDefinition(
        id="net_cert_check",
        name="net_cert_check",
        description="Verifica certificado SSL (emisor, expiración, validez).",
        parameters={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Dominio a verificar"},
                "port": {"type": "integer", "description": "Puerto (default 443)", "default": 443},
            },
            "required": ["host"],
        },
        handler=_net_cert_check_handler,
        section=ToolSection.MONITORING,
        timeout_secs=15,
    ))

    registry.register(ToolDefinition(
        id="net_http_check",
        name="net_http_check",
        description="Verifica respuesta HTTP (status, timing, security headers).",
        parameters={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "URL o dominio a verificar"},
            },
            "required": ["host"],
        },
        handler=_net_http_check_handler,
        section=ToolSection.MONITORING,
        timeout_secs=20,
    ))

    registry.register(ToolDefinition(
        id="net_dns_health",
        name="net_dns_health",
        description="Verifica salud DNS de un dominio (registros, SPF, DMARC).",
        parameters={
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Dominio a verificar"},
            },
            "required": ["domain"],
        },
        handler=_net_dns_health_handler,
        section=ToolSection.MONITORING,
        timeout_secs=30,
    ))
