---
name: nano-pdf
description: Edit PDFs with natural-language instructions using the nano-pdf CLI.
homepage: https://pypi.org/project/nano-pdf/
metadata:
  {
    "somer":
      {
        "emoji": "📄",
        "requires": { "bins": ["nano-pdf"] },
        "install":
          [
            {
              "id": "uv",
              "kind": "uv",
              "package": "nano-pdf",
              "bins": ["nano-pdf"],
              "label": "Install nano-pdf (uv)",
            },
          ],
      },
  }
---

# nano-pdf

Use `nano-pdf` to apply edits to a specific page in a PDF using a natural-language instruction.

## Quick start

```bash
nano-pdf edit deck.pdf 1 "Change the title to 'Q3 Results' and fix the typo in the subtitle"
```

Notes:

- Page numbers are 0-based or 1-based depending on the tool’s version/config; if the result looks off by one, retry with the other.
- Always sanity-check the output PDF before sending it out.

## Formato de Respuesta

**Usar plantilla `TPL-ACTION`** de `_templates/RESPONSE_FORMATS.md`. Ejemplo:

```
ACCIÓN — Nano PDF | PDF editado | 26/Mar/2026

RESULTADO
  Estado:     Completado
  Detalle:    Página 1 de propuesta.pdf editada — logo actualizado

SALIDA
  Archivo:    propuesta.pdf
  Página:     1
  Instrucción: "Reemplazar logo viejo con nuevo logo"

---
Ejecutado por: SOMER Nano PDF
```
