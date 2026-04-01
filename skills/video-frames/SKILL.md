---
name: video-frames
description: Extract frames or short clips from videos using ffmpeg.
homepage: https://ffmpeg.org
metadata:
  {
    "somer":
      {
        "emoji": "🎬",
        "requires": { "bins": ["ffmpeg"] },
        "install":
          [
            {
              "id": "brew",
              "kind": "brew",
              "formula": "ffmpeg",
              "bins": ["ffmpeg"],
              "label": "Install ffmpeg (brew)",
            },
          ],
      },
  }
---

# Video Frames (ffmpeg)

Extract a single frame from a video, or create quick thumbnails for inspection.

## Quick start

First frame:

```bash
{baseDir}/scripts/frame.sh /path/to/video.mp4 --out /tmp/frame.jpg
```

At a timestamp:

```bash
{baseDir}/scripts/frame.sh /path/to/video.mp4 --time 00:00:10 --out /tmp/frame-10s.jpg
```

## Notes

- Prefer `--time` for “what is happening around here?”.
- Use a `.jpg` for quick share; use `.png` for crisp UI frames.

## Formato de Respuesta

**Usar plantilla `TPL-MEDIA`** de `_templates/RESPONSE_FORMATS.md`. Ejemplo:

```
MEDIA — Frames extraídos | 26/Mar/2026

RESULTADO
  Tipo:       Video frames
  Archivo:    demo_producto.mp4
  Formato:    MP4
  Duración:   05:30

DETALLES
  Frames extraídos: 12
  Intervalo:        cada 30 segundos
  Resolución:       1920x1080
  Salida:           ~/frames/demo_producto/

---
Procesado por: SOMER Media | Herramienta: ffmpeg
```
