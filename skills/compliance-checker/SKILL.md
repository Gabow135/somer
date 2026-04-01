---
name: compliance-checker
description: "Verificación de cumplimiento de estándares de seguridad — OWASP Top 10, PCI-DSS, GDPR, ISO 27001. Genera checklists y reportes de cumplimiento."
version: "1.0.0"
triggers:
  - compliance
  - cumplimiento
  - owasp
  - pci-dss
  - pci dss
  - gdpr
  - iso 27001
  - checklist de seguridad
  - verificar cumplimiento
  - estándares de seguridad
  - security compliance
  - normativa
  - regulación
  - auditoría de cumplimiento
  - compliance check
  - está en cumplimiento
  - check standards
  - security standards
  - best practices
  - buenas prácticas de seguridad
tags:
  - compliance
  - owasp
  - pci-dss
  - gdpr
  - iso27001
  - standards
  - checklist
  - audit
  - security
category: security
enabled: true
---

# Skill: Compliance Checker

Verificación de cumplimiento de estándares de seguridad contra dominios, aplicaciones o infraestructura.

## Reglas

1. **No reemplaza auditoría formal** — es una verificación automatizada inicial.
2. **Especificar estándar** — si no se indica, usar OWASP Top 10 como default.
3. **Evidencia por check** — cada verificación incluye pass/fail con evidencia.

## Cuándo Usar

- "¿Cumple example.com con OWASP Top 10?"
- "Checklist PCI-DSS para mi sitio"
- "Verificar GDPR compliance de example.com"
- "¿Qué estándares de seguridad cumple?"
- "Auditoría de buenas prácticas de seguridad"
- "Check ISO 27001 para mi infraestructura"

## Tools Disponibles

- `compliance_owasp_check` — Verifica OWASP Top 10 2021 (A01-A10) contra un dominio
- `compliance_pci_check` — Verifica PCI-DSS v4.0 básico (TLS, headers, storage, access)
- `compliance_gdpr_check` — Verifica GDPR básico (privacy policy, cookies, data handling, contact)
- `compliance_headers_check` — Verifica security headers (CSP, HSTS, X-Frame, etc.)
- `compliance_ssl_check` — Verifica TLS/SSL compliance (versión, cipher suites, HSTS)
- `compliance_full_audit` — Pipeline: OWASP + PCI + GDPR + headers + SSL

## Estándares Soportados

### OWASP Top 10 (2021)
- A01: Broken Access Control
- A02: Cryptographic Failures
- A03: Injection
- A04: Insecure Design
- A05: Security Misconfiguration
- A06: Vulnerable Components
- A07: Auth Failures
- A08: Software/Data Integrity
- A09: Logging Failures
- A10: SSRF

### PCI-DSS v4.0 (básico)
- Req 2: Secure configurations
- Req 4: Strong cryptography (TLS)
- Req 6: Secure software
- Req 8: Access management

### GDPR (básico)
- Privacy policy presence
- Cookie consent
- Data processing disclosure
- DPO contact

## Integración con Otras Skills

- **security-audit**: Complementa auditoría técnica con compliance
- **security-scanner**: Usa resultados de escaneo para verificar OWASP
- **report-generator**: Exporta checklist completo a PDF con pass/fail
- **pentest-orchestrator**: Agrega verificación de compliance post-pentest

## Formato de Respuesta

**Usar plantilla `TPL-COMPLIANCE`** de `_templates/RESPONSE_FORMATS.md`. Ejemplo:

```
COMPLIANCE — example.com | OWASP Top 10 (2021) | 26/Mar/2026

RESULTADO: 5/8 verificables = 63% | Riesgo: MEDIO

CHECKS
  [OK] A01 Broken Access Control
  [!]  A02 Cryptographic Failures — TLS 1.2 OK pero no HSTS preload
  [OK] A03 Injection
  [--] A04 Insecure Design — requiere revisión manual
  [!!] A05 Security Misconfiguration — Server header expuesto, directory listing
  [!]  A06 Vulnerable Components — jQuery 3.3.1 (CVE conocidos)
  [OK] A07 Auth Failures
  [!!] A08 Integrity Failures — No SRI en scripts externos
  [--] A09 Logging Failures — requiere acceso interno
  [OK] A10 SSRF

HALLAZGOS RELEVANTES
  A05: Ocultar Server header y deshabilitar directory listing en config del servidor
  A08: Agregar integrity="sha384-..." y crossorigin="anonymous" a todos los scripts CDN

---
Estándar: OWASP Top 10 2021 | Verificado por: SOMER Compliance
```
