---
name: claude-code
description: "Integración directa con Claude Code CLI para tareas de desarrollo automatizado. Use when: (1) delegar tareas complejas de código a Claude Code, (2) ejecutar refactorings masivos, (3) generar features completas, (4) revisar PRs con análisis profundo, (5) debugging asistido, (6) generación de tests. NOT for: ediciones simples de una línea (editar directo), lectura de archivos (usar read tool), tareas que no requieren análisis de código."
metadata:
  {
    "somer":
      {
        "emoji": "🤖",
        "requires": { "bins": ["claude"] },
        "install":
          [
            {
              "id": "npm",
              "kind": "npm",
              "package": "@anthropic-ai/claude-code",
              "global": true,
              "bins": ["claude"],
              "label": "Install Claude Code CLI (npm)",
            },
          ],
      },
  }
---

# Claude Code Skill

Integración con el CLI de Claude Code (`claude`) para delegar tareas complejas de desarrollo, refactoring, revisión de código y debugging.

## Cuándo Usar

✅ **USA esta skill cuando:**

- Implementar features completas que tocan múltiples archivos
- Refactorizar módulos grandes o migrar patrones
- Revisar PRs con análisis profundo del código
- Debugging complejo que requiere explorar el codebase
- Generar tests unitarios o de integración
- Análisis de seguridad del código
- Documentar módulos o APIs existentes
- Tareas paralelas en múltiples directorios

## Cuándo NO Usar

❌ **NO uses esta skill cuando:**

- Ediciones de 1-3 líneas → editar directo
- Solo leer/explorar código → usar read/grep
- El proyecto no tiene código fuente
- La tarea es solo de configuración o infra

---

## Instalación

```bash
# Via npm (recomendado)
npm install -g @anthropic-ai/claude-code

# Verificar instalación
claude --version

# Login (una sola vez)
claude login
```

## Modos de Ejecución

### Modo Print (recomendado para automatización)

Sin interacción, salida directa, acceso completo a herramientas:

```bash
claude --permission-mode bypassPermissions --print "Tu tarea aquí"
```

### Modo Interactivo

Para sesiones donde quieres intervenir:

```bash
claude "Tu tarea aquí"
```

### Flags Principales

| Flag | Efecto |
|------|--------|
| `--print` | Modo no-interactivo, imprime resultado y sale |
| `--permission-mode bypassPermissions` | Auto-aprueba todas las operaciones |
| `--model <model>` | Elegir modelo (opus, sonnet, haiku) |
| `--max-turns <n>` | Limitar turnos de conversación |
| `--output-format json` | Salida en JSON estructurado |
| `--verbose` | Logs detallados |
| `--allowedTools <tools>` | Restringir herramientas disponibles |

---

## Tareas Comunes

### Implementar una Feature

```bash
cd ~/Projects/mi-proyecto && \
claude --permission-mode bypassPermissions --print \
  "Implementa un sistema de caché LRU en memory/cache.py con:
   - Tamaño máximo configurable
   - TTL por entrada
   - Métodos get, set, invalidate, clear
   - Tests unitarios en tests/unit/test_cache.py
   Sigue las convenciones del proyecto existente."
```

### Refactoring Masivo

```bash
claude --permission-mode bypassPermissions --print \
  "Refactoriza todos los archivos en providers/ para:
   1. Extraer lógica de retry a un decorator compartido
   2. Unificar el manejo de errores usando shared/errors.py
   3. Asegurar que todos los providers implementen health_check()
   No modifiques la interfaz pública de BaseProvider."
```

### Revisar un PR

```bash
# Clonar a directorio temporal para no tocar el proyecto activo
REVIEW_DIR=$(mktemp -d)
git clone . "$REVIEW_DIR"
cd "$REVIEW_DIR" && git checkout feature/mi-rama

claude --permission-mode bypassPermissions --print \
  "Revisa los cambios en esta rama vs main:
   - git diff main...HEAD
   - Busca bugs, race conditions, problemas de seguridad
   - Verifica que los tests cubran los cambios
   - Genera un reporte con: resumen, issues encontrados, sugerencias
   NO hagas cambios, solo analiza y reporta."
```

### Generar Tests

```bash
claude --permission-mode bypassPermissions --print \
  "Genera tests unitarios para el módulo sessions/router.py:
   - Usa pytest con asyncio
   - Cubre happy path, edge cases y errores
   - Mockea dependencias externas
   - Apunta a >90% de coverage
   - Escribe en tests/unit/sessions/test_router.py"
```

### Debugging Asistido

```bash
claude --permission-mode bypassPermissions --print \
  "El test test_memory_search está fallando con 'KeyError: embeddings'.
   - Lee el test y el módulo memory/search.py
   - Encuentra la causa raíz
   - Aplica el fix mínimo necesario
   - Verifica que el test pase"
```

### Análisis de Seguridad

```bash
claude --permission-mode bypassPermissions --print \
  "Analiza el directorio gateway/ buscando:
   - Inyección de comandos
   - Validación insuficiente de input
   - Secrets hardcodeados
   - SSRF o path traversal
   - Permisos excesivos
   Genera un reporte con severidad (crítica/alta/media/baja) por hallazgo."
```

---

## Ejecución en Background

Para tareas largas, ejecutar en background y monitorear:

```bash
# Iniciar en background
bash workdir:~/project background:true command:"claude --permission-mode bypassPermissions --print 'Refactoriza el módulo de providers completo.

Cuando termines, ejecuta: somer system event --text \"Done: refactoring providers completado\" --mode now'"

# Monitorear
process action:log sessionId:XXX
process action:poll sessionId:XXX

# Matar si es necesario
process action:kill sessionId:XXX
```

---

## Ejecución Paralela con Worktrees

Para trabajar en múltiples tareas simultáneamente:

```bash
# Crear worktrees para cada tarea
git worktree add -b feat/auth-refactor /tmp/auth-refactor main
git worktree add -b feat/add-caching /tmp/add-caching main
git worktree add -b fix/memory-leak /tmp/memory-leak main

# Lanzar Claude Code en cada uno (en paralelo)
bash workdir:/tmp/auth-refactor background:true \
  command:"claude --permission-mode bypassPermissions --print 'Refactoriza el sistema de auth...'"

bash workdir:/tmp/add-caching background:true \
  command:"claude --permission-mode bypassPermissions --print 'Implementa caching en providers...'"

bash workdir:/tmp/memory-leak background:true \
  command:"claude --permission-mode bypassPermissions --print 'Investiga y corrige el memory leak en sessions...'"

# Monitorear todos
process action:list

# Cuando terminen, crear PRs
cd /tmp/auth-refactor && git push -u origin feat/auth-refactor
cd /tmp/add-caching && git push -u origin feat/add-caching
cd /tmp/memory-leak && git push -u origin fix/memory-leak

# Limpiar
git worktree remove /tmp/auth-refactor
git worktree remove /tmp/add-caching
git worktree remove /tmp/memory-leak
```

---

## Salida Estructurada (JSON)

Para integrar con pipelines o procesar la salida programáticamente:

```bash
claude --permission-mode bypassPermissions --print --output-format json \
  "Lista todos los endpoints del gateway con su método HTTP y ruta" \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)
# Procesar resultado estructurado
print(json.dumps(data, indent=2))
"
```

---

## Integración con SOMER

### Desde el Agent Runner

```python
import asyncio
import subprocess

async def delegate_to_claude_code(task: str, workdir: str = ".") -> str:
    """Delega una tarea al CLI de Claude Code."""
    proc = await asyncio.create_subprocess_exec(
        "claude",
        "--permission-mode", "bypassPermissions",
        "--print",
        "--output-format", "json",
        task,
        cwd=workdir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"Claude Code falló: {stderr.decode()}")
    return stdout.decode()
```

### Desde una Skill con bash

```bash
# Wrapper simple que cualquier skill puede usar
claude_task() {
    local workdir="${1:-.}"
    local task="$2"
    cd "$workdir" && claude --permission-mode bypassPermissions --print "$task"
}

# Uso
claude_task ~/Projects/api "Agrega validación de input a todos los endpoints POST"
```

---

## Patrones de Prompt Efectivos

### Prompt con contexto del proyecto

```bash
claude --permission-mode bypassPermissions --print \
  "CONTEXTO: Proyecto Python 3.9+, Pydantic v2, asyncio, pytest.
   Convenciones: tipos en shared/types.py, errores en shared/errors.py.

   TAREA: [tu tarea aquí]

   RESTRICCIONES:
   - No modificar interfaces públicas existentes
   - Mantener compatibilidad con Python 3.9
   - Agregar tests para código nuevo"
```

### Prompt de revisión con checklist

```bash
claude --permission-mode bypassPermissions --print \
  "Revisa los cambios recientes (git diff HEAD~3):

   Checklist:
   □ Sin vulnerabilidades de seguridad
   □ Manejo de errores adecuado
   □ Sin código duplicado
   □ Tests suficientes
   □ Sin prints de debug
   □ Sin secrets hardcodeados
   □ Tipos correctos (Pydantic v2)
   □ Async/await correcto

   Responde con la checklist marcada y comentarios por item."
```

### Prompt de migración

```bash
claude --permission-mode bypassPermissions --print \
  "Migra el módulo old_auth/ al nuevo patrón en auth/:
   - Lee old_auth/ para entender la lógica actual
   - Lee auth/base.py para entender la nueva interfaz
   - Crea auth/providers/ con un provider por archivo
   - Migra tests de tests/old_auth/ a tests/auth/
   - Asegura que todos los tests pasen
   - NO elimines old_auth/ (lo haremos después de validar)"
```

---

## Restricción de Herramientas

Para limitar qué puede hacer Claude Code:

```bash
# Solo lectura (análisis sin modificar)
claude --permission-mode bypassPermissions --print \
  --allowedTools "Read,Glob,Grep,Bash(readonly)" \
  "Analiza la arquitectura del proyecto y genera un diagrama de dependencias"

# Sin acceso a internet
claude --permission-mode bypassPermissions --print \
  --allowedTools "Read,Write,Edit,Glob,Grep,Bash" \
  "Refactoriza sin consultar documentación externa"
```

---

## Notas

- **Nunca ejecutar Claude Code dentro del directorio de SOMER activo** — usar worktrees o temp dirs
- `--print` es esencial para automatización — sin él, Claude Code espera input interactivo
- `--permission-mode bypassPermissions` evita confirmaciones — usar solo en entornos controlados
- Las tareas largas (>5 min) deben ejecutarse en background con notificación de completitud
- Claude Code tiene acceso al filesystem — restringir con `--allowedTools` si es necesario
- Para modelos específicos: `--model claude-opus-4-6` o `--model claude-sonnet-4-6`
- El CLI respeta `ANTHROPIC_API_KEY` del entorno — no necesita config adicional si ya está seteado

## Formato de Respuesta

**Usar plantilla `TPL-ACTION`** de `_templates/RESPONSE_FORMATS.md`. Ejemplo:

```
ACCIÓN — Claude Code | Tarea completada | 26/Mar/2026

RESULTADO
  Estado:     Completado
  Detalle:    PR #52 creado — "Fix: token refresh on expired sessions"

SALIDA
  Repo:       owner/repo
  Branch:     fix/token-refresh
  PR:         #52
  Archivos:   4 modificados
  Tests:      Todos pasando

---
Ejecutado por: SOMER Claude Code
```
