---
name: sentry
description: "Sentry error tracking operations via `sentry-cli` and Sentry API: list/search issues, view error details, manage releases, check project health, resolve/assign issues. Use when: (1) investigating production errors, (2) checking error frequency/trends, (3) managing releases and deploys, (4) triaging unresolved issues. NOT for: local debugging (use debugger), log analysis (use ELK/Datadog), or performance profiling (use APM tools)."
metadata:
  {
    "somer":
      {
        "emoji": "🐛",
        "requires": { "bins": ["sentry-cli"], "env": ["SENTRY_AUTH_TOKEN", "SENTRY_ORG"] },
        "install":
          [
            {
              "id": "brew",
              "kind": "brew",
              "formula": "getsentry/tools/sentry-cli",
              "bins": ["sentry-cli"],
              "label": "Install Sentry CLI (brew)",
            },
            {
              "id": "pip",
              "kind": "pip",
              "package": "sentry-cli",
              "bins": ["sentry-cli"],
              "label": "Install Sentry CLI (pip)",
            },
            {
              "id": "npm",
              "kind": "npm",
              "package": "@sentry/cli",
              "bins": ["sentry-cli"],
              "label": "Install Sentry CLI (npm)",
            },
          ],
        "secrets":
          [
            {
              "key": "SENTRY_AUTH_TOKEN",
              "description": "Token de autenticación de Sentry (Settings > Auth Tokens)",
              "required": true,
            },
            {
              "key": "SENTRY_ORG",
              "description": "Slug de la organización en Sentry",
              "required": true,
            },
            {
              "key": "SENTRY_PROJECT",
              "description": "Slug del proyecto en Sentry (opcional, se puede pasar por comando)",
              "required": false,
            },
          ],
      },
  }
---

# Sentry Skill

Gestiona errores, releases y salud de proyectos en Sentry usando `sentry-cli` y la API REST.

## When to Use

✅ **USA este skill cuando:**

- Investigar errores de producción (stacktraces, frecuencia, usuarios afectados)
- Listar issues no resueltos ordenados por impacto
- Ver tendencias de errores y regresiones
- Crear y gestionar releases (versiones)
- Subir source maps para debugging
- Asignar issues a miembros del equipo
- Resolver o archivar issues
- Monitorear salud post-deploy

## When NOT to Use

❌ **NO uses este skill cuando:**

- Debugging local → usar debugger o logs locales
- Análisis de logs → usar ELK, Datadog, CloudWatch
- Performance profiling → usar APM dedicado
- Monitoreo de uptime → usar UptimeRobot, Pingdom
- El proyecto no usa Sentry

## Setup

```bash
# Instalar sentry-cli
brew install getsentry/tools/sentry-cli

# Configurar autenticación
export SENTRY_AUTH_TOKEN="sntrys_..."
export SENTRY_ORG="mi-organizacion"
export SENTRY_PROJECT="mi-proyecto"

# Verificar
sentry-cli info
```

## Common Commands

### Issues y Errores

```bash
# Listar issues no resueltos del proyecto
curl -s -H "Authorization: Bearer $SENTRY_AUTH_TOKEN" \
  "https://sentry.io/api/0/projects/$SENTRY_ORG/$SENTRY_PROJECT/issues/?query=is:unresolved&sort=freq" \
  | python3 -c "
import sys, json
issues = json.load(sys.stdin)
for i in issues[:20]:
    print(f'[{i[\"shortId\"]}] {i[\"title\"]}')
    print(f'  Events: {i[\"count\"]} | Users: {i[\"userCount\"]} | Level: {i[\"level\"]}')
    print(f'  First: {i[\"firstSeen\"][:10]} | Last: {i[\"lastSeen\"][:10]}')
    print()
"

# Ver detalles de un issue específico
curl -s -H "Authorization: Bearer $SENTRY_AUTH_TOKEN" \
  "https://sentry.io/api/0/issues/<issue-id>/" \
  | python3 -c "
import sys, json
i = json.load(sys.stdin)
print(f'# {i[\"shortId\"]}: {i[\"title\"]}')
print(f'Level: {i[\"level\"]} | Events: {i[\"count\"]} | Users: {i[\"userCount\"]}')
print(f'First: {i[\"firstSeen\"]} | Last: {i[\"lastSeen\"]}')
print(f'Status: {i[\"status\"]} | Assignee: {i.get(\"assignedTo\",{}).get(\"name\",\"unassigned\")}')
"

# Ver último evento de un issue (stacktrace completo)
curl -s -H "Authorization: Bearer $SENTRY_AUTH_TOKEN" \
  "https://sentry.io/api/0/issues/<issue-id>/events/latest/" \
  | python3 -c "
import sys, json
e = json.load(sys.stdin)
for entry in e.get('entries', []):
    if entry['type'] == 'exception':
        for val in entry['data'].get('values', []):
            print(f'Exception: {val[\"type\"]}: {val[\"value\"]}')
            for frame in val.get('stacktrace', {}).get('frames', [])[-5:]:
                print(f'  {frame.get(\"filename\",\"?\")}:{frame.get(\"lineNo\",\"?\")} in {frame.get(\"function\",\"?\")}')
                if frame.get('context'):
                    for ctx in frame['context']:
                        print(f'    {ctx[0]}: {ctx[1]}')
"

# Buscar issues por query
curl -s -H "Authorization: Bearer $SENTRY_AUTH_TOKEN" \
  "https://sentry.io/api/0/projects/$SENTRY_ORG/$SENTRY_PROJECT/issues/?query=is:unresolved+TypeError"
```

### Gestión de Issues

```bash
# Resolver un issue
curl -s -X PUT \
  -H "Authorization: Bearer $SENTRY_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  "https://sentry.io/api/0/issues/<issue-id>/" \
  -d '{"status": "resolved"}'

# Asignar issue a usuario
curl -s -X PUT \
  -H "Authorization: Bearer $SENTRY_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  "https://sentry.io/api/0/issues/<issue-id>/" \
  -d '{"assignedTo": "user:usuario@example.com"}'

# Ignorar issue
curl -s -X PUT \
  -H "Authorization: Bearer $SENTRY_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  "https://sentry.io/api/0/issues/<issue-id>/" \
  -d '{"status": "ignored", "statusDetails": {"ignoreCount": 100}}'

# Resolver múltiples issues a la vez
curl -s -X PUT \
  -H "Authorization: Bearer $SENTRY_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  "https://sentry.io/api/0/projects/$SENTRY_ORG/$SENTRY_PROJECT/issues/?id=<id1>&id=<id2>" \
  -d '{"status": "resolved"}'
```

### Releases

```bash
# Crear release
sentry-cli releases new "v1.2.3" --project $SENTRY_PROJECT

# Asociar commits
sentry-cli releases set-commits "v1.2.3" --auto

# Marcar deploy
sentry-cli releases deploys "v1.2.3" new -e production

# Finalizar release
sentry-cli releases finalize "v1.2.3"

# Subir source maps
sentry-cli releases files "v1.2.3" upload-sourcemaps ./dist/ \
  --url-prefix "~/static/js"

# Listar releases
curl -s -H "Authorization: Bearer $SENTRY_AUTH_TOKEN" \
  "https://sentry.io/api/0/organizations/$SENTRY_ORG/releases/?project=$SENTRY_PROJECT" \
  | python3 -c "import sys,json; [print(f'{r[\"version\"]} ({r[\"dateCreated\"][:10]}) - new: {r[\"newGroups\"]}') for r in json.load(sys.stdin)]"
```

### Salud del Proyecto

```bash
# Stats del proyecto (últimas 24h)
curl -s -H "Authorization: Bearer $SENTRY_AUTH_TOKEN" \
  "https://sentry.io/api/0/projects/$SENTRY_ORG/$SENTRY_PROJECT/stats/?stat=received&resolution=1h" \
  | python3 -c "
import sys, json
from datetime import datetime
stats = json.load(sys.stdin)
total = sum(s[1] for s in stats[-24:])
print(f'Total eventos (24h): {total}')
print(f'Promedio/hora: {total/24:.1f}')
"

# Listar proyectos de la org
sentry-cli projects list

# Verificar conectividad
sentry-cli info
```

## Templates

### Triage Diario

```bash
echo "## Triage de Errores — $(date +%Y-%m-%d)"
echo ""
echo "### Top Issues por Frecuencia"
curl -s -H "Authorization: Bearer $SENTRY_AUTH_TOKEN" \
  "https://sentry.io/api/0/projects/$SENTRY_ORG/$SENTRY_PROJECT/issues/?query=is:unresolved&sort=freq&limit=10" \
  | python3 -c "
import sys, json
for i, issue in enumerate(json.load(sys.stdin), 1):
    print(f'{i}. [{issue[\"shortId\"]}] {issue[\"title\"]}')
    print(f'   Events: {issue[\"count\"]} | Users: {issue[\"userCount\"]} | {issue[\"level\"]}')
"
```

### Check Post-Deploy

```bash
VERSION="v1.2.3"
echo "## Post-Deploy Check: $VERSION"
curl -s -H "Authorization: Bearer $SENTRY_AUTH_TOKEN" \
  "https://sentry.io/api/0/projects/$SENTRY_ORG/$SENTRY_PROJECT/issues/?query=is:unresolved+firstRelease:$VERSION" \
  | python3 -c "
import sys, json
issues = json.load(sys.stdin)
if issues:
    print(f'⚠️ {len(issues)} nuevos issues en {\"$VERSION\"}:')
    for i in issues:
        print(f'  - [{i[\"shortId\"]}] {i[\"title\"]} ({i[\"count\"]} events)')
else:
    print('✅ Sin nuevos issues en esta release')
"
```

## Notes

- El auth token se genera en: Settings > Account > Auth Tokens
- Usar tokens con scope `project:read`, `project:write`, `org:read` como mínimo
- `sentry-cli` usa `SENTRY_AUTH_TOKEN`, `SENTRY_ORG`, `SENTRY_PROJECT` por defecto
- La API REST es más flexible que la CLI para queries complejas
- Rate limit: 100 requests/min por token
- Para self-hosted Sentry: configurar `SENTRY_URL` con la URL del servidor

## Formato de Respuesta

**Usar plantilla `TPL-STATUS`** de `_templates/RESPONSE_FORMATS.md`. Ejemplo:

```
ESTADO — Sentry | proyecto-api | 26/Mar/2026

ESTADO GENERAL: WARN

CHECKS
  [!!] 3 issues sin resolver (últimas 24h)
  [OK] Release v2.1.0 — 0 regresiones
  [OK] Crash-free rate: 99.2%

MÉTRICAS
  Issues abiertos:   12
  Eventos (24h):     45
  Usuarios afectados: 3

ALERTAS
  [!!] TypeError: Cannot read property 'token' — 23 eventos | 2 usuarios
  [!]  TimeoutError: Request timeout — 12 eventos | 1 usuario
  [!]  ValidationError: Invalid email — 10 eventos | 1 usuario

---
Verificado por: SOMER | Servicio: Sentry | Proyecto: proyecto-api
```
