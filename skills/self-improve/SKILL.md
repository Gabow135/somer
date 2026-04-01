---
name: self-improve
description: "Agente de auto-mejora que permite a SOMER escanear sus propios skills para aprender patrones, detectar y guardar credenciales, aplicar parches a su código, validar cambios y reiniciarse. Use when: (1) el usuario pide mejorar algo de SOMER, (2) agregar soporte para un servicio nuevo, (3) aprender patrones de credenciales, (4) verificar estado de mejoras, (5) aplicar un fix y reiniciar. NOT for: desarrollo de features nuevas completas, ni cambios que requieran refactoring mayor."
homepage: https://github.com/somer-ai/somer
metadata:
  {
    "somer":
      {
        "emoji": "🧠",
        "category": "system",
        "priority": "high",
        "requires": { "bins": ["python3", "git"], "env": [] },
        "auto_detect": true,
      },
  }
---

# Self-Improve — Agente de Auto-Mejora de SOMER

SOMER puede mejorarse a si mismo: aprender patrones nuevos, aplicar parches a su codigo, validar cambios y reiniciarse para que tomen efecto.

## Cuando Usar

USA esta skill cuando:

- El usuario pide que SOMER aprenda algo nuevo
- Se necesita agregar soporte para un servicio o integracion nueva
- El usuario quiere que SOMER se auto-mejore en algun aspecto
- Se necesita verificar que credenciales o dependencias de un skill
- El usuario quiere aplicar un fix rapido y reiniciar

NO uses esta skill cuando:

- Se requiere desarrollo de features completamente nuevas (usar coding-agent)
- Cambios que afectan la arquitectura core del sistema
- El usuario solo quiere informacion, no modificaciones

---

## Herramientas Disponibles

### 1. `scan_skills` — Aprender patrones de credenciales

Escanea TODOS los SKILL.md del proyecto y aprende que variables de entorno necesita cada skill. Los patrones se guardan en `~/.somer/learned_patterns.json`.

```
Invocar: scan_skills({})
```

Resultado: Cuantos skills se escanearon y cuantos patrones nuevos se aprendieron.

### 2. `detect_credentials` — Detectar credenciales en texto

Busca API keys, tokens y secretos en un texto usando 3 estrategias:
- **Prefijo**: Reconoce `sk-ant-`, `ghp_`, `gsk_`, etc.
- **Contexto**: Entiende "mi trello key es XYZ"
- **Directa**: Parsea `VARIABLE=valor`

```
Invocar: detect_credentials({"text": "mensaje del usuario", "auto_save": true})
```

### 3. `patch_file` — Aplicar parches al codigo

Modifica archivos del proyecto con find & replace. Crea backup automatico. Valida sintaxis Python antes de aplicar.

```
Invocar: patch_file({
  "file_path": "secrets/detector.py",
  "old_content": "texto a reemplazar",
  "new_content": "texto nuevo",
  "dry_run": false
})
```

IMPORTANTE: Siempre hacer dry_run=true primero para verificar.

### 4. `revert_patch` — Revertir un parche

Restaura un archivo desde su backup .bak.

```
Invocar: revert_patch({"file_path": "secrets/detector.py"})
```

### 5. `validate_change` — Validar cambios

Verifica sintaxis Python y opcionalmente corre tests.

```
Invocar: validate_change({
  "source": "codigo python aqui",
  "run_tests": true,
  "test_path": "tests/unit/secrets/"
})
```

### 6. `restart_service` — Reiniciar SOMER

Solicita reinicio para aplicar cambios. Dos modos:

- **Graceful** (default): Escribe sentinel, el supervisor reinicia
- **Force**: Hard restart via os.execv

```
Invocar: restart_service({"reason": "Nuevos patrones aprendidos"})
Invocar: restart_service({"reason": "Fix critico", "force": true})
```

### 7. `self_improve_status` — Estado del motor

Muestra: project root, patrones aprendidos, restart pendiente, historial.

```
Invocar: self_improve_status({"limit": 10})
```

### 8. `check_skill_deps` — Verificar dependencias

Verifica que variables de entorno faltan para un skill.

```
Invocar: check_skill_deps({"required_env": ["TRELLO_API_KEY", "TRELLO_TOKEN"]})
```

---

## Protocolo de Auto-Mejora

Cuando el usuario pide una mejora, sigue este protocolo:

### Paso 1: Diagnosticar

```
1. Usar self_improve_status para ver el estado actual
2. Identificar que necesita mejorar
3. Usar check_skill_deps si es un problema de credenciales
```

### Paso 2: Planificar

```
1. Si es aprender patrones → scan_skills
2. Si es guardar credenciales → detect_credentials con auto_save
3. Si es modificar codigo → patch_file con dry_run=true primero
```

### Paso 3: Ejecutar

```
1. Aplicar el cambio (patch_file dry_run=false)
2. Validar (validate_change con run_tests=true)
3. Si falla → revert_patch y reportar
```

### Paso 4: Aplicar

```
1. Si los tests pasan → restart_service
2. Confirmar con el usuario antes del restart
3. Reportar que se hizo y que cambio
```

---

## Paths del Proyecto

El sistema soporta multiples ubicaciones:

| Entorno | Path del repo | Path de config |
|---------|---------------|----------------|
| Desarrollo macOS | ~/Documents/Proyectos/Somer | ~/.somer/ |
| Produccion Ubuntu | /var/www/somer | ~/.somer/ |
| Custom | $SOMER_PROJECT_ROOT | $SOMER_HOME |

Para configurar en produccion:

```bash
export SOMER_PROJECT_ROOT=/var/www/somer
export SOMER_HOME=/home/somer/.somer
```

---

## Formato de Respuesta

Usar **TPL-ACTION** para reportar mejoras:

```
ACCION — self-improve | {operacion} | {fecha}

RESULTADO
  Estado:     {completado|error|parcial}
  Detalle:    {descripcion de lo ejecutado}

CAMBIOS
  [OK] {cambio 1} — {detalle}
  [OK] {cambio 2} — {detalle}

SIGUIENTE
  {que falta o que se recomienda}
```

## Seguridad

- SIEMPRE hacer backup antes de parchear
- SIEMPRE validar sintaxis antes de aplicar
- SIEMPRE correr tests despues de cambios
- SIEMPRE confirmar con el usuario antes de restart
- NUNCA modificar archivos fuera del proyecto SOMER
- NUNCA hacer force restart sin confirmacion explicita
- Los parches a archivos marcan requires_approval=True en el tool registry
