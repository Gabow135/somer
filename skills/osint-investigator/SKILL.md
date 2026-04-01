---
name: osint-investigator
description: "Investigación OSINT — busca emails filtrados, datos expuestos, perfiles en redes sociales, información corporativa pública (Shodan, Censys, HIBP). Conecta con security-recon y pentest-orchestrator."
version: "1.0.0"
triggers:
  - osint
  - investigación osint
  - emails filtrados
  - datos expuestos
  - buscar información de
  - have i been pwned
  - breaches
  - filtraciones
  - datos públicos de
  - perfiles de
  - información corporativa
  - shodan
  - censys
  - exposición de datos
  - data breach
  - leaked credentials
  - buscar persona
  - investigar dominio
  - intelligence gathering
tags:
  - osint
  - intelligence
  - recon
  - breach
  - hibp
  - shodan
  - censys
  - exposure
  - credentials
category: security
enabled: true
---

# Skill: OSINT Investigator

Investigación de inteligencia de fuentes abiertas — recopila información pública sobre targets (dominios, emails, organizaciones).

## Reglas

1. **Solo información pública** — nunca acceder a datos privados o ilegales.
2. **Respetar scope** — investigar solo lo solicitado.
3. **Redactar datos sensibles** — en reportes, ocultar parcialmente emails/passwords filtrados.
4. **Conecta con security-recon** — si se necesita recon técnico, delegar a `security-recon`.

## Cuándo Usar

- "¿Ha sido filtrado el email juan@empresa.com?"
- "¿Qué información pública hay de empresa.com?"
- "Busca filtraciones de datos de este dominio"
- "Investiga qué hay expuesto en Shodan de 1.2.3.4"
- "¿Qué perfiles públicos tiene @usuario?"
- "OSINT de empresa.com"

## Tools Disponibles

- `osint_email_breach` — Verifica si un email aparece en filtraciones conocidas (HIBP API)
- `osint_domain_exposure` — Analiza exposición pública de un dominio (DNS, WHOIS, certificados CT, pastebins)
- `osint_shodan_lookup` — Busca host/IP en Shodan (servicios, puertos, banners, vulns)
- `osint_social_profiles` — Busca perfiles en redes sociales asociados a un username/email
- `osint_corporate_intel` — Información corporativa pública (empleados en LinkedIn, tecnologías, subdominios)
- `osint_full_investigation` — Pipeline completo: breach + exposure + shodan + social + corporate

## Flujo Recomendado

1. `osint_email_breach` para verificar filtraciones de credenciales
2. `osint_domain_exposure` para superficie de exposición del dominio
3. `osint_shodan_lookup` para servicios expuestos en internet
4. `osint_social_profiles` para mapear presencia social
5. `osint_corporate_intel` para información organizacional
6. Generar reporte con `report-generator` si se solicita

## Integración con Otras Skills

- **security-recon**: Complementa con recon técnico (puertos, WAF, tecnologías)
- **pentest-orchestrator**: Alimenta la fase de reconocimiento del pentest
- **report-generator**: Exporta hallazgos a PDF/Excel
- **security-evidence**: Captura evidencia de hallazgos OSINT

## Formato de Respuesta

**Usar plantilla `TPL-OSINT`** de `_templates/RESPONSE_FORMATS.md`. Ejemplo:

```
OSINT — example.com | 26/Mar/2026

EXPOSICIÓN: Alto

BRECHAS DE DATOS (3 encontradas)
  [!!] admin@example.com — LinkedIn Breach (2023)
  [!!] admin@example.com — Collection #1 (2019)
  [!!] info@example.com — Adobe Breach (2013)

SERVICIOS EXPUESTOS (2)
  104.21.x.x:443 — HTTPS — nginx/1.18
  104.21.x.x:8080 — HTTP — Node.js (Express)

PERFILES ENCONTRADOS (3)
  GitHub: github.com/example-team
  LinkedIn: linkedin.com/company/example
  Twitter: twitter.com/example_official

DATOS CORPORATIVOS
  Dominio:     example.com (registrado 2015)
  Registrante: WHOIS protegido
  Empleados:   12 perfiles públicos en LinkedIn
  Tecnologías: React, Node.js, PostgreSQL, AWS

RECOMENDACIONES
  1. Cambiar contraseñas de emails comprometidos
  2. Cerrar puerto 8080 expuesto a internet

---
Investigado por: SOMER OSINT | Fuentes: HIBP, Shodan, DNS
```
