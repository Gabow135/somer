---
name: security-evidence
description: "Gestión de evidencia de pentesting — screenshots, HTTP logs, redacción de datos sensibles, cadenas de evidencia y paquetes ZIP exportables. Use when: user asks to capture evidence, export findings, build evidence chain."
homepage: https://github.com/somer-ai/somer
metadata: { "somer": { "emoji": "📸", "requires": { "env": [] } } }
tags: [evidence, screenshot, http-log, redaction, chain, export, zip, package, report]
triggers: [capturar evidencia, evidence, screenshot de seguridad, exportar evidencia, cadena de evidencia, paquete de evidencia, redactar datos, extraer datos sensibles, evidence package, export evidence]
---

# Security Evidence Skill

Gestión de evidencia de pentesting — captura, redacción y exportación.

## Reglas

1. **Siempre redactar datos sensibles** — passwords, API keys, emails, tarjetas.
2. **Organizar en workspace** — toda la evidencia se guarda en ~/.somer/security/.
3. **Cadena de evidencia** — conectar findings con exploits para trazabilidad.

## Tools

- `capture_screenshot` — Screenshot full-page de una URL
- `extract_sensitive_data` — Extrae y redacta datos sensibles
- `build_evidence_chain` — Construye cadena de evidencia
- `pentest_evidence` — Fase de evidencia completa del orquestador

## Estructura del Workspace

```
~/.somer/security/scans/{domain}_{timestamp}/
├── plan.json
├── recon/
├── scan_report.json
├── scan_report.md
├── exploits/{exploit_id}/
│   ├── result.json
│   ├── screenshot_*.png
│   └── request_log.json
├── evidence/
│   ├── chain.json
│   ├── screenshots/
│   └── http_logs/
├── exploit_report.md
├── final_report.md
└── evidence_package.zip
```

## Datos que se Redactan Automáticamente

- Passwords y secrets (`password=****`)
- API keys y tokens
- Emails (`[EMAIL]`)
- Números de tarjeta (`[CARD_NUMBER]`)
- SSN (`[SSN]`)
- SSH keys

## Cuándo Usar

- "Captura screenshot de example.com"
- "Exporta la evidencia del pentest"
- "Construye la cadena de evidencia"
- "Redacta los datos sensibles de este texto"

## Formato de Respuesta

**Usar plantilla `TPL-EVIDENCE`** de `_templates/RESPONSE_FORMATS.md`. Ejemplo:

```
EVIDENCIA — example.com | 26/Mar/2026

PAQUETE
  Capturas:     6 screenshots
  Logs HTTP:    12 request/response
  Datos:        3 archivos (redactados)
  Cadena:       5 pasos documentados

CADENA DE EVIDENCIA
  1. Reconocimiento — 4 subdominios, 3 puertos abiertos
  2. Escaneo — 11 vulnerabilidades detectadas
  3. Explotación SQLi — dump parcial de DB (redactado)
  4. Explotación XSS — cookie de sesión capturada
  5. Escalamiento — acceso a panel admin demostrado

EXPORTADO
  ZIP: ~/.somer/security/evidence_example_com_20260326.zip
  Tamaño: 2.3 MB

---
Capturado por: SOMER Evidence | Workspace: ~/.somer/security/pentest_example_com/
```
