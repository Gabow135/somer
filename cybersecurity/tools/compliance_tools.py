"""Tools de compliance — OWASP Top 10, PCI-DSS, GDPR, headers, SSL checks."""

from __future__ import annotations

import json
import logging
import re
import socket
import ssl
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict

from agents.tools.registry import ToolDefinition, ToolRegistry, ToolSection

logger = logging.getLogger(__name__)

_MAX_RESPONSE = 8000


def _truncate(text: str, max_len: int = _MAX_RESPONSE) -> str:
    if len(text) > max_len:
        return text[:max_len] + "\n...(truncado)"
    return text


async def _http_get(url: str, headers: dict = None) -> Dict[str, Any]:
    """GET request."""
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers or {}, timeout=aiohttp.ClientTimeout(total=20), ssl=False) as resp:
                return {"status": resp.status, "headers": dict(resp.headers), "data": await resp.text()}
    except ImportError:
        import urllib.request
        req = urllib.request.Request(url, headers=headers or {})
        resp = urllib.request.urlopen(req, timeout=20)
        return {"status": resp.status, "headers": dict(resp.headers), "data": resp.read().decode()}


# ── Handlers ─────────────────────────────────────────────────


async def _compliance_headers_handler(args: Dict[str, Any]) -> str:
    """Verifica security headers."""
    domain = args.get("domain", "").strip()
    if not domain:
        return "Error: domain es requerido"

    url = domain if domain.startswith("http") else f"https://{domain}"
    checks = []

    try:
        resp = await _http_get(url)
        h = resp.get("headers", {})

        required_headers = {
            "Strict-Transport-Security": {"severity": "HIGH", "desc": "HSTS — protege contra downgrade HTTPS"},
            "Content-Security-Policy": {"severity": "HIGH", "desc": "CSP — previene XSS e inyección de contenido"},
            "X-Frame-Options": {"severity": "MEDIUM", "desc": "Previene clickjacking"},
            "X-Content-Type-Options": {"severity": "MEDIUM", "desc": "Previene MIME sniffing"},
            "Referrer-Policy": {"severity": "LOW", "desc": "Controla info enviada en Referer header"},
            "Permissions-Policy": {"severity": "LOW", "desc": "Controla acceso a APIs del navegador"},
            "X-XSS-Protection": {"severity": "LOW", "desc": "Filtro XSS del navegador (legacy)"},
        }

        for header, info in required_headers.items():
            value = h.get(header, "")
            checks.append({
                "header": header,
                "status": "PASS" if value else "FAIL",
                "value": value or "MISSING",
                "severity": info["severity"],
                "description": info["desc"],
            })

        # Check for info leaking headers
        leak_headers = ["Server", "X-Powered-By", "X-AspNet-Version"]
        for lh in leak_headers:
            if h.get(lh):
                checks.append({
                    "header": lh,
                    "status": "WARN",
                    "value": h[lh],
                    "severity": "LOW",
                    "description": f"Header expone información del servidor: {h[lh]}",
                })

        passed = sum(1 for c in checks if c["status"] == "PASS")
        total = sum(1 for c in checks if c["status"] in ("PASS", "FAIL"))
        score = round(passed / total * 100) if total else 0

        return json.dumps({
            "domain": domain,
            "checks": checks,
            "score": f"{passed}/{total} ({score}%)",
            "grade": "A" if score >= 85 else "B" if score >= 70 else "C" if score >= 50 else "F",
        }, indent=2)
    except Exception as exc:
        return json.dumps({"domain": domain, "error": str(exc)})


async def _compliance_ssl_handler(args: Dict[str, Any]) -> str:
    """Verifica TLS/SSL compliance."""
    domain = args.get("domain", "").strip().replace("https://", "").replace("http://", "").split("/")[0]
    if not domain:
        return "Error: domain es requerido"

    checks = []

    try:
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(socket.socket(), server_hostname=domain) as s:
            s.settimeout(10)
            s.connect((domain, 443))
            cert = s.getpeercert()
            proto = s.version()
            cipher = s.cipher()

        # TLS version check
        checks.append({
            "check": "TLS Version",
            "status": "PASS" if proto in ("TLSv1.2", "TLSv1.3") else "FAIL",
            "value": proto,
            "severity": "HIGH",
            "recommendation": "Use TLS 1.2 or higher" if proto not in ("TLSv1.2", "TLSv1.3") else "",
        })

        # Cipher suite
        if cipher:
            weak_ciphers = ["RC4", "DES", "3DES", "MD5", "NULL", "EXPORT"]
            is_weak = any(w in cipher[0].upper() for w in weak_ciphers)
            checks.append({
                "check": "Cipher Suite",
                "status": "FAIL" if is_weak else "PASS",
                "value": cipher[0],
                "severity": "HIGH" if is_weak else "INFO",
            })

        # Certificate validity
        not_after = cert.get("notAfter", "")
        try:
            expiry = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
            days_left = (expiry - datetime.now(timezone.utc)).days
            checks.append({
                "check": "Certificate Expiry",
                "status": "PASS" if days_left > 30 else "WARN" if days_left > 7 else "FAIL",
                "value": f"{days_left} days remaining",
                "severity": "HIGH" if days_left < 7 else "MEDIUM" if days_left < 30 else "INFO",
            })
        except Exception:
            pass

        # SAN check
        san = [x[1] for x in cert.get("subjectAltName", [])]
        checks.append({
            "check": "SAN Coverage",
            "status": "PASS" if domain in san or f"*.{'.'.join(domain.split('.')[1:])}" in san else "WARN",
            "value": f"{len(san)} SANs",
            "severity": "MEDIUM",
        })

        passed = sum(1 for c in checks if c["status"] == "PASS")
        return json.dumps({"domain": domain, "checks": checks, "score": f"{passed}/{len(checks)}"}, indent=2)
    except Exception as exc:
        return json.dumps({"domain": domain, "error": str(exc)})


async def _compliance_owasp_handler(args: Dict[str, Any]) -> str:
    """Verifica OWASP Top 10 2021."""
    domain = args.get("domain", "").strip()
    if not domain:
        return "Error: domain es requerido"

    url = domain if domain.startswith("http") else f"https://{domain}"
    checks = []

    # Headers check (for A05: Security Misconfiguration)
    headers_result = await _compliance_headers_handler({"domain": domain})
    headers_data = json.loads(headers_result)

    # A01: Broken Access Control
    checks.append({
        "id": "A01", "name": "Broken Access Control",
        "status": "CHECK", "severity": "CRITICAL",
        "detail": "Requires manual testing — check for exposed admin panels, IDOR, etc.",
    })

    # A02: Cryptographic Failures
    ssl_result = await _compliance_ssl_handler({"domain": domain})
    ssl_data = json.loads(ssl_result)
    ssl_pass = all(c.get("status") == "PASS" for c in ssl_data.get("checks", []))
    checks.append({
        "id": "A02", "name": "Cryptographic Failures",
        "status": "PASS" if ssl_pass else "WARN",
        "severity": "HIGH",
        "detail": f"SSL/TLS: {ssl_data.get('score', 'N/A')}",
    })

    # A03: Injection
    checks.append({
        "id": "A03", "name": "Injection",
        "status": "CHECK", "severity": "CRITICAL",
        "detail": "Requires active testing — use security-scanner for SQLi/XSS checks.",
    })

    # A04: Insecure Design
    checks.append({
        "id": "A04", "name": "Insecure Design",
        "status": "N/A", "severity": "HIGH",
        "detail": "Requires architecture review — cannot be automated.",
    })

    # A05: Security Misconfiguration
    header_score = headers_data.get("grade", "F")
    checks.append({
        "id": "A05", "name": "Security Misconfiguration",
        "status": "PASS" if header_score in ("A", "B") else "FAIL",
        "severity": "HIGH",
        "detail": f"Security headers: {headers_data.get('score', 'N/A')} (grade {header_score})",
    })

    # A06: Vulnerable and Outdated Components
    try:
        resp = await _http_get(url)
        body = resp.get("data", "")
        libs = re.findall(r"(?:jquery|bootstrap|angular|react|vue)[.\-/](\d+\.\d+(?:\.\d+)?)", body, re.I)
        checks.append({
            "id": "A06", "name": "Vulnerable Components",
            "status": "WARN" if libs else "CHECK",
            "severity": "HIGH",
            "detail": f"Detected versions: {', '.join(libs[:5])}" if libs else "No version info found in HTML — manual check needed",
        })
    except Exception:
        checks.append({"id": "A06", "name": "Vulnerable Components", "status": "CHECK", "severity": "HIGH"})

    # A07: Identification and Authentication Failures
    checks.append({
        "id": "A07", "name": "Auth Failures",
        "status": "CHECK", "severity": "HIGH",
        "detail": "Requires manual testing — check login flows, session management.",
    })

    # A08: Software and Data Integrity Failures
    try:
        resp = await _http_get(url)
        body = resp.get("data", "")
        has_sri = "integrity=" in body
        checks.append({
            "id": "A08", "name": "Integrity Failures",
            "status": "PASS" if has_sri else "WARN",
            "severity": "MEDIUM",
            "detail": "SRI found on external scripts" if has_sri else "No SRI on external scripts",
        })
    except Exception:
        checks.append({"id": "A08", "name": "Integrity Failures", "status": "CHECK", "severity": "MEDIUM"})

    # A09: Logging Failures
    checks.append({
        "id": "A09", "name": "Logging Failures",
        "status": "N/A", "severity": "HIGH",
        "detail": "Requires internal access — cannot verify externally.",
    })

    # A10: SSRF
    checks.append({
        "id": "A10", "name": "SSRF",
        "status": "CHECK", "severity": "HIGH",
        "detail": "Requires active testing — use security-scanner.",
    })

    passed = sum(1 for c in checks if c["status"] == "PASS")
    total_verifiable = sum(1 for c in checks if c["status"] in ("PASS", "FAIL", "WARN"))

    return _truncate(json.dumps({
        "domain": domain,
        "standard": "OWASP Top 10 (2021)",
        "checks": checks,
        "score": f"{passed}/{total_verifiable} verified checks pass",
        "recommendation": "Run security-scanner for A01/A03/A07 active testing",
    }, indent=2, ensure_ascii=False))


async def _compliance_pci_handler(args: Dict[str, Any]) -> str:
    """Verifica PCI-DSS v4.0 básico."""
    domain = args.get("domain", "").strip()
    if not domain:
        return "Error: domain es requerido"

    checks = []

    # Req 2: Secure default configs
    headers_result = await _compliance_headers_handler({"domain": domain})
    headers_data = json.loads(headers_result)
    server_exposed = any(c["header"] == "Server" and c["status"] == "WARN" for c in headers_data.get("checks", []))
    checks.append({
        "req": "2.2", "name": "Secure Configurations",
        "status": "WARN" if server_exposed else "PASS",
        "detail": "Server header exposes version info" if server_exposed else "No server info leaked",
    })

    # Req 4: Strong cryptography
    ssl_result = await _compliance_ssl_handler({"domain": domain})
    ssl_data = json.loads(ssl_result)
    ssl_ok = all(c.get("status") == "PASS" for c in ssl_data.get("checks", []))
    checks.append({
        "req": "4.1", "name": "Strong Cryptography in Transit",
        "status": "PASS" if ssl_ok else "FAIL",
        "detail": f"SSL/TLS: {ssl_data.get('score', 'N/A')}",
    })

    # Req 6: Secure software
    hsts = any(c["header"] == "Strict-Transport-Security" and c["status"] == "PASS"
               for c in headers_data.get("checks", []))
    csp = any(c["header"] == "Content-Security-Policy" and c["status"] == "PASS"
              for c in headers_data.get("checks", []))
    checks.append({
        "req": "6.2", "name": "Secure Development",
        "status": "PASS" if hsts and csp else "WARN",
        "detail": f"HSTS: {'Yes' if hsts else 'No'}, CSP: {'Yes' if csp else 'No'}",
    })

    # Req 8: Access management
    checks.append({
        "req": "8.3", "name": "Access Authentication",
        "status": "CHECK",
        "detail": "Requires manual verification of authentication mechanisms",
    })

    passed = sum(1 for c in checks if c["status"] == "PASS")
    total = sum(1 for c in checks if c["status"] in ("PASS", "FAIL"))

    return json.dumps({
        "domain": domain,
        "standard": "PCI-DSS v4.0 (basic)",
        "checks": checks,
        "score": f"{passed}/{total}" if total else "N/A",
    }, indent=2)


async def _compliance_gdpr_handler(args: Dict[str, Any]) -> str:
    """Verifica GDPR básico."""
    domain = args.get("domain", "").strip()
    if not domain:
        return "Error: domain es requerido"

    url = domain if domain.startswith("http") else f"https://{domain}"
    checks = []

    try:
        resp = await _http_get(url)
        body = resp.get("data", "").lower()

        # Privacy policy
        has_privacy = any(term in body for term in ["privacy policy", "política de privacidad", "datenschutz", "privacidad"])
        checks.append({
            "check": "Privacy Policy",
            "status": "PASS" if has_privacy else "FAIL",
            "detail": "Privacy policy link found" if has_privacy else "No privacy policy link detected",
        })

        # Cookie consent
        has_cookies = any(term in body for term in ["cookie", "consent", "consentimiento", "cookies"])
        checks.append({
            "check": "Cookie Consent",
            "status": "PASS" if has_cookies else "WARN",
            "detail": "Cookie/consent mechanism detected" if has_cookies else "No cookie consent detected",
        })

        # Data processing
        has_data_processing = any(term in body for term in [
            "data processing", "procesamiento de datos", "tratamiento de datos",
            "data controller", "responsable del tratamiento",
        ])
        checks.append({
            "check": "Data Processing Disclosure",
            "status": "PASS" if has_data_processing else "WARN",
            "detail": "Data processing info found" if has_data_processing else "No explicit data processing disclosure",
        })

        # DPO contact
        has_dpo = any(term in body for term in ["dpo", "data protection officer", "delegado de protección"])
        checks.append({
            "check": "DPO Contact",
            "status": "PASS" if has_dpo else "WARN",
            "detail": "DPO reference found" if has_dpo else "No DPO contact found",
        })

        # HTTPS
        checks.append({
            "check": "HTTPS",
            "status": "PASS" if url.startswith("https") else "FAIL",
            "detail": "Site uses HTTPS" if url.startswith("https") else "Site not using HTTPS",
        })

    except Exception as exc:
        return json.dumps({"domain": domain, "error": str(exc)})

    passed = sum(1 for c in checks if c["status"] == "PASS")
    return json.dumps({
        "domain": domain,
        "standard": "GDPR (basic)",
        "checks": checks,
        "score": f"{passed}/{len(checks)}",
    }, indent=2)


async def _compliance_full_audit_handler(args: Dict[str, Any]) -> str:
    """Pipeline completo de compliance."""
    domain = args.get("domain", "").strip()
    standards = args.get("standards", ["owasp", "pci", "gdpr", "headers", "ssl"])

    if not domain:
        return "Error: domain es requerido"

    results: Dict[str, Any] = {"domain": domain, "audits": {}}

    if "owasp" in standards:
        r = await _compliance_owasp_handler({"domain": domain})
        results["audits"]["owasp_top10"] = json.loads(r)

    if "pci" in standards:
        r = await _compliance_pci_handler({"domain": domain})
        results["audits"]["pci_dss"] = json.loads(r)

    if "gdpr" in standards:
        r = await _compliance_gdpr_handler({"domain": domain})
        results["audits"]["gdpr"] = json.loads(r)

    if "headers" in standards:
        r = await _compliance_headers_handler({"domain": domain})
        results["audits"]["security_headers"] = json.loads(r)

    if "ssl" in standards:
        r = await _compliance_ssl_handler({"domain": domain})
        results["audits"]["ssl_tls"] = json.loads(r)

    return _truncate(json.dumps(results, indent=2, ensure_ascii=False), 12000)


# ── Registro ─────────────────────────────────────────────────


def register_compliance_tools(registry: ToolRegistry) -> None:
    """Registra las tools de compliance."""

    registry.register(ToolDefinition(
        id="compliance_full_audit",
        name="compliance_full_audit",
        description=(
            "Auditoría de compliance COMPLETA: OWASP Top 10 + PCI-DSS + GDPR + "
            "security headers + SSL/TLS. USA ESTA HERRAMIENTA cuando el usuario "
            "pida verificar cumplimiento, compliance, o estándares de seguridad."
        ),
        parameters={
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Dominio a auditar"},
                "standards": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["owasp", "pci", "gdpr", "headers", "ssl"]},
                    "description": "Estándares a verificar (default: todos)",
                },
            },
            "required": ["domain"],
        },
        handler=_compliance_full_audit_handler,
        section=ToolSection.SECURITY,
        timeout_secs=120,
    ))

    registry.register(ToolDefinition(
        id="compliance_owasp_check",
        name="compliance_owasp_check",
        description="Verifica OWASP Top 10 2021 contra un dominio.",
        parameters={
            "type": "object",
            "properties": {"domain": {"type": "string", "description": "Dominio"}},
            "required": ["domain"],
        },
        handler=_compliance_owasp_handler,
        section=ToolSection.SECURITY,
        timeout_secs=60,
    ))

    registry.register(ToolDefinition(
        id="compliance_pci_check",
        name="compliance_pci_check",
        description="Verifica PCI-DSS v4.0 básico (TLS, headers, configs).",
        parameters={
            "type": "object",
            "properties": {"domain": {"type": "string", "description": "Dominio"}},
            "required": ["domain"],
        },
        handler=_compliance_pci_handler,
        section=ToolSection.SECURITY,
        timeout_secs=60,
    ))

    registry.register(ToolDefinition(
        id="compliance_gdpr_check",
        name="compliance_gdpr_check",
        description="Verifica GDPR básico (privacy policy, cookies, DPO).",
        parameters={
            "type": "object",
            "properties": {"domain": {"type": "string", "description": "Dominio"}},
            "required": ["domain"],
        },
        handler=_compliance_gdpr_handler,
        section=ToolSection.SECURITY,
        timeout_secs=30,
    ))

    registry.register(ToolDefinition(
        id="compliance_headers_check",
        name="compliance_headers_check",
        description="Verifica security headers (CSP, HSTS, X-Frame, etc.).",
        parameters={
            "type": "object",
            "properties": {"domain": {"type": "string", "description": "Dominio"}},
            "required": ["domain"],
        },
        handler=_compliance_headers_handler,
        section=ToolSection.SECURITY,
        timeout_secs=15,
    ))

    registry.register(ToolDefinition(
        id="compliance_ssl_check",
        name="compliance_ssl_check",
        description="Verifica TLS/SSL compliance (versión, cipher, certificado).",
        parameters={
            "type": "object",
            "properties": {"domain": {"type": "string", "description": "Dominio"}},
            "required": ["domain"],
        },
        handler=_compliance_ssl_handler,
        section=ToolSection.SECURITY,
        timeout_secs=15,
    ))
