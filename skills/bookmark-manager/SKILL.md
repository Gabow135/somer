---
name: bookmark-manager
description: "Guardar y categorizar links — búsqueda semántica con memoria vectorial de SOMER. Organización por tags y categorías."
version: "1.0.0"
triggers:
  - guardar link
  - guardar url
  - bookmark
  - guarda este link
  - guarda esta página
  - save link
  - save bookmark
  - mis bookmarks
  - links guardados
  - buscar en mis links
  - tenía un link sobre
  - dónde guardé
  - favoritos
  - link sobre
  - artículo sobre
  - recurso sobre
tags:
  - bookmarks
  - links
  - urls
  - save
  - organize
  - search
  - personal
category: personal
enabled: true
---

# Skill: Bookmark Manager

Guardar, categorizar y buscar links con búsqueda semántica usando la memoria vectorial de SOMER.

## Reglas

1. **Auto-categorizar** — detectar categoría del link por contenido/título.
2. **Búsqueda semántica** — usar memoria vectorial para encontrar links por concepto, no solo keywords.
3. **Persistencia en memoria** — usa el sistema de memoria de SOMER (BM25 + vector).
4. **Extraer metadata** — título, descripción, og:image del link al guardar.

## Cuándo Usar

- "Guarda este link: https://example.com/article"
- "Tenía un link sobre kubernetes networking"
- "Mis bookmarks de seguridad"
- "¿Dónde guardé el artículo sobre SSTI?"
- "Links que guardé esta semana"
- "Elimina el bookmark de X"

## Tools Disponibles

- `bookmark_save` — Guardar link con metadata (título, descripción, tags, categoría, notas)
- `bookmark_search` — Búsqueda semántica en bookmarks guardados (por concepto o keywords)
- `bookmark_list` — Listar bookmarks por categoría, tag, o rango de fechas
- `bookmark_delete` — Eliminar un bookmark
- `bookmark_export` — Exportar bookmarks a Markdown, HTML (compatible con navegador), o JSON

## Categorías Default

dev, security, devops, ai, design, business, learning, tools, news, personal, other

## Integración con Otras Skills

- **daily-briefing**: Links guardados recientemente en el briefing
- **summarize**: Auto-resumir el contenido del link al guardar
- **osint-investigator**: Guardar hallazgos OSINT como bookmarks
- **report-generator**: Incluir links relevantes en reportes

## Formato de Respuesta

**Usar plantilla `TPL-BOOKMARKS`** de `_templates/RESPONSE_FORMATS.md`. Ejemplo guardado:

```
BOOKMARKS — Guardado | 26/Mar/2026

GUARDADO
  Título:     Kubernetes Networking Guide
  URL:        https://example.com/k8s-networking
  Categoría:  devops
  Tags:       #kubernetes #networking #cni
  Resumen:    Guía completa de networking en K8s: CNI, Services, Ingress

---
Fuente: SOMER Bookmarks
```

Ejemplo búsqueda:
```
BOOKMARKS — Búsqueda | 26/Mar/2026

BÚSQUEDA: "kubernetes networking" — 3 resultados
  1. Kubernetes Networking Guide (devops)
     https://example.com/k8s-networking — 15/Mar/2026
  2. Calico vs Cilium CNI Comparison (security)
     https://example.com/cni-compare — 10/Mar/2026
  3. Service Mesh con Istio (devops)
     https://example.com/istio-mesh — 02/Mar/2026

---
Fuente: SOMER Bookmarks
```
