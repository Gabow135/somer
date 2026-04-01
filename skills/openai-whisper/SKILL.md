---
name: openai-whisper
description: Local speech-to-text with the Whisper CLI (no API key).
homepage: https://openai.com/research/whisper
metadata:
  {
    "somer":
      {
        "emoji": "🎤",
        "requires": { "bins": ["whisper"] },
        "install":
          [
            {
              "id": "brew",
              "kind": "brew",
              "formula": "openai-whisper",
              "bins": ["whisper"],
              "label": "Install OpenAI Whisper (brew)",
            },
          ],
      },
  }
---

# Whisper (CLI)

Use `whisper` to transcribe audio locally.

Quick start

- `whisper /path/audio.mp3 --model medium --output_format txt --output_dir .`
- `whisper /path/audio.m4a --task translate --output_format srt`

Notes

- Models download to `~/.cache/whisper` on first run.
- `--model` defaults to `turbo` on this install.
- Use smaller models for speed, larger for accuracy.

## Formato de Respuesta

**Usar plantilla `TPL-MEDIA`** de `_templates/RESPONSE_FORMATS.md`. Ejemplo:

```
MEDIA — Transcripción | 26/Mar/2026

RESULTADO
  Tipo:       Transcripción
  Archivo:    audio_reunion.m4a
  Formato:    M4A
  Duración:   12:45

TRANSCRIPCIÓN
  Idioma:     Español (detectado)
  Duración:   12:45
  ---
  [texto transcrito del audio]

---
Procesado por: SOMER Media | Herramienta: Whisper (local)
```
