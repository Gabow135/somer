---
name: crm-lite
description: "CRM minimalista — registrar contactos, notas de reuniones, seguimientos pendientes, historial de interacciones. Almacenado en SQLite."
version: "1.0.0"
triggers:
  - contacto
  - cliente
  - crm
  - agregar contacto
  - nuevo contacto
  - notas de reunión con
  - seguimiento con
  - pendientes con
  - registrar cliente
  - historial del cliente
  - recordar llamar a
  - qué pendientes tengo
  - cuándo fue mi última reunión con
  - nuevo lead
  - pipeline de ventas
  - seguimiento pendiente
  - agenda de contactos
  - client management
  - customer
tags:
  - crm
  - contacts
  - clients
  - follow-up
  - meetings
  - sales
  - pipeline
  - business
category: business
enabled: true
---

# Skill: CRM Lite

CRM minimalista integrado — gestiona contactos, reuniones, seguimientos y pipeline de ventas desde Telegram.

## Reglas

1. **Persistencia en SQLite** — datos en `~/.somer/crm.db`.
2. **Búsqueda flexible** — por nombre, empresa, tag o fecha.
3. **Recordatorios** — conecta con cron para follow-ups automáticos.
4. **Privacidad** — datos nunca salen del dispositivo local.

## Cuándo Usar

- "Agrega a Juan Pérez de Empresa X como contacto"
- "Notas de mi reunión con María: acordamos precio de $5000"
- "¿Qué pendientes tengo con el cliente Acme?"
- "Recuérdame llamar a Pedro el viernes"
- "Historial de interacciones con Empresa Y"
- "¿Cuántos leads tengo este mes?"
- "Mover a Juan a etapa de negociación"

## Tools Disponibles

- `crm_add_contact` — Crear/actualizar contacto (nombre, email, empresa, teléfono, tags, notas)
- `crm_search_contacts` — Buscar contactos por nombre, empresa, tag o texto libre
- `crm_add_interaction` — Registrar interacción (reunión, llamada, email, nota) con un contacto
- `crm_get_history` — Ver historial de interacciones con un contacto
- `crm_add_followup` — Programar seguimiento futuro (qué, cuándo, prioridad)
- `crm_list_followups` — Listar seguimientos pendientes (hoy, esta semana, vencidos)
- `crm_update_pipeline` — Mover contacto en pipeline (lead → contactado → negociación → cerrado → perdido)
- `crm_dashboard` — Resumen: contactos totales, seguimientos pendientes, pipeline por etapa

## Pipeline de Ventas

```
Lead → Contactado → Propuesta → Negociación → Cerrado Ganado
                                                    ↘ Cerrado Perdido
```

## Integración con Otras Skills

- **daily-briefing**: Seguimientos del día en el briefing matutino
- **financial-tracker**: Vincular ingresos a clientes del CRM
- **meeting-notes**: Auto-registrar interacciones desde notas de reunión
- **google-calendar**: Sincronizar seguimientos con calendario
- **report-generator**: Exportar pipeline y contactos a Excel/PDF

## Formato de Respuesta

**Usar plantilla `TPL-CRM`** de `_templates/RESPONSE_FORMATS.md`. Ejemplo:

```
CRM — Contacto registrado | 26/Mar/2026

CONTACTO
  Nombre:       Juan Pérez
  Empresa:      Acme
  Email:        juan@acme.com
  Teléfono:     +52 555 1234
  Tags:         #cliente #premium
  Pipeline:     Negociación

SEGUIMIENTO
  Próximo:      28/Mar/2026 — Enviar cotización revisada
  Prioridad:    Alta

HISTORIAL (4 interacciones)
  20/Mar/2026 — Reunión: Revisión de propuesta
  15/Mar/2026 — Email: Envío de cotización inicial
  10/Mar/2026 — Llamada: Primer contacto
  05/Mar/2026 — Lead: Ingresó por formulario web

---
Fuente: SOMER CRM | DB: ~/.somer/crm.db
```

Para listar seguimientos pendientes:
```
CRM — Seguimientos pendientes | 26/Mar/2026

RESUMEN: 5 pendientes | 1 vencido

VENCIDOS
  [!!] Juan Pérez (Acme) — Enviar contrato (vencido 24/Mar/2026)

HOY
  [ ] Pedro López (StartupX) — Llamar para cotización
  [ ] María García (TechCo) — Enviar demo

ESTA SEMANA
  [ ] Carlos Ruiz (BigCorp) — Seguimiento propuesta (28/Mar/2026)
  [ ] Ana Torres (MiniApp) — Revisar contrato (29/Mar/2026)

---
Fuente: SOMER CRM | DB: ~/.somer/crm.db
```
