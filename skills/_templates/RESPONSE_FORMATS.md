# Plantillas de Respuesta Estandarizadas — SOMER 2.0

Todas las skills DEBEN usar estas plantillas para garantizar consistencia en cada respuesta.
Cada plantilla define la estructura exacta. NO improvisar formatos.

---

## Reglas Generales

1. **Encabezado**: Siempre iniciar con `TIPO — Título | Fecha`
2. **Separadores**: Usar líneas en blanco entre secciones, NO líneas horizontales
3. **Estado**: Usar SIEMPRE estos indicadores:
   - `[OK]` = correcto / aprobado / sin problemas
   - `[!!]` = crítico / requiere acción inmediata
   - `[!]`  = advertencia / atención recomendada
   - `[--]` = no aplica / no verificable
   - `[ ]`  = pendiente / sin completar
   - `[x]`  = completado
4. **Métricas**: Alinear valores con espacios para legibilidad
5. **Listas**: Usar indentación de 2 espacios
6. **Fechas**: Formato `DD/MMM/YYYY` (ej: `26/Mar/2026`)
7. **Montos**: Con separador de miles y 2 decimales (ej: `$12,500.00`)
8. **Porcentajes**: Sin decimales a menos que sea relevante (ej: `65%`)
9. **Idioma**: Español siempre

---

## TPL-TASKS — Tareas (Notion, Trello, etc.)

```
TAREAS — {fuente} | {fecha}

RESUMEN: {total} tareas | {pendientes} pendientes | {vencidas} vencidas

URGENTES / VENCIDAS
  [!!] {tarea} — vence {fecha} | {asignado}
  [!!] {tarea} — vencida {fecha} | {asignado}

HOY
  [ ] {tarea} — {hora o contexto} | {asignado}
  [x] {tarea} — completada | {asignado}

ESTA SEMANA
  [ ] {tarea} — {día} | {asignado}
  [ ] {tarea} — {día} | {asignado}

PRÓXIMAMENTE
  [ ] {tarea} — {fecha} | {asignado}

---
Fuente: {Notion/Trello/etc} | Actualizado: {timestamp}
```

---

## TPL-SECURITY-AUDIT — Auditoría de Seguridad

```
AUDITORÍA DE SEGURIDAD — {dominio} | {fecha}

RESUMEN EJECUTIVO
  Riesgo global:  {0-10}/10 — {CRÍTICO|ALTO|MEDIO|BAJO|OK}
  Hallazgos:      {n} críticos | {n} altos | {n} medios | {n} bajos | {n} info

TOP 3 CRÍTICOS
  1. {hallazgo} — {impacto breve}
  2. {hallazgo} — {impacto breve}
  3. {hallazgo} — {impacto breve}

HALLAZGOS DETALLADOS

  [{OK|!!|!|--}] {ID} {nombre del check}
    Severidad:    {CRITICAL|HIGH|MEDIUM|LOW|INFO}
    Hallazgo:     {descripción concisa}
    Impacto:      {qué puede pasar}
    Remediación:  {pasos concretos}
    Código:
      nginx:   {snippet}
      apache:  {snippet}

  [{OK|!!|!|--}] {ID} {nombre del check}
    ...

EVIDENCIA DE EXPLOITS (si aplica)
  {ID} — {qué se demostró}
    Resultado: {datos/screenshot ref}
    Impacto:   {impacto real demostrado}

ACCIONES PRIORITARIAS
  1. {acción inmediata}
  2. {acción a corto plazo}
  3. {acción a mediano plazo}

---
Escaneado por: SOMER Security | Método: {rápido|completo|pentest}
```

---

## TPL-COMPLIANCE — Verificación de Cumplimiento

```
COMPLIANCE — {dominio} | {estándar} | {fecha}

RESULTADO: {score}/{total} verificables = {porcentaje}% | Riesgo: {CRÍTICO|ALTO|MEDIO|BAJO|OK}

CHECKS
  [{OK|!!|!|--}] {código} {nombre}
  [{OK|!!|!|--}] {código} {nombre} — {detalle si WARN/FAIL}
  [{OK|!!|!|--}] {código} {nombre}
  ...

HALLAZGOS RELEVANTES
  {código}: {explicación y remediación}
  {código}: {explicación y remediación}

---
Estándar: {OWASP Top 10 2021|PCI-DSS v4.0|GDPR|ISO 27001} | Verificado por: SOMER Compliance
```

---

## TPL-PENTEST — Pentest Completo

```
PENTEST — {dominio} | Scope: {full|quick|recon-only} | {fecha}

RESUMEN EJECUTIVO
  Riesgo global:     {0-10}/10
  Vulnerabilidades:  {n} críticas | {n} altas | {n} medias | {n} bajas
  Exploits exitosos: {n}/{total intentados}

FASES COMPLETADAS
  [x] Planificación
  [x] Reconocimiento — {n} hallazgos
  [x] Escaneo — {n} vulnerabilidades
  [x] Explotación — {n} exploits exitosos
  [x] Evidencia — {n} capturas
  [x] Reporte

TOP 5 HALLAZGOS
  1. [{!!|!}] {hallazgo} — {severidad} — {explotable: Sí/No}
     Impacto: {descripción}
     Remediación: {pasos}

  2. [{!!|!}] {hallazgo} — {severidad} — {explotable: Sí/No}
     ...

TECNOLOGÍAS DETECTADAS
  Servidor:    {tech}
  Framework:   {tech}
  CDN/WAF:     {tech}
  CMS:         {tech}

EVIDENCIA
  {exploit_id}: {descripción} — {resultado}
  {exploit_id}: {descripción} — {resultado}

ACCIONES PRIORITARIAS
  1. {acción inmediata}
  2. {acción a corto plazo}
  3. {acción a mediano plazo}

---
Workspace: {ruta} | Método: SOMER Pentest | Scope: {scope}
```

---

## TPL-FINANCIAL — Resumen Financiero

```
FINANZAS — {período} | {fecha}

BALANCE
  Ingresos:   ${monto}
  Gastos:     ${monto}
  Balance:    {+/-}${monto}

TOP GASTOS
  1. {categoría}:  ${monto}  ({porcentaje}%)
  2. {categoría}:  ${monto}  ({porcentaje}%)
  3. {categoría}:  ${monto}  ({porcentaje}%)

TOP INGRESOS
  1. {fuente}:     ${monto}  ({porcentaje}%)
  2. {fuente}:     ${monto}  ({porcentaje}%)
  3. {fuente}:     ${monto}  ({porcentaje}%)

DEUDAS
  A favor:    ${monto} ({n} pendientes)
  En contra:  ${monto} ({n} pendientes)

PRESUPUESTOS
  [{OK|!|!!}] {categoría}: ${usado}/${límite} ({porcentaje}%)
  [{OK|!|!!}] {categoría}: ${usado}/${límite} ({porcentaje}%)

---
Fuente: SOMER Finance | DB: ~/.somer/finance.db
```

---

## TPL-BRIEFING — Briefing Diario

```
BRIEFING — {fecha}

CLIMA
  {ciudad}: {temp}°C, {condición}
  Máx {temp}° / Mín {temp}°

AGENDA ({n} eventos)
  {hora} — {evento} ({lugar/medio})
  {hora} — {evento} ({lugar/medio})

SEGUIMIENTOS CRM ({n} pendientes)
  [!!] {contacto} ({empresa}) — {acción} (vencido {fecha})
  [ ] {contacto} ({empresa}) — {acción} ({fecha})

TAREAS ({n} pendientes)
  [ ] {tarea} — {fecha}
  [ ] {tarea} — {fecha}
  [x] {tarea} — completada

FINANZAS
  Ayer: +${ingresos} / -${gastos}
  Mes:  {+/-}${balance}
  [!] {alerta de presupuesto si aplica}

SERVIDORES ({n} monitoreados)
  [{OK|!|!!}] {host} — {status} ({latencia})
  [{OK|!|!!}] {host} — {status} ({detalle})

---
Generado: {timestamp} | Canal: {canal}
```

---

## TPL-CRM — Contacto / Seguimiento

```
CRM — {operación} | {fecha}

CONTACTO
  Nombre:       {nombre completo}
  Empresa:      {empresa}
  Email:        {email}
  Teléfono:     {teléfono}
  Tags:         {#tag1 #tag2}
  Pipeline:     {etapa}

SEGUIMIENTO
  Próximo:      {fecha} — {acción}
  Prioridad:    {alta|media|baja}

HISTORIAL ({n} interacciones)
  {fecha} — {tipo}: {resumen}
  {fecha} — {tipo}: {resumen}

---
Fuente: SOMER CRM | DB: ~/.somer/crm.db
```

---

## TPL-MEETING — Minuta de Reunión

```
MINUTA — {título/contacto} | {fecha}

DATOS
  Asistentes:   {nombres}
  Duración:     ~{n} min

TEMAS
  1. {tema}
  2. {tema}

ACUERDOS
  - {acuerdo con detalle}
  - {acuerdo con detalle}

ACTION ITEMS
  [ ] {acción} — {responsable} ({fecha límite})
  [ ] {acción} — {responsable} ({fecha límite})
  [ ] {acción} — {responsable} ({fecha límite})

PRÓXIMA REUNIÓN: {fecha} {hora} ({medio})

DISPATCH
  [x] {n} tareas creadas en Trello
  [x] Interacción registrada en CRM ({empresa})
  [x] Próxima reunión agendada en Calendar
  [x] ${monto} registrado en Finance

---
Procesado por: SOMER Meeting Notes
```

---

## TPL-NETWORK — Monitoreo de Red

```
MONITOREO — {host} | {fecha}

ESTADO GENERAL: {OK|WARN|CRITICAL|DOWN}

CHECKS
  [{OK|!|!!}] Ping:    {latencia} avg, {packet_loss}% loss
  [{OK|!|!!}] HTTP:    {status_code} ({ttfb} TTFB)
  [{OK|!|!!}] SSL:     {estado}, expira en {n} días ({emisor})
  [{OK|!|!!}] DNS:     {estado}, {n} NS, {registros presentes}

ALERTAS (si aplica)
  [!!] {alerta con detalle}
  [!]  {advertencia con detalle}

---
Verificado por: SOMER Network Monitor
```

---

## TPL-REPORT — Confirmación de Reporte Generado

```
REPORTE GENERADO — {título} | {fecha}

  Formato:    {PDF|Excel|Markdown}
  Secciones:  {n}
  Tamaño:     {tamaño}

El archivo se envía automáticamente por este canal.

---
Generado por: SOMER Reports | Ruta: {file_path}
```

---

## TPL-RECON — Reconocimiento de Seguridad

```
RECONOCIMIENTO — {dominio} | {fecha}

SUPERFICIE DE ATAQUE
  Tecnologías:   {servidor}, {framework}, {CMS}, {lenguaje}
  CDN/WAF:       {detectado o "No detectado"}
  IPs:           {lista de IPs}

SUBDOMINIOS ({n} encontrados)
  {subdominio} — {IP} — {status HTTP}
  {subdominio} — {IP} — {status HTTP}

PUERTOS ABIERTOS ({n})
  {puerto}/tcp — {servicio} — {versión}
  {puerto}/tcp — {servicio} — {versión}

DNS
  A:      {registros}
  MX:     {registros}
  NS:     {registros}
  TXT:    {registros relevantes}

OBSERVACIONES
  [!] {hallazgo relevante}
  [!] {hallazgo relevante}

---
Reconocimiento por: SOMER Recon | Método: pasivo
```

---

## TPL-EXPLOIT — Evidencia de Exploits

```
EXPLOITS — {dominio} | {fecha}

RESUMEN: {n} exitosos / {n} intentados

RESULTADOS
  [{OK|!!}] {exploit_id} — {nombre}
    Estado:    {Exitoso|Fallido|Parcial}
    PoC:       {descripción de lo ejecutado}
    Evidencia: {screenshot ref / datos capturados}
    Impacto:   {impacto real demostrado}

  [{OK|!!}] {exploit_id} — {nombre}
    ...

ARCHIVOS GENERADOS
  {ruta/archivo} — {descripción}
  {ruta/archivo} — {descripción}

---
Ejecutado por: SOMER Exploits | Workspace: {ruta}
```

---

## TPL-EVIDENCE — Paquete de Evidencia

```
EVIDENCIA — {dominio} | {fecha}

PAQUETE
  Capturas:     {n} screenshots
  Logs HTTP:    {n} request/response
  Datos:        {n} archivos (redactados)
  Cadena:       {n} pasos documentados

CADENA DE EVIDENCIA
  1. {paso} — {resultado}
  2. {paso} — {resultado}
  3. {paso} — {resultado}

EXPORTADO
  ZIP: {ruta al archivo .zip}
  Tamaño: {tamaño}

---
Capturado por: SOMER Evidence | Workspace: {ruta}
```

---

## TPL-OSINT — Investigación OSINT

```
OSINT — {target} | {fecha}

EXPOSICIÓN: {Bajo|Medio|Alto|Crítico}

BRECHAS DE DATOS ({n} encontradas)
  [!!] {email} — {fuente del breach} ({fecha})
  [!!] {email} — {fuente del breach} ({fecha})

SERVICIOS EXPUESTOS ({n})
  {IP}:{puerto} — {servicio} — {banner}
  {IP}:{puerto} — {servicio} — {banner}

PERFILES ENCONTRADOS ({n})
  {plataforma}: {URL}
  {plataforma}: {URL}

DATOS CORPORATIVOS
  Dominio:     {dominio}
  Registrante: {info}
  Empleados:   {n} perfiles públicos
  Tecnologías: {stack detectado}

RECOMENDACIONES
  1. {acción}
  2. {acción}

---
Investigado por: SOMER OSINT | Fuentes: {fuentes usadas}
```

---

## TPL-MALWARE — Análisis de Malware

```
ANÁLISIS DE ARCHIVO — {nombre_archivo} | {fecha}

METADATOS
  Tamaño:   {tamaño}
  Tipo:     {tipo MIME}
  SHA256:   {hash}

DETECCIONES ({n}/{total} motores)
  [!!] {motor}: {detección}
  [!!] {motor}: {detección}
  [OK] {motor}: Limpio

STRINGS SOSPECHOSOS ({n})
  URLs:     {lista}
  IPs:      {lista}
  Otros:    {datos relevantes}

IoCs EXTRAÍDOS
  {tipo}: {valor}
  {tipo}: {valor}

VEREDICTO: {LIMPIO|SOSPECHOSO|MALICIOSO} — {explicación breve}

---
Analizado por: SOMER Malware Analyzer | Método: estático
```

---

## TPL-DEVOPS — Operaciones Git / Issues / PRs

```
DEVOPS — {operación} | {fecha}

  {qué se hizo} → {resultado}
  URL: {url si aplica}

ITEMS (solo si es listado)
  [{OK|!|!!| }] #{número} {título} — {estado}
  [{OK|!|!!| }] #{número} {título} — {estado}

---
Fuente: {GitHub|Bitbucket|Trello} | {repo o board}
```

---

## TPL-REMINDERS — Recordatorios

```
RECORDATORIOS — {fuente} | {fecha}

RESUMEN: {total} | {pendientes} pendientes | {vencidos} vencidos

VENCIDOS
  [!!] {recordatorio} — vencido {fecha} | {lista}

HOY
  [ ] {recordatorio} — {hora} | {lista}
  [x] {recordatorio} — completado | {lista}

PRÓXIMOS
  [ ] {recordatorio} — {fecha} | {lista}
  [ ] {recordatorio} — {fecha} | {lista}

---
Fuente: {Apple Reminders|Things 3} | Actualizado: {timestamp}
```

---

## TPL-BOOKMARKS — Links Guardados

```
BOOKMARKS — {operación} | {fecha}

GUARDADO (si es nuevo)
  Título:     {título}
  URL:        {url}
  Categoría:  {categoría}
  Tags:       {#tag1 #tag2}
  Resumen:    {descripción breve}

BÚSQUEDA (si es consulta): "{query}" — {n} resultados
  1. {título} ({categoría})
     {url} — {fecha guardado}
  2. {título} ({categoría})
     {url} — {fecha guardado}

---
Fuente: SOMER Bookmarks
```

---

## TPL-CALENDAR — Eventos de Calendario

```
CALENDARIO — {operación} | {fecha}

EVENTO (si es individual)
  Título:     {título}
  Fecha:      {fecha} {hora inicio} - {hora fin}
  Ubicación:  {lugar o enlace}
  Asistentes: {nombres}
  Estado:     {confirmado|tentativo|cancelado}

AGENDA (si es listado): {período}
  {hora} — {título} ({duración}) | {ubicación}
  {hora} — {título} ({duración}) | {ubicación}
  {hora} — {título} ({duración}) | {ubicación}

DISPONIBILIDAD (si es consulta)
  [OK] {hora} - {hora} — Libre
  [!!] {hora} - {hora} — Ocupado: {evento}
  [OK] {hora} - {hora} — Libre

---
Fuente: {Google Calendar|Apple Calendar}
```

---

## TPL-DRIVE — Archivos / Drive

```
ARCHIVOS — {operación} | {fecha}

RESULTADO
  Archivo:    {nombre}
  Ruta:       {ruta o URL}
  Tamaño:     {tamaño}
  Tipo:       {tipo}
  Acción:     {subido|descargado|compartido|movido|eliminado}

LISTADO (si es búsqueda/lista)
  {nombre} — {tamaño} — {última modificación} — {compartido con}
  {nombre} — {tamaño} — {última modificación} — {compartido con}

---
Fuente: {Google Drive|Local}
```

---

## TPL-MESSAGE — Mensajes Enviados/Recibidos

```
MENSAJE — {plataforma} | {operación} | {fecha}

RESULTADO
  Destino:    {contacto/canal/grupo}
  Tipo:       {texto|archivo|imagen|audio|reacción}
  Estado:     {enviado|entregado|leído|error}
  Contenido:  {resumen breve si aplica}

CONVERSACIÓN (si es lectura)
  [{hora}] {remitente}: {mensaje}
  [{hora}] {remitente}: {mensaje}
  [{hora}] {remitente}: {mensaje}

---
Fuente: {Slack|Discord|iMessage|WhatsApp|BlueBubbles}
```

---

## TPL-EMAIL — Correo Electrónico

```
EMAIL — {operación} | {fecha}

ENVIADO (si se envió)
  Para:       {destinatarios}
  Asunto:     {asunto}
  CC:         {cc}
  Adjuntos:   {n} archivos
  Estado:     Enviado

BANDEJA (si es lectura): {carpeta} — {n} mensajes
  [{OK|!|!!}] {remitente} — {asunto} — {fecha} {leído/no leído}
  [{OK|!|!!}] {remitente} — {asunto} — {fecha} {leído/no leído}

MENSAJE (si es lectura individual)
  De:         {remitente}
  Asunto:     {asunto}
  Fecha:      {fecha}
  Adjuntos:   {lista}
  ---
  {resumen del contenido}

---
Fuente: {Himalaya|Gmail}
```

---

## TPL-NOTES — Notas

```
NOTAS — {operación} | {fuente} | {fecha}

NOTA (si es individual)
  Título:     {título}
  Carpeta:    {carpeta/vault}
  Tags:       {#tag1 #tag2}
  Creada:     {fecha}
  Modificada: {fecha}
  ---
  {contenido o resumen}

BÚSQUEDA (si es consulta): "{query}" — {n} resultados
  1. {título} — {carpeta} — {fecha}
  2. {título} — {carpeta} — {fecha}

CREADA/ACTUALIZADA (si es acción)
  Título:     {título}
  Carpeta:    {carpeta}
  Acción:     {creada|actualizada|movida|eliminada}

---
Fuente: {Obsidian|Bear|Apple Notes}
```

---

## TPL-SUMMARY — Resumen de Contenido

```
RESUMEN — {tipo de fuente} | {fecha}

FUENTE
  Tipo:       {URL|PDF|Archivo|YouTube}
  Título:     {título}
  Autor:      {autor si disponible}
  Tamaño:     {duración/páginas/palabras}

RESUMEN
  {resumen estructurado del contenido}

PUNTOS CLAVE
  1. {punto clave}
  2. {punto clave}
  3. {punto clave}

---
Resumido por: SOMER Summarize
```

---

## TPL-MEDIA — Operaciones de Media

```
MEDIA — {operación} | {fecha}

RESULTADO
  Tipo:       {imagen|audio|video|screenshot|GIF|transcripción}
  Archivo:    {nombre o ruta}
  Formato:    {formato}
  Tamaño:     {tamaño}
  Duración:   {duración si aplica}

DETALLES (según tipo)
  {detalles específicos: prompt usado, modelo, resolución, idioma detectado, etc.}

TRANSCRIPCIÓN (si aplica)
  Idioma:     {idioma detectado}
  Duración:   {duración}
  ---
  {texto transcrito}

---
Procesado por: SOMER Media | Herramienta: {whisper|dall-e|ffmpeg|etc}
```

---

## TPL-WEATHER — Clima

```
CLIMA — {ciudad} | {fecha}

ACTUAL
  Temperatura:  {temp}°C (sensación {temp}°C)
  Condición:    {condición}
  Humedad:      {humedad}%
  Viento:       {velocidad} km/h {dirección}

PRONÓSTICO
  Hoy:    Máx {temp}° / Mín {temp}° — {condición}
  Mañana: Máx {temp}° / Mín {temp}° — {condición}
  {día}:  Máx {temp}° / Mín {temp}° — {condición}

ALERTAS (si aplica)
  [!] {alerta meteorológica}

---
Fuente: {wttr.in|Open-Meteo}
```

---

## TPL-PLACES — Lugares

```
LUGARES — "{búsqueda}" | {fecha}

RESULTADOS ({n})
  1. {nombre} — {rating}/5 ({n} reseñas)
     Dirección:  {dirección}
     Teléfono:   {teléfono}
     Horario:    {abierto/cerrado} — {horario hoy}
     Categoría:  {tipo}

  2. {nombre} — {rating}/5 ({n} reseñas)
     Dirección:  {dirección}
     ...

---
Fuente: Google Places
```

---

## TPL-IOT — Dispositivos Inteligentes

```
DISPOSITIVO — {operación} | {fecha}

RESULTADO
  Dispositivo:  {nombre}
  Tipo:         {luz|bocina|termostato|sensor}
  Ubicación:    {habitación/zona}
  Estado:       {encendido|apagado|reproduciendo|etc}
  Acción:       {descripción de lo ejecutado}

LISTADO (si es consulta de estado)
  [{OK|!}] {nombre} ({ubicación}) — {estado} | {detalle}
  [{OK|!}] {nombre} ({ubicación}) — {estado} | {detalle}

---
Fuente: {OpenHue|Sonos|Eight Sleep|Bluesound}
```

---

## TPL-STATUS — Estado del Sistema

```
ESTADO — {servicio} | {fecha}

ESTADO GENERAL: {OK|WARN|CRITICAL|DOWN}

CHECKS
  [{OK|!|!!}] {componente}: {estado} — {detalle}
  [{OK|!|!!}] {componente}: {estado} — {detalle}
  [{OK|!|!!}] {componente}: {estado} — {detalle}

MÉTRICAS (si aplica)
  {métrica}:  {valor}
  {métrica}:  {valor}

ALERTAS (si aplica)
  [!!] {alerta con detalle}
  [!]  {advertencia con detalle}

---
Verificado por: SOMER | Servicio: {nombre}
```

---

## TPL-CRON — Gestión de Cron

```
CRON — {operación} | {fecha}

RESULTADO
  Job:        {nombre}
  Schedule:   {expresión cron} ({descripción legible})
  Comando:    {comando}
  Estado:     {activo|pausado|eliminado|ejecutado}
  Próxima:    {fecha próxima ejecución}

LISTADO (si es lista)
  [{OK|!}] {nombre} — {schedule} — {estado} | Última: {fecha} {resultado}
  [{OK|!}] {nombre} — {schedule} — {estado} | Última: {fecha} {resultado}

HISTORIAL (si es history)
  {fecha} — {estado} — {duración} — {resultado}
  {fecha} — {estado} — {duración} — {resultado}

---
Fuente: SOMER Cron Scheduler
```

---

## TPL-FEEDS — RSS / Blogs

```
FEEDS — {operación} | {fecha}

ACTUALIZACIONES ({n} nuevas)
  1. [{fuente}] {título}
     {url} — {fecha publicación}
     {resumen breve}

  2. [{fuente}] {título}
     {url} — {fecha publicación}
     {resumen breve}

FUENTES MONITOREADAS ({n})
  [{OK|!}] {nombre} — {url} — Última: {fecha}
  [{OK|!}] {nombre} — {url} — Última: {fecha}

---
Fuente: SOMER BlogWatcher
```

---

## TPL-ACTION — Confirmación de Acción Genérica

```
ACCIÓN — {skill} | {operación} | {fecha}

RESULTADO
  Estado:     {completado|error|parcial}
  Detalle:    {descripción de lo ejecutado}

SALIDA (si hay output relevante)
  {output formateado}

---
Ejecutado por: SOMER {skill}
```

---

## TPL-MUSIC — Música / Audio

```
MÚSICA — {operación} | {fecha}

REPRODUCIENDO (si es playback)
  Canción:    {título}
  Artista:    {artista}
  Álbum:      {álbum}
  Duración:   {duración}
  Dispositivo: {dispositivo}

BÚSQUEDA (si es search): "{query}" — {n} resultados
  1. {título} — {artista} — {álbum} ({duración})
  2. {título} — {artista} — {álbum} ({duración})

COLA (si es queue)
  > {título} — {artista} (reproduciendo)
  1. {título} — {artista}
  2. {título} — {artista}

---
Fuente: {Spotify|Sonos|Bluesound}
```

---

## TPL-COST — Uso y Costos de Modelos

```
USO DE MODELOS — {período} | {fecha}

RESUMEN
  Costo total:  ${monto}
  Tokens:       {total} ({input} in / {output} out)
  Sesiones:     {n}

POR MODELO
  {modelo}: ${costo} — {tokens} tokens — {n} sesiones
  {modelo}: ${costo} — {tokens} tokens — {n} sesiones

---
Fuente: SOMER Model Usage
```

---

## TPL-SOCIAL — Redes Sociales

```
SOCIAL — {plataforma} | {operación} | {fecha}

RESULTADO
  Acción:     {publicado|buscado|seguido|DM enviado}
  Contenido:  {resumen}
  URL:        {url si aplica}
  Engagement: {likes|retweets|replies si aplica}

BÚSQUEDA (si es consulta): "{query}" — {n} resultados
  1. @{usuario}: {contenido} — {fecha} | {engagement}
  2. @{usuario}: {contenido} — {fecha} | {engagement}

---
Fuente: {X/Twitter|LinkedIn|etc}
```

---

## TPL-ORDERS — Pedidos / Tracking

```
PEDIDOS — {operación} | {fecha}

PEDIDO
  Tienda:     {tienda}
  Número:     #{número}
  Estado:     {pendiente|en camino|entregado}
  Fecha:      {fecha pedido}
  Entrega:    {fecha estimada}

HISTORIAL (si es lista)
  [{OK|!| }] #{número} — {tienda} — {estado} — {fecha}
  [{OK|!| }] #{número} — {tienda} — {estado} — {fecha}

---
Fuente: {OrderCLI|Foodora}
```

---

## Notas de Implementación

- Cada skill DEBE referenciar su plantilla TPL-* correspondiente en la sección "Formato de Respuesta"
- Si una sección no tiene datos, OMITIRLA (no mostrar secciones vacías)
- Si hay múltiples resultados del mismo tipo (ej: varios hosts), repetir el bloque por cada uno
- El pie de página (`---` + metadata) es OBLIGATORIO en toda respuesta
- Cuando se genera un PDF/reporte, el contenido interno del documento DEBE seguir la misma plantilla
