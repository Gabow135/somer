---
name: bitbucket
description: "Bitbucket operations via REST API and git CLI: crear ramas, revisar commits, pull requests, push/pull. Use when: (1) gestionar repositorios en Bitbucket, (2) crear/listar ramas, (3) revisar commits y diffs, (4) crear/revisar/mergear pull requests, (5) hacer push/pull de código. NOT for: repos en GitHub (usar skill github), operaciones locales de git sin relación a Bitbucket, ni gestión de pipelines complejas."
metadata:
  {
    "somer":
      {
        "emoji": "🪣",
        "requires": { "bins": ["git", "curl"], "env": ["BITBUCKET_USERNAME", "BITBUCKET_APP_PASSWORD"], "tools": ["bb_list_prs", "bb_review_pr", "bb_review_all_prs", "bb_get_pr_diff", "bb_set_review_rules", "bb_add_repo", "bb_list_repos"] },
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

## Configuracion Multi-Repositorio

El skill soporta multiples repositorios y credenciales. La configuracion se almacena en `skills/bitbucket/scripts/repos_config.json`.

### Estructura de repos_config.json

```json
{
  "default_workspace": "cgarcia_m",
  "default_credentials": "sukasa",
  "credentials": {
    "sukasa": {
      "username": "greyes@sukasa.com",
      "label": "Sukasa"
    }
  },
  "repositories": [
    {
      "workspace": "cgarcia_m",
      "repo_slug": "web-front-sukasa",
      "label": "Web Front Sukasa",
      "credentials_key": "sukasa",
      "rules_override": {},
      "notify_phones": ["593995466833"],
      "active": true
    }
  ]
}
```

### Credenciales

- Los passwords/tokens NUNCA se almacenan en repos_config.json
- Se almacenan en `~/.somer/.env` con la convención: `BITBUCKET_APP_PASSWORD_{KEY}=xxx`
- Ejemplo: para credentials_key "sukasa" → busca `BITBUCKET_APP_PASSWORD_SUKASA`
- Fallback: si no existe la variable con sufijo, usa `BITBUCKET_APP_PASSWORD`

### Agregar un nuevo repositorio

```
bb_add_repo(workspace="cgarcia_m", repo_slug="nuevo-repo", label="Nuevo Repo", credentials_key="sukasa", notify_phones=["593995466833"])
```

### Revisar todos los repos configurados

```
bb_review_all_prs(all_repos=true, auto_action=true)
```

## Revision Automatica de PRs

Sistema automatizado de revisión de Pull Requests que evalúa PRs contra reglas configurables, publica comentarios, aprueba/rechaza y notifica por WhatsApp.

### Configuración de Reglas

Las reglas se configuran en `skills/bitbucket/scripts/review_rules.json`. Cada regla tiene:

- `enabled` — Activar/desactivar la regla
- `severity` — `"critical"` (rechaza el PR), `"warning"` (solo comenta), `"info"` (informativo)
- Valores específicos de la regla (umbrales, patrones, etc.)
- `message` — Plantilla del mensaje de violación

**Reglas disponibles:**

| Regla | Severidad | Descripción | Default |
|-------|-----------|-------------|---------|
| `max_files_changed` | critical | Máximo de archivos modificados | 20 |
| `max_lines_added` | critical | Máximo de líneas agregadas | 500 |
| `forbidden_patterns` | critical | Patrones regex prohibidos en el diff | console.log, debugger, TODO, passwords |
| `required_patterns` | warning | Patrones que deben existir en el diff | (vacío) |
| `forbidden_files` | critical | Archivos que no deben modificarse | .env, .env.local, .env.production |
| `branch_naming` | warning | Convención de nombres de rama | feature/, fix/, hotfix/, etc. |
| `title_format` | warning | Formato del título del PR | feat:, fix:, chore:, etc. |
| `require_description` | warning | PR debe tener descripción | true |
| `max_commits` | warning | Máximo de commits en el PR | 10 |
| `require_reviewer` | warning | PR debe tener revisor asignado | true |

Para modificar reglas vía tool:

```
bb_set_review_rules({"rules": {"max_files_changed": {"value": 30}, "forbidden_patterns": {"patterns": ["console\\.log", "debugger"]}}})
```

### Comportamiento de Revisión

- **Todas las reglas pasan** → Aprueba el PR + comenta "LGTM"
- **Solo advertencias** → Comenta las advertencias + notifica por WhatsApp (NO rechaza)
- **Errores críticos** → Rechaza el PR + comenta los errores + notifica por WhatsApp

### Notificación WhatsApp

Cuando un PR tiene problemas, se envía notificación WhatsApp al número configurado (default: `593995466833`) con:
- Nombre del repo y número de PR
- Estado (rechazado o advertencias)
- Lista de violaciones encontradas
- Acción tomada

### Uso Manual (CLI)

```bash
# Listar PRs abiertos
python3 skills/bitbucket/scripts/pr_reviewer.py list <workspace> <repo>

# Revisar un PR específico con acción automática y notificación
python3 skills/bitbucket/scripts/pr_reviewer.py review <workspace> <repo> <pr_id> --auto --notify 593995466833

# Revisar todos los PRs abiertos
python3 skills/bitbucket/scripts/pr_reviewer.py review-all <workspace> <repo> --auto --notify 593995466833

# Usar reglas personalizadas
python3 skills/bitbucket/scripts/pr_reviewer.py review <workspace> <repo> <pr_id> --rules /path/to/rules.json --auto
```

### Uso vía Tools SOMER

```
bb_list_prs(workspace="mi-ws", repo="mi-repo", state="OPEN")
bb_review_pr(workspace="mi-ws", repo="mi-repo", pr_id=42, auto_action=true, notify_phone="593995466833")
bb_review_all_prs(workspace="mi-ws", repo="mi-repo", auto_action=true)
bb_review_all_prs(all_repos=true, auto_action=true)   # Revisa TODOS los repos configurados
bb_get_pr_diff(workspace="mi-ws", repo="mi-repo", pr_id=42)
bb_set_review_rules(rules={"max_files_changed": {"value": 30}})
bb_add_repo(workspace="cgarcia_m", repo_slug="mi-otro-repo", label="Mi Otro Repo", credentials_key="sukasa", notify_phones=["593995466833"])
bb_list_repos()
```

### Tools Registradas

| Tool | Descripcion |
|------|-------------|
| `bb_list_prs` | Lista PRs de un repositorio por estado |
| `bb_review_pr` | Revisa un PR contra reglas, aprueba/rechaza, notifica |
| `bb_review_all_prs` | Revisa todos los PRs abiertos de un repo o de todos los repos (all_repos=true) |
| `bb_get_pr_diff` | Obtiene el diff de un PR |
| `bb_set_review_rules` | Actualiza configuracion de reglas de revision |
| `bb_add_repo` | Agrega un repositorio a la configuracion multi-repo |
| `bb_list_repos` | Lista todos los repositorios configurados |

### Ejemplo de Respuesta de Revisión

```json
{
  "pr_id": 42,
  "pr_title": "feat: add user notifications",
  "repo": "mi-repo",
  "workspace": "mi-ws",
  "passed": false,
  "has_critical": true,
  "has_warnings": true,
  "action": "declined",
  "comment_posted": true,
  "notification_sent": true,
  "violations": [
    {"rule": "forbidden_patterns", "severity": "critical", "message": "Se encontró patrón prohibido 'console\\.log' en el diff (3 ocurrencias)."},
    {"rule": "branch_naming", "severity": "warning", "message": "La rama 'add-notifications' no sigue la convención de nombres."}
  ]
}
```

### Configuración de Cron para Revisión Periódica

Para ejecutar revisiones automáticas cada 30 minutos:

```bash
# Editar crontab
crontab -e

# Agregar línea (cada 30 minutos, revisa todos los PRs abiertos)
*/30 * * * * cd /var/www/somer && python3 skills/bitbucket/scripts/pr_reviewer.py review-all mi-workspace mi-repo --auto --notify 593995466833 >> /var/log/somer-pr-review.log 2>&1

# Cada hora, solo durante horario laboral (8am-6pm, lunes a viernes)
0 8-18 * * 1-5 cd /var/www/somer && python3 skills/bitbucket/scripts/pr_reviewer.py review-all mi-workspace mi-repo --auto --notify 593995466833 >> /var/log/somer-pr-review.log 2>&1
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
