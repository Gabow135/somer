"""Escáneres de seguridad web — funciones async independientes.

Cada función ejecuta un chequeo específico y retorna su modelo tipado.
Solo escaneo pasivo + activo ligero (sin explotación).
"""

from __future__ import annotations

import asyncio
import logging
import re
import ssl
import socket
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx

from cybersecurity.types import (
    CookieAnalysis,
    CookieInfo,
    CORSAnalysis,
    CrawlResult,
    CSPAnalysis,
    DirectoryListingAnalysis,
    DiscoveredPath,
    DNSResult,
    EmailSecurityAnalysis,
    Finding,
    FormAnalysis,
    FormInfo,
    HeaderAnalysis,
    HtmlLeaksAnalysis,
    HttpMethodsAnalysis,
    HttpsRedirectAnalysis,
    MixedContentAnalysis,
    OpenPort,
    OpenRedirectResult,
    PathDiscoveryResult,
    PortScanResult,
    Severity,
    SRIAnalysis,
    SSLAnalysis,
    TechFingerprint,
    XSSResult,
)
from cybersecurity.utils import (
    extract_hostname,
    is_same_origin,
    normalize_url,
    parse_html_forms,
    parse_html_links,
    parse_set_cookie,
    sanitize_for_display,
)

logger = logging.getLogger(__name__)

# ── Headers de seguridad esperados ───────────────────────────

_SECURITY_HEADERS = [
    "Content-Security-Policy",
    "Strict-Transport-Security",
    "X-Content-Type-Options",
    "X-Frame-Options",
    "X-XSS-Protection",
    "Referrer-Policy",
    "Permissions-Policy",
    "Cross-Origin-Opener-Policy",
    "Cross-Origin-Resource-Policy",
    "Cross-Origin-Embedder-Policy",
]

_INFO_DISCLOSURE_HEADERS = ["Server", "X-Powered-By", "X-AspNet-Version"]

# ── Rutas comunes a probar ───────────────────────────────────

_COMMON_PATHS = [
    "/robots.txt", "/.env", "/.git/HEAD", "/.git/config",
    "/admin", "/admin/", "/login", "/wp-admin/",
    "/wp-login.php", "/.htaccess", "/.htpasswd",
    "/server-status", "/server-info", "/phpinfo.php",
    "/.DS_Store", "/backup/", "/config.json",
    "/api/", "/swagger.json", "/openapi.json",
    "/.well-known/security.txt", "/sitemap.xml",
    "/crossdomain.xml", "/clientaccesspolicy.xml",
    "/elmah.axd", "/trace.axd",
]

# ── Patrones de fingerprinting ───────────────────────────────

_TECH_PATTERNS: List[Tuple[str, str, str]] = [
    # (patrón regex, nombre tech, dónde buscar: "header", "body", "meta")
    (r"WordPress", "WordPress", "body"),
    (r"wp-content", "WordPress", "body"),
    (r"Joomla", "Joomla", "body"),
    (r"Drupal", "Drupal", "body"),
    (r"react", "React", "body"),
    (r"vue\.js|vuejs", "Vue.js", "body"),
    (r"angular", "Angular", "body"),
    (r"next\.js|nextjs|_next/", "Next.js", "body"),
    (r"nuxt", "Nuxt.js", "body"),
    (r"jquery", "jQuery", "body"),
    (r"bootstrap", "Bootstrap", "body"),
    (r"tailwindcss|tailwind", "Tailwind CSS", "body"),
    (r"nginx", "nginx", "header"),
    (r"Apache", "Apache", "header"),
    (r"cloudflare", "Cloudflare", "header"),
    (r"IIS", "Microsoft IIS", "header"),
    (r"Express", "Express.js", "header"),
    (r"PHP/[\d.]+", "PHP", "header"),
    (r"ASP\.NET", "ASP.NET", "header"),
    (r"Laravel", "Laravel", "body"),
    (r"Django", "Django", "body"),
    (r"Ruby on Rails|rails", "Ruby on Rails", "body"),
]

# ── Puertos web comunes ──────────────────────────────────────

_COMMON_PORTS: Dict[int, str] = {
    21: "FTP", 22: "SSH", 25: "SMTP", 53: "DNS",
    80: "HTTP", 110: "POP3", 143: "IMAP", 443: "HTTPS",
    445: "SMB", 993: "IMAPS", 995: "POP3S",
    3000: "Dev Server", 3306: "MySQL", 5432: "PostgreSQL",
    5900: "VNC", 6379: "Redis", 8080: "HTTP Proxy",
    8443: "HTTPS Alt", 8888: "Alt HTTP", 9200: "Elasticsearch",
    27017: "MongoDB",
}

# ── Redirect param names ─────────────────────────────────────

_REDIRECT_PARAMS = [
    "redirect", "url", "next", "goto", "return",
    "returnUrl", "redirect_uri", "return_to", "continue",
    "dest", "destination", "rurl", "target",
]


# ── Escáneres ────────────────────────────────────────────────


async def check_headers(url: str) -> HeaderAnalysis:
    """Analiza headers de seguridad HTTP."""

    url = normalize_url(url)
    result = HeaderAnalysis()

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
            verify=False,
        ) as client:
            resp = await client.get(url)

        resp_headers = {k.lower(): v for k, v in resp.headers.items()}

        # Headers de seguridad
        for header_name in _SECURITY_HEADERS:
            key = header_name.lower()
            if key in resp_headers:
                result.present[header_name] = resp_headers[key]
            else:
                result.missing.append(header_name)

        # Findings por headers faltantes
        critical_missing = {
            "Content-Security-Policy": (Severity.HIGH, "CWE-1021"),
            "Strict-Transport-Security": (Severity.HIGH, "CWE-319"),
            "X-Content-Type-Options": (Severity.MEDIUM, "CWE-16"),
            "X-Frame-Options": (Severity.MEDIUM, "CWE-1021"),
        }
        for name in result.missing:
            sev, cwe = critical_missing.get(name, (Severity.LOW, None))
            result.findings.append(Finding(
                check_id=f"header-missing-{name.lower()}",
                severity=sev,
                title=f"Header de seguridad faltante: {name}",
                detail=f"El header {name} no está presente en la respuesta.",
                remediation=f"Configurar el header {name} en el servidor web.",
                cwe=cwe,
            ))

        # Info disclosure
        for name in _INFO_DISCLOSURE_HEADERS:
            key = name.lower()
            if key in resp_headers:
                val = resp_headers[key]
                result.findings.append(Finding(
                    check_id=f"header-disclosure-{name.lower()}",
                    severity=Severity.LOW,
                    title=f"Divulgación de información: {name}",
                    detail=f"El header {name} revela: {sanitize_for_display(val)}",
                    remediation=f"Eliminar o enmascarar el header {name}.",
                    evidence=f"{name}: {sanitize_for_display(val)}",
                    cwe="CWE-200",
                ))

    except Exception as exc:
        logger.warning("Error analizando headers de %s: %s", url, exc)
        result.findings.append(Finding(
            check_id="header-error",
            severity=Severity.INFO,
            title="Error al analizar headers",
            detail=str(exc)[:200],
            remediation="Verificar que la URL es accesible.",
        ))

    return result


async def check_ssl(hostname: str, port: int = 443) -> SSLAnalysis:
    """Analiza el certificado SSL/TLS."""
    result = SSLAnalysis()

    try:
        ctx = ssl.create_default_context()
        conn = ctx.wrap_socket(
            socket.socket(socket.AF_INET, socket.SOCK_STREAM),
            server_hostname=hostname,
        )
        conn.settimeout(10.0)
        conn.connect((hostname, port))

        cert = conn.getpeercert()
        cipher_info = conn.cipher()
        protocol = conn.version() or ""

        conn.close()

        if not cert:
            result.findings.append(Finding(
                check_id="ssl-no-cert",
                severity=Severity.CRITICAL,
                title="Sin certificado SSL",
                detail="El servidor no presentó un certificado SSL.",
                remediation="Configurar un certificado SSL válido.",
                cwe="CWE-295",
            ))
            return result

        result.valid = True
        result.protocol = protocol
        if cipher_info:
            result.cipher = cipher_info[0]

        # Issuer
        issuer_parts = cert.get("issuer", ())
        issuer_str_parts: List[str] = []
        for rdn in issuer_parts:
            for attr_name, attr_val in rdn:
                issuer_str_parts.append(f"{attr_name}={attr_val}")
        result.issuer = ", ".join(issuer_str_parts)

        # Subject
        subject_parts = cert.get("subject", ())
        subj_str_parts: List[str] = []
        for rdn in subject_parts:
            for attr_name, attr_val in rdn:
                subj_str_parts.append(f"{attr_name}={attr_val}")
        result.subject = ", ".join(subj_str_parts)

        # Expiry
        not_after = cert.get("notAfter", "")
        result.expires = not_after
        if not_after:
            try:
                exp_dt = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z")
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                days_left = (exp_dt - now).days
                if days_left < 0:
                    result.valid = False
                    result.findings.append(Finding(
                        check_id="ssl-expired",
                        severity=Severity.CRITICAL,
                        title="Certificado SSL expirado",
                        detail=f"El certificado expiró hace {abs(days_left)} días ({not_after}).",
                        remediation="Renovar el certificado SSL inmediatamente.",
                        evidence=f"notAfter: {not_after}",
                        cwe="CWE-298",
                    ))
                elif days_left < 30:
                    result.findings.append(Finding(
                        check_id="ssl-expiring-soon",
                        severity=Severity.MEDIUM,
                        title="Certificado SSL próximo a expirar",
                        detail=f"El certificado expira en {days_left} días ({not_after}).",
                        remediation="Renovar el certificado SSL antes de su expiración.",
                        evidence=f"notAfter: {not_after}",
                    ))
            except ValueError:
                pass

        # SAN
        san_list: List[str] = []
        for san_type, san_val in cert.get("subjectAltName", ()):
            san_list.append(f"{san_type}:{san_val}")
        result.san = san_list

        # Protocol warnings
        if protocol and protocol in ("SSLv2", "SSLv3", "TLSv1", "TLSv1.1"):
            result.findings.append(Finding(
                check_id="ssl-weak-protocol",
                severity=Severity.HIGH,
                title=f"Protocolo TLS débil: {protocol}",
                detail=f"El servidor usa {protocol}, que tiene vulnerabilidades conocidas.",
                remediation="Actualizar a TLS 1.2 o superior.",
                evidence=f"Protocol: {protocol}",
                cwe="CWE-326",
            ))

    except ssl.SSLCertVerificationError as exc:
        result.valid = False
        result.findings.append(Finding(
            check_id="ssl-verification-failed",
            severity=Severity.HIGH,
            title="Verificación de certificado SSL fallida",
            detail=str(exc)[:200],
            remediation="Instalar un certificado SSL válido de una CA confiable.",
            cwe="CWE-295",
        ))
    except (socket.timeout, socket.gaierror, ConnectionRefusedError, OSError) as exc:
        result.findings.append(Finding(
            check_id="ssl-connection-error",
            severity=Severity.INFO,
            title="No se pudo conectar para verificar SSL",
            detail=str(exc)[:200],
            remediation="Verificar que el puerto 443 está abierto y accesible.",
        ))

    return result


async def check_cookies(url: str) -> CookieAnalysis:
    """Analiza las flags de seguridad de las cookies."""

    url = normalize_url(url)
    result = CookieAnalysis()

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
            verify=False,
        ) as client:
            resp = await client.get(url)

        # httpx expone cookies del jar
        for cookie in resp.cookies.jar:
            info = CookieInfo(
                name=cookie.name,
                secure=cookie.secure,
                path=cookie.path or "/",
            )
            # Parsear atributos extras del header raw
            raw_headers = resp.headers.get_list("set-cookie")
            for raw in raw_headers:
                if raw.lower().startswith(cookie.name.lower() + "="):
                    _, attrs = parse_set_cookie(raw)
                    info.httponly = "httponly" in attrs
                    info.samesite = attrs.get("samesite", "")
                    break

            result.cookies.append(info)

            # Findings
            is_session = any(
                kw in cookie.name.lower()
                for kw in ("session", "sess", "sid", "token", "auth", "jwt")
            )
            if is_session:
                if not info.secure:
                    result.findings.append(Finding(
                        check_id=f"cookie-no-secure-{cookie.name}",
                        severity=Severity.HIGH,
                        title=f"Cookie de sesión sin flag Secure: {cookie.name}",
                        detail="La cookie puede transmitirse por HTTP sin cifrar.",
                        remediation="Agregar el flag Secure a la cookie.",
                        evidence=f"Cookie: {cookie.name}",
                        cwe="CWE-614",
                    ))
                if not info.httponly:
                    result.findings.append(Finding(
                        check_id=f"cookie-no-httponly-{cookie.name}",
                        severity=Severity.MEDIUM,
                        title=f"Cookie de sesión sin flag HttpOnly: {cookie.name}",
                        detail="La cookie es accesible desde JavaScript (riesgo de XSS).",
                        remediation="Agregar el flag HttpOnly a la cookie.",
                        evidence=f"Cookie: {cookie.name}",
                        cwe="CWE-1004",
                    ))
                if not info.samesite or info.samesite.lower() == "none":
                    result.findings.append(Finding(
                        check_id=f"cookie-no-samesite-{cookie.name}",
                        severity=Severity.MEDIUM,
                        title=f"Cookie sin SameSite adecuado: {cookie.name}",
                        detail="La cookie no tiene SameSite o es None (riesgo CSRF).",
                        remediation="Configurar SameSite=Lax o SameSite=Strict.",
                        evidence=f"Cookie: {cookie.name}, SameSite: {info.samesite or 'no set'}",
                        cwe="CWE-1275",
                    ))

    except Exception as exc:
        logger.warning("Error analizando cookies de %s: %s", url, exc)

    return result


async def discover_tech(url: str) -> TechFingerprint:
    """Detecta tecnologías por headers, meta tags y patrones en HTML."""

    url = normalize_url(url)
    result = TechFingerprint()
    detected: Set[str] = set()

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
            verify=False,
        ) as client:
            resp = await client.get(url)

        headers_str = " ".join(f"{k}: {v}" for k, v in resp.headers.items())
        body = resp.text[:50000]  # Limitar a 50KB

        for pattern, tech_name, source in _TECH_PATTERNS:
            if tech_name in detected:
                continue
            search_in = headers_str if source == "header" else body
            if re.search(pattern, search_in, re.IGNORECASE):
                detected.add(tech_name)
                result.technologies.append({
                    "name": tech_name,
                    "detected_in": source,
                })

        # Meta generator tag
        gen_match = re.search(
            r'<meta\s+name=["\']generator["\']\s+content=["\']([^"\']+)["\']',
            body,
            re.IGNORECASE,
        )
        if gen_match:
            gen = gen_match.group(1)
            if gen not in detected:
                detected.add(gen)
                result.technologies.append({
                    "name": gen,
                    "detected_in": "meta",
                })

        # Findings si se detectan versiones específicas
        for tech in result.technologies:
            version_match = re.search(
                r"[\d]+\.[\d]+(?:\.[\d]+)?",
                tech.get("name", ""),
            )
            if version_match:
                result.findings.append(Finding(
                    check_id=f"tech-version-{tech['name'].lower().replace(' ', '-')}",
                    severity=Severity.LOW,
                    title=f"Versión de tecnología expuesta: {tech['name']}",
                    detail=f"Se detectó la versión {version_match.group(0)}.",
                    remediation="Ocultar información de versiones cuando sea posible.",
                    evidence=f"Detectado: {tech['name']}",
                    cwe="CWE-200",
                ))

    except Exception as exc:
        logger.warning("Error detectando tecnologías en %s: %s", url, exc)

    return result


async def dns_lookup(hostname: str, record_types: Optional[List[str]] = None) -> DNSResult:
    """Consulta registros DNS. Usa dnspython si está disponible, fallback a socket."""
    result = DNSResult()
    types = record_types or ["A", "AAAA", "MX", "TXT", "NS"]

    try:
        import dns.resolver  # type: ignore[import-untyped]

        resolver = dns.resolver.Resolver()
        resolver.timeout = 5.0
        resolver.lifetime = 10.0

        for rtype in types:
            try:
                answers = resolver.resolve(hostname, rtype)
                records: List[str] = []
                for rdata in answers:
                    records.append(str(rdata))
                if records:
                    result.records[rtype] = records
            except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.NoNameservers):
                pass
            except Exception:
                pass

    except ImportError:
        # Fallback a socket para A records
        try:
            addrs = socket.getaddrinfo(hostname, None)
            a_records: List[str] = []
            aaaa_records: List[str] = []
            seen: Set[str] = set()
            for family, _, _, _, addr in addrs:
                ip = addr[0]
                if ip in seen:
                    continue
                seen.add(ip)
                if family == socket.AF_INET:
                    a_records.append(ip)
                elif family == socket.AF_INET6:
                    aaaa_records.append(ip)
            if a_records:
                result.records["A"] = a_records
            if aaaa_records:
                result.records["AAAA"] = aaaa_records
        except socket.gaierror as exc:
            result.findings.append(Finding(
                check_id="dns-resolution-failed",
                severity=Severity.HIGH,
                title="Resolución DNS fallida",
                detail=f"No se pudo resolver {hostname}: {exc}",
                remediation="Verificar que el dominio existe y tiene registros DNS.",
            ))
            return result

    # Chequear SPF/DMARC en TXT records
    txt_records = result.records.get("TXT", [])
    has_spf = any("v=spf1" in r for r in txt_records)
    has_dmarc = any("v=DMARC1" in r for r in txt_records)

    if not has_spf:
        # Intentar _dmarc subdomain por separado
        result.findings.append(Finding(
            check_id="dns-no-spf",
            severity=Severity.MEDIUM,
            title="Sin registro SPF",
            detail="No se encontró un registro SPF en los TXT records.",
            remediation="Agregar un registro TXT con política SPF.",
            cwe="CWE-290",
        ))

    if not has_dmarc:
        result.findings.append(Finding(
            check_id="dns-no-dmarc",
            severity=Severity.MEDIUM,
            title="Sin registro DMARC",
            detail="No se encontró un registro DMARC.",
            remediation="Agregar un registro TXT _dmarc con política DMARC.",
            cwe="CWE-290",
        ))

    return result


async def discover_paths(url: str) -> PathDiscoveryResult:
    """Prueba rutas comunes para descubrir archivos expuestos."""

    url = normalize_url(url)
    result = PathDiscoveryResult()
    sem = asyncio.Semaphore(5)

    async def _check_path(client: httpx.AsyncClient, path: str) -> Optional[DiscoveredPath]:
        async with sem:
            try:
                resp = await client.get(url.rstrip("/") + path)
                if resp.status_code < 400:
                    content_len = len(resp.content)
                    return DiscoveredPath(
                        path=path,
                        status_code=resp.status_code,
                        content_length=content_len,
                    )
            except Exception:
                pass
            return None

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            follow_redirects=False,
            verify=False,
        ) as client:
            tasks = [_check_path(client, p) for p in _COMMON_PATHS]
            results = await asyncio.gather(*tasks)

        for dp in results:
            if dp is not None:
                result.found.append(dp)

                # Findings para rutas sensibles
                sensitive = {
                    "/.env": (Severity.CRITICAL, "Archivo .env expuesto con posibles credenciales"),
                    "/.git/HEAD": (Severity.CRITICAL, "Repositorio Git expuesto"),
                    "/.git/config": (Severity.CRITICAL, "Config de Git expuesta"),
                    "/.htpasswd": (Severity.CRITICAL, "Archivo de contraseñas expuesto"),
                    "/.htaccess": (Severity.HIGH, "Archivo .htaccess expuesto"),
                    "/.DS_Store": (Severity.LOW, "Archivo .DS_Store expuesto"),
                    "/phpinfo.php": (Severity.HIGH, "phpinfo() expuesto"),
                    "/server-status": (Severity.MEDIUM, "Server status expuesto"),
                    "/server-info": (Severity.MEDIUM, "Server info expuesto"),
                    "/elmah.axd": (Severity.HIGH, "ELMAH error log expuesto"),
                    "/trace.axd": (Severity.HIGH, "ASP.NET trace expuesto"),
                }
                if dp.path in sensitive:
                    sev, desc = sensitive[dp.path]
                    result.findings.append(Finding(
                        check_id=f"path-sensitive-{dp.path.strip('/').replace('/', '-')}",
                        severity=sev,
                        title=f"Ruta sensible accesible: {dp.path}",
                        detail=desc,
                        remediation=f"Restringir acceso a {dp.path} en el servidor web.",
                        evidence=f"HTTP {dp.status_code} en {dp.path}",
                        cwe="CWE-538",
                    ))

    except Exception as exc:
        logger.warning("Error descubriendo rutas en %s: %s", url, exc)

    return result


async def check_cors(url: str) -> CORSAnalysis:
    """Verifica la configuración CORS enviando un Origin malicioso."""

    url = normalize_url(url)
    result = CORSAnalysis()
    evil_origin = "https://evil-attacker.example.com"

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
            verify=False,
        ) as client:
            resp = await client.get(
                url,
                headers={"Origin": evil_origin},
            )

        acao = resp.headers.get("access-control-allow-origin", "")
        acac = resp.headers.get("access-control-allow-credentials", "")
        acam = resp.headers.get("access-control-allow-methods", "")

        result.allow_origin = acao
        result.allow_methods = acam
        result.allows_credentials = acac.lower() == "true"

        if acao == evil_origin:
            result.origin_reflected = True
            sev = Severity.HIGH if result.allows_credentials else Severity.MEDIUM
            result.findings.append(Finding(
                check_id="cors-origin-reflected",
                severity=sev,
                title="CORS refleja origen arbitrario",
                detail=(
                    f"El servidor refleja el Origin '{evil_origin}' en "
                    f"Access-Control-Allow-Origin"
                    + (". Además permite credentials." if result.allows_credentials else ".")
                ),
                remediation="Configurar una whitelist de orígenes permitidos en CORS.",
                evidence=f"ACAO: {acao}, ACAC: {acac}",
                cwe="CWE-942",
            ))
        elif acao == "*" and result.allows_credentials:
            result.findings.append(Finding(
                check_id="cors-wildcard-credentials",
                severity=Severity.HIGH,
                title="CORS permite wildcard con credentials",
                detail="Access-Control-Allow-Origin: * con Allow-Credentials: true.",
                remediation="No usar wildcard (*) cuando se permiten credentials.",
                evidence=f"ACAO: {acao}, ACAC: {acac}",
                cwe="CWE-942",
            ))

    except Exception as exc:
        logger.warning("Error analizando CORS de %s: %s", url, exc)

    return result


async def check_forms(url: str) -> FormAnalysis:
    """Analiza formularios: CSRF tokens, autocomplete en passwords, actions externos."""

    url = normalize_url(url)
    result = FormAnalysis()

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
            verify=False,
        ) as client:
            resp = await client.get(url)

        html = resp.text
        raw_forms = parse_html_forms(html)

        for raw in raw_forms:
            action = raw.get("action", "")
            method = raw.get("method", "GET")
            inputs = raw.get("inputs", "").split(",") if raw.get("inputs") else []

            has_csrf = any(
                kw in inp.lower()
                for inp in inputs
                for kw in ("csrf", "token", "_token", "authenticity_token", "nonce")
            )
            has_password = any("password" in inp.lower() for inp in inputs)
            external = bool(action and not is_same_origin(url, action) and action.startswith("http"))

            info = FormInfo(
                action=action,
                method=method,
                has_csrf_token=has_csrf,
                password_autocomplete=has_password,
                external_action=external,
            )
            result.forms.append(info)

            if method == "POST" and not has_csrf:
                result.findings.append(Finding(
                    check_id="form-no-csrf",
                    severity=Severity.MEDIUM,
                    title="Formulario POST sin token CSRF",
                    detail=f"Formulario con action='{sanitize_for_display(action, 100)}' no tiene token CSRF visible.",
                    remediation="Agregar un token CSRF a todos los formularios POST.",
                    evidence=f"Form action: {sanitize_for_display(action, 100)}, method: {method}",
                    cwe="CWE-352",
                ))

            if external:
                result.findings.append(Finding(
                    check_id="form-external-action",
                    severity=Severity.MEDIUM,
                    title="Formulario con action externo",
                    detail=f"Un formulario envía datos a un dominio externo: {sanitize_for_display(action, 100)}",
                    remediation="Verificar que el destino externo es legítimo.",
                    evidence=f"Action: {sanitize_for_display(action, 100)}",
                    cwe="CWE-601",
                ))

    except Exception as exc:
        logger.warning("Error analizando formularios de %s: %s", url, exc)

    return result


async def check_xss_reflection(url: str) -> XSSResult:
    """Inyecta marcador único en query params y verifica reflexión sin encoding."""

    url = normalize_url(url)
    result = XSSResult()
    marker = "somer7x5s3q9"

    try:
        from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

        parsed = urlparse(url)
        params = parse_qs(parsed.query, keep_blank_values=True)

        if not params:
            return result

        result.tested_params = len(params)

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
            verify=False,
        ) as client:
            for param_name in params:
                test_params = dict(params)
                test_params[param_name] = [f"<{marker}>"]
                new_query = urlencode(test_params, doseq=True)
                test_url = urlunparse(parsed._replace(query=new_query))

                try:
                    resp = await client.get(test_url)
                    body = resp.text
                    if f"<{marker}>" in body:
                        result.reflected_params.append(param_name)
                except Exception:
                    pass

        if result.reflected_params:
            result.findings.append(Finding(
                check_id="xss-reflection-detected",
                severity=Severity.HIGH,
                title="Reflexión de entrada sin encoding detectada",
                detail=(
                    f"Los parámetros {', '.join(result.reflected_params)} reflejan "
                    f"entrada HTML sin encoding."
                ),
                remediation="Aplicar encoding de salida (HTML entity encoding) a todos los datos reflejados.",
                evidence=f"Params reflejados: {', '.join(result.reflected_params)}",
                cwe="CWE-79",
            ))

    except Exception as exc:
        logger.warning("Error en check XSS de %s: %s", url, exc)

    return result


async def check_open_redirects(url: str) -> OpenRedirectResult:
    """Prueba parámetros comunes de redirect con URL externa."""

    url = normalize_url(url)
    result = OpenRedirectResult()
    target = "https://evil-redirect.example.com"

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            follow_redirects=False,
            verify=False,
        ) as client:
            base = url.rstrip("/")
            for param in _REDIRECT_PARAMS:
                test_url = f"{base}?{param}={target}"
                try:
                    resp = await client.get(test_url)
                    location = resp.headers.get("location", "")
                    if resp.status_code in (301, 302, 303, 307, 308):
                        if target in location:
                            result.vulnerable_params.append(param)
                except Exception:
                    pass

        if result.vulnerable_params:
            result.findings.append(Finding(
                check_id="open-redirect-detected",
                severity=Severity.MEDIUM,
                title="Open redirect detectado",
                detail=(
                    f"Los parámetros {', '.join(result.vulnerable_params)} permiten "
                    f"redirección a dominios externos."
                ),
                remediation="Validar y restringir URLs de redirección a dominios permitidos.",
                evidence=f"Params vulnerables: {', '.join(result.vulnerable_params)}",
                cwe="CWE-601",
            ))

    except Exception as exc:
        logger.warning("Error en check open redirects de %s: %s", url, exc)

    return result


async def crawl_links(
    url: str,
    max_pages: int = 20,
    max_depth: int = 2,
) -> CrawlResult:
    """BFS de links internos con profundidad máxima."""

    url = normalize_url(url)
    result = CrawlResult()
    visited: Set[str] = set()
    internal: Set[str] = set()
    external: Set[str] = set()
    forms_count = 0
    queue: List[Tuple[str, int]] = [(url, 0)]
    sem = asyncio.Semaphore(3)

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            follow_redirects=True,
            verify=False,
        ) as client:
            while queue and len(visited) < max_pages:
                current_url, depth = queue.pop(0)
                if current_url in visited:
                    continue
                visited.add(current_url)

                async with sem:
                    try:
                        resp = await client.get(current_url)
                    except Exception:
                        continue

                content_type = resp.headers.get("content-type", "")
                if "text/html" not in content_type:
                    continue

                html = resp.text
                links = parse_html_links(html, current_url)
                forms_count += len(parse_html_forms(html))

                for link in links:
                    if is_same_origin(url, link):
                        internal.add(link)
                        if depth + 1 <= max_depth and link not in visited:
                            queue.append((link, depth + 1))
                    else:
                        external.add(link)

    except Exception as exc:
        logger.warning("Error crawling %s: %s", url, exc)

    result.internal_links = sorted(internal)[:100]
    result.external_links = sorted(external)[:50]
    result.forms_found = forms_count
    result.pages_crawled = len(visited)

    if external:
        result.findings.append(Finding(
            check_id="crawl-external-links",
            severity=Severity.INFO,
            title=f"Se encontraron {len(external)} links externos",
            detail="Links que apuntan a dominios externos.",
            remediation="Verificar que los links externos son legítimos y usar rel='noopener'.",
        ))

    return result


async def scan_ports(
    hostname: str,
    ports: Optional[List[int]] = None,
) -> PortScanResult:
    """Escaneo TCP connect a puertos comunes."""
    result = PortScanResult()
    target_ports = ports or list(_COMMON_PORTS.keys())

    async def _check_port(port: int) -> Optional[OpenPort]:
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(hostname, port),
                timeout=3.0,
            )
            writer.close()
            await writer.wait_closed()
            service = _COMMON_PORTS.get(port, "unknown")
            return OpenPort(port=port, service=service)
        except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
            return None

    tasks = [_check_port(p) for p in target_ports]
    results = await asyncio.gather(*tasks)

    for op in results:
        if op is not None:
            result.open_ports.append(op)

    # Findings para puertos inesperados
    unexpected = [
        p for p in result.open_ports
        if p.port not in (80, 443)
    ]
    if unexpected:
        ports_str = ", ".join(f"{p.port} ({p.service})" for p in unexpected)
        result.findings.append(Finding(
            check_id="ports-unexpected-open",
            severity=Severity.MEDIUM,
            title=f"Puertos no estándar abiertos: {ports_str}",
            detail=f"Se detectaron {len(unexpected)} puertos abiertos además de 80/443.",
            remediation="Verificar que los puertos abiertos son necesarios y filtrar los demás.",
            evidence=f"Puertos: {ports_str}",
            cwe="CWE-16",
        ))

    # Puertos de bases de datos
    db_ports = {3306, 5432, 27017, 6379, 9200}
    exposed_db = [p for p in result.open_ports if p.port in db_ports]
    if exposed_db:
        db_str = ", ".join(f"{p.port} ({p.service})" for p in exposed_db)
        result.findings.append(Finding(
            check_id="ports-database-exposed",
            severity=Severity.CRITICAL,
            title=f"Puerto de base de datos expuesto: {db_str}",
            detail="Puertos de bases de datos accesibles públicamente.",
            remediation="Restringir acceso a puertos de bases de datos usando firewall.",
            evidence=f"Puertos: {db_str}",
            cwe="CWE-284",
        ))

    return result


# ── Nuevos escáneres ────────────────────────────────────────


_UNSAFE_HTTP_METHODS = {"PUT", "DELETE", "TRACE", "CONNECT", "PATCH"}

_DIRECTORY_LISTING_PATHS = [
    "/images/", "/uploads/", "/css/", "/js/", "/assets/",
    "/static/", "/media/", "/files/",
]

_DIRECTORY_LISTING_SIGNATURES = [
    "Index of /", "Directory listing for", "<title>Directory",
    "Parent Directory", "[To Parent Directory]",
]


async def check_http_methods(url: str) -> HttpMethodsAnalysis:
    """Detecta métodos HTTP inseguros habilitados (PUT/DELETE/TRACE)."""

    url = normalize_url(url)
    result = HttpMethodsAnalysis()

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
            verify=False,
        ) as client:
            resp = await client.options(url)

        allow = resp.headers.get("allow", "")
        if allow:
            methods = [m.strip().upper() for m in allow.split(",")]
            result.allowed_methods = methods
            result.unsafe_methods = [m for m in methods if m in _UNSAFE_HTTP_METHODS]

            if result.unsafe_methods:
                result.findings.append(Finding(
                    check_id="unsafe-http-methods",
                    severity=Severity.MEDIUM,
                    title=f"Métodos HTTP inseguros habilitados: {', '.join(result.unsafe_methods)}",
                    detail=(
                        f"El servidor permite los métodos {', '.join(result.unsafe_methods)} "
                        "que pueden ser usados para modificar o eliminar recursos."
                    ),
                    remediation="Deshabilitar métodos HTTP innecesarios en el servidor.",
                    evidence=f"Allow: {allow}",
                    cwe="CWE-749",
                ))

    except Exception as exc:
        logger.warning("Error verificando métodos HTTP de %s: %s", url, exc)

    return result


async def check_https_redirect(url: str) -> HttpsRedirectAnalysis:
    """Verifica que HTTP redirige correctamente a HTTPS."""

    result = HttpsRedirectAnalysis()

    # Forzar URL HTTP para probar redirect
    url = normalize_url(url)
    http_url = url.replace("https://", "http://", 1)

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            follow_redirects=False,
            verify=False,
        ) as client:
            chain: List[str] = [http_url]
            current = http_url
            for _ in range(5):  # Max 5 redirects
                resp = await client.get(current)
                if resp.status_code in (301, 302, 303, 307, 308):
                    location = resp.headers.get("location", "")
                    if location:
                        chain.append(location)
                        if location.startswith("https://"):
                            result.redirects_to_https = True
                            break
                        current = location
                    else:
                        break
                else:
                    break

            result.redirect_chain = chain

            if not result.redirects_to_https:
                result.findings.append(Finding(
                    check_id="no-https-redirect",
                    severity=Severity.HIGH,
                    title="Sin redirección HTTP → HTTPS",
                    detail="El sitio no redirige automáticamente de HTTP a HTTPS.",
                    remediation="Configurar redirección 301 de HTTP a HTTPS en el servidor.",
                    evidence=f"Chain: {' → '.join(chain)}",
                    cwe="CWE-319",
                ))

    except Exception as exc:
        logger.warning("Error verificando redirect HTTPS de %s: %s", url, exc)

    return result


async def check_sri(url: str) -> SRIAnalysis:
    """Busca scripts y stylesheets externos sin Subresource Integrity."""

    url = normalize_url(url)
    result = SRIAnalysis()

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
            verify=False,
        ) as client:
            resp = await client.get(url)

        html = resp.text

        # Scripts externos
        script_pattern = re.compile(
            r'<script\b([^>]*)src=["\']([^"\']+)["\']([^>]*)>',
            re.IGNORECASE,
        )
        for match in script_pattern.finditer(html):
            attrs = match.group(1) + " " + match.group(3)
            src = match.group(2)
            if not is_same_origin(url, src) and src.startswith("http"):
                result.external_scripts += 1
                if "integrity" in attrs.lower():
                    result.scripts_with_sri += 1
                else:
                    result.scripts_without_sri.append(src)

        # Stylesheets externos
        link_pattern = re.compile(
            r'<link\b([^>]*)href=["\']([^"\']+)["\']([^>]*)>',
            re.IGNORECASE,
        )
        for match in link_pattern.finditer(html):
            attrs = match.group(1) + " " + match.group(3)
            href = match.group(2)
            if "stylesheet" in attrs.lower() and not is_same_origin(url, href) and href.startswith("http"):
                result.external_scripts += 1
                if "integrity" in attrs.lower():
                    result.scripts_with_sri += 1
                else:
                    result.scripts_without_sri.append(href)

        if result.scripts_without_sri:
            result.findings.append(Finding(
                check_id="missing-sri",
                severity=Severity.MEDIUM,
                title=f"{len(result.scripts_without_sri)} recursos externos sin SRI",
                detail=(
                    "Recursos cargados desde CDNs sin atributo integrity pueden "
                    "ser modificados si el CDN es comprometido."
                ),
                remediation="Agregar atributo integrity con hash SHA-384 a scripts y stylesheets externos.",
                evidence=f"Sin SRI: {', '.join(result.scripts_without_sri[:3])}",
                cwe="CWE-353",
            ))

    except Exception as exc:
        logger.warning("Error verificando SRI en %s: %s", url, exc)

    return result


async def check_mixed_content(url: str) -> MixedContentAnalysis:
    """Busca recursos HTTP en páginas HTTPS (contenido mixto)."""

    url = normalize_url(url)
    result = MixedContentAnalysis()

    if not url.startswith("https://"):
        return result

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
            verify=False,
        ) as client:
            resp = await client.get(url)

        html = resp.text

        # Scripts HTTP
        for match in re.finditer(r'<script\b[^>]*src=["\']http://([^"\']+)["\']', html, re.IGNORECASE):
            result.mixed_scripts.append("http://" + match.group(1))

        # Stylesheets HTTP
        for match in re.finditer(r'<link\b[^>]*href=["\']http://([^"\']+)["\']', html, re.IGNORECASE):
            if "stylesheet" in html[max(0, match.start() - 100):match.end()].lower():
                result.mixed_styles.append("http://" + match.group(1))

        # Images HTTP
        for match in re.finditer(r'<img\b[^>]*src=["\']http://([^"\']+)["\']', html, re.IGNORECASE):
            result.mixed_images.append("http://" + match.group(1))

        total = len(result.mixed_scripts) + len(result.mixed_styles) + len(result.mixed_images)
        if total > 0:
            sev = Severity.HIGH if result.mixed_scripts else Severity.MEDIUM
            result.findings.append(Finding(
                check_id="mixed-content",
                severity=sev,
                title=f"Contenido mixto detectado ({total} recursos HTTP)",
                detail=(
                    f"Scripts: {len(result.mixed_scripts)}, "
                    f"Styles: {len(result.mixed_styles)}, "
                    f"Imágenes: {len(result.mixed_images)}"
                ),
                remediation=(
                    "Cambiar todos los recursos a HTTPS o agregar "
                    "Content-Security-Policy: upgrade-insecure-requests."
                ),
                evidence=f"Recursos HTTP: {total}",
                cwe="CWE-319",
            ))

    except Exception as exc:
        logger.warning("Error verificando mixed content en %s: %s", url, exc)

    return result


async def check_directory_listing(url: str) -> DirectoryListingAnalysis:
    """Prueba directorios comunes por directory listing habilitado."""

    url = normalize_url(url)
    result = DirectoryListingAnalysis()
    sem = asyncio.Semaphore(5)

    async def _check_dir(client: httpx.AsyncClient, path: str) -> Optional[str]:
        async with sem:
            try:
                test_url = url.rstrip("/") + path
                resp = await client.get(test_url)
                if resp.status_code == 200:
                    body = resp.text[:2000]
                    for sig in _DIRECTORY_LISTING_SIGNATURES:
                        if sig.lower() in body.lower():
                            return path
            except Exception:
                pass
            return None

    try:
        result.paths_tested = list(_DIRECTORY_LISTING_PATHS)

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            follow_redirects=True,
            verify=False,
        ) as client:
            tasks = [_check_dir(client, p) for p in _DIRECTORY_LISTING_PATHS]
            results = await asyncio.gather(*tasks)

        for path in results:
            if path is not None:
                result.listings_found.append(path)

        if result.listings_found:
            result.findings.append(Finding(
                check_id="directory-listing",
                severity=Severity.MEDIUM,
                title=f"Directory listing habilitado en {len(result.listings_found)} ruta(s)",
                detail=f"Rutas con listing: {', '.join(result.listings_found)}",
                remediation="Deshabilitar directory listing (autoindex off en nginx, Options -Indexes en Apache).",
                evidence=f"Listings: {', '.join(result.listings_found)}",
                cwe="CWE-548",
            ))

    except Exception as exc:
        logger.warning("Error verificando directory listing en %s: %s", url, exc)

    return result


async def check_html_leaks(url: str) -> HtmlLeaksAnalysis:
    """Busca fugas de información en HTML: comentarios, versiones, emails."""

    url = normalize_url(url)
    result = HtmlLeaksAnalysis()

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
            verify=False,
        ) as client:
            resp = await client.get(url)

        html = resp.text[:100000]

        # Comentarios HTML
        comments = re.findall(r"<!--(.*?)-->", html, re.DOTALL)
        result.comments_found = len(comments)

        # Buscar debug/sensitive en comentarios
        sensitive_comments = []
        for c in comments:
            lower = c.lower()
            if any(kw in lower for kw in ("todo", "fixme", "hack", "bug", "password", "secret", "debug", "api_key")):
                sensitive_comments.append(c.strip()[:100])

        if sensitive_comments:
            result.findings.append(Finding(
                check_id="html-comment-leak",
                severity=Severity.LOW,
                title=f"Comentarios HTML con información sensible ({len(sensitive_comments)})",
                detail="Comentarios HTML contienen palabras clave sensibles (TODO, FIXME, password, etc.).",
                remediation="Eliminar comentarios de depuración y con información sensible del HTML de producción.",
                evidence=f"Ej: {sensitive_comments[0][:80]}",
                cwe="CWE-615",
            ))

        # Versiones en meta tags y generadores
        version_patterns = [
            re.compile(r'<meta\b[^>]*content=["\'][^"\']*(\d+\.\d+\.\d+)[^"\']*["\']', re.IGNORECASE),
            re.compile(r'<meta\b[^>]*name=["\']generator["\'][^>]*content=["\']([^"\']+)["\']', re.IGNORECASE),
        ]
        for pat in version_patterns:
            for match in pat.finditer(html):
                result.versions_found.append(match.group(1))

        if result.versions_found:
            result.findings.append(Finding(
                check_id="html-version-leak",
                severity=Severity.LOW,
                title=f"Versiones expuestas en HTML ({len(result.versions_found)})",
                detail=f"Versiones detectadas: {', '.join(result.versions_found[:5])}",
                remediation="Eliminar meta tags que exponen versiones de software.",
                evidence=f"Versiones: {', '.join(result.versions_found[:3])}",
                cwe="CWE-200",
            ))

        # Emails en HTML
        email_pattern = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
        emails = list(set(email_pattern.findall(html)))
        result.emails_found = emails[:20]

        if emails:
            result.findings.append(Finding(
                check_id="html-email-leak",
                severity=Severity.INFO,
                title=f"Emails encontrados en HTML ({len(emails)})",
                detail=f"Emails: {', '.join(emails[:5])}",
                remediation="Considerar ofuscar emails en el HTML para prevenir spam.",
                evidence=f"Emails: {', '.join(emails[:3])}",
            ))

    except Exception as exc:
        logger.warning("Error verificando leaks HTML en %s: %s", url, exc)

    return result


async def analyze_csp(url: str) -> CSPAnalysis:
    """Parsea y analiza Content-Security-Policy en profundidad."""

    url = normalize_url(url)
    result = CSPAnalysis()

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
            verify=False,
        ) as client:
            resp = await client.get(url)

        csp = resp.headers.get("content-security-policy", "")
        if not csp:
            result.findings.append(Finding(
                check_id="missing-csp",
                severity=Severity.HIGH,
                title="Content-Security-Policy no configurada",
                detail="El header CSP no está presente, permitiendo cualquier origen de recursos.",
                remediation="Configurar una política CSP restrictiva.",
                cwe="CWE-1021",
            ))
            return result

        result.raw_policy = csp

        # Parsear directivas
        for directive_str in csp.split(";"):
            directive_str = directive_str.strip()
            if not directive_str:
                continue
            parts = directive_str.split()
            if parts:
                name = parts[0]
                values = parts[1:]
                result.directives[name] = values

        # Chequear unsafe-inline
        for name, values in result.directives.items():
            if "'unsafe-inline'" in values:
                result.has_unsafe_inline = True
            if "'unsafe-eval'" in values:
                result.has_unsafe_eval = True

        if result.has_unsafe_inline:
            result.findings.append(Finding(
                check_id="csp-unsafe-inline",
                severity=Severity.MEDIUM,
                title="CSP permite 'unsafe-inline'",
                detail="La política CSP incluye 'unsafe-inline' que reduce la protección contra XSS.",
                remediation="Reemplazar 'unsafe-inline' con nonces o hashes específicos.",
                evidence=f"CSP: {csp[:200]}",
                cwe="CWE-79",
            ))

        if result.has_unsafe_eval:
            result.findings.append(Finding(
                check_id="csp-unsafe-eval",
                severity=Severity.MEDIUM,
                title="CSP permite 'unsafe-eval'",
                detail="La política CSP incluye 'unsafe-eval' que permite eval() y similar.",
                remediation="Eliminar 'unsafe-eval' y refactorizar código que use eval().",
                evidence=f"CSP: {csp[:200]}",
                cwe="CWE-79",
            ))

        # Chequear wildcards
        for name, values in result.directives.items():
            if "*" in values:
                result.findings.append(Finding(
                    check_id="csp-wildcard",
                    severity=Severity.MEDIUM,
                    title=f"CSP con wildcard en directiva {name}",
                    detail=f"La directiva '{name}' usa wildcard (*) que permite cualquier origen.",
                    remediation=f"Restringir la directiva {name} a orígenes específicos.",
                    evidence=f"{name}: {' '.join(values)}",
                    cwe="CWE-1021",
                ))
                break  # Solo reportar una vez

        # Chequear que default-src existe
        if "default-src" not in result.directives:
            result.findings.append(Finding(
                check_id="csp-no-default-src",
                severity=Severity.LOW,
                title="CSP sin directiva default-src",
                detail="La política CSP no incluye default-src como fallback.",
                remediation="Agregar default-src 'self' como directiva base de la política CSP.",
                evidence=f"Directivas: {', '.join(result.directives.keys())}",
            ))

    except Exception as exc:
        logger.warning("Error analizando CSP de %s: %s", url, exc)

    return result


async def check_email_security(hostname: str) -> EmailSecurityAnalysis:
    """Verifica SPF, DMARC y DKIM en DNS TXT records."""

    result = EmailSecurityAnalysis()

    try:
        import dns.resolver  # type: ignore[import-untyped]

        resolver = dns.resolver.Resolver()
        resolver.timeout = 5.0
        resolver.lifetime = 10.0

        # SPF — en TXT del dominio principal
        try:
            txt_answers = resolver.resolve(hostname, "TXT")
            for rdata in txt_answers:
                txt = str(rdata).strip('"')
                if "v=spf1" in txt:
                    result.has_spf = True
                    result.spf_record = txt
                    break
        except Exception:
            pass

        # DMARC — en _dmarc.dominio
        try:
            dmarc_answers = resolver.resolve(f"_dmarc.{hostname}", "TXT")
            for rdata in dmarc_answers:
                txt = str(rdata).strip('"')
                if "v=DMARC1" in txt:
                    result.has_dmarc = True
                    result.dmarc_record = txt
                    break
        except Exception:
            pass

        # DKIM — probar selector default
        for selector in ("default", "google", "selector1", "selector2"):
            try:
                dkim_answers = resolver.resolve(f"{selector}._domainkey.{hostname}", "TXT")
                for rdata in dkim_answers:
                    txt = str(rdata).strip('"')
                    if "v=DKIM1" in txt or "p=" in txt:
                        result.has_dkim = True
                        break
            except Exception:
                pass
            if result.has_dkim:
                break

    except ImportError:
        # Fallback sin dnspython — usar socket para TXT básico
        try:
            addrs = socket.getaddrinfo(hostname, None)
            if addrs:
                # Sin dnspython solo podemos reportar que no se pudo verificar
                result.findings.append(Finding(
                    check_id="email-dns-unavailable",
                    severity=Severity.INFO,
                    title="No se pudo verificar registros email (dnspython no instalado)",
                    detail="Instalar dnspython para verificar SPF, DMARC y DKIM.",
                    remediation="pip install dnspython",
                ))
                return result
        except Exception:
            pass

    # Generar findings
    if not result.has_spf:
        result.findings.append(Finding(
            check_id="missing-spf",
            severity=Severity.MEDIUM,
            title="Sin registro SPF",
            detail="No se encontró registro SPF para el dominio, facilitando email spoofing.",
            remediation='Agregar registro TXT: "v=spf1 include:_spf.google.com ~all" (ajustar según proveedor).',
            cwe="CWE-290",
        ))

    if not result.has_dmarc:
        result.findings.append(Finding(
            check_id="missing-dmarc",
            severity=Severity.MEDIUM,
            title="Sin registro DMARC",
            detail="No se encontró registro DMARC, sin políticas de autenticación de email.",
            remediation='Agregar registro TXT en _dmarc: "v=DMARC1; p=quarantine; rua=mailto:dmarc@dominio.com".',
            cwe="CWE-290",
        ))

    if not result.has_dkim:
        result.findings.append(Finding(
            check_id="missing-dkim",
            severity=Severity.LOW,
            title="Sin registro DKIM detectado",
            detail="No se encontró DKIM en selectores comunes (default, google, selector1/2).",
            remediation="Configurar DKIM con el proveedor de email y publicar el registro DNS.",
            cwe="CWE-290",
        ))

    return result
