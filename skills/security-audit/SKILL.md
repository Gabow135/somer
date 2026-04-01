---
name: security-audit
description: "Auditoría de seguridad web defensiva — analiza sitios para encontrar vulnerabilidades, demuestra su impacto con PoC seguros, y genera reportes con remediaciones detalladas. Use when: user asks to scan, audit, check, or exploit-test a website's security. NOT for: destructive attacks, DDoS, or brute force. No API key needed."
homepage: https://github.com/somer-ai/somer
metadata: { "somer": { "emoji": "🛡️", "requires": { "env": [] } } }
tags: [security, audit, web, cybersecurity, vulnerability, headers, ssl, scanning, csp, sri, email-security, exploit, poc, proof-of-concept]
triggers: [security audit, escaneo de seguridad, auditoría de seguridad, analizar seguridad, vulnerabilidades, buscar vulnerabilidades, scan security, check security, check headers, check ssl, sri, subresource integrity, mixed content, contenido mixto, directory listing, métodos http, http methods, csp, content security policy, email security, spf, dmarc, dkim, https redirect, demuestra vulnerabilidades, comprueba seguridad]
---

# Security Audit Skill

Auditoría de seguridad web defensiva — detectar, reportar y demostrar impacto con PoC seguros.

## Reglas

1. **Solo escanear cuando se pida explícitamente** — nunca iniciar un escaneo sin que el usuario lo solicite.
2. **Asumir autorización** — si el usuario pide analizar un sitio, asume que tiene permiso.
3. **PoC seguros y no destructivos** — los exploits solo demuestran impacto, nunca modifican datos del target.
4. **Responder en español** — reportes y explicaciones en español.
5. **Ser específico en remediaciones** — dar pasos concretos con código real para cada hallazgo.

## Cuándo Usar

✅ **USA este skill cuando:**

- "Analiza la seguridad de example.com"
- "Revisa los headers de seguridad de mi sitio"
- "¿Mi certificado SSL está bien configurado?"
- "Busca vulnerabilidades en mi página"
- "Escaneo de seguridad completo"
- "¿Qué tecnologías usa example.com?"
- "Revisa las cookies de mi sitio"
- "Verifica el CSP de mi sitio"
- "¿Tiene SRI los scripts externos?"
- "Revisa si hay contenido mixto"
- "¿Está habilitado el directory listing?"
- "Verifica SPF, DMARC y DKIM de mi dominio"
- "¿Redirige bien de HTTP a HTTPS?"
- "Demuestra las vulnerabilidades de mi sitio"
- "Ejecuta exploits sobre los hallazgos"
- "Comprueba si las vulnerabilidades son explotables"
- "Prueba de concepto de las vulnerabilidades encontradas"

## Cuándo NO Usar

❌ **NO uses este skill cuando:**

- Ataques DDoS o de fuerza bruta → nunca
- Análisis de código fuente → usar herramientas de SAST
- Auditoría de red interna → fuera de alcance
- Modificación de datos del target → nunca

## Flujo de Trabajo

### Escaneo Rápido (por defecto)
Cuando el usuario pide "revisa" o "analiza" sin más detalle:
1. Usa `check_headers` para headers de seguridad
2. Usa `check_ssl` para certificado SSL
3. Usa `check_cookies` para cookies
4. Interpreta resultados y da recomendaciones con código

### Escaneo Completo
Cuando el usuario pide "escaneo completo" o "auditoría completa":
1. Usa `security_scan` con todos los checks habilitados (18 checks)
2. Interpreta el reporte completo
3. Ofrece generar reporte Markdown con `generate_security_report`
4. Incluye remediaciones detalladas con snippets de código por plataforma

### Escaneo con Exploits
Cuando el usuario pide "demuestra", "ejecuta exploits", "comprueba" o "prueba de concepto":
1. Primero ejecuta `security_scan` para obtener los findings
2. Luego ejecuta `run_security_exploits` pasando los scan_data
3. El reporte con capturas se envía automáticamente por el canal
4. Todo queda guardado en ~/.somer/security/

### Pentest Completo (Orquestador)
Para auditorías completas con todas las fases (recon → scan → exploit → evidence → report),
usa el skill **pentest-orchestrator** que coordina el flujo completo con tools especializadas:
`pentest_plan` → `pentest_recon` → `pentest_scan` → `pentest_exploit` → `pentest_evidence` → `pentest_report`

### Checks Individuales
Cuando el usuario pregunta algo específico, usa la tool correspondiente:
- "headers" → `check_headers`
- "SSL/certificado" → `check_ssl`
- "cookies" → `check_cookies`
- "tecnologías" → `discover_tech`
- "DNS" → `dns_lookup`
- "rutas/archivos expuestos" → descubrimiento con `security_scan` checks=["paths"]
- "CORS" → `security_scan` checks=["cors"]
- "puertos" → `scan_ports`
- "links" → `crawl_links`
- "métodos HTTP" → `check_http_methods`
- "HTTPS redirect" → `check_https_redirect`
- "SRI" → `check_sri`
- "contenido mixto" → `check_mixed_content`
- "directory listing" → `check_directory_listing`
- "HTML leaks" → `check_html_leaks`
- "CSP" → `analyze_csp`
- "email security (SPF/DMARC/DKIM)" → `check_email_security`

## Formato de Respuesta

**Usar plantilla `TPL-SECURITY-AUDIT`** de `_templates/RESPONSE_FORMATS.md`. Ejemplo:

```
AUDITORÍA DE SEGURIDAD — example.com | 26/Mar/2026

RESUMEN EJECUTIVO
  Riesgo global:  6.2/10 — MEDIO
  Hallazgos:      0 críticos | 2 altos | 3 medios | 1 bajo | 4 info

TOP 3 CRÍTICOS
  1. Sin HSTS — permite downgrade a HTTP
  2. Server header expuesto — revela nginx/1.18
  3. Sin SRI en scripts CDN — riesgo de supply-chain

HALLAZGOS DETALLADOS

  [!!] H01 Security Headers
    Severidad:    HIGH
    Hallazgo:     Faltan HSTS, X-Content-Type-Options, Permissions-Policy
    Impacto:      Ataques MITM y clickjacking
    Remediación:  Agregar headers en server config
    Código:
      nginx:   add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
      apache:  Header always set Strict-Transport-Security "max-age=31536000; includeSubDomains"

  [OK] H02 SSL/TLS
    Severidad:    INFO
    Hallazgo:     TLS 1.3, certificado válido 89 días

EVIDENCIA DE EXPLOITS (si aplica)
  H01: Downgrade HTTP demostrado — redirect sin HSTS permite intercepción
    Resultado: Cookie de sesión capturada en HTTP plano
    Impacto:   Session hijacking posible

ACCIONES PRIORITARIAS
  1. Implementar HSTS con preload
  2. Ocultar Server header
  3. Agregar SRI a scripts externos

---
Escaneado por: SOMER Security | Método: completo
```

### Remediaciones con Código
Cada hallazgo HIGH/CRITICAL incluye snippets para: nginx, Apache, Express/Node.js, Next.js, Django, General (HTML, DNS, etc.)

## Interpretación de Severidades

| Severidad | Significado |
|-----------|-------------|
| CRITICAL | Vulnerabilidad explotable activamente, requiere acción inmediata |
| HIGH | Riesgo significativo, corregir lo antes posible |
| MEDIUM | Riesgo moderado, planificar corrección |
| LOW | Riesgo bajo, mejorar cuando sea posible |
| INFO | Informativo, no necesariamente un problema |

## Puntuación de Riesgo

- **0-2**: Buen estado de seguridad
- **3-4**: Algunas mejoras necesarias
- **5-6**: Riesgos moderados, requiere atención
- **7-8**: Riesgos altos, acción urgente
- **9-10**: Estado crítico, acción inmediata

## Tools Disponibles

- `security_scan` — Escaneo completo o parcial (combina 18 checks)
- `check_headers` — Análisis de headers de seguridad HTTP
- `check_ssl` — Análisis de certificado SSL/TLS
- `check_cookies` — Análisis de cookies de seguridad
- `discover_tech` — Detección de tecnologías del servidor
- `dns_lookup` — Consulta de registros DNS
- `crawl_links` — Descubrimiento de links internos/externos
- `scan_ports` — Escaneo de puertos TCP abiertos
- `generate_security_report` — Genera reporte Markdown exportable
- `check_http_methods` — Detecta métodos HTTP inseguros (PUT/DELETE/TRACE)
- `check_https_redirect` — Verifica redirección HTTP → HTTPS
- `check_sri` — Verifica Subresource Integrity en recursos externos
- `check_mixed_content` — Detecta contenido mixto HTTP en HTTPS
- `check_directory_listing` — Detecta directory listing habilitado
- `check_html_leaks` — Detecta fugas en HTML (comentarios, versiones, emails)
- `analyze_csp` — Análisis detallado de Content Security Policy
- `check_email_security` — Verifica SPF, DMARC y DKIM en DNS
- `run_security_exploits` — Ejecuta PoC seguros sobre findings y genera reporte con evidencia
