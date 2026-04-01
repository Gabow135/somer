"""Scanners avanzados de ciberseguridad — checks adicionales para pentesting.

Cada scanner es async, produce lista de Finding y/o tipos especializados.
Todos son no destructivos — solo detectan y reportan.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import socket
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urljoin, urlparse

import httpx

from cybersecurity.types import (
    Finding,
    JWTAnalysisResult,
    Severity,
    SubdomainResult,
    WAFDetectionResult,
)

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(15)


# ── 1. SQL Injection Indicators ──────────────────────────────────


async def check_sqli_indicators(url: str) -> List[Finding]:
    """Detecta indicadores de SQL injection con payloads de detección.

    Usa payloads que provocan errores SQL detectables en la respuesta.
    NO extrae datos — solo detecta la vulnerabilidad.
    """
    findings: List[Finding] = []
    parsed = urlparse(url)
    separator = "&" if parsed.query else "?"

    # Payloads de detección — provocan errores SQL, no extraen datos
    payloads = [
        ("'", "error-based single quote"),
        ("1' OR '1'='1", "boolean-based OR"),
        ("1; WAITFOR DELAY '0:0:3'--", "time-based MSSQL"),
        ("1' AND SLEEP(3)--", "time-based MySQL"),
    ]

    # Patrones de error SQL en respuesta
    sql_error_patterns = [
        r"sql syntax.*?mysql",
        r"warning.*?\Wmysqli?_",
        r"valid mysql result",
        r"mysqlclient\.",
        r"postgresql.*?error",
        r"pg_query\(\)",
        r"pg_exec\(\)",
        r"warning.*?\Wpg_",
        r"syntax error at or near",
        r"unclosed quotation mark",
        r"microsoft.*?odbc.*?driver",
        r"microsoft.*?sql.*?server",
        r"ora-\d{5}",
        r"oracle.*?driver",
        r"sqlite.*?error",
        r"sqlite3\.",
        r"jdbc\.sqlite",
        r"you have an error in your sql syntax",
    ]
    combined_pattern = re.compile("|".join(sql_error_patterns), re.IGNORECASE)

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            # Obtener respuesta baseline
            baseline = await client.get(url)
            baseline_len = len(baseline.text)

            for payload, desc in payloads:
                test_url = f"{url}{separator}q={quote(payload)}"
                try:
                    resp = await client.get(test_url)
                    body = resp.text

                    # Buscar errores SQL
                    match = combined_pattern.search(body)
                    if match:
                        findings.append(Finding(
                            check_id=f"sqli-error-{desc.split()[0]}",
                            severity=Severity.CRITICAL,
                            title=f"SQL Injection detectado ({desc})",
                            detail=(
                                f"Payload '{payload}' provocó error SQL en la respuesta: "
                                f"'{match.group()[:100]}'"
                            ),
                            remediation=(
                                "Usar consultas parametrizadas (prepared statements). "
                                "Nunca concatenar input del usuario en queries SQL."
                            ),
                            evidence=f"URL: {test_url}\nError: {match.group()[:200]}",
                            cwe="CWE-89",
                        ))
                except httpx.HTTPError:
                    continue
    except Exception as exc:
        logger.warning("Error en check_sqli_indicators: %s", exc)

    return findings


# ── 2. Admin Panel Detection ────────────────────────────────────


async def check_admin_panels(url: str) -> List[Finding]:
    """Detecta paneles de administración accesibles sin autenticación."""
    findings: List[Finding] = []

    admin_paths = [
        "/admin", "/admin/", "/administrator", "/wp-admin",
        "/wp-login.php", "/dashboard", "/panel", "/cpanel",
        "/admin/login", "/manager", "/admin.php", "/login",
        "/backend", "/control", "/adminpanel",
    ]

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False) as client:
            for path in admin_paths:
                test_url = urljoin(url, path)
                try:
                    resp = await client.get(test_url)
                    # Accesible si 200 o redirect a login del mismo dominio
                    if resp.status_code == 200:
                        # Verificar si tiene contenido de panel admin
                        body_lower = resp.text.lower()
                        has_admin_content = any(
                            marker in body_lower
                            for marker in [
                                "login", "password", "username", "admin",
                                "dashboard", "panel", "sign in", "log in",
                            ]
                        )
                        if has_admin_content:
                            findings.append(Finding(
                                check_id=f"admin-panel-{path.strip('/').replace('/', '-')}",
                                severity=Severity.MEDIUM,
                                title=f"Panel admin accesible en {path}",
                                detail=(
                                    f"El panel de administración en {path} responde con "
                                    f"HTTP 200 y contiene contenido de login/admin."
                                ),
                                remediation=(
                                    "Restringir acceso a paneles admin por IP, VPN o "
                                    "autenticación multi-factor. Ocultar rutas de admin "
                                    "con paths no predecibles."
                                ),
                                evidence=f"URL: {test_url} (HTTP {resp.status_code})",
                                cwe="CWE-425",
                            ))
                except httpx.HTTPError:
                    continue
    except Exception as exc:
        logger.warning("Error en check_admin_panels: %s", exc)

    return findings


# ── 3. Subdomain Enumeration ────────────────────────────────────


async def enumerate_subdomains(hostname: str) -> Tuple[List[SubdomainResult], List[Finding]]:
    """Enumera subdominios via Certificate Transparency (crt.sh) + DNS brute."""
    subdomains: List[SubdomainResult] = []
    findings: List[Finding] = []
    seen: set = set()

    # 1. Certificate Transparency via crt.sh
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20)) as client:
            resp = await client.get(
                f"https://crt.sh/?q=%.{hostname}&output=json",
            )
            if resp.status_code == 200:
                entries = resp.json()
                for entry in entries[:200]:  # Limitar a 200
                    name = entry.get("name_value", "")
                    for sub in name.split("\n"):
                        sub = sub.strip().lower()
                        if sub and sub not in seen and sub.endswith(hostname):
                            seen.add(sub)
                            subdomains.append(SubdomainResult(
                                subdomain=sub, source="crt.sh",
                            ))
    except Exception as exc:
        logger.debug("crt.sh error: %s", exc)

    # 2. DNS brute con prefijos comunes
    common_prefixes = [
        "www", "mail", "ftp", "remote", "blog", "api", "dev",
        "staging", "test", "admin", "portal", "vpn", "ns1", "ns2",
        "mx", "smtp", "pop", "imap", "webmail", "cdn", "app",
        "m", "mobile", "static", "assets", "img", "docs",
    ]

    async def _resolve(prefix: str) -> Optional[SubdomainResult]:
        sub = f"{prefix}.{hostname}"
        if sub in seen:
            return None
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, socket.getaddrinfo, sub, None, socket.AF_INET, socket.SOCK_STREAM,
            )
            if result:
                ip = result[0][4][0]
                return SubdomainResult(
                    subdomain=sub, source="dns-brute",
                    resolves=True, ip=ip,
                )
        except (socket.gaierror, OSError):
            pass
        return None

    dns_results = await asyncio.gather(
        *[_resolve(p) for p in common_prefixes],
        return_exceptions=True,
    )
    for r in dns_results:
        if isinstance(r, SubdomainResult):
            subdomains.append(r)
            seen.add(r.subdomain)

    if subdomains:
        findings.append(Finding(
            check_id="subdomain-enumeration",
            severity=Severity.INFO,
            title=f"{len(subdomains)} subdominios encontrados para {hostname}",
            detail=(
                f"Se encontraron {len(subdomains)} subdominios via CT logs y DNS brute force. "
                f"Algunos pueden exponer servicios internos."
            ),
            remediation=(
                "Revisar subdominios expuestos. Deshabilitar servicios innecesarios. "
                "Usar Certificate Transparency monitoring."
            ),
            evidence=", ".join(s.subdomain for s in subdomains[:20]),
        ))

    return subdomains, findings


# ── 4. WAF Detection ────────────────────────────────────────────


async def detect_waf(url: str) -> WAFDetectionResult:
    """Detecta Web Application Firewalls por fingerprinting de respuestas."""
    result = WAFDetectionResult()

    # Fingerprints de WAF conocidos (header patterns)
    waf_signatures = {
        "Cloudflare": {
            "headers": ["cf-ray", "cf-cache-status", "__cfduid"],
            "server": ["cloudflare"],
        },
        "AWS WAF": {
            "headers": ["x-amzn-requestid", "x-amz-cf-id"],
            "server": ["awselb", "amazons3"],
        },
        "ModSecurity": {
            "headers": ["x-mod-security"],
            "server": ["mod_security"],
        },
        "Sucuri": {
            "headers": ["x-sucuri-id", "x-sucuri-cache"],
            "server": ["sucuri"],
        },
        "Akamai": {
            "headers": ["x-akamai-transformed"],
            "server": ["akamaighost"],
        },
        "Imperva": {
            "headers": ["x-iinfo"],
            "server": [],
        },
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            # Request normal
            resp = await client.get(url)
            resp_headers = {k.lower(): v for k, v in resp.headers.items()}
            server = resp_headers.get("server", "").lower()

            for waf_name, sigs in waf_signatures.items():
                # Verificar headers
                for h in sigs["headers"]:
                    if h.lower() in resp_headers:
                        result.detected = True
                        result.waf_name = waf_name
                        result.confidence = "high"
                        break
                # Verificar server header
                if not result.detected:
                    for s in sigs["server"]:
                        if s in server:
                            result.detected = True
                            result.waf_name = waf_name
                            result.confidence = "medium"
                            break
                if result.detected:
                    break

            # Request con payload malicioso para provocar WAF
            if not result.detected:
                evil_url = f"{url}?q=<script>alert(1)</script>&id=1' OR 1=1--"
                try:
                    evil_resp = await client.get(evil_url)
                    if evil_resp.status_code in (403, 406, 429, 503):
                        result.detected = True
                        result.waf_name = "Unknown WAF"
                        result.confidence = "low"
                except httpx.HTTPError:
                    result.detected = True
                    result.waf_name = "Unknown WAF (connection blocked)"
                    result.confidence = "low"

    except Exception as exc:
        logger.warning("Error en detect_waf: %s", exc)

    if result.detected:
        result.bypass_suggestions = [
            "Variar encoding de payloads (URL-encode, double-encode, Unicode)",
            "Usar payloads de caso mixto (e.g., <ScRiPt>)",
            "Fragmentar payloads en múltiples parámetros",
            "Usar HTTP Parameter Pollution (HPP)",
        ]
        result.findings.append(Finding(
            check_id=f"waf-detected-{result.waf_name.lower().replace(' ', '-')}",
            severity=Severity.INFO,
            title=f"WAF detectado: {result.waf_name}",
            detail=(
                f"Se detectó {result.waf_name} protegiendo el sitio "
                f"(confianza: {result.confidence})."
            ),
            remediation="WAF detectado — tener en cuenta para ajustar payloads de testing.",
            evidence=f"WAF: {result.waf_name}, Confianza: {result.confidence}",
        ))

    return result


# ── 5. Session Fixation Check ───────────────────────────────────


async def check_session_management(url: str) -> List[Finding]:
    """Verifica si session tokens cambian entre requests (session fixation)."""
    findings: List[Finding] = []

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            # Primera petición — obtener cookies de sesión
            resp1 = await client.get(url)
            cookies1 = dict(resp1.cookies)

            if not cookies1:
                return findings

            # Segunda petición con las mismas cookies
            resp2 = await client.get(url)
            cookies2 = dict(resp2.cookies)

            # Buscar cookies que parecen session IDs
            session_names = [
                n for n in cookies1
                if any(k in n.lower() for k in ["sess", "sid", "token", "jwt", "auth"])
            ]

            for name in session_names:
                val1 = cookies1.get(name, "")
                val2 = cookies2.get(name, "")
                if val1 and val1 == val2:
                    findings.append(Finding(
                        check_id=f"session-fixation-{name}",
                        severity=Severity.MEDIUM,
                        title=f"Session token '{name}' no rota entre requests",
                        detail=(
                            f"La cookie de sesión '{name}' mantiene el mismo valor entre "
                            f"requests sucesivos. Esto podría indicar vulnerabilidad "
                            f"a session fixation si no se regenera post-autenticación."
                        ),
                        remediation=(
                            "Regenerar session ID después de la autenticación. "
                            "Implementar rotación periódica de tokens de sesión."
                        ),
                        evidence=f"Cookie: {name}, Valor constante: {val1[:20]}...",
                        cwe="CWE-384",
                    ))
    except Exception as exc:
        logger.warning("Error en check_session_management: %s", exc)

    return findings


# ── 6. HTTP Request Smuggling Detection ─────────────────────────


async def check_request_smuggling(url: str) -> List[Finding]:
    """Detecta posibles vulnerabilidades de HTTP Request Smuggling (CL/TE)."""
    findings: List[Finding] = []

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10), follow_redirects=False) as client:
            # Test CL.TE — Content-Length dice una cosa, Transfer-Encoding otra
            # Enviamos headers conflictivos y observamos comportamiento
            try:
                resp = await client.post(
                    url,
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Transfer-Encoding": "chunked",
                    },
                    content="0\r\n\r\n",
                )
                # Si el servidor no rechaza TE chunked con body "0", puede ser vulnerable
                # Esto es solo detección — no explotación
            except httpx.HTTPError:
                pass

            # Verificar si el servidor acepta ambos headers
            try:
                resp = await client.post(
                    url,
                    headers={
                        "Content-Length": "6",
                        "Transfer-Encoding": "chunked",
                    },
                    content="0\r\n\r\n",
                )
                # Si responde sin error, ambos headers son procesados
                if resp.status_code < 500:
                    findings.append(Finding(
                        check_id="request-smuggling-cl-te",
                        severity=Severity.LOW,
                        title="Servidor acepta Content-Length y Transfer-Encoding simultáneamente",
                        detail=(
                            "El servidor procesó una request con ambos headers "
                            "Content-Length y Transfer-Encoding sin rechazarla. "
                            "Esto podría indicar vulnerabilidad a request smuggling."
                        ),
                        remediation=(
                            "Configurar el servidor para rechazar requests con ambos "
                            "Content-Length y Transfer-Encoding headers. "
                            "Usar HTTP/2 cuando sea posible."
                        ),
                        evidence=f"Status: {resp.status_code}",
                        cwe="CWE-444",
                    ))
            except httpx.HTTPError:
                pass
    except Exception as exc:
        logger.warning("Error en check_request_smuggling: %s", exc)

    return findings


# ── 7. SSTI Detection ───────────────────────────────────────────


async def check_ssti(url: str) -> List[Finding]:
    """Detecta Server-Side Template Injection con payloads de detección."""
    findings: List[Finding] = []
    parsed = urlparse(url)
    separator = "&" if parsed.query else "?"

    # Payloads que producen resultados calculables
    payloads = [
        ("{{7*7}}", "49", "Jinja2/Twig"),
        ("${7*7}", "49", "Freemarker/Velocity"),
        ("#{7*7}", "49", "Ruby ERB/Java EL"),
        ("<%= 7*7 %>", "49", "ERB/ASP"),
        ("{{7*'7'}}", "7777777", "Jinja2 string multiply"),
    ]

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            for payload, expected, engine in payloads:
                test_url = f"{url}{separator}q={quote(payload)}"
                try:
                    resp = await client.get(test_url)
                    if expected in resp.text:
                        # Verificar que no está en el baseline
                        baseline = await client.get(url)
                        if expected not in baseline.text:
                            findings.append(Finding(
                                check_id=f"ssti-{engine.split('/')[0].lower().replace(' ', '-')}",
                                severity=Severity.CRITICAL,
                                title=f"SSTI detectado (posible {engine})",
                                detail=(
                                    f"Payload '{payload}' fue evaluado por el servidor, "
                                    f"produciendo '{expected}' en la respuesta. "
                                    f"Esto indica Server-Side Template Injection."
                                ),
                                remediation=(
                                    "Nunca pasar input de usuario directamente a template engines. "
                                    "Usar sandboxing en templates. Implementar allowlists de funciones."
                                ),
                                evidence=f"Payload: {payload} → {expected}",
                                cwe="CWE-1336",
                            ))
                            break  # Una detección es suficiente
                except httpx.HTTPError:
                    continue
    except Exception as exc:
        logger.warning("Error en check_ssti: %s", exc)

    return findings


# ── 8. Path Traversal Detection ──────────────────────────────────


async def check_path_traversal(url: str) -> List[Finding]:
    """Detecta vulnerabilidades de path traversal en parámetros."""
    findings: List[Finding] = []
    parsed = urlparse(url)
    separator = "&" if parsed.query else "?"

    # Payloads de path traversal
    payloads = [
        ("../../etc/passwd", ["root:", "/bin/bash", "/bin/sh"]),
        ("..\\..\\windows\\win.ini", ["[fonts]", "[extensions]"]),
        ("....//....//etc/passwd", ["root:", "/bin/bash"]),
        ("%2e%2e/%2e%2e/etc/passwd", ["root:", "/bin/bash"]),
    ]

    # Parámetros comunes que podrían ser vulnerables
    param_names = ["file", "path", "page", "doc", "template", "include", "dir", "img", "src"]

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            for param in param_names:
                for payload, indicators in payloads:
                    test_url = f"{url}{separator}{param}={quote(payload)}"
                    try:
                        resp = await client.get(test_url)
                        if any(ind in resp.text for ind in indicators):
                            findings.append(Finding(
                                check_id=f"path-traversal-{param}",
                                severity=Severity.CRITICAL,
                                title=f"Path Traversal detectado en parámetro '{param}'",
                                detail=(
                                    f"Payload '{payload}' en parámetro '{param}' expuso "
                                    f"contenido del sistema de archivos en la respuesta."
                                ),
                                remediation=(
                                    "Validar y sanitizar todas las rutas de archivo. "
                                    "Usar allowlists de archivos permitidos. "
                                    "Nunca usar input de usuario directamente en operaciones de archivo."
                                ),
                                evidence=f"Param: {param}, Payload: {payload}",
                                cwe="CWE-22",
                            ))
                            return findings  # Una detección es suficiente
                    except httpx.HTTPError:
                        continue
    except Exception as exc:
        logger.warning("Error en check_path_traversal: %s", exc)

    return findings


# ── 9. Information Disclosure ────────────────────────────────────


async def check_info_disclosure(url: str) -> List[Finding]:
    """Detecta fugas de información en rutas de debug, backups y archivos expuestos."""
    findings: List[Finding] = []

    # Rutas de debug y archivos sensibles
    sensitive_paths = [
        ("/debug", "debug endpoint"),
        ("/trace", "trace endpoint"),
        ("/server-status", "Apache server-status"),
        ("/server-info", "Apache server-info"),
        ("/.env.bak", "env backup"),
        ("/.env.old", "env old backup"),
        ("/.env.save", "env save"),
        ("/config.bak", "config backup"),
        ("/config.old", "config old"),
        ("/web.config", "IIS config"),
        ("/phpinfo.php", "phpinfo"),
        ("/.DS_Store", "macOS DS_Store"),
        ("/Thumbs.db", "Windows Thumbs.db"),
        ("/.svn/entries", "SVN entries"),
        ("/.hg/dirstate", "Mercurial dirstate"),
        ("/robots.txt", "robots.txt"),
        ("/sitemap.xml", "sitemap"),
        ("/crossdomain.xml", "Flash crossdomain"),
        ("/elmah.axd", "ELMAH error log"),
        ("/wp-config.php.bak", "WordPress config backup"),
    ]

    # Patrones de stack traces
    stack_trace_patterns = [
        r"Traceback \(most recent call last\)",
        r"at [\w.]+\([\w.]+:\d+\)",
        r"Exception in thread",
        r"Fatal error:",
        r"Stack trace:",
        r"Internal Server Error.*?at ",
    ]
    stack_pattern = re.compile("|".join(stack_trace_patterns), re.IGNORECASE)

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            for path, desc in sensitive_paths:
                test_url = urljoin(url, path)
                try:
                    resp = await client.get(test_url)
                    if resp.status_code == 200 and len(resp.text.strip()) > 10:
                        # Filtrar páginas de error genéricas
                        body_lower = resp.text.lower()
                        is_generic_404 = any(
                            m in body_lower
                            for m in ["not found", "404", "page not found"]
                        )
                        if not is_generic_404:
                            severity = Severity.HIGH if "bak" in path or "config" in path else Severity.MEDIUM
                            findings.append(Finding(
                                check_id=f"info-disclosure-{desc.replace(' ', '-')}",
                                severity=severity,
                                title=f"Información expuesta: {desc}",
                                detail=f"La ruta {path} responde con contenido (HTTP 200).",
                                remediation=(
                                    f"Bloquear acceso a {path} en la configuración del servidor. "
                                    "Eliminar archivos de backup y debug de producción."
                                ),
                                evidence=f"URL: {test_url}, Size: {len(resp.text)} bytes",
                                cwe="CWE-200",
                            ))
                except httpx.HTTPError:
                    continue

            # Verificar stack traces en página principal
            try:
                main_resp = await client.get(url)
                if stack_pattern.search(main_resp.text):
                    findings.append(Finding(
                        check_id="info-disclosure-stack-trace",
                        severity=Severity.MEDIUM,
                        title="Stack trace detectado en respuesta",
                        detail="La respuesta del servidor contiene un stack trace visible.",
                        remediation=(
                            "Deshabilitar debug mode en producción. "
                            "Configurar páginas de error personalizadas."
                        ),
                        evidence="Stack trace encontrado en la respuesta principal.",
                        cwe="CWE-209",
                    ))
            except httpx.HTTPError:
                pass
    except Exception as exc:
        logger.warning("Error en check_info_disclosure: %s", exc)

    return findings


# ── 10. JWT Weakness Analysis ────────────────────────────────────


async def analyze_jwt(url: str) -> JWTAnalysisResult:
    """Analiza JWTs encontrados en respuestas o cookies del sitio."""
    result = JWTAnalysisResult()

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(url)

            # Buscar JWTs en cookies
            jwt_pattern = re.compile(
                r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"
            )

            # Buscar en Set-Cookie headers
            tokens: List[str] = []
            for cookie_header in resp.headers.get_list("set-cookie"):
                matches = jwt_pattern.findall(cookie_header)
                tokens.extend(matches)

            # Buscar en body
            body_matches = jwt_pattern.findall(resp.text)
            tokens.extend(body_matches)

            if not tokens:
                return result

            result.token_found = True
            token = tokens[0]  # Analizar el primero

            # Decodificar header y payload (sin verificar firma)
            parts = token.split(".")
            if len(parts) >= 2:
                try:
                    header_b64 = parts[0] + "=" * (4 - len(parts[0]) % 4)
                    header = json.loads(base64.urlsafe_b64decode(header_b64))
                    result.header = header
                    result.algorithm = header.get("alg", "unknown")
                except Exception:
                    pass

                try:
                    payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
                    payload = json.loads(base64.urlsafe_b64decode(payload_b64))
                    # Redactar datos sensibles
                    safe_claims = {}
                    for k, v in payload.items():
                        if k in ("sub", "iss", "aud", "exp", "iat", "nbf", "jti", "typ"):
                            safe_claims[k] = v
                        else:
                            safe_claims[k] = "[REDACTED]"
                    result.claims = safe_claims
                except Exception:
                    pass

            # Verificar debilidades
            alg = result.algorithm.lower()
            if alg == "none":
                result.weaknesses.append("Algorithm 'none' — firma no requerida")
                result.findings.append(Finding(
                    check_id="jwt-alg-none",
                    severity=Severity.CRITICAL,
                    title="JWT con algorithm 'none'",
                    detail="El JWT usa algorithm 'none', permitiendo tokens falsificados sin firma.",
                    remediation="Siempre validar el algorithm del JWT. Rechazar 'none'.",
                    evidence=f"Algorithm: {result.algorithm}",
                    cwe="CWE-345",
                ))
            elif alg in ("hs256", "hs384", "hs512"):
                result.weaknesses.append(f"HMAC simétrico ({alg}) — vulnerable a brute force de secret")
                result.findings.append(Finding(
                    check_id="jwt-weak-hmac",
                    severity=Severity.MEDIUM,
                    title=f"JWT usa HMAC simétrico ({result.algorithm})",
                    detail=(
                        f"El JWT usa {result.algorithm}. Si el secret es débil, "
                        "un atacante podría adivinarlo y falsificar tokens."
                    ),
                    remediation=(
                        "Usar secrets de al menos 256 bits de entropía. "
                        "Considerar migrar a RSA/ECDSA (RS256/ES256)."
                    ),
                    evidence=f"Algorithm: {result.algorithm}",
                    cwe="CWE-326",
                ))

            # Verificar claims faltantes
            if "exp" not in result.claims:
                result.weaknesses.append("Sin claim 'exp' — token sin expiración")
                result.findings.append(Finding(
                    check_id="jwt-no-expiration",
                    severity=Severity.MEDIUM,
                    title="JWT sin expiración (claim 'exp' ausente)",
                    detail="El JWT no tiene claim de expiración, permanece válido indefinidamente.",
                    remediation="Agregar claim 'exp' con tiempo de expiración razonable.",
                    evidence="Claim 'exp' no encontrado en el payload.",
                    cwe="CWE-613",
                ))

    except Exception as exc:
        logger.warning("Error en analyze_jwt: %s", exc)

    return result
