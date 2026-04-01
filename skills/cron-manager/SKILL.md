---
name: cron-manager
description: "Gestión de tareas cron programadas — crear, editar, listar y eliminar jobs en crontab del sistema. Usar cuando el usuario pida programar tareas automáticas, ejecutar skills periódicamente, configurar briefings diarios, o cualquier acción recurrente con cron. Triggers: programar tarea, crear cron, agendar ejecución, crontab, ejecutar cada día, ejecutar cada hora, schedule, timer, tarea programada, automatizar."
---

# Skill: Cron Manager

Gestión de tareas programadas via crontab del sistema operativo.

## Reglas Críticas

1. **NUNCA usar `somer exec`** — ese comando NO existe.
2. **NUNCA usar `/usr/local/bin/somer`** directamente — requiere estar en el directorio del proyecto.
3. **SIEMPRE usar la ruta completa del virtualenv** con `cd` al directorio del proyecto.
4. **SIEMPRE cargar variables de entorno** desde `.env` antes de ejecutar.

## Comando Correcto

El formato EXACTO para ejecutar Somer desde crontab es:

```
cd /var/www/somer && source .env 2>/dev/null; /var/www/somer/venv/bin/python3 entry.py agent run "MENSAJE"
```

### Desglose

| Parte | Propósito |
|-------|-----------|
| `cd /var/www/somer` | Posicionar en el directorio del proyecto (requerido para imports) |
| `source .env 2>/dev/null;` | Cargar API keys y variables de entorno |
| `/var/www/somer/venv/bin/python3` | Python del virtualenv con todas las dependencias |
| `entry.py agent run "MENSAJE"` | Entry point real del CLI |

## Cómo Crear un Cron Job

### Paso 1 — Editar crontab

```bash
crontab -e
```

### Paso 2 — Agregar la línea con el formato correcto

**Briefing diario a las 7 AM (lunes a viernes):**
```
0 7 * * 1-5 cd /var/www/somer && source .env 2>/dev/null; /var/www/somer/venv/bin/python3 entry.py agent run "Dame mi briefing del día" >> /var/www/somer/logs/cron.log 2>&1
```

**Reporte financiero semanal (lunes 9 AM):**
```
0 9 * * 1 cd /var/www/somer && source .env 2>/dev/null; /var/www/somer/venv/bin/python3 entry.py agent run "Genera reporte financiero semanal" >> /var/www/somer/logs/cron.log 2>&1
```

**Monitor de servidores cada 30 minutos:**
```
*/30 * * * * cd /var/www/somer && source .env 2>/dev/null; /var/www/somer/venv/bin/python3 entry.py agent run "Revisa el estado de los servidores" >> /var/www/somer/logs/cron.log 2>&1
```

**Recordatorio diario a las 8 PM:**
```
0 20 * * * cd /var/www/somer && source .env 2>/dev/null; /var/www/somer/venv/bin/python3 entry.py agent run "Dame mis pendientes para mañana" >> /var/www/somer/logs/cron.log 2>&1
```

## Enviar Resultado a un Canal

Para que la salida vaya a Telegram u otro canal, incluirlo en el mensaje:

```
0 7 * * 1-5 cd /var/www/somer && source .env 2>/dev/null; /var/www/somer/venv/bin/python3 entry.py agent run "Dame mi briefing del día y envíalo por telegram" >> /var/www/somer/logs/cron.log 2>&1
```

## Expresiones Cron Comunes

| Expresión | Significado |
|-----------|-------------|
| `0 7 * * *` | Todos los días a las 7:00 AM |
| `0 7 * * 1-5` | Lunes a viernes a las 7:00 AM |
| `*/30 * * * *` | Cada 30 minutos |
| `0 */2 * * *` | Cada 2 horas |
| `0 9 * * 1` | Lunes a las 9:00 AM |
| `0 0 1 * *` | Primer día del mes a medianoche |
| `0 8,13,18 * * *` | A las 8, 13 y 18 horas |

## Gestión de Cron Jobs

**Listar jobs actuales:**
```bash
crontab -l
```

**Editar jobs:**
```bash
crontab -e
```

**Eliminar un job:** editar con `crontab -e` y borrar la línea.

**Eliminar TODOS los jobs (peligroso):**
```bash
crontab -r
```

## Diagnóstico

Si un cron no funciona, verificar:

1. **Logs:** `tail -f /var/www/somer/logs/cron.log`
2. **Variables de entorno:** `cd /var/www/somer && cat .env | grep API_KEY`
3. **Ejecución manual:** correr el comando completo en la terminal para ver errores
4. **Permisos:** `ls -la /var/www/somer/venv/bin/python3`
5. **Timezone:** `timedatectl` — crontab usa la zona horaria del sistema

## Errores Comunes

| Error | Causa | Solución |
|-------|-------|----------|
| `ModuleNotFoundError: No module named 'entry'` | No se hizo `cd` al directorio del proyecto | Agregar `cd /var/www/somer &&` al inicio |
| `No hay providers disponibles` | API keys no cargadas | Agregar `source .env 2>/dev/null;` |
| `command not found: somer` | Ejecutable no está en PATH | Usar ruta completa del venv |
| Sin salida ni error | Cron no está corriendo | Verificar con `crontab -l` y revisar logs del sistema `grep CRON /var/log/syslog` |

## Formato de Respuesta

**Usar plantilla `TPL-CRON`** de `_templates/RESPONSE_FORMATS.md`. Ejemplo:

```
CRON — Job creado | 26/Mar/2026

RESULTADO
  Job:        briefing-matutino
  Schedule:   0 7 * * 1-5 (Lunes a Viernes 7:00 AM)
  Comando:    cd /var/www/somer && source .env 2>/dev/null; /var/www/somer/venv/bin/python3 entry.py agent run "Genera mi briefing del día"
  Estado:     Activo
  Próxima:    27/Mar/2026 07:00

---
Fuente: SOMER Cron Scheduler
```

Ejemplo listado:
```
CRON — Lista de jobs | 26/Mar/2026

LISTADO
  [OK] briefing-matutino — 0 7 * * 1-5 — Activo | Última: 26/Mar/2026 07:00 OK
  [OK] monitor-servers — */30 * * * * — Activo | Última: 26/Mar/2026 09:30 OK
  [!]  reporte-semanal — 0 9 * * 1 — Activo | Última: 24/Mar/2026 09:00 ERROR

---
Fuente: SOMER Cron Scheduler
```
