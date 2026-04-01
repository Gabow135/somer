# SOMER 2.0

**System for Optimized Modular Execution & Reasoning**

---

## Descripcion

SOMER 2.0 es un motor cognitivo modular en Python, inspirado en la arquitectura de OpenClaw. Provee un gateway WebSocket, soporte multi-provider LLM, memoria hibrida (BM25 + vector), plugins de canal (Telegram/Slack/Discord) y un sistema de skills basado en SKILL.md.

```
Python 3.9+ | Build: hatchling | CLI: typer + rich
```

## Caracteristicas

- **21 Providers LLM** - Anthropic, OpenAI, DeepSeek, Google, Ollama, Bedrock y mas
- **15 Canales** - Telegram, Slack, Discord y otros plugins de comunicacion
- **Memoria Hibrida** - BM25 + vector con temporal decay, MMR reranking y categorias evergreen
- **7 Providers de Embeddings** - OpenAI, Gemini, Voyage, Mistral, SentenceTransformers, Ollama, Dummy + auto-seleccion y fallback
- **52 Skills** - Sistema SKILL.md con loader, registro y validacion
- **Gateway WebSocket** - JSON-RPC 2.0 en `ws://127.0.0.1:18789`
- **Routing 7 Niveles** - peer, parent, guild+roles, guild, team, account, channel, default
- **Cron Avanzado** - Jitter, overlap, timezone, retry, alertas de fallo
- **Secretos Cifrados** - Fernet store, SecretRef (env/file/exec/keychain)
- **Multi-Agente** - Runner, fallback de modelos, compactacion, sub-agentes

## Inicio Rapido

### Requisitos

- Python 3.9+
- SQLite (incluido)

### Instalacion

```bash
# Clonar repositorio
git clone <repo-url>
cd Somer

# Instalacion de desarrollo
pip install -e ".[dev]"

# Instalacion completa con todos los extras
pip install -e ".[all]"
```

### Configuracion

```bash
# Crear configuracion por defecto
somer config init

# Verificar salud del sistema
somer doctor check

# Mostrar configuracion actual
somer config show
```

### Uso Basico

```bash
# Iniciar gateway WebSocket
somer gateway start

# Enviar mensaje al agente
somer agent run "Hola, SOMER"

# Listar canales configurados
somer channels list

# Ver version
somer version
```

### Uso desde Python

```python
from agents.runner import AgentRunner
from memory import MemoryManager, create_embedding_provider

# Crear provider de embeddings con auto-seleccion
embeddings = create_embedding_provider("auto")

# Crear memory manager
memory = MemoryManager(embedding_provider=embeddings)

# Almacenar y buscar
await memory.store("Python es un lenguaje de programacion")
results = await memory.search("lenguaje programacion")
```

## Arquitectura

### Flujo de Ejecucion

```
Mensaje → Canal → Session Router → Context Engine → Agent Runner → Provider → Respuesta
```

### Estructura del Proyecto

```
Somer/
├── agents/           # Runner, fallback, compactacion, sub-agentes, auth profiles
├── browser/          # Automatizacion Playwright, perfiles
├── channels/         # 15 plugins de canal + AgentChannelRouter
├── cli/              # 11 grupos de comandos, 62 sub-comandos (Typer)
├── config/           # Schemas Pydantic v2, JSON5 loader, env overrides
├── context_engine/   # Ciclo: bootstrap → ingest → assemble → compact → after_turn
├── cron/             # Scheduler con jitter, overlap, timezone, retry
├── gateway/          # WebSocket JSON-RPC 2.0
├── hooks/            # Sistema async de hooks con carga dinamica
├── infra/            # Eventos, migraciones, status, file lock, puertos
├── media/            # Pipeline: detectar tipo, transcribir, resize, OCR
├── memory/           # BM25 + vector hibrido, temporal decay, 7 embedding providers
├── plugins/          # Ciclo completo: tipos, contratos, loader, registry, SDK
├── providers/        # 21 providers LLM
├── routing/          # AgentRouter 7 niveles, BindingStore, TTL
├── secrets/          # Fernet store, SecretRef, validacion, rotacion
├── security/         # Auditoria de config + scanner de SKILL.md
├── sessions/         # Routing jerarquico, persistencia JSONL, pub/sub
├── shared/           # Tipos Pydantic v2, 30+ errores, constantes
├── skills/           # 52 skills (SKILL.md) + loader/registry/validator
├── tts/              # System TTS + ElevenLabs
├── web_search/       # Tavily, Brave, DuckDuckGo + SearchManager
├── webhooks/         # Receptor HTTP webhook asyncio
├── tests/            # Unit + integration tests
├── entry.py          # Punto de entrada CLI
├── pyproject.toml    # Configuracion de build
├── CLAUDE.md         # Instrucciones para Claude Code
└── SOUL.md           # Personalidad del agente
```

### Componentes Principales

| Componente | Descripcion |
|------------|-------------|
| **Gateway** | WebSocket JSON-RPC 2.0 con TLS, auth y rate limiting |
| **Agent Runner** | Ejecucion de agentes con fallback de modelos y compactacion |
| **Context Engine** | Ciclo pluggable: bootstrap → ingest → assemble → compact → after_turn |
| **Memory** | Busqueda hibrida BM25 + vector, temporal decay, MMR, evergreen |
| **Routing** | 7 niveles de prioridad para vincular agentes a rutas |
| **Sessions** | Persistencia JSONL, routing jerarquico, pub/sub |
| **Channels** | Plugins para Telegram, Slack, Discord y mas |
| **Skills** | 52 skills en formato SKILL.md con YAML frontmatter |
| **Providers** | 21 providers LLM (OpenAI-compatible extienden `OpenAIProvider`) |
| **Secrets** | Almacenamiento cifrado Fernet con SecretRef multi-fuente |

### Sistema de Memoria

El sistema de memoria soporta:

- **Busqueda hibrida** - BM25 (texto) + vector (semantica) con pesos configurables
- **7 Embedding providers** - OpenAI, Gemini, Voyage, Mistral, SentenceTransformers, Ollama, Dummy
- **Auto-seleccion** - `create_embedding_provider("auto")` detecta el mejor provider disponible
- **Fallback automatico** - Si el provider primario falla, usa el secundario
- **MMR Reranking** - Maximal Marginal Relevance con cosine (vector) o Jaccard (texto)
- **Temporal Decay** - Exponencial basado en `accessed_at`, con categorias evergreen y factor de importancia
- **Deduplicacion** - Por hash de contenido
- **Compactacion** - Fusion de entradas similares

### Configuracion

- `~/.somer/config.json` - Config principal (JSON5 soportado)
- `~/.somer/credentials/` - Almacenamiento cifrado de credenciales
- `~/.somer/sessions/` - Persistencia de sesiones (JSONL)
- `~/.somer/memory/` - Base de datos SQLite de memoria
- Variables de entorno sobreescriben config (`SOMER_DEFAULT_MODEL`, `ANTHROPIC_API_KEY`, etc.)

## Desarrollo

### Tests

```bash
# Todos los tests unitarios
PYTHONPATH=. python3 -m pytest tests/unit/ -v

# Tests de un modulo especifico
PYTHONPATH=. python3 -m pytest tests/unit/memory/ -v

# Todos los tests con traceback corto
PYTHONPATH=. python3 -m pytest tests/ -v --tb=short
```

### Estadisticas

- ~200 archivos Python, ~48,100 LOC (sin tests)
- 52 skills, 21 providers, 15 canales
- 1,500+ tests pasando

## Protocolos Clave

| Protocolo | Metodos |
|-----------|---------|
| **ContextEngine** | `bootstrap` → `ingest` → `assemble` → `compact` → `after_turn` |
| **ChannelPlugin** | `setup` → `start` → `stop` → `send_message` → `on_message` |
| **BaseProvider** | `complete` → `stream` → `health_check` → `list_models` |
| **EmbeddingProvider** | `dimension` (property) → `embed` → `embed_single` |

## Puntos de Entrada

1. **CLI**: `somer` → `entry.py` → `cli/app.py`
2. **Gateway**: `somer gateway start` → WebSocket en `ws://127.0.0.1:18789`
3. **Python**: `from agents.runner import AgentRunner`

## Licencia

MIT

---

> *"No estas aqui para impresionar. Estas aqui para ejecutar eficientemente."*
