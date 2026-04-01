# TOOLS.md - Notas Locales

Los Skills definen _cómo_ funcionan las herramientas. Este archivo es para _tus_ específicos — lo que es único de tu configuración.

## Qué Va Aquí

Cosas como:

- Nombres de APIs y endpoints frecuentes
- Hosts SSH y aliases
- Voces preferidas para TTS
- Nombres de dispositivos/servicios
- Cualquier cosa específica del entorno

## APIs Configuradas

| API | Variable de Entorno | Estado | Notas |
|-----|---------------------|--------|-------|
| Notion | `NOTION_API_KEY` | | Páginas, bases de datos |
| Telegram | `TELEGRAM_BOT_TOKEN` | | Bot de mensajes |
| GitHub | `GITHUB_TOKEN` | | Repos, issues, PRs |
| Slack | `SLACK_BOT_TOKEN` | | Mensajes, canales |
| Discord | `DISCORD_BOT_TOKEN` | | Bot de Discord |
| OpenWeather | `OPENWEATHER_API_KEY` | | Clima |
| SendGrid | `SENDGRID_API_KEY` | | Emails |

## LLM Providers

| Provider | Variable | Modelos |
|----------|----------|---------|
| Anthropic | `ANTHROPIC_API_KEY` | Claude 3.5/4 |
| OpenAI | `OPENAI_API_KEY` | GPT-4o, o1 |
| DeepSeek | `DEEPSEEK_API_KEY` | DeepSeek V3 |
| Google | `GOOGLE_API_KEY` | Gemini |
| Groq | `GROQ_API_KEY` | Llama, Mixtral |
| xAI | `XAI_API_KEY` | Grok |
| Ollama | (local) | Modelos locales |

## Configuraciones Específicas

### Rutas importantes
- Workspace: `~/.somer/workspace`
- Config: `~/.somer/config.json`
- Credenciales: `~/.somer/credentials/`
- Sesiones: `~/.somer/sessions/`
- Memoria: `~/.somer/memory/`

### Comandos frecuentes
```bash
somer version          # Ver versión
somer doctor check     # Health check
somer config show      # Ver configuración
somer gateway start    # Iniciar gateway
somer channels list    # Listar canales
```

## Por Qué Separado?

Los Skills son compartidos. Tu configuración es tuya. Mantenerlos aparte significa que puedes actualizar skills sin perder tus notas, y compartir skills sin filtrar tu infraestructura.

---

Agrega lo que te ayude a hacer tu trabajo. Esta es tu hoja de trucos.
