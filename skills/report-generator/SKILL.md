---
name: report-generator
description: "Genera reportes profesionales en Markdown, Excel y PDF con entrega automática por canal."
version: "1.1.0"
triggers:
  - genera reporte
  - generar reporte
  - crear reporte
  - exportar reporte
  - reporte pdf
  - reporte excel
  - descargar reporte
  - enviar reporte
  - generate report
  - export report
  - mándame el archivo
  - link de descarga
tags:
  - report
  - reporte
  - excel
  - pdf
  - markdown
  - export
  - download
  - documento
category: productivity
enabled: true
---

# Skill: Generador de Reportes

## Cuándo usar

Activa este skill cuando el usuario solicite:
- Generar, crear o exportar un reporte
- Enviar un documento o archivo
- Exportar datos a Excel, PDF o Markdown
- Obtener un link de descarga de información discutida

## Flujo de trabajo (1 solo paso)

Usa la tool `generate_report` para crear el archivo. **El orquestador envía el archivo automáticamente al usuario por el canal actual** — NO necesitas usar otra tool para entregar el archivo.

### Elegir formato
- **Excel (`xlsx`)**: Ideal para datos tabulares, listas, métricas numéricas
- **PDF (`pdf`)**: Ideal para reportes formales, documentos para presentar
- **Markdown (`md`)**: Ideal para contenido rápido, texto con formato ligero

### Estructurar secciones
Usa la información de la conversación para crear secciones:
- Cada sección tiene un `heading` (título), `content` (texto) y opcionalmente `table` (datos tabulares con `headers` y `rows`)
- Si el usuario provee texto en formato markdown, úsalo en el campo `markdown`

## Link de descarga

Solo si el usuario pide explícitamente un **link de descarga** (no archivo directo), usa `get_download_link` con el `file_path` retornado por `generate_report`.

## Ejemplo

```
Usuario: "Genera un reporte en PDF con el resumen de ventas del mes"

→ generate_report:
    title: "Resumen de Ventas - Marzo 2025"
    format: "pdf"
    sections:
      - heading: "Resumen General"
        content: "Las ventas del mes totalizaron..."
      - heading: "Detalle por Producto"
        table:
          headers: ["Producto", "Unidades", "Total"]
          rows: [["Widget A", 150, "$4,500"], ...]

→ Responder: "Listo, te envío el reporte de ventas en PDF."
   (El archivo se envía automáticamente por el canal)
```

## Formato de Respuesta

**Usar plantilla `TPL-REPORT`** de `_templates/RESPONSE_FORMATS.md`. Al confirmar generación:

```
REPORTE GENERADO — Resumen de Ventas Marzo 2026 | 26/Mar/2026

  Formato:    PDF
  Secciones:  3
  Tamaño:     45 KB

El archivo se envía automáticamente por este canal.

---
Generado por: SOMER Reports | Ruta: ~/.somer/reports/report_20260326_091500.pdf
```

El contenido interno del PDF/Excel DEBE seguir la plantilla correspondiente al tipo de datos (TPL-FINANCIAL para finanzas, TPL-SECURITY-AUDIT para seguridad, etc.).

## Importante

- **NO uses deliver_file ni get_download_link** a menos que el usuario pida explícitamente un link
- Solo llama `generate_report` UNA vez — el archivo llega solo al usuario
- Confirma al usuario que el reporte fue generado y se le está enviando
