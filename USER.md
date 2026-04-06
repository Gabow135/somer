# USER.md - Sobre Tu Humano

_Aprende sobre la persona a la que ayudas. Actualiza esto conforme avances._

- **Nombre:** Gabriel
- **Cómo llamarle:** Gabriel / Gabo
- **Pronombres:** él
- **Timezone:** America/Bogota (UTC-5)
- **Idioma preferido:** Español
- **Telegram ID:** 881607309
- **WhatsApp:** +593995466833
- **Username:** Gabow135

## Contexto

Gabriel es desarrollador/emprendedor basado en Ecuador/Colombia. Usa SOMER como su asistente principal para gestión de proyectos, desarrollo y operaciones diarias.

### Proyectos activos
- **Multi-repo workflow**: 14 repositorios + 5 boards de Trello conectados via KG. Workflow automatizado: repo + descripción → tarjeta Trello + rama Bitbucket
- **SOMER 2.0**: El propio sistema que usa, contribuye activamente a mejorarlo
- **Vehículo**: Carro que lleva a mantenimiento en AMBACAR (próxima cita: 06/Abr/2026)

### Preferencias detectadas
- Canal principal: **Telegram** (es donde más interactúa)
- Quiere briefing diario a las **7:00 AM** por Telegram y WhatsApp
- Prefiere respuestas directas y concisas, no relleno
- Le interesa mejorar y optimizar sus herramientas constantemente
- Usa Bitbucket (no GitHub) para sus repos principales
- Trabaja con Trello para gestión de tareas

### Configuración técnica
- WhatsApp Business API: funcional pero requiere ventana de 24h
- Google Calendar: OAuth no funciona desde Telegram, usar links directos o configurar gog CLI
- Briefing cron: configurado en `/var/www/somer/briefing.sh` a las 7 AM

### Cosas que le gustan
- Automatización — si algo se puede automatizar, lo quiere automatizado
- Que SOMER aprenda y mejore por sí mismo
- Respuestas rápidas y accionables

### Cosas que le molestan
- Perder contexto entre sesiones
- Tener que repetir información que ya dio
- Herramientas que no funcionan (OAuth, APIs sin configurar)

## Historial de interacciones

_(Aprendizajes clave de conversaciones pasadas)_

- **03/Abr/2026**: Configuró briefing diario por cron. WhatsApp envía OK pero ventana de 24h puede bloquear. Telegram funciona perfecto.
- **02/Abr/2026**: Necesitó agendar mantenimiento AMBACAR para 06/Abr. Google Calendar OAuth falló desde Telegram — se resolvió con link directo.
- **Sesiones anteriores**: Configuró multi-repo workflow con 14 repos y 5 boards. KG tiene entidades de repos y workspaces.

## Lecciones aprendidas (errores a no repetir)

- **Google Calendar desde Telegram**: OAuth no funciona. Usar link directo de Google Calendar o configurar gog CLI.
- **WhatsApp Business API**: Requiere que el usuario haya escrito al bot en las últimas 24h. Si no, los mensajes no llegan aunque la API responda 200.
- **Briefing**: El cron está en `/var/www/somer/briefing.sh`. Si falla, revisar permisos y que source .env cargue las API keys.

---

Entre más sepas, mejor podrás ayudar. Pero recuerda — estás aprendiendo sobre una persona, no construyendo un dossier. Respeta la diferencia.
