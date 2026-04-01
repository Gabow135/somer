---
name: network-monitor
description: "Monitoreo de red e infraestructura — ping, traceroute, cert expiry, uptime, DNS health. Combinado con cron para alertas proactivas."
version: "1.0.0"
triggers:
  - monitorear
  - monitor
  - ping
  - traceroute
  - certificado ssl
  - cert expiry
  - uptime
  - está caído
  - está online
  - health check de
  - verificar servidor
  - check server
  - dns health
  - latencia de
  - tiempo de respuesta
  - monitoreo de red
  - network monitor
  - verificar disponibilidad
  - cuándo expira el certificado
  - ssl check
  - está funcionando
tags:
  - monitoring
  - network
  - ping
  - uptime
  - ssl
  - cert
  - dns
  - health
  - infrastructure
category: monitoring
enabled: true
---

# Skill: Network Monitor

Monitoreo de red e infraestructura — verifica disponibilidad, latencia, certificados SSL y salud DNS.

## Reglas

1. **No intrusivo** — solo verificaciones pasivas (ping, HTTP HEAD, DNS query).
2. **Alertas claras** — reportar estado con emojis: OK / WARN / CRITICAL / DOWN.
3. **Uso con cron** — ideal para verificaciones periódicas automáticas.

## Cuándo Usar

- "¿Está online example.com?"
- "¿Cuándo expira el certificado SSL de example.com?"
- "Haz ping a 1.2.3.4"
- "Traceroute a example.com"
- "Verifica la salud DNS de example.com"
- "Monitorea estos 5 servidores cada hora"

## Tools Disponibles

- `net_ping` — Ping a host/IP con estadísticas (RTT min/avg/max, packet loss)
- `net_traceroute` — Traza la ruta de red hasta un host
- `net_cert_check` — Verifica certificado SSL (emisor, expiración, cadena, alertas)
- `net_http_check` — Verifica respuesta HTTP (status, headers, redirect chain, timing)
- `net_dns_health` — Verifica salud DNS (resolución, propagación, registros críticos)
- `net_full_check` — Pipeline completo: ping + HTTP + cert + DNS para un host

## Flujo Recomendado

1. `net_ping` para verificar conectividad básica
2. `net_http_check` para verificar servicio web
3. `net_cert_check` para expiración de certificado
4. `net_dns_health` para salud DNS
5. Consolidar resultado con estado general

## Uso con Cron

Configurar verificaciones periódicas:
```
"Monitorea example.com cada 30 minutos y alerta si cae"
```
El cron ejecuta `net_full_check` y envía alerta por Telegram si algo falla.

## Integración con Otras Skills

- **daily-briefing**: Estado de servidores en el briefing matutino
- **security-recon**: Complementa con info de infraestructura
- **report-generator**: Exporta historial de uptime a reporte

## Formato de Respuesta

**Usar plantilla `TPL-NETWORK`** de `_templates/RESPONSE_FORMATS.md`. Ejemplo:

```
MONITOREO — example.com | 26/Mar/2026

ESTADO GENERAL: OK

CHECKS
  [OK] Ping:    23ms avg, 0% loss
  [OK] HTTP:    200 OK (342ms TTFB)
  [OK] SSL:     Válido, expira en 45 días (Let's Encrypt)
  [OK] DNS:     Resolución OK, 4 NS, SPF+DMARC presentes

---
Verificado por: SOMER Network Monitor
```

Para múltiples hosts:
```
MONITOREO — 3 hosts | 26/Mar/2026

RESUMEN: 2 OK | 1 WARN

  [OK] api.example.com — OK (23ms)
  [OK] web.example.com — OK (45ms)
  [!]  db.example.com  — SSL expira en 12 días

ALERTAS
  [!] db.example.com: Renovar certificado SSL antes de 07/Abr/2026

---
Verificado por: SOMER Network Monitor
```
