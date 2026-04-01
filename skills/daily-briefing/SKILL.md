---
name: daily-briefing
description: "Briefing matutino automático — clima, eventos, seguimientos, finanzas, estado de servidores. Un solo mensaje cada mañana via cron."
version: "1.0.0"
triggers:
  - briefing
  - briefing del día
  - resumen del día
  - qué tengo hoy
  - daily briefing
  - mi agenda de hoy
  - dame mi resumen
  - buenos días qué hay
  - cómo está todo hoy
  - morning briefing
  - resumen matutino
  - agenda del día
tags:
  - briefing
  - daily
  - summary
  - agenda
  - morning
  - productivity
  - personal
category: personal
enabled: true
---

# Skill: Daily Briefing

Briefing diario consolidado — reúne información de todas las skills conectadas en un solo mensaje.

## Reglas

1. **Consolidar, no duplicar** — un solo mensaje con toda la información relevante.
2. **Priorizar lo urgente** — mostrar primero: alertas, vencimientos, citas próximas.
3. **Configurable** — el usuario elige qué secciones incluir.
4. **Ideal con cron** — programar ejecución automática cada mañana.

## Cuándo Usar

- "Dame mi briefing del día"
- "¿Qué tengo para hoy?"
- Automáticamente via cron cada mañana (recomendado)
- "Configura briefing diario a las 7 AM"

## Tools Disponibles

- `briefing_generate` — Genera briefing completo consultando todas las skills activas
- `briefing_configure` — Configura secciones a incluir y horario de cron
- `briefing_history` — Ver briefings anteriores

## Secciones del Briefing

1. **Clima** — Temperatura y pronóstico del día (via `weather`)
2. **Calendario** — Eventos de hoy y mañana (via `google-calendar`)
3. **Seguimientos CRM** — Follow-ups del día y vencidos (via `crm-lite`)
4. **Tareas** — Tarjetas de Trello con fecha hoy (via `trello`)
5. **Finanzas** — Balance del día anterior, gastos pendientes (via `financial-tracker`)
6. **Servidores** — Estado de hosts monitoreados (via `network-monitor`)
7. **Action Items** — Pendientes de reuniones (via `meeting-notes`)
8. **Bookmarks recientes** — Links guardados ayer (via `bookmark-manager`)

## Configuración con Cron

```json
{
  "schedule": "0 7 * * 1-5",
  "message": "Genera mi briefing del día",
  "channel": "telegram",
  "sections": ["weather", "calendar", "crm", "tasks", "finance", "servers"]
}
```

## Integración con Otras Skills

- **weather**: Clima del día
- **google-calendar**: Eventos
- **crm-lite**: Seguimientos pendientes
- **trello**: Tareas con deadline hoy
- **financial-tracker**: Balance y presupuestos
- **network-monitor**: Estado de servidores
- **meeting-notes**: Action items pendientes
- **bookmark-manager**: Links recientes
- **apple-reminders**: Recordatorios del día

## Formato de Respuesta

**Usar plantilla `TPL-BRIEFING`** de `_templates/RESPONSE_FORMATS.md`. Ejemplo:

```
BRIEFING — 26/Mar/2026

CLIMA
  Bogotá: 18°C, parcialmente nublado
  Máx 22° / Mín 12°

AGENDA (3 eventos)
  09:00 — Standup equipo (Google Meet)
  11:00 — Reunión con Acme (presencial)
  15:00 — Demo producto (Zoom)

SEGUIMIENTOS CRM (2 pendientes)
  [!!] Juan (Acme) — Enviar contrato (vencido 24/Mar/2026)
  [ ]  Pedro (StartupX) — Llamar para cotización (27/Mar/2026)

TAREAS (4 pendientes)
  [ ] Preparar ambiente staging — hoy
  [ ] Revisar PR #142 — hoy
  [ ] Actualizar docs API — mañana
  [ ] Deploy v2.1 — viernes

FINANZAS
  Ayer: +$3,000.00 / -$150.00
  Mes:  +$8,270.00
  [!] Marketing al 85% del presupuesto

SERVIDORES (3 monitoreados)
  [OK] api.example.com — OK (23ms)
  [OK] web.example.com — OK (45ms)
  [!]  db.example.com — SSL expira en 12 días

---
Generado: 26/Mar/2026 07:00 | Canal: telegram
```
