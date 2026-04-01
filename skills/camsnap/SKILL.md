---
name: camsnap
description: Capture frames or clips from RTSP/ONVIF cameras.
homepage: https://camsnap.ai
metadata:
  {
    "somer":
      {
        "emoji": "📸",
        "requires": { "bins": ["camsnap"] },
        "install":
          [
            {
              "id": "brew",
              "kind": "brew",
              "formula": "steipete/tap/camsnap",
              "bins": ["camsnap"],
              "label": "Install camsnap (brew)",
            },
          ],
      },
  }
---

# camsnap

Use `camsnap` to grab snapshots, clips, or motion events from configured cameras.

Setup

- Config file: `~/.config/camsnap/config.yaml`
- Add camera: `camsnap add --name kitchen --host 192.168.0.10 --user user --pass pass`

Common commands

- Discover: `camsnap discover --info`
- Snapshot: `camsnap snap kitchen --out shot.jpg`
- Clip: `camsnap clip kitchen --dur 5s --out clip.mp4`
- Motion watch: `camsnap watch kitchen --threshold 0.2 --action '...'`
- Doctor: `camsnap doctor --probe`

Notes

- Requires `ffmpeg` on PATH.
- Prefer a short test capture before longer clips.

## Formato de Respuesta

**Usar plantilla `TPL-MEDIA`** de `_templates/RESPONSE_FORMATS.md`. Ejemplo:

```
MEDIA — Captura de cámara | 26/Mar/2026

RESULTADO
  Tipo:       Screenshot
  Archivo:    cam_oficina_001.jpg
  Formato:    JPEG
  Tamaño:     1920x1080

DETALLES
  Cámara:     Oficina Principal (RTSP)
  Modo:       Snapshot
  Timestamp:  26/Mar/2026 14:30:05

---
Procesado por: SOMER Media | Herramienta: camsnap
```
