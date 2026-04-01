---
name: google-calendar
description: "Google Calendar operations via `gcalcli` CLI and Google Calendar API: list events, create/edit/delete events, check availability, manage calendars. Use when: (1) scheduling or checking events, (2) finding free time slots, (3) managing recurring events, (4) sending invitations. NOT for: non-Google calendar systems, complex scheduling AI, or bulk calendar migrations."
metadata:
  {
    "somer":
      {
        "emoji": "📅",
        "requires": { "bins": ["gcalcli"], "env": ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"] },
        "install":
          [
            {
              "id": "pip",
              "kind": "pip",
              "package": "gcalcli",
              "bins": ["gcalcli"],
              "label": "Install Google Calendar CLI (pip)",
            },
            {
              "id": "brew",
              "kind": "brew",
              "formula": "gcalcli",
              "bins": ["gcalcli"],
              "label": "Install Google Calendar CLI (brew)",
            },
          ],
        "secrets":
          [
            {
              "key": "GOOGLE_CLIENT_ID",
              "description": "Google OAuth2 client ID para Calendar API",
              "required": true,
            },
            {
              "key": "GOOGLE_CLIENT_SECRET",
              "description": "Google OAuth2 client secret para Calendar API",
              "required": true,
            },
          ],
      },
  }
---

# Google Calendar Skill

Gestiona calendarios de Google Calendar usando `gcalcli` CLI y la API REST directamente.

## When to Use

✅ **USA este skill cuando:**

- Listar eventos del día, semana o rango de fechas
- Crear nuevos eventos con título, hora, ubicación, invitados
- Editar o eliminar eventos existentes
- Buscar disponibilidad y huecos libres
- Gestionar calendarios recurrentes
- Enviar invitaciones a otros usuarios
- Consultar próximos eventos rápidamente

## When NOT to Use

❌ **NO uses este skill cuando:**

- Calendarios no-Google (Outlook, Apple Calendar) → usar skills específicos
- Scheduling complejo con múltiples participantes → usar herramientas dedicadas
- Migraciones masivas de calendario → script dedicado
- Solo necesitas la fecha/hora actual → usar datetime directamente

## Setup

```bash
# Instalar gcalcli
pip install gcalcli

# Autenticar (primera vez — abre navegador)
gcalcli init

# Verificar autenticación
gcalcli list
```

### Autenticación con OAuth2

1. Crear proyecto en Google Cloud Console
2. Habilitar Google Calendar API
3. Crear credenciales OAuth2 (Desktop App)
4. Exportar variables:
```bash
export GOOGLE_CLIENT_ID="tu-client-id.apps.googleusercontent.com"
export GOOGLE_CLIENT_SECRET="tu-client-secret"
```

## Common Commands

### Listar Eventos

```bash
# Eventos de hoy
gcalcli agenda

# Eventos de la semana
gcalcli agenda "today" "next week"

# Eventos en rango específico
gcalcli agenda "2026-03-25" "2026-03-31"

# Formato detallado con IDs
gcalcli agenda --details all --tsv
```

### Crear Eventos

```bash
# Evento simple
gcalcli add --title "Reunión de equipo" \
  --when "2026-03-25 10:00" \
  --duration 60 \
  --where "Sala A"

# Evento con invitados
gcalcli add --title "Sync semanal" \
  --when "2026-03-26 14:00" \
  --duration 30 \
  --attendees "juan@example.com,maria@example.com"

# Evento recurrente (semanal)
gcalcli add --title "Daily standup" \
  --when "2026-03-25 09:00" \
  --duration 15 \
  --reminder 5

# Evento de todo el día
gcalcli add --title "Vacaciones" \
  --allday "2026-04-01" "2026-04-05"
```

### Buscar Disponibilidad

```bash
# Huecos libres de 1 hora en los próximos 3 días
gcalcli calm "today" "3 days from now" --duration 60

# Buscar en calendario específico
gcalcli calm --calendar "Work" "today" "next friday" --duration 30
```

### Editar y Eliminar

```bash
# Buscar evento por texto
gcalcli search "Reunión" "2026-03-25" "2026-03-31"

# Editar (interactivo — mejor usar API directa)
gcalcli edit --title "Reunión de equipo"

# Eliminar evento
gcalcli delete --title "Reunión cancelada"
```

### Listar Calendarios

```bash
# Listar todos los calendarios
gcalcli list

# Mostrar calendarios con detalles
gcalcli list --nocolor
```

## API REST Directa

Para operaciones avanzadas, usar la API REST de Google Calendar con `curl`:

```bash
# Listar eventos (requiere access token)
curl -s -H "Authorization: Bearer $GOOGLE_ACCESS_TOKEN" \
  "https://www.googleapis.com/calendar/v3/calendars/primary/events?timeMin=$(date -u +%Y-%m-%dT%H:%M:%SZ)&maxResults=10&singleEvents=true&orderBy=startTime" \
  | python3 -c "import sys,json; [print(f'{e[\"start\"].get(\"dateTime\",e[\"start\"].get(\"date\"))} - {e[\"summary\"]}') for e in json.load(sys.stdin).get('items',[])]"

# Crear evento via API
curl -s -X POST \
  -H "Authorization: Bearer $GOOGLE_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  "https://www.googleapis.com/calendar/v3/calendars/primary/events" \
  -d '{
    "summary": "Reunión importante",
    "start": {"dateTime": "2026-03-25T10:00:00-05:00"},
    "end": {"dateTime": "2026-03-25T11:00:00-05:00"},
    "attendees": [{"email": "invitado@example.com"}]
  }'

# Quick add (lenguaje natural)
curl -s -X POST \
  -H "Authorization: Bearer $GOOGLE_ACCESS_TOKEN" \
  "https://www.googleapis.com/calendar/v3/calendars/primary/events/quickAdd?text=Almuerzo+mañana+a+las+12pm"
```

## Templates

### Vista del Día

```bash
echo "## Agenda de Hoy"
gcalcli agenda "today" "tomorrow" --nocolor --military
```

### Resumen Semanal

```bash
echo "## Semana $(date +%V)"
gcalcli agenda "monday" "next monday" --nocolor --details location
```

## Notes

- `gcalcli init` solo necesita ejecutarse una vez (guarda tokens en ~/.gcalcli_oauth)
- Los tiempos se interpretan en la zona horaria local del sistema
- Para múltiples cuentas, usar `--config-folder` con directorios separados
- La API REST requiere un access token OAuth2 válido (expira cada hora)
- Usar `--calendar "nombre"` para operar en calendarios específicos

## Formato de Respuesta

**Usar plantilla `TPL-CALENDAR`** de `_templates/RESPONSE_FORMATS.md`. Ejemplo:

```
CALENDARIO — Agenda del día | 26/Mar/2026

AGENDA: 26/Mar/2026
  09:00 — Standup equipo (30 min) | Google Meet
  11:00 — Reunión con Acme (60 min) | Oficina cliente
  14:00 — Code review (30 min) | Zoom
  16:00 — Demo producto (45 min) | Google Meet

---
Fuente: Google Calendar
```

Ejemplo evento creado:
```
CALENDARIO — Evento creado | 26/Mar/2026

EVENTO
  Título:     Reunión con Acme
  Fecha:      28/Mar/2026 11:00 - 12:00
  Ubicación:  Oficina cliente
  Asistentes: Juan Pérez, María García
  Estado:     Confirmado

---
Fuente: Google Calendar
```
