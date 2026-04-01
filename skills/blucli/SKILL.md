---
name: blucli
description: BluOS CLI (blu) for discovery, playback, grouping, and volume.
homepage: https://blucli.sh
metadata:
  {
    "somer":
      {
        "emoji": "🫐",
        "requires": { "bins": ["blu"] },
        "install":
          [
            {
              "id": "go",
              "kind": "go",
              "module": "github.com/steipete/blucli/cmd/blu@latest",
              "bins": ["blu"],
              "label": "Install blucli (go)",
            },
          ],
      },
  }
---

# blucli (blu)

Use `blu` to control Bluesound/NAD players.

Quick start

- `blu devices` (pick target)
- `blu --device <id> status`
- `blu play|pause|stop`
- `blu volume set 15`

Target selection (in priority order)

- `--device <id|name|alias>`
- `BLU_DEVICE`
- config default (if set)

Common tasks

- Grouping: `blu group status|add|remove`
- TuneIn search/play: `blu tunein search "query"`, `blu tunein play "query"`

Prefer `--json` for scripts. Confirm the target device before changing playback.

## Formato de Respuesta

**Usar plantilla `TPL-MUSIC`** de `_templates/RESPONSE_FORMATS.md`. Ejemplo:

```
MÚSICA — Reproduciendo | 26/Mar/2026

REPRODUCIENDO
  Canción:    Kind of Blue
  Artista:    Miles Davis
  Álbum:      Kind of Blue
  Duración:   09:22
  Dispositivo: Bluesound Node (Sala)

---
Fuente: Bluesound
```
