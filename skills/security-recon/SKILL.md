---
name: security-recon
description: "Reconocimiento de seguridad — descubre tecnologías, DNS, puertos, subdominios y WAF de un target. Use when: user asks to recon, discover, enumerate, or fingerprint a website."
homepage: https://github.com/somer-ai/somer
metadata: { "somer": { "emoji": "🔍", "requires": { "env": [] } } }
tags: [recon, reconnaissance, discovery, subdomain, dns, ports, waf, fingerprint, technology]
triggers: [reconocimiento, recon, descubrir tecnologías, enumerar subdominios, detectar waf, fingerprint, descubrimiento, qué tecnologías usa, subdominios de, puertos abiertos de, dns de, waf de]
---

# Security Recon Skill

Fase de reconocimiento de seguridad — recopila información del target antes del escaneo.

## Reglas

1. **Solo ejecutar cuando se pida** — nunca iniciar recon sin solicitud.
2. **No destructivo** — solo recopila información pública.
3. **Respetar scope** — no expandir más allá de lo solicitado.

## Cuándo Usar

- "¿Qué tecnologías usa example.com?"
- "Enumera los subdominios de example.com"
- "¿Tiene WAF example.com?"
- "Haz reconocimiento de example.com"
- "¿Qué puertos tiene abiertos?"
- "DNS de example.com"

## Tools Disponibles

- `discover_tech` — Detecta tecnologías (frameworks, CMS, servidor web)
- `dns_lookup` — Consulta DNS (A, AAAA, MX, TXT, NS)
- `scan_ports` — Escaneo de puertos TCP abiertos
- `enumerate_subdomains` — Enumeración via CT logs + DNS brute
- `detect_waf` — Detección de Web Application Firewall

## Flujo Recomendado

1. `discover_tech` para entender el stack
2. `dns_lookup` para registros DNS
3. `enumerate_subdomains` para superficie de ataque
4. `scan_ports` para servicios expuestos
5. `detect_waf` para conocer protecciones

## Formato de Respuesta

**Usar plantilla `TPL-RECON`** de `_templates/RESPONSE_FORMATS.md`. Ejemplo:

```
RECONOCIMIENTO — example.com | 26/Mar/2026

SUPERFICIE DE ATAQUE
  Tecnologías:   nginx/1.18, Express 4.x, React
  CDN/WAF:       Cloudflare detectado (confianza: alta)
  IPs:           104.21.x.x, 172.67.x.x

SUBDOMINIOS (4 encontrados)
  api.example.com — 104.21.x.x — 200
  staging.example.com — 172.67.x.x — 403
  mail.example.com — 104.21.x.x — 200
  dev.example.com — 172.67.x.x — 503

PUERTOS ABIERTOS (3)
  80/tcp — HTTP — nginx/1.18
  443/tcp — HTTPS — nginx/1.18
  8080/tcp — HTTP-ALT — Node.js

DNS
  A:      104.21.x.x
  MX:     mx1.mail.example.com
  NS:     ns1.cloudflare.com, ns2.cloudflare.com
  TXT:    v=spf1 include:_spf.google.com ~all

OBSERVACIONES
  [!] staging.example.com accesible públicamente (403 pero responde)
  [!] Puerto 8080 expuesto — posible entorno de desarrollo

---
Reconocimiento por: SOMER Recon | Método: pasivo
```
