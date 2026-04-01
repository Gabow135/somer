---
name: security-scanner
description: "Escaneo avanzado de vulnerabilidades — 18 checks estándar + 10 scanners avanzados (SQLi, SSTI, path traversal, JWT, etc.). Use when: user asks to scan for vulnerabilities, check for specific vulnerability types."
homepage: https://github.com/somer-ai/somer
metadata: { "somer": { "emoji": "🔬", "requires": { "env": [] } } }
tags: [scanner, vulnerability, sqli, ssti, xss, path-traversal, jwt, session, smuggling, admin-panel, info-disclosure]
triggers: [escanear vulnerabilidades, buscar vulnerabilidades avanzadas, sql injection, ssti, path traversal, jwt, session fixation, request smuggling, paneles admin, information disclosure, escaneo avanzado, vulnerability scan]
---

# Security Scanner Skill

Escaneo avanzado de vulnerabilidades — combina 18 checks estándar con 10 scanners avanzados.

## Reglas

1. **Solo escanear cuando se pida** — nunca sin solicitud.
2. **No destructivo** — solo detección, nunca explotación.
3. **Reportar en español** con severidad clara.

## Scanners Estándar (18)

- Headers de seguridad, SSL/TLS, Cookies, Tecnologías, DNS
- Rutas expuestas, CORS, Formularios, XSS, Puertos
- Métodos HTTP, HTTPS redirect, SRI, Contenido mixto
- Directory listing, HTML leaks, CSP, Email security

## Scanners Avanzados (10)

- `check_sqli` — SQL Injection (error-based, time-based)
- `check_admin_panels` — Paneles admin accesibles
- `enumerate_subdomains` — Enumeración de subdominios
- `detect_waf` — Detección de WAF
- `check_session_management` — Session fixation
- `check_request_smuggling` — HTTP Request Smuggling
- `check_ssti` — Server-Side Template Injection
- `check_path_traversal` — Path traversal
- `check_info_disclosure` — Fugas de información
- `analyze_jwt` — Debilidades en JWT

## Flujo Recomendado

### Escaneo Completo
```
security_scan(url="target.com")  # 18 checks estándar
```
Luego scanners avanzados específicos según findings.

### Escaneo Específico
Usar tools individuales según lo que pida el usuario.

## Formato de Respuesta

**Usar plantilla `TPL-SECURITY-AUDIT`** de `_templates/RESPONSE_FORMATS.md`. Ejemplo:

```
AUDITORÍA DE SEGURIDAD — example.com | 26/Mar/2026

RESUMEN EJECUTIVO
  Riesgo global:  5.4/10 — MEDIO
  Hallazgos:      1 crítico | 1 alto | 2 medios | 3 bajos | 5 info

TOP 3 CRÍTICOS
  1. SQLi detectado en /api/search — error-based
  2. Sin HSTS — permite downgrade
  3. Admin panel accesible en /admin

HALLAZGOS DETALLADOS

  [!!] V01 SQL Injection
    Severidad:    CRITICAL
    Hallazgo:     Parámetro q en /api/search vulnerable a error-based SQLi
    Impacto:      Lectura completa de base de datos
    Remediación:  Usar prepared statements / parameterized queries

  [OK] V02 SSL/TLS
    Severidad:    INFO
    Hallazgo:     TLS 1.3, certificado válido

ACCIONES PRIORITARIAS
  1. Corregir SQLi en /api/search (inmediato)
  2. Implementar HSTS
  3. Restringir acceso a /admin por IP

---
Escaneado por: SOMER Security | Método: escaneo avanzado
```
