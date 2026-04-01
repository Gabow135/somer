---
name: google-drive
description: "Google Drive operations via `gdrive` CLI and Google Drive API: upload/download files, manage folders, search files, share/permissions, sync. Use when: (1) uploading or downloading files, (2) organizing folders, (3) searching across Drive, (4) managing file sharing permissions. NOT for: non-Google storage (S3, Dropbox), local file operations, or Google Docs editing (use Docs API)."
metadata:
  {
    "somer":
      {
        "emoji": "📁",
        "requires": { "bins": ["gdrive"], "env": ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"] },
        "install":
          [
            {
              "id": "brew",
              "kind": "brew",
              "formula": "gdrive",
              "bins": ["gdrive"],
              "label": "Install Google Drive CLI (brew)",
            },
          ],
        "secrets":
          [
            {
              "key": "GOOGLE_CLIENT_ID",
              "description": "Google OAuth2 client ID para Drive API",
              "required": true,
            },
            {
              "key": "GOOGLE_CLIENT_SECRET",
              "description": "Google OAuth2 client secret para Drive API",
              "required": true,
            },
          ],
      },
  }
---

# Google Drive Skill

Gestiona archivos y carpetas en Google Drive usando `gdrive` CLI y la API REST.

## When to Use

✅ **USA este skill cuando:**

- Subir archivos locales a Google Drive
- Descargar archivos de Drive al sistema local
- Buscar archivos por nombre, tipo o contenido
- Crear y organizar carpetas
- Compartir archivos y gestionar permisos
- Listar contenido de carpetas
- Sincronizar directorios locales con Drive
- Obtener links de descarga o compartir

## When NOT to Use

❌ **NO uses este skill cuando:**

- Almacenamiento no-Google (S3, Dropbox, OneDrive) → skills específicos
- Operaciones solo en archivos locales → usar filesystem directamente
- Edición de Google Docs/Sheets → usar API de Docs/Sheets específica
- Clonado masivo de repositorios → usar git

## Setup

```bash
# Instalar gdrive
brew install gdrive

# Autenticar (primera vez)
gdrive account add

# Verificar
gdrive account list
```

## Common Commands

### Listar Archivos

```bash
# Listar raíz de Drive
gdrive files list

# Listar con query
gdrive files list --query "name contains 'informe'"

# Listar carpeta específica
gdrive files list --parent <folder-id>

# Listar solo PDFs
gdrive files list --query "mimeType = 'application/pdf'"

# Listar archivos recientes (últimos 7 días)
gdrive files list --query "modifiedTime > '$(date -v-7d +%Y-%m-%dT%H:%M:%S)'" --order-by "modifiedTime desc"
```

### Subir Archivos

```bash
# Subir archivo
gdrive files upload ./reporte.pdf

# Subir a carpeta específica
gdrive files upload --parent <folder-id> ./datos.xlsx

# Subir directorio completo
gdrive files upload --recursive ./mi-carpeta/

# Subir y convertir a Google Docs
gdrive files upload --mime-type "application/vnd.google-apps.document" ./documento.docx
```

### Descargar Archivos

```bash
# Descargar por ID
gdrive files download <file-id>

# Descargar a directorio específico
gdrive files download <file-id> --destination ./descargas/

# Exportar Google Doc como PDF
gdrive files export <file-id> --mime-type "application/pdf"

# Descargar carpeta completa
gdrive files download <folder-id> --recursive
```

### Crear Carpetas

```bash
# Crear carpeta en raíz
gdrive files mkdir "Proyecto Alpha"

# Crear subcarpeta
gdrive files mkdir --parent <parent-folder-id> "Documentos"
```

### Buscar Archivos

```bash
# Buscar por nombre
gdrive files list --query "name = 'presupuesto.xlsx'"

# Buscar por contenido (fullText)
gdrive files list --query "fullText contains 'presupuesto Q1'"

# Buscar archivos compartidos conmigo
gdrive files list --query "sharedWithMe = true"

# Buscar archivos con estrella
gdrive files list --query "starred = true"

# Buscar por tipo MIME y fecha
gdrive files list --query "mimeType = 'application/pdf' and modifiedTime > '2026-01-01'"
```

### Compartir y Permisos

```bash
# Compartir con usuario (lectura)
gdrive permissions create <file-id> --type user --email juan@example.com --role reader

# Compartir con usuario (edición)
gdrive permissions create <file-id> --type user --email maria@example.com --role writer

# Compartir con link público (solo lectura)
gdrive permissions create <file-id> --type anyone --role reader

# Listar permisos
gdrive permissions list <file-id>

# Revocar permiso
gdrive permissions delete <file-id> <permission-id>
```

### Mover y Renombrar

```bash
# Mover archivo a otra carpeta
gdrive files update <file-id> --add-parent <new-folder-id> --remove-parent <old-folder-id>

# Renombrar archivo
gdrive files update <file-id> --name "nuevo-nombre.pdf"
```

### Info del Archivo

```bash
# Detalles de archivo
gdrive files info <file-id>

# Info con link de descarga
gdrive files info <file-id> --fields "name,size,webViewLink,webContentLink"
```

## API REST Directa

```bash
# Listar archivos via API
curl -s -H "Authorization: Bearer $GOOGLE_ACCESS_TOKEN" \
  "https://www.googleapis.com/drive/v3/files?pageSize=10&fields=files(id,name,mimeType,modifiedTime,size)" \
  | python3 -c "import sys,json; [print(f'{f[\"name\"]} ({f.get(\"size\",\"folder\")}) - {f[\"id\"]}') for f in json.load(sys.stdin).get('files',[])]"

# Subir archivo via API
curl -s -X POST \
  -H "Authorization: Bearer $GOOGLE_ACCESS_TOKEN" \
  -F "metadata={\"name\":\"mi-archivo.pdf\"};type=application/json" \
  -F "file=@./mi-archivo.pdf" \
  "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart"

# Crear carpeta via API
curl -s -X POST \
  -H "Authorization: Bearer $GOOGLE_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  "https://www.googleapis.com/drive/v3/files" \
  -d '{"name": "Nueva Carpeta", "mimeType": "application/vnd.google-apps.folder"}'
```

## Templates

### Listar Documentos del Proyecto

```bash
PROJECT_FOLDER="<folder-id>"
echo "## Archivos del Proyecto"
gdrive files list --parent "$PROJECT_FOLDER" --order-by "modifiedTime desc"
```

### Backup Local a Drive

```bash
BACKUP_FOLDER="<backup-folder-id>"
gdrive files upload --parent "$BACKUP_FOLDER" --recursive ./proyecto/
echo "Backup completado: $(date)"
```

## Notes

- `gdrive account add` solo necesita ejecutarse una vez por cuenta
- Los file IDs se obtienen con `gdrive files list` o de la URL de Drive
- Límite de subida: 5TB por archivo (cuenta de Workspace), 15GB gratis
- Las queries usan Google Drive query syntax (no SQL)
- Para Google Docs/Sheets/Slides, usar `export` en vez de `download`
- Múltiples cuentas: usar `--account <email>` en cada comando

## Formato de Respuesta

**Usar plantilla `TPL-DRIVE`** de `_templates/RESPONSE_FORMATS.md`. Ejemplo:

```
ARCHIVOS — Subido | 26/Mar/2026

RESULTADO
  Archivo:    propuesta_acme_v2.pdf
  Ruta:       Proyectos/Acme/
  Tamaño:     2.4 MB
  Tipo:       PDF
  Acción:     Subido

---
Fuente: Google Drive
```

Ejemplo búsqueda:
```
ARCHIVOS — Búsqueda | 26/Mar/2026

LISTADO: "propuesta" — 3 archivos
  propuesta_acme_v2.pdf — 2.4 MB — 25/Mar/2026 — Compartido con Juan
  propuesta_startup_x.docx — 1.1 MB — 20/Mar/2026 — Privado
  propuesta_template.gdoc — 340 KB — 15/Feb/2026 — Compartido con equipo

---
Fuente: Google Drive
```
