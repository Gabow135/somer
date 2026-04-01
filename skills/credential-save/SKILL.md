---
name: credential-save
description: "Detecta y guarda automáticamente API keys, tokens y secretos cuando el usuario los proporciona en la conversación. Use when: (1) el usuario pega o menciona una API key, token o secreto, (2) el usuario quiere configurar credenciales de un servicio, (3) verificar qué credenciales están configuradas, (4) el usuario dice 'mi X es Y' donde X es una credencial. NOT for: rotación de secretos, auditoría de seguridad, ni gestión de CredentialStore cifrado."
homepage: https://github.com/somer-ai/somer
metadata:
  {
    "somer":
      {
        "emoji": "🔑",
        "category": "system",
        "priority": "high",
        "requires": { "bins": ["python3"], "env": [] },
        "auto_detect": true,
      },
  }
---

# Credential Save — Detección y almacenamiento automático de credenciales

Detecta automáticamente API keys, tokens y secretos en los mensajes del usuario y los guarda de forma segura en `~/.somer/.env`.

## Cuándo Usar

USA esta skill cuando:

- El usuario proporciona una API key, token o secreto en su mensaje
- El usuario dice "mi X key es Y", "aquí está mi token: Z", etc.
- El usuario pega credenciales con formato VARIABLE=valor
- El usuario quiere verificar qué credenciales están configuradas
- Un skill reporta credenciales faltantes

NO uses esta skill cuando:

- El usuario pregunta cómo obtener credenciales (mostrar instrucciones en su lugar)
- Auditoría de seguridad o escaneo de vulnerabilidades → usar `security-scanner`
- Gestión de secretos cifrados avanzada → usar CredentialStore directamente

---

## Capacidades de Detección

### 1. Detección por Prefijo Conocido (confianza: alta)

Reconoce automáticamente credenciales por su formato:

| Prefijo | Servicio | Variable |
|---------|----------|----------|
| `sk-ant-` | Anthropic | ANTHROPIC_API_KEY |
| `sk-` | OpenAI | OPENAI_API_KEY |
| `sk-or-` | OpenRouter | OPENROUTER_API_KEY |
| `gsk_` | Groq | GROQ_API_KEY |
| `AIza` | Google | GOOGLE_API_KEY |
| `hf_` | HuggingFace | HUGGINGFACE_API_KEY |
| `xai-` | xAI | XAI_API_KEY |
| `pplx-` | Perplexity | PERPLEXITY_API_KEY |
| `nvapi-` | NVIDIA | NVIDIA_API_KEY |
| `secret_` | Notion | NOTION_API_KEY |
| `ghp_` / `gho_` | GitHub | GITHUB_TOKEN |
| `glpat-` | GitLab | GITLAB_TOKEN |
| `xoxb-` | Slack Bot | SLACK_BOT_TOKEN |
| `xapp-` | Slack App | SLACK_APP_TOKEN |
| `NNN:AAA` | Telegram | TELEGRAM_BOT_TOKEN |

### 2. Detección por Contexto (confianza: media)

Cuando el usuario dice frases como:
- "mi trello api key es abc123"
- "el token de discord es XYZ"
- "notion api key: secret_abc..."

Servicios soportados: Trello, Notion, GitHub, Telegram, Discord, Slack, Anthropic, OpenAI, DeepSeek, Google, Groq, Redis, ElevenLabs, Tavily, Brave.

### 3. Detección Directa (confianza: alta)

Formato explícito variable=valor:
- `TRELLO_API_KEY=abc123def456`
- `TRELLO_TOKEN: abc123def456`

---

## Procedimiento de Detección y Guardado

Cuando detectes credenciales en el mensaje del usuario:

### Paso 1: Escanear

```python
from secrets.detector import CredentialDetector

detector = CredentialDetector()
report = detector.scan(user_message)
```

### Paso 2: Confirmar con el usuario

SIEMPRE confirmar antes de guardar. Mostrar qué se detectó usando TPL-ACTION:

```
ACCION — credential-save | Deteccion de credenciales | {fecha}

RESULTADO
  Estado:     detectado
  Detalle:    {N} credencial(es) encontrada(s) en tu mensaje

DETECTADAS
  [OK] {VARIABLE_1}: {valor_enmascarado} ({servicio}) — nueva
  [OK] {VARIABLE_2}: {valor_enmascarado} ({servicio}) — ya configurada

PENDIENTE
  Confirma para guardar las {N} credenciales nuevas en ~/.somer/.env
```

### Paso 3: Guardar

```python
saved = detector.save_detected(report)
```

### Paso 4: Confirmar guardado

```
ACCION — credential-save | Guardado | {fecha}

RESULTADO
  Estado:     completado
  Detalle:    {N} credencial(es) guardada(s) en ~/.somer/.env

GUARDADAS
  [OK] {VARIABLE_1}: {valor_enmascarado} — guardada
  [OK] {VARIABLE_2}: {valor_enmascarado} — guardada

NOTA: Las credenciales estan disponibles de inmediato para los skills que las requieran.
```

---

## Verificar Credenciales de un Skill

Para verificar si un skill tiene todo lo necesario:

```python
from secrets.detector import CredentialDetector

detector = CredentialDetector()
missing = detector.check_skill_requirements("trello", ["TRELLO_API_KEY", "TRELLO_TOKEN"])
if missing:
    print(f"Faltan: {', '.join(missing)}")
```

---

## Variables de Entorno Conocidas por Servicio

### Proveedores LLM
| Variable | Servicio |
|----------|----------|
| ANTHROPIC_API_KEY | Anthropic (Claude) |
| OPENAI_API_KEY | OpenAI |
| DEEPSEEK_API_KEY | DeepSeek |
| GOOGLE_API_KEY | Google (Gemini) |
| GROQ_API_KEY | Groq |
| MISTRAL_API_KEY | Mistral |
| XAI_API_KEY | xAI (Grok) |
| OPENROUTER_API_KEY | OpenRouter |
| PERPLEXITY_API_KEY | Perplexity |
| NVIDIA_API_KEY | NVIDIA |
| TOGETHER_API_KEY | Together AI |
| HUGGINGFACE_API_KEY | HuggingFace |

### Canales
| Variable | Servicio |
|----------|----------|
| TELEGRAM_BOT_TOKEN | Telegram |
| DISCORD_TOKEN | Discord |
| SLACK_BOT_TOKEN | Slack |
| WHATSAPP_API_TOKEN | WhatsApp |

### Servicios / Integraciones
| Variable | Servicio |
|----------|----------|
| TRELLO_API_KEY | Trello (API Key) |
| TRELLO_TOKEN | Trello (Token OAuth) |
| TRELLO_BOARD_ID | Trello (Board ID, opcional) |
| NOTION_API_KEY | Notion |
| NOTION_DEFAULT_DATABASE | Notion (Database ID) |
| GITHUB_TOKEN | GitHub |
| GITLAB_TOKEN | GitLab |
| TAVILY_API_KEY | Tavily (web search) |
| BRAVE_API_KEY | Brave Search |
| ELEVENLABS_API_KEY | ElevenLabs (TTS) |
| REDIS_URL | Redis |

---

## Formato de Respuesta

Usar **TPL-ACTION** para todas las respuestas de esta skill.

## Seguridad

- Las credenciales se guardan en `~/.somer/.env` con permisos `0600`
- SIEMPRE enmascarar valores al mostrarlos al usuario (usar `mask_secret()`)
- NUNCA loguear valores completos de credenciales
- SIEMPRE confirmar con el usuario antes de guardar
- Si se detecta algo que parece una credencial pero no se esta seguro, preguntar
