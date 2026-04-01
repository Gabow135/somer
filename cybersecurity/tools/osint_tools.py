"""Tools OSINT — investigación de fuentes abiertas: breaches, exposición, Shodan, perfiles."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import socket
import ssl
from datetime import datetime
from typing import Any, Dict, List, Optional

from agents.tools.registry import ToolDefinition, ToolRegistry, ToolSection

logger = logging.getLogger(__name__)

_MAX_RESPONSE = 8000


def _truncate(text: str, max_len: int = _MAX_RESPONSE) -> str:
    if len(text) > max_len:
        return text[:max_len] + "\n...(truncado)"
    return text


# ── Helpers ──────────────────────────────────────────────────


async def _http_get(url: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """GET request async usando aiohttp o urllib fallback."""
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                data = await resp.text()
                return {"status": resp.status, "data": data}
    except ImportError:
        import urllib.request
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return {"status": resp.status, "data": resp.read().decode()}


def _whois_lookup(domain: str) -> Dict[str, Any]:
    """WHOIS básico via socket."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(10)
        s.connect(("whois.iana.org", 43))
        s.send((domain + "\r\n").encode())
        data = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
        s.close()
        return {"raw": data.decode(errors="replace")}
    except Exception as exc:
        return {"error": str(exc)}


# ── Handlers ─────────────────────────────────────────────────


async def _osint_email_breach_handler(args: Dict[str, Any]) -> str:
    """Verifica si un email aparece en filtraciones conocidas."""
    email = args.get("email", "").strip()
    if not email:
        return "Error: email es requerido"

    results: Dict[str, Any] = {"email": email, "breaches": [], "checked_at": datetime.now().isoformat()}

    # HIBP API (requiere API key)
    hibp_key = os.environ.get("HIBP_API_KEY", "")
    if hibp_key:
        try:
            resp = await _http_get(
                f"https://haveibeenpwned.com/api/v3/breachedaccount/{email}?truncateResponse=false",
                headers={"hibp-api-key": hibp_key, "user-agent": "SOMER-OSINT"},
            )
            if resp["status"] == 200:
                breaches = json.loads(resp["data"])
                for b in breaches:
                    results["breaches"].append({
                        "name": b.get("Name", ""),
                        "date": b.get("BreachDate", ""),
                        "data_classes": b.get("DataClasses", []),
                        "description": b.get("Description", "")[:200],
                        "is_verified": b.get("IsVerified", False),
                    })
            elif resp["status"] == 404:
                results["message"] = "No se encontraron filtraciones para este email"
            else:
                results["hibp_status"] = resp["status"]
        except Exception as exc:
            results["hibp_error"] = str(exc)
    else:
        results["hibp_note"] = "HIBP_API_KEY no configurada — set env var para habilitar"

    # Breach Directory (fallback gratuito)
    try:
        resp = await _http_get(
            f"https://breachdirectory.org/api/lookup?email={email}",
        )
        if resp["status"] == 200:
            bd_data = json.loads(resp["data"])
            if bd_data.get("found"):
                results["breach_directory"] = {
                    "found": True,
                    "sources_count": bd_data.get("result_count", 0),
                }
    except Exception:
        pass

    results["total_breaches"] = len(results["breaches"])
    results["risk_level"] = (
        "CRITICAL" if len(results["breaches"]) > 5
        else "HIGH" if len(results["breaches"]) > 2
        else "MEDIUM" if len(results["breaches"]) > 0
        else "LOW"
    )

    return _truncate(json.dumps(results, indent=2, ensure_ascii=False))


async def _osint_domain_exposure_handler(args: Dict[str, Any]) -> str:
    """Analiza exposición pública de un dominio."""
    domain = args.get("domain", "").strip().replace("https://", "").replace("http://", "").split("/")[0]
    if not domain:
        return "Error: domain es requerido"

    results: Dict[str, Any] = {"domain": domain, "checks": {}}

    # DNS records
    try:
        ips = socket.getaddrinfo(domain, None)
        results["checks"]["dns"] = {
            "resolved": True,
            "ips": list(set(addr[4][0] for addr in ips)),
        }
    except Exception as exc:
        results["checks"]["dns"] = {"resolved": False, "error": str(exc)}

    # SSL cert info
    try:
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(socket.socket(), server_hostname=domain) as s:
            s.settimeout(10)
            s.connect((domain, 443))
            cert = s.getpeercert()
            results["checks"]["ssl"] = {
                "valid": True,
                "issuer": dict(x[0] for x in cert.get("issuer", [])),
                "subject": dict(x[0] for x in cert.get("subject", [])),
                "not_after": cert.get("notAfter", ""),
                "san": [x[1] for x in cert.get("subjectAltName", [])],
            }
    except Exception as exc:
        results["checks"]["ssl"] = {"valid": False, "error": str(exc)}

    # WHOIS
    whois_data = _whois_lookup(domain)
    if "error" not in whois_data:
        results["checks"]["whois"] = {"available": True, "preview": whois_data["raw"][:500]}
    else:
        results["checks"]["whois"] = {"available": False}

    # CT logs (crt.sh)
    try:
        resp = await _http_get(f"https://crt.sh/?q=%.{domain}&output=json")
        if resp["status"] == 200:
            certs = json.loads(resp["data"])
            unique_names = set()
            for c in certs[:100]:
                name = c.get("name_value", "")
                for n in name.split("\n"):
                    unique_names.add(n.strip())
            results["checks"]["ct_logs"] = {
                "certificates_found": len(certs),
                "unique_subdomains": sorted(unique_names)[:50],
            }
    except Exception as exc:
        results["checks"]["ct_logs"] = {"error": str(exc)}

    # HTTP headers exposure
    try:
        resp = await _http_get(f"https://{domain}/")
        if resp["status"]:
            results["checks"]["http"] = {"reachable": True, "status": resp["status"]}
    except Exception:
        results["checks"]["http"] = {"reachable": False}

    return _truncate(json.dumps(results, indent=2, ensure_ascii=False))


async def _osint_shodan_lookup_handler(args: Dict[str, Any]) -> str:
    """Busca host/IP en Shodan."""
    target = args.get("target", "").strip()
    if not target:
        return "Error: target (IP o dominio) es requerido"

    api_key = os.environ.get("SHODAN_API_KEY", "")
    if not api_key:
        return json.dumps({
            "error": "SHODAN_API_KEY no configurada",
            "note": "Configura: export SHODAN_API_KEY=tu_key",
            "alternative": "Usa osint_domain_exposure para un análisis básico sin Shodan",
        })

    # Resolver dominio a IP si es necesario
    ip = target
    try:
        socket.inet_aton(target)
    except socket.error:
        try:
            ip = socket.gethostbyname(target)
        except Exception:
            return f"Error: no se pudo resolver {target}"

    try:
        resp = await _http_get(f"https://api.shodan.io/shodan/host/{ip}?key={api_key}")
        if resp["status"] == 200:
            data = json.loads(resp["data"])
            result = {
                "ip": ip,
                "original_target": target,
                "org": data.get("org", ""),
                "os": data.get("os", ""),
                "ports": data.get("ports", []),
                "vulns": data.get("vulns", []),
                "hostnames": data.get("hostnames", []),
                "services": [],
            }
            for svc in data.get("data", [])[:20]:
                result["services"].append({
                    "port": svc.get("port"),
                    "transport": svc.get("transport", "tcp"),
                    "product": svc.get("product", ""),
                    "version": svc.get("version", ""),
                    "banner_preview": svc.get("data", "")[:200],
                })
            return _truncate(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            return json.dumps({"error": f"Shodan API returned {resp['status']}", "ip": ip})
    except Exception as exc:
        return json.dumps({"error": str(exc), "ip": ip})


async def _osint_social_profiles_handler(args: Dict[str, Any]) -> str:
    """Busca perfiles en redes sociales asociados a un username."""
    username = args.get("username", "").strip().lstrip("@")
    if not username:
        return "Error: username es requerido"

    platforms = {
        "GitHub": f"https://github.com/{username}",
        "Twitter/X": f"https://x.com/{username}",
        "LinkedIn": f"https://linkedin.com/in/{username}",
        "Instagram": f"https://instagram.com/{username}",
        "Reddit": f"https://reddit.com/user/{username}",
        "Medium": f"https://medium.com/@{username}",
        "Dev.to": f"https://dev.to/{username}",
        "Keybase": f"https://keybase.io/{username}",
        "HackerOne": f"https://hackerone.com/{username}",
        "Telegram": f"https://t.me/{username}",
    }

    results: Dict[str, Any] = {"username": username, "profiles": [], "not_found": []}

    for platform, url in platforms.items():
        try:
            resp = await _http_get(url)
            if resp["status"] == 200:
                results["profiles"].append({"platform": platform, "url": url, "status": "found"})
            else:
                results["not_found"].append(platform)
        except Exception:
            results["not_found"].append(platform)

    results["total_found"] = len(results["profiles"])
    return _truncate(json.dumps(results, indent=2, ensure_ascii=False))


async def _osint_corporate_intel_handler(args: Dict[str, Any]) -> str:
    """Información corporativa pública de un dominio."""
    domain = args.get("domain", "").strip().replace("https://", "").replace("http://", "").split("/")[0]
    if not domain:
        return "Error: domain es requerido"

    results: Dict[str, Any] = {"domain": domain, "intel": {}}

    # robots.txt
    try:
        resp = await _http_get(f"https://{domain}/robots.txt")
        if resp["status"] == 200:
            results["intel"]["robots_txt"] = {
                "found": True,
                "content_preview": resp["data"][:500],
                "disallowed_paths": re.findall(r"Disallow:\s*(.+)", resp["data"]),
            }
    except Exception:
        pass

    # sitemap.xml
    try:
        resp = await _http_get(f"https://{domain}/sitemap.xml")
        if resp["status"] == 200:
            urls = re.findall(r"<loc>(.*?)</loc>", resp["data"])
            results["intel"]["sitemap"] = {"found": True, "urls_count": len(urls), "sample_urls": urls[:10]}
    except Exception:
        pass

    # security.txt
    try:
        resp = await _http_get(f"https://{domain}/.well-known/security.txt")
        if resp["status"] == 200:
            results["intel"]["security_txt"] = {"found": True, "content": resp["data"][:500]}
    except Exception:
        pass

    # humans.txt
    try:
        resp = await _http_get(f"https://{domain}/humans.txt")
        if resp["status"] == 200:
            results["intel"]["humans_txt"] = {"found": True, "content": resp["data"][:300]}
    except Exception:
        pass

    # Email patterns (from MX)
    try:
        import subprocess
        mx_result = subprocess.run(
            ["dig", "+short", "MX", domain],
            capture_output=True, text=True, timeout=10,
        )
        if mx_result.stdout.strip():
            mx_records = [line.strip() for line in mx_result.stdout.strip().split("\n")]
            results["intel"]["email"] = {
                "mx_records": mx_records,
                "provider": (
                    "Google Workspace" if any("google" in m for m in mx_records)
                    else "Microsoft 365" if any("outlook" in m for m in mx_records)
                    else "Other"
                ),
            }
    except Exception:
        pass

    return _truncate(json.dumps(results, indent=2, ensure_ascii=False))


async def _osint_full_investigation_handler(args: Dict[str, Any]) -> str:
    """Pipeline OSINT completo."""
    target = args.get("target", "").strip()
    target_type = args.get("target_type", "auto")

    if not target:
        return "Error: target es requerido"

    results: Dict[str, Any] = {"target": target, "type": target_type, "phases": {}}

    # Auto-detect type
    if target_type == "auto":
        if "@" in target:
            target_type = "email"
        elif re.match(r"\d+\.\d+\.\d+\.\d+", target):
            target_type = "ip"
        else:
            target_type = "domain"

    results["type"] = target_type

    if target_type == "email":
        breach_result = await _osint_email_breach_handler({"email": target})
        results["phases"]["breach_check"] = json.loads(breach_result)

        username = target.split("@")[0]
        social_result = await _osint_social_profiles_handler({"username": username})
        results["phases"]["social_profiles"] = json.loads(social_result)

        domain = target.split("@")[1]
        exposure_result = await _osint_domain_exposure_handler({"domain": domain})
        results["phases"]["domain_exposure"] = json.loads(exposure_result)

    elif target_type in ("domain", "ip"):
        exposure_result = await _osint_domain_exposure_handler({"domain": target})
        results["phases"]["domain_exposure"] = json.loads(exposure_result)

        shodan_result = await _osint_shodan_lookup_handler({"target": target})
        results["phases"]["shodan"] = json.loads(shodan_result)

        if target_type == "domain":
            corp_result = await _osint_corporate_intel_handler({"domain": target})
            results["phases"]["corporate_intel"] = json.loads(corp_result)

    return _truncate(json.dumps(results, indent=2, ensure_ascii=False), 12000)


# ── Registro ─────────────────────────────────────────────────


def register_osint_tools(registry: ToolRegistry) -> None:
    """Registra las tools OSINT en el registry."""

    registry.register(ToolDefinition(
        id="osint_full_investigation",
        name="osint_full_investigation",
        description=(
            "Investigación OSINT COMPLETA de un target (email, dominio o IP). "
            "Ejecuta automáticamente: breach check, exposición de dominio, "
            "Shodan lookup, perfiles sociales e inteligencia corporativa. "
            "USA ESTA HERRAMIENTA cuando el usuario pida investigar, hacer OSINT "
            "o buscar información pública de un target."
        ),
        parameters={
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Email, dominio o IP a investigar",
                },
                "target_type": {
                    "type": "string",
                    "enum": ["auto", "email", "domain", "ip"],
                    "description": "Tipo de target (auto-detect si no se especifica)",
                },
            },
            "required": ["target"],
        },
        handler=_osint_full_investigation_handler,
        section=ToolSection.SECURITY,
        timeout_secs=120,
    ))

    registry.register(ToolDefinition(
        id="osint_email_breach",
        name="osint_email_breach",
        description="Verifica si un email aparece en filtraciones de datos conocidas (HIBP).",
        parameters={
            "type": "object",
            "properties": {
                "email": {"type": "string", "description": "Email a verificar"},
            },
            "required": ["email"],
        },
        handler=_osint_email_breach_handler,
        section=ToolSection.SECURITY,
        timeout_secs=30,
    ))

    registry.register(ToolDefinition(
        id="osint_domain_exposure",
        name="osint_domain_exposure",
        description="Analiza exposición pública de un dominio (DNS, SSL, WHOIS, CT logs).",
        parameters={
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Dominio a analizar"},
            },
            "required": ["domain"],
        },
        handler=_osint_domain_exposure_handler,
        section=ToolSection.SECURITY,
        timeout_secs=60,
    ))

    registry.register(ToolDefinition(
        id="osint_shodan_lookup",
        name="osint_shodan_lookup",
        description="Busca un host/IP en Shodan (servicios, puertos, vulnerabilidades).",
        parameters={
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "IP o dominio a buscar en Shodan"},
            },
            "required": ["target"],
        },
        handler=_osint_shodan_lookup_handler,
        section=ToolSection.SECURITY,
        timeout_secs=30,
    ))

    registry.register(ToolDefinition(
        id="osint_social_profiles",
        name="osint_social_profiles",
        description="Busca perfiles en redes sociales asociados a un username.",
        parameters={
            "type": "object",
            "properties": {
                "username": {"type": "string", "description": "Username a buscar (sin @)"},
            },
            "required": ["username"],
        },
        handler=_osint_social_profiles_handler,
        section=ToolSection.SECURITY,
        timeout_secs=60,
    ))

    registry.register(ToolDefinition(
        id="osint_corporate_intel",
        name="osint_corporate_intel",
        description="Recopila información corporativa pública de un dominio (robots, sitemap, security.txt, email provider).",
        parameters={
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Dominio corporativo a investigar"},
            },
            "required": ["domain"],
        },
        handler=_osint_corporate_intel_handler,
        section=ToolSection.SECURITY,
        timeout_secs=30,
    ))
