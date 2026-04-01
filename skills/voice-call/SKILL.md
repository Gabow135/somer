---
name: voice-call
description: Start voice calls via the SOMER voice-call plugin.
metadata:
  {
    "somer":
      {
        "emoji": "📞",
        "skillKey": "voice-call",
        "requires": { "config": ["plugins.entries.voice-call.enabled"] },
      },
  }
---

# Voice Call

Use the voice-call plugin to start or inspect calls (Twilio, Telnyx, Plivo, or mock).

## CLI

```bash
somer voicecall call --to "+15555550123" --message "Hello from SOMER"
somer voicecall status --call-id <id>
```

## Tool

Use `voice_call` for agent-initiated calls.

Actions:

- `initiate_call` (message, to?, mode?)
- `continue_call` (callId, message)
- `speak_to_user` (callId, message)
- `end_call` (callId)
- `get_status` (callId)

Notes:

- Requires the voice-call plugin to be enabled.
- Plugin config lives under `plugins.entries.voice-call.config`.
- Twilio config: `provider: "twilio"` + `twilio.accountSid/authToken` + `fromNumber`.
- Telnyx config: `provider: "telnyx"` + `telnyx.apiKey/connectionId` + `fromNumber`.
- Plivo config: `provider: "plivo"` + `plivo.authId/authToken` + `fromNumber`.
- Dev fallback: `provider: "mock"` (no network).

## Formato de Respuesta

**Usar plantilla `TPL-ACTION`** de `_templates/RESPONSE_FORMATS.md`. Ejemplo:

```
ACCIÓN — Voice Call | Llamada iniciada | 26/Mar/2026

RESULTADO
  Estado:     Completado
  Detalle:    Llamada iniciada a +52 555 1234

SALIDA
  Destino:    +52 555 1234
  Proveedor:  Twilio
  Estado:     En curso
  Duración:   --

---
Ejecutado por: SOMER Voice Call
```
