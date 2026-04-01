---
name: blogwatcher
description: Monitor blogs and RSS/Atom feeds for updates using the blogwatcher CLI.
homepage: https://github.com/Hyaxia/blogwatcher
metadata:
  {
    "somer":
      {
        "emoji": "📰",
        "requires": { "bins": ["blogwatcher"] },
        "install":
          [
            {
              "id": "go",
              "kind": "go",
              "module": "github.com/Hyaxia/blogwatcher/cmd/blogwatcher@latest",
              "bins": ["blogwatcher"],
              "label": "Install blogwatcher (go)",
            },
          ],
      },
  }
---

# blogwatcher

Track blog and RSS/Atom feed updates with the `blogwatcher` CLI.

Install

- Go: `go install github.com/Hyaxia/blogwatcher/cmd/blogwatcher@latest`

Quick start

- `blogwatcher --help`

Common commands

- Add a blog: `blogwatcher add "My Blog" https://example.com`
- List blogs: `blogwatcher blogs`
- Scan for updates: `blogwatcher scan`
- List articles: `blogwatcher articles`
- Mark an article read: `blogwatcher read 1`
- Mark all articles read: `blogwatcher read-all`
- Remove a blog: `blogwatcher remove "My Blog"`

Example output

```
$ blogwatcher blogs
Tracked blogs (1):

  xkcd
    URL: https://xkcd.com
```

```
$ blogwatcher scan
Scanning 1 blog(s)...

  xkcd
    Source: RSS | Found: 4 | New: 4

Found 4 new article(s) total!
```

Notes

- Use `blogwatcher <command> --help` to discover flags and options.

## Formato de Respuesta

**Usar plantilla `TPL-FEEDS`** de `_templates/RESPONSE_FORMATS.md`. Ejemplo:

```
FEEDS — Actualizaciones | 26/Mar/2026

ACTUALIZACIONES (3 nuevas)
  1. [Hacker News] Show HN: A new approach to WebSocket scaling
     https://news.ycombinator.com/item?id=123 — 26/Mar/2026
     Nuevo enfoque para escalar WebSocket con Redis Streams

  2. [CSS-Tricks] Modern CSS Reset 2026
     https://css-tricks.com/modern-reset — 25/Mar/2026
     Reset CSS actualizado para navegadores modernos

  3. [Go Blog] Go 1.23 Release Notes
     https://go.dev/blog/go1.23 — 25/Mar/2026
     Nuevas features incluyendo range over integers

---
Fuente: SOMER BlogWatcher
```
