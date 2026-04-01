---
name: trello
description: "Trello project management con gestión automática de ramas Git por tarjeta, búsqueda de bugs y código comentado. Use when: (1) gestionar boards/listas/tarjetas, (2) crear ramas Git vinculadas a tarjetas, (3) mover tarjetas según estado del código, (4) buscar bugs o código comentado en el repo, (5) sincronizar flujo Trello ↔ Git. NOT for: repos sin Trello, CI/CD pipelines, ni administración de workspace Trello."
homepage: https://developer.atlassian.com/cloud/trello/rest/
metadata:
  {
    "somer":
      {
        "emoji": "📋",
        "requires": { "bins": ["git", "curl", "python3"], "env": ["TRELLO_API_KEY", "TRELLO_TOKEN"] },
        "secrets":
          [
            {
              "key": "TRELLO_API_KEY",
              "description": "Trello API Key (desde https://trello.com/power-ups/admin)",
              "required": true,
            },
            {
              "key": "TRELLO_TOKEN",
              "description": "Trello Token de autorización",
              "required": true,
            },
            {
              "key": "TRELLO_BOARD_ID",
              "description": "ID del board principal (opcional, se puede descubrir via API)",
              "required": false,
            },
          ],
      },
  }
---

# Trello Skill

Gestión completa de Trello integrada con Git: crea ramas por tarjeta, administra el flujo de trabajo, y detecta bugs o código comentado en el repositorio.

## Cuándo Usar

✅ **USA esta skill cuando:**

- Gestionar boards, listas y tarjetas en Trello
- Crear ramas Git automáticamente vinculadas a tarjetas
- Mover tarjetas según el progreso del desarrollo
- Buscar bugs, TODOs o código comentado en el repositorio
- Sincronizar el estado del código con el board de Trello
- Revisar qué tarjetas tienen ramas activas o PRs pendientes

## Cuándo NO Usar

❌ **NO uses esta skill cuando:**

- No hay un board de Trello asociado al proyecto
- Operaciones Git sin relación a tarjetas → usar `git` directamente
- Gestión de miembros/permisos del workspace → usar la UI web
- Automatización de Trello con Butler → configurar en la UI web

---

## Cómo Obtener el API Key y Token

### Paso 1: Obtener tu API Key

1. Inicia sesión en [trello.com](https://trello.com)
2. Ve a **https://trello.com/power-ups/admin**
3. Click en **"New"** para crear un nuevo Power-Up (o usa uno existente)
4. Completa los campos:
   - **Name**: `SOMER Integration` (o el nombre que prefieras)
   - **Workspace**: selecciona tu workspace
   - **Iframe connector URL**: déjalo vacío
   - **Email**: tu email
   - **Support contact**: tu email
   - **Author**: tu nombre
5. Click en **"Create"**
6. En la página del Power-Up, ve a la pestaña **"API Key"**
7. Click en **"Generate a new API Key"**
8. Copia el **API Key** — este es tu `TRELLO_API_KEY`

### Paso 2: Generar Token de Autorización

1. En la misma página del Power-Up donde obtuviste el API Key
2. A la derecha del API Key verás un link que dice **"Token"**
3. Click en ese link — te llevará a una página de autorización
4. Verás los permisos que solicita (lectura/escritura de boards, etc.)
5. Click en **"Allow"**
6. Copia el token generado — este es tu `TRELLO_TOKEN`

> **Alternativa manual**: visita esta URL reemplazando `{YOUR_API_KEY}`:
> ```
> https://trello.com/1/authorize?expiration=never&scope=read,write&response_type=token&key={YOUR_API_KEY}
> ```

### Paso 3: Configurar variables de entorno

```bash
export TRELLO_API_KEY="tu-api-key-aquí"
export TRELLO_TOKEN="tu-token-aquí"
```

### Paso 4: Verificar conexión

```bash
curl -s "https://api.trello.com/1/members/me?key=$TRELLO_API_KEY&token=$TRELLO_TOKEN" \
  | python3 -c "
import sys, json
u = json.load(sys.stdin)
print(f\"✓ Conectado como: {u['fullName']} (@{u['username']})\")"
```

---

## Variables Base

```bash
TK="key=$TRELLO_API_KEY&token=$TRELLO_TOKEN"
TB="https://api.trello.com/1"
```

---

## Boards y Listas

### Listar boards

```bash
curl -s "$TB/members/me/boards?$TK&fields=name,id,url" \
  | python3 -c "
import sys, json
for b in json.load(sys.stdin):
    print(f\"{b['id']}  {b['name']}\")"
```

### Listar listas de un board

```bash
BOARD_ID="abc123"
curl -s "$TB/boards/$BOARD_ID/lists?$TK&fields=name,id" \
  | python3 -c "
import sys, json
for l in json.load(sys.stdin):
    print(f\"{l['id']}  {l['name']}\")"
```

### Crear lista

```bash
curl -s -X POST "$TB/lists?$TK" \
  -d "name=🐛 Bugs Encontrados" \
  -d "idBoard=$BOARD_ID" \
  -d "pos=bottom"
```

---

## Tarjetas

### Listar tarjetas de una lista

```bash
LIST_ID="xyz789"
curl -s "$TB/lists/$LIST_ID/cards?$TK&fields=name,id,desc,labels,shortUrl" \
  | python3 -c "
import sys, json
for c in json.load(sys.stdin):
    labels = ', '.join(l['name'] for l in c.get('labels', []) if l.get('name'))
    lbl = f' [{labels}]' if labels else ''
    print(f\"{c['id']}  {c['name']}{lbl}\")"
```

### Crear tarjeta

```bash
curl -s -X POST "$TB/cards?$TK" \
  -d "idList=$LIST_ID" \
  -d "name=feat: implementar login OAuth" \
  -d "desc=Implementar flujo OAuth 2.0 con Google y GitHub"
```

### Mover tarjeta a otra lista

```bash
CARD_ID="card123"
NEW_LIST_ID="list456"
curl -s -X PUT "$TB/cards/$CARD_ID?$TK" \
  -d "idList=$NEW_LIST_ID"
```

### Agregar comentario a tarjeta

```bash
curl -s -X POST "$TB/cards/$CARD_ID/actions/comments?$TK" \
  -d "text=Rama creada: feature/CARD-123-login-oauth"
```

### Agregar etiqueta a tarjeta

```bash
LABEL_ID="label789"
curl -s -X POST "$TB/cards/$CARD_ID/idLabels?$TK" \
  -d "value=$LABEL_ID"
```

### Archivar tarjeta

```bash
curl -s -X PUT "$TB/cards/$CARD_ID?$TK" -d "closed=true"
```

### Obtener adjuntos de una tarjeta

```bash
curl -s "$TB/cards/$CARD_ID/attachments?$TK" \
  | python3 -c "
import sys, json
for a in json.load(sys.stdin):
    print(f\"{a['name']}: {a['url']}\")"
```

---

## Gestión de Ramas por Tarjeta

### Convención de nombres

El formato de rama sigue: `tipo/CARD-{shortId}-{slug-del-nombre}`

```
feature/CARD-a1b2-login-oauth
bugfix/CARD-c3d4-fix-null-pointer
hotfix/CARD-e5f6-crash-on-startup
```

### Crear rama desde tarjeta

```bash
# Obtener info de la tarjeta
CARD_ID="card123"
CARD_INFO=$(curl -s "$TB/cards/$CARD_ID?$TK&fields=name,shortLink,labels")

# Extraer datos y crear rama
python3 -c "
import json, re, subprocess, sys

card = json.loads('''$CARD_INFO''')
name = card['name']
short = card['shortLink']
labels = [l['name'].lower() for l in card.get('labels', []) if l.get('name')]

# Determinar prefijo por etiqueta
prefix = 'feature'
if any(l in ('bug', 'bugfix', '🐛') for l in labels):
    prefix = 'bugfix'
elif any(l in ('hotfix', '🔥', 'urgent') for l in labels):
    prefix = 'hotfix'
elif any(l in ('chore', 'tech-debt') for l in labels):
    prefix = 'chore'

# Generar slug limpio
slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')[:40]
branch = f'{prefix}/CARD-{short}-{slug}'
print(f'Rama: {branch}')
"
```

```bash
# Crear y pushear la rama
BRANCH="feature/CARD-a1b2-login-oauth"
git checkout -b "$BRANCH" main
git push -u origin "$BRANCH"

# Comentar en la tarjeta
curl -s -X POST "$TB/cards/$CARD_ID/actions/comments?$TK" \
  -d "text=🔀 Rama creada: \`$BRANCH\`"

# Adjuntar URL del repo (opcional)
curl -s -X POST "$TB/cards/$CARD_ID/attachments?$TK" \
  -d "name=Branch: $BRANCH" \
  -d "url=https://bitbucket.org/workspace/repo/branch/$BRANCH"
```

### Listar tarjetas con sus ramas activas

```bash
# Obtener todas las tarjetas del board y cruzar con ramas remotas
BOARD_ID="abc123"
CARDS=$(curl -s "$TB/boards/$BOARD_ID/cards?$TK&fields=name,shortLink,idList")
BRANCHES=$(git branch -r --list 'origin/*' | sed 's|origin/||;s|^ *||')

python3 -c "
import json

cards = json.loads('''$CARDS''')
branches = '''$BRANCHES'''.strip().split('\n')

for card in cards:
    short = card['shortLink']
    matching = [b for b in branches if f'CARD-{short}' in b]
    status = f'🔀 {matching[0]}' if matching else '⏳ sin rama'
    print(f\"{card['name']} [{short}] → {status}\")
"
```

### Mover tarjeta según estado de la rama

```bash
# Flujo: Backlog → In Progress → Review → Done
IN_PROGRESS_LIST="list_progress"
REVIEW_LIST="list_review"
DONE_LIST="list_done"

# Al crear la rama → mover a In Progress
curl -s -X PUT "$TB/cards/$CARD_ID?$TK" -d "idList=$IN_PROGRESS_LIST"
curl -s -X POST "$TB/cards/$CARD_ID/actions/comments?$TK" \
  -d "text=📌 Movida a In Progress — desarrollo iniciado"

# Al crear PR → mover a Review
curl -s -X PUT "$TB/cards/$CARD_ID?$TK" -d "idList=$REVIEW_LIST"
curl -s -X POST "$TB/cards/$CARD_ID/actions/comments?$TK" \
  -d "text=👀 Movida a Review — PR creado"

# Al mergear → mover a Done
curl -s -X PUT "$TB/cards/$CARD_ID?$TK" -d "idList=$DONE_LIST"
curl -s -X POST "$TB/cards/$CARD_ID/actions/comments?$TK" \
  -d "text=✅ Completada — rama mergeada y cerrada"
```

### Limpiar ramas de tarjetas completadas

```bash
DONE_LIST="list_done"
DONE_CARDS=$(curl -s "$TB/lists/$DONE_LIST/cards?$TK&fields=shortLink,name")

python3 -c "
import json, subprocess

cards = json.loads('''$DONE_CARDS''')
branches = subprocess.run(['git', 'branch', '-r'], capture_output=True, text=True).stdout

for card in cards:
    short = card['shortLink']
    for line in branches.strip().split('\n'):
        branch = line.strip().replace('origin/', '')
        if f'CARD-{short}' in branch:
            print(f\"Rama para eliminar: {branch} (tarjeta: {card['name']})\")"

# Para eliminar ejecutar:
# git push origin --delete <rama>
# git branch -d <rama>
```

---

## Búsqueda de Bugs y Código Comentado

### Buscar TODOs, FIXMEs y HACKs en el repo

```bash
echo "=== TODOs ==="
grep -rn "TODO" --include="*.py" . | head -20

echo -e "\n=== FIXMEs ==="
grep -rn "FIXME" --include="*.py" . | head -20

echo -e "\n=== HACKs ==="
grep -rn "HACK\|XXX\|WORKAROUND" --include="*.py" . | head -20
```

### Buscar código comentado (bloques grandes)

```bash
# Detectar bloques de código Python comentado (3+ líneas consecutivas con #)
python3 -c "
import os, re

exts = {'.py'}
min_block = 3  # mínimo de líneas comentadas consecutivas

for root, dirs, files in os.walk('.'):
    dirs[:] = [d for d in dirs if d not in {'.git', '__pycache__', 'node_modules', '.venv', 'venv'}]
    for f in files:
        if not any(f.endswith(e) for e in exts):
            continue
        path = os.path.join(root, f)
        try:
            lines = open(path).readlines()
        except:
            continue
        block_start = None
        count = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            # Línea de código comentada (no docstrings, no headers)
            if stripped.startswith('#') and len(stripped) > 3 and not stripped.startswith('#!') and not stripped.startswith('# -*-'):
                if block_start is None:
                    block_start = i + 1
                count += 1
            else:
                if count >= min_block:
                    print(f'{path}:{block_start}-{block_start + count - 1}  ({count} líneas comentadas)')
                block_start = None
                count = 0
        if count >= min_block:
            print(f'{path}:{block_start}-{block_start + count - 1}  ({count} líneas comentadas)')
"
```

### Buscar patrones sospechosos (posibles bugs)

```bash
python3 -c "
import os, re

patterns = {
    'except vacío (traga errores)': r'except\s*:',
    'pass en except (ignora error)': r'except.*:\s*\n\s*pass',
    'print de debug suelto': r'^\s*print\s*\(',
    'breakpoint olvidado': r'breakpoint\(\)|pdb\.set_trace\(\)|import\s+pdb',
    'variable no usada (_)': r'^\s*_\s*=\s*',
    'credencial hardcodeada': r'(password|secret|api_key)\s*=\s*[\"\\'][^\"\\'\$]',
    'sleep sospechoso': r'time\.sleep\(\d{2,}\)',
    'raise genérico': r'raise\s+Exception\s*\(',
}

for root, dirs, files in os.walk('.'):
    dirs[:] = [d for d in dirs if d not in {'.git', '__pycache__', 'node_modules', '.venv', 'venv', 'tests'}]
    for f in files:
        if not f.endswith('.py'):
            continue
        path = os.path.join(root, f)
        try:
            content = open(path).read()
            lines = content.split('\n')
        except:
            continue
        for desc, pat in patterns.items():
            for i, line in enumerate(lines):
                if re.search(pat, line):
                    print(f'{path}:{i+1}  ⚠ {desc}')
                    print(f'    {line.strip()[:100]}')
"
```

### Crear tarjetas automáticas por bugs encontrados

```bash
# Buscar TODOs y crear tarjetas en la lista de Bugs
BUGS_LIST="list_bugs"

python3 -c "
import os, re, json, urllib.request, urllib.parse

api_key = os.environ['TRELLO_API_KEY']
token = os.environ['TRELLO_TOKEN']
list_id = '$BUGS_LIST'

todos = []
for root, dirs, files in os.walk('.'):
    dirs[:] = [d for d in dirs if d not in {'.git', '__pycache__', '.venv', 'venv'}]
    for f in files:
        if not f.endswith('.py'):
            continue
        path = os.path.join(root, f)
        try:
            for i, line in enumerate(open(path)):
                match = re.search(r'#\s*(TODO|FIXME|BUG|HACK)[\s:]+(.+)', line)
                if match:
                    kind, msg = match.groups()
                    todos.append({'kind': kind, 'msg': msg.strip(), 'file': path, 'line': i+1})
        except:
            pass

print(f'Encontrados: {len(todos)} items')
for t in todos[:10]:  # máximo 10 para no saturar
    name = f\"[{t['kind']}] {t['msg'][:80]}\"
    desc = f\"Archivo: \`{t['file']}:{t['line']}\`\nLínea original: {t['msg']}\"
    data = urllib.parse.urlencode({
        'key': api_key, 'token': token,
        'idList': list_id,
        'name': name,
        'desc': desc,
    }).encode()
    req = urllib.request.Request(f'https://api.trello.com/1/cards', data=data, method='POST')
    resp = urllib.request.urlopen(req)
    card = json.loads(resp.read())
    print(f\"  ✓ Tarjeta creada: {card['shortUrl']}  →  {name}\")
"
```

### Reporte completo: tarjetas + ramas + bugs

```bash
BOARD_ID="abc123"

echo "╔══════════════════════════════════════╗"
echo "║     REPORTE TRELLO ↔ GIT            ║"
echo "╚══════════════════════════════════════╝"

echo -e "\n📋 TARJETAS ACTIVAS Y RAMAS"
echo "────────────────────────────────────────"

CARDS=$(curl -s "$TB/boards/$BOARD_ID/cards?$TK&fields=name,shortLink,idList,labels")
LISTS=$(curl -s "$TB/boards/$BOARD_ID/lists?$TK&fields=name,id")
BRANCHES=$(git branch -r --list 'origin/*' 2>/dev/null | sed 's|origin/||;s|^ *||')

python3 -c "
import json

cards = json.loads('''$CARDS''')
lists = {l['id']: l['name'] for l in json.loads('''$LISTS''')}
branches = '''$BRANCHES'''.strip().split('\n')

for card in cards:
    short = card['shortLink']
    list_name = lists.get(card['idList'], '?')
    matching = [b for b in branches if f'CARD-{short}' in b]
    labels = ', '.join(l['name'] for l in card.get('labels', []) if l.get('name'))

    branch_info = matching[0] if matching else 'sin rama'
    lbl = f' [{labels}]' if labels else ''
    print(f'  {list_name:20s} │ {card[\"name\"][:40]:40s}{lbl} │ {branch_info}')
"

echo -e "\n🐛 CÓDIGO SOSPECHOSO"
echo "────────────────────────────────────────"
grep -rn "TODO\|FIXME\|HACK\|BUG\|XXX" --include="*.py" . 2>/dev/null | grep -v __pycache__ | head -15

echo -e "\n💬 CÓDIGO COMENTADO (bloques ≥3 líneas)"
echo "────────────────────────────────────────"
python3 -c "
import os
for root, dirs, files in os.walk('.'):
    dirs[:] = [d for d in dirs if d not in {'.git', '__pycache__', '.venv'}]
    for f in files:
        if not f.endswith('.py'): continue
        path = os.path.join(root, f)
        try: lines = open(path).readlines()
        except: continue
        start, count = None, 0
        for i, l in enumerate(lines):
            s = l.strip()
            if s.startswith('#') and len(s) > 3 and not s.startswith('#!'):
                if start is None: start = i + 1
                count += 1
            else:
                if count >= 3:
                    print(f'  {path}:{start}-{start+count-1}  ({count} líneas)')
                start, count = None, 0
        if count >= 3:
            print(f'  {path}:{start}-{start+count-1}  ({count} líneas)')
" | head -15

echo -e "\n🔀 RAMAS SIN TARJETA"
echo "────────────────────────────────────────"
python3 -c "
branches = '''$BRANCHES'''.strip().split('\n')
for b in branches:
    b = b.strip()
    if b and 'CARD-' not in b and b not in ('main', 'master', 'develop', 'HEAD'):
        print(f'  ⚠ {b} (sin tarjeta vinculada)')
" | head -10
```

---

## Etiquetas Recomendadas para el Board

Configura estas etiquetas en tu board de Trello para que la automatización funcione:

| Color    | Nombre     | Uso                                |
|----------|------------|------------------------------------|
| 🔴 Rojo  | `bug`      | Bug confirmado → rama `bugfix/`    |
| 🟠 Naranja | `hotfix` | Corrección urgente → rama `hotfix/` |
| 🟢 Verde | `feature`  | Nueva funcionalidad → rama `feature/` |
| 🔵 Azul  | `chore`    | Mantenimiento → rama `chore/`       |
| 🟡 Amarillo | `tech-debt` | Deuda técnica → rama `chore/`   |
| 🟣 Morado | `review`  | En revisión de código               |

---

## Checklists y Due Dates

### Agregar checklist a tarjeta

```bash
# Crear checklist
CL=$(curl -s -X POST "$TB/cards/$CARD_ID/checklists?$TK" \
  -d "name=Definition of Done" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# Agregar items
for item in "Tests unitarios" "Code review" "Sin código comentado" "CI verde" "Documentación"; do
  curl -s -X POST "$TB/checklists/$CL/checkItems?$TK" -d "name=$item" > /dev/null
done
echo "✓ Checklist creada con 5 items"
```

### Establecer fecha límite

```bash
curl -s -X PUT "$TB/cards/$CARD_ID?$TK" -d "due=2026-04-01T12:00:00.000Z"
```

---

## Notas

- **API Key**: se obtiene en https://trello.com/power-ups/admin → tu Power-Up → API Key
- **Token**: nunca expira si usas `expiration=never`; revócalo en https://trello.com/my/account si es comprometido
- **Rate limits**: 300 req/10s por API key, 100 req/10s por token
- **IDs**: los puedes obtener agregando `.json` a cualquier URL de Trello (ej: `https://trello.com/b/abc123.json`)
- **shortLink**: es el ID corto visible en la URL de la tarjeta, ideal para nombres de ramas
- La convención `CARD-{shortLink}` permite vincular ramas con tarjetas automáticamente
- Los scripts de búsqueda de bugs excluyen `tests/`, `__pycache__`, `.venv` y `.git`

## Formato de Respuesta

**Usar plantilla `TPL-TASKS`** de `_templates/RESPONSE_FORMATS.md` para listados/revisiones y `TPL-DEVOPS` para operaciones individuales.

### Revisión de tablero

Al revisar un board, listar CADA tarjeta con contexto suficiente para tomar decisiones.
Agrupar por lista (no por fecha) cuando no hay due dates. Incluir: nombre, descripción (resumen corto o "sin descripción"), labels, due date, checklist, y miembros.

```
TAREAS — Trello: {board} | {fecha}

RESUMEN: {total} tareas | {pendientes} pendientes | {vencidas} vencidas

{NOMBRE DE LISTA 1}
  [!!] {tarjeta} — vencida {fecha} | {labels} | {miembro}
       {resumen de descripción o "sin descripción"}
       Checklist: {completados}/{total} items
  [ ] {tarjeta} — vence {fecha} | {labels} | {miembro}
       {resumen de descripción o "sin descripción"}

{NOMBRE DE LISTA 2}
  [ ] {tarjeta} — sin fecha | {labels} | {miembro}
       {resumen de descripción o "sin descripción"}
  [ ] {tarjeta} — sin fecha | sin labels | sin asignar
       sin descripción

ALERTAS
  [!] {n} tarjetas sin descripción: {nombres cortos}
  [!] {n} tarjetas sin fecha límite
  [!] {n} tarjetas sin checklist

---
Fuente: Trello | Board: {nombre} | URL: {url} | Actualizado: {timestamp}
```

### Listado por fechas (cuando hay due dates)

```
TAREAS — Trello: {board} | {fecha}

RESUMEN: {total} tareas | {pendientes} pendientes | {vencidas} vencidas

URGENTES / VENCIDAS
  [!!] {tarjeta} — vencida {fecha} | {lista} | {labels}

HOY
  [ ] {tarjeta} — {contexto} | {lista} | {labels}

ESTA SEMANA
  [ ] {tarjeta} — {día} | {lista} | {labels}

PRÓXIMAMENTE
  [ ] {tarjeta} — {fecha} | {lista} | {labels}

SIN FECHA
  [ ] {tarjeta} — {lista} | {labels}

---
Fuente: Trello | Board: {nombre} | URL: {url} | Actualizado: {timestamp}
```

### Acción individual (crear/mover/archivar tarjeta)

```
DEVOPS — {operación} | {fecha}

  {tarjeta} → {qué se hizo} | {lista destino}
  URL: {shortUrl}

---
Fuente: Trello | {board}
```
