---
name: goplaces
description: Query Google Places API (New) via the goplaces CLI for text search, place details, resolve, and reviews. Use for human-friendly place lookup or JSON output for scripts.
homepage: https://github.com/steipete/goplaces
metadata:
  {
    "somer":
      {
        "emoji": "📍",
        "requires": { "bins": ["goplaces"], "env": ["GOOGLE_PLACES_API_KEY"] },
        "primaryEnv": "GOOGLE_PLACES_API_KEY",
        "install":
          [
            {
              "id": "brew",
              "kind": "brew",
              "formula": "steipete/tap/goplaces",
              "bins": ["goplaces"],
              "label": "Install goplaces (brew)",
            },
          ],
      },
  }
---

# goplaces

Modern Google Places API (New) CLI. Human output by default, `--json` for scripts.

Install

- Homebrew: `brew install steipete/tap/goplaces`

Config

- `GOOGLE_PLACES_API_KEY` required.
- Optional: `GOOGLE_PLACES_BASE_URL` for testing/proxying.

Common commands

- Search: `goplaces search "coffee" --open-now --min-rating 4 --limit 5`
- Bias: `goplaces search "pizza" --lat 40.8 --lng -73.9 --radius-m 3000`
- Pagination: `goplaces search "pizza" --page-token "NEXT_PAGE_TOKEN"`
- Resolve: `goplaces resolve "Soho, London" --limit 5`
- Details: `goplaces details <place_id> --reviews`
- JSON: `goplaces search "sushi" --json`

Notes

- `--no-color` or `NO_COLOR` disables ANSI color.
- Price levels: 0..4 (free → very expensive).
- Type filter sends only the first `--type` value (API accepts one).

## Formato de Respuesta

**Usar plantilla `TPL-PLACES`** de `_templates/RESPONSE_FORMATS.md`. Ejemplo:

```
LUGARES — "café especialidad bogotá" | 26/Mar/2026

RESULTADOS (3)
  1. Azahar Coffee — 4.7/5 (234 reseñas)
     Dirección:  Cra 7 #45-12, Bogotá
     Teléfono:   +57 1 234 5678
     Horario:    Abierto — 7:00-20:00
     Categoría:  Café

  2. Devotion Coffee — 4.5/5 (189 reseñas)
     Dirección:  Calle 85 #15-20, Bogotá
     Teléfono:   +57 1 987 6543
     Horario:    Abierto — 8:00-21:00
     Categoría:  Café

---
Fuente: Google Places
```
