---
name: bitbucket
description: "Bitbucket operations via REST API and git CLI: crear ramas, revisar commits, pull requests, push/pull. Use when: (1) gestionar repositorios en Bitbucket, (2) crear/listar ramas, (3) revisar commits y diffs, (4) crear/revisar/mergear pull requests, (5) hacer push/pull de código. NOT for: repos en GitHub (usar skill github), operaciones locales de git sin relación a Bitbucket, ni gestión de pipelines complejas."
metadata:
  {
    "somer":
      {
        "emoji": "🪣",
        "requires": { "bins": ["git", "curl"], "env": ["BITBUCKET_USERNAME", "BITBUCKET_APP_PASSWORD"] },
        "install": [],
        "secrets":
          [
            {
              "key": "BITBUCKET_USERNAME",
              "description": "Bitbucket username or email",
              "required": true,
            },
            {
              "key": "BITBUCKET_APP_PASSWORD",
              "description": "Bitbucket App Password (Settings → App passwords → Create)",
              "required": true,
            },
            {
              "key": "BITBUCKET_WORKSPACE",
              "description": "Default Bitbucket workspace slug",
              "required": false,
            },
          ],
      },
  }
---

# Bitbucket Skill

Interactúa con repositorios Bitbucket usando la API REST 2.0 y `git` para operaciones locales (push, pull, ramas).

## Cuándo Usar

✅ **USA esta skill cuando:**

- Crear, listar o eliminar ramas en Bitbucket
- Revisar commits, historial y diffs
- Crear, listar, revisar o mergear Pull Requests
- Hacer push o pull de código desde/hacia Bitbucket
- Consultar información de repositorios en Bitbucket
- Agregar comentarios a Pull Requests
- Aprobar o rechazar Pull Requests

## Cuándo NO Usar

❌ **NO uses esta skill cuando:**

- El repositorio está en GitHub → usar skill `github`
- Operaciones de git puramente locales sin relación a Bitbucket
- Gestión de Bitbucket Pipelines complejas → usar la UI web
- Administración de workspace/usuarios → usar la UI web

## Setup

### 1. Crear App Password en Bitbucket

1. Ir a **Bitbucket → Settings → App passwords**
2. Click en **Create app password**
3. Permisos recomendados:
   - `Repositories: Read, Write, Admin`
   - `Pull requests: Read, Write`
   - `Account: Read`
4. Copiar el password generado

### 2. Configurar credenciales

```bash
export BITBUCKET_USERNAME="tu-usuario"
export BITBUCKET_APP_PASSWORD="tu-app-password"
export BITBUCKET_WORKSPACE="tu-workspace"  # opcional, slug del workspace
```

### 3. Verificar conexión

```bash
curl -s -u "$BITBUCKET_USERNAME:$BITBUCKET_APP_PASSWORD" \
  "https://api.bitbucket.org/2.0/user" | python3 -m json.tool
```

## Variables

A lo largo de los comandos se usan estas variables:

```bash
BB_USER="$BITBUCKET_USERNAME"
BB_PASS="$BITBUCKET_APP_PASSWORD"
BB_WS="${BITBUCKET_WORKSPACE:-mi-workspace}"   # workspace slug
BB_REPO="mi-repo"                               # repo slug
BB_API="https://api.bitbucket.org/2.0"
```

## Ramas

### Listar ramas

```bash
curl -s -u "$BB_USER:$BB_PASS" \
  "$BB_API/repositories/$BB_WS/$BB_REPO/refs/branches" \
  | python3 -c "import sys,json; [print(b['name']) for b in json.load(sys.stdin)['values']]"
```

### Crear rama

```bash
# Crear rama desde main
curl -s -u "$BB_USER:$BB_PASS" \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{
    "name": "feature/nueva-funcionalidad",
    "target": {"hash": "main"}
  }' \
  "$BB_API/repositories/$BB_WS/$BB_REPO/refs/branches"
```

### Crear rama local y push

```bash
# Crear rama local y pushear a Bitbucket
git checkout -b feature/nueva-funcionalidad
git push -u origin feature/nueva-funcionalidad
```

### Eliminar rama remota

```bash
curl -s -u "$BB_USER:$BB_PASS" \
  -X DELETE \
  "$BB_API/repositories/$BB_WS/$BB_REPO/refs/branches/feature/rama-vieja"
```

## Commits

### Listar commits recientes

```bash
curl -s -u "$BB_USER:$BB_PASS" \
  "$BB_API/repositories/$BB_WS/$BB_REPO/commits" \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)
for c in data['values']:
    print(f\"{c['hash'][:7]} {c['date'][:10]} {c['author']['raw']} — {c['message'].splitlines()[0]}\")
"
```

### Commits de una rama específica

```bash
curl -s -u "$BB_USER:$BB_PASS" \
  "$BB_API/repositories/$BB_WS/$BB_REPO/commits/feature/mi-rama" \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)
for c in data['values']:
    print(f\"{c['hash'][:7]} {c['message'].splitlines()[0]}\")
"
```

### Ver diff de un commit

```bash
curl -s -u "$BB_USER:$BB_PASS" \
  "$BB_API/repositories/$BB_WS/$BB_REPO/diff/<commit-hash>"
```

### Ver detalle de un commit

```bash
curl -s -u "$BB_USER:$BB_PASS" \
  "$BB_API/repositories/$BB_WS/$BB_REPO/commit/<commit-hash>" \
  | python3 -m json.tool
```

## Pull Requests

### Listar PRs abiertos

```bash
curl -s -u "$BB_USER:$BB_PASS" \
  "$BB_API/repositories/$BB_WS/$BB_REPO/pullrequests?state=OPEN" \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)
for pr in data['values']:
    print(f\"#{pr['id']} [{pr['state']}] {pr['title']} — {pr['source']['branch']['name']} → {pr['destination']['branch']['name']}\")
"
```

### Crear Pull Request

```bash
curl -s -u "$BB_USER:$BB_PASS" \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{
    "title": "feat: nueva funcionalidad",
    "description": "Descripción detallada del cambio",
    "source": {
      "branch": {"name": "feature/nueva-funcionalidad"}
    },
    "destination": {
      "branch": {"name": "main"}
    },
    "close_source_branch": true,
    "reviewers": [
      {"username": "reviewer-user"}
    ]
  }' \
  "$BB_API/repositories/$BB_WS/$BB_REPO/pullrequests"
```

### Ver detalle de un PR

```bash
curl -s -u "$BB_USER:$BB_PASS" \
  "$BB_API/repositories/$BB_WS/$BB_REPO/pullrequests/<pr-id>" \
  | python3 -m json.tool
```

### Ver diff de un PR

```bash
curl -s -u "$BB_USER:$BB_PASS" \
  "$BB_API/repositories/$BB_WS/$BB_REPO/pullrequests/<pr-id>/diff"
```

### Aprobar un PR

```bash
curl -s -u "$BB_USER:$BB_PASS" \
  -X POST \
  "$BB_API/repositories/$BB_WS/$BB_REPO/pullrequests/<pr-id>/approve"
```

### Rechazar (Decline) un PR

```bash
curl -s -u "$BB_USER:$BB_PASS" \
  -X POST \
  "$BB_API/repositories/$BB_WS/$BB_REPO/pullrequests/<pr-id>/decline"
```

### Mergear un PR

```bash
curl -s -u "$BB_USER:$BB_PASS" \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{
    "merge_strategy": "squash",
    "close_source_branch": true,
    "message": "Merged: feat nueva funcionalidad"
  }' \
  "$BB_API/repositories/$BB_WS/$BB_REPO/pullrequests/<pr-id>/merge"
```

### Comentar en un PR

```bash
curl -s -u "$BB_USER:$BB_PASS" \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{
    "content": {"raw": "LGTM! Aprobado."}
  }' \
  "$BB_API/repositories/$BB_WS/$BB_REPO/pullrequests/<pr-id>/comments"
```

### Listar comentarios de un PR

```bash
curl -s -u "$BB_USER:$BB_PASS" \
  "$BB_API/repositories/$BB_WS/$BB_REPO/pullrequests/<pr-id>/comments" \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)
for c in data['values']:
    print(f\"@{c['user']['display_name']}: {c['content']['raw']}\")
"
```

## Push y Pull

### Pull (traer cambios)

```bash
# Pull de la rama actual
git pull origin

# Pull de una rama específica
git pull origin feature/mi-rama

# Pull con rebase
git pull --rebase origin main
```

### Push (subir cambios)

```bash
# Push de la rama actual
git push origin

# Push de una rama nueva (con tracking)
git push -u origin feature/nueva-funcionalidad

# Push forzado (usar con precaución)
git push --force-with-lease origin feature/mi-rama
```

### Clonar repositorio

```bash
# HTTPS (usa App Password automáticamente si git credential está configurado)
git clone https://bitbucket.org/$BB_WS/$BB_REPO.git

# Con credenciales explícitas
git clone https://$BB_USER:$BB_PASS@bitbucket.org/$BB_WS/$BB_REPO.git

# SSH
git clone git@bitbucket.org:$BB_WS/$BB_REPO.git
```

## Repositorios

### Listar repositorios del workspace

```bash
curl -s -u "$BB_USER:$BB_PASS" \
  "$BB_API/repositories/$BB_WS?pagelen=50" \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)
for r in data['values']:
    print(f\"{r['slug']} — {r.get('description', 'sin descripción')[:60]}\")
"
```

### Info de un repositorio

```bash
curl -s -u "$BB_USER:$BB_PASS" \
  "$BB_API/repositories/$BB_WS/$BB_REPO" \
  | python3 -c "
import sys, json
r = json.load(sys.stdin)
print(f\"Repo: {r['full_name']}\")
print(f\"Descripción: {r.get('description', 'N/A')}\")
print(f\"Lenguaje: {r.get('language', 'N/A')}\")
print(f\"Rama principal: {r['mainbranch']['name']}\")
print(f\"Privado: {r['is_private']}\")
"
```

## Templates

### Resumen de PR para revisión

```bash
PR_ID=42
echo "## PR #$PR_ID Review"
curl -s -u "$BB_USER:$BB_PASS" \
  "$BB_API/repositories/$BB_WS/$BB_REPO/pullrequests/$PR_ID" \
  | python3 -c "
import sys, json
pr = json.load(sys.stdin)
print(f\"**{pr['title']}** por @{pr['author']['display_name']}\")
print(f\"\n{pr.get('description', 'Sin descripción')}\")
print(f\"\n📌 {pr['source']['branch']['name']} → {pr['destination']['branch']['name']}\")
print(f\"Estado: {pr['state']} | Comentarios: {pr['comment_count']}\")
"
```

### Estado rápido del repo

```bash
echo "=== Ramas ==="
curl -s -u "$BB_USER:$BB_PASS" \
  "$BB_API/repositories/$BB_WS/$BB_REPO/refs/branches?pagelen=10" \
  | python3 -c "import sys,json; [print(f\"  {b['name']}\") for b in json.load(sys.stdin)['values']]"

echo "=== PRs Abiertos ==="
curl -s -u "$BB_USER:$BB_PASS" \
  "$BB_API/repositories/$BB_WS/$BB_REPO/pullrequests?state=OPEN" \
  | python3 -c "
import sys, json
prs = json.load(sys.stdin)['values']
print(f\"  Total: {len(prs)}\")
for pr in prs:
    print(f\"  #{pr['id']} {pr['title']}\")
"

echo "=== Últimos Commits ==="
curl -s -u "$BB_USER:$BB_PASS" \
  "$BB_API/repositories/$BB_WS/$BB_REPO/commits?pagelen=5" \
  | python3 -c "
import sys, json
for c in json.load(sys.stdin)['values']:
    print(f\"  {c['hash'][:7]} {c['message'].splitlines()[0]}\")
"
```

## Notas

- La API de Bitbucket usa paginación: el campo `next` en la respuesta contiene la URL de la siguiente página
- Las respuestas paginadas tienen por defecto `pagelen=10`, máximo `pagelen=100`
- App Passwords no soportan 2FA interactivo — son el método recomendado para automatización
- Para operaciones de git (push/pull), configura las credenciales en git credential store o usa SSH keys
- `merge_strategy` puede ser: `merge_commit`, `squash`, o `fast_forward`
- Los slugs de workspace y repo están en minúsculas y usan guiones

## Formato de Respuesta

**Usar plantilla `TPL-DEVOPS`** de `_templates/RESPONSE_FORMATS.md`. Ejemplo:

```
DEVOPS — PR creado | team/repo | 26/Mar/2026

RESULTADO
  Pull Request creado exitosamente

DETALLES
  Tipo:       PR
  Título:     Feature: Add webhook notifications
  Estado:     Abierto
  URL:        bitbucket.org/team/repo/pull-requests/15
  Autor:      gabriel
  Reviewers:  carlos, maria

---
Fuente: Bitbucket | Repo: team/repo
```
