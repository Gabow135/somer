---
name: meeting-notes
description: "Procesar notas de reunión o audio — transcribir, extraer action items, crear tareas, enviar resumen. Conecta con Trello, CRM y Calendar."
version: "1.0.0"
triggers:
  - notas de reunión
  - meeting notes
  - reunión con
  - resumen de reunión
  - minuta
  - action items
  - acuerdos de la reunión
  - tuve reunión con
  - procesar reunión
  - lo que acordamos
  - puntos de la reunión
  - compromisos de la reunión
  - meeting summary
tags:
  - meeting
  - notes
  - transcription
  - action-items
  - summary
  - productivity
  - business
category: business
enabled: true
---

# Skill: Meeting Notes

Procesa notas de reunión (texto o audio) — extrae action items, acuerdos, y distribuye a las herramientas correspondientes.

## Reglas

1. **Extraer estructura** — siempre identificar: asistentes, temas, acuerdos, action items, fechas.
2. **Auto-dispatch** — crear tareas en Trello, registrar en CRM, agendar en Calendar automáticamente.
3. **Formato estándar** — las minutas siguen un formato consistente.

## Cuándo Usar

- "Tuve reunión con Juan de Acme, acordamos X, Y, Z"
- "Procesa esta nota de voz de mi reunión" (audio por Telegram)
- "Minuta de la reunión del lunes con el equipo"
- "¿Cuáles fueron los action items de mi última reunión con Acme?"

## Tools Disponibles

- `meeting_process_notes` — Procesa texto de reunión: extrae asistentes, temas, acuerdos, action items
- `meeting_create_minute` — Genera minuta formal en Markdown con toda la estructura
- `meeting_dispatch_actions` — Distribuye action items: crea tareas en Trello, seguimientos en CRM, eventos en Calendar
- `meeting_list_actions` — Lista action items pendientes de reuniones anteriores
- `meeting_search` — Busca en minutas anteriores por participante, tema o fecha

## Flujo Recomendado

1. Usuario envía notas (texto) o audio (transcrito automáticamente por Whisper)
2. `meeting_process_notes` extrae toda la estructura
3. `meeting_dispatch_actions` distribuye:
   - Action items → Trello (tarjetas con fecha límite)
   - Contactos nuevos → CRM (agregar/actualizar)
   - Montos acordados → Financial Tracker (registrar)
   - Próxima reunión → Google Calendar (agendar)
4. `meeting_create_minute` genera minuta formal
5. Enviar resumen al usuario por Telegram

## Integración con Otras Skills

- **trello**: Crear tarjetas con action items automáticamente
- **crm-lite**: Registrar interacción con el contacto/cliente
- **financial-tracker**: Registrar montos acordados (cotizaciones, pagos)
- **google-calendar**: Agendar próxima reunión si se menciona fecha
- **report-generator**: Exportar minuta a PDF
- **slack**: Enviar resumen a canal de equipo

## Formato de Respuesta

**Usar plantilla `TPL-MEETING`** de `_templates/RESPONSE_FORMATS.md`. Ejemplo:

```
MINUTA — Reunión con Juan (Acme) | 20/Mar/2026

DATOS
  Asistentes:   Juan Pérez (Acme), Gabriel
  Duración:     ~30 min

TEMAS
  1. Revisión de propuesta de hosting
  2. Timeline de migración

ACUERDOS
  - Precio cerrado: $5,000.00/mes
  - Inicio de migración: 01/Abr/2026
  - Juan envía accesos el miércoles

ACTION ITEMS
  [ ] Enviar contrato final — Gabriel (25/Mar/2026)
  [ ] Enviar accesos SSH — Juan (26/Mar/2026)
  [ ] Preparar ambiente staging — Gabriel (28/Mar/2026)

PRÓXIMA REUNIÓN: 28/Mar/2026 10:00 AM (Google Meet)

DISPATCH
  [x] 2 tareas creadas en Trello
  [x] Interacción registrada en CRM (Acme)
  [x] Próxima reunión agendada en Calendar
  [x] $5,000.00/mes registrado en Finance

---
Procesado por: SOMER Meeting Notes
```
