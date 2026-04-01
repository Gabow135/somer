# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

SOMER 2.0 (System for Optimized Modular Execution & Reasoning) is a Python cognitive engine inspired by OpenClaw's architecture. It provides a WebSocket gateway, multi-provider LLM support, hybrid memory (BM25 + vector), channel plugins (Telegram/Slack/Discord), and a SKILL.md-based skill system.

Language: Python 3.9+ | Build: hatchling | CLI: typer + rich

## Commands

```bash
# Testing (always set PYTHONPATH=.)
PYTHONPATH=. python3 -m pytest tests/unit/ -v          # All unit tests
PYTHONPATH=. python3 -m pytest tests/unit/config/ -v   # Single module
PYTHONPATH=. python3 -m pytest tests/ -v --tb=short    # All tests, short traceback

# CLI
somer version           # Show version
somer doctor check      # Health check
somer config show       # Show config
somer config init       # Create default config
somer gateway start     # Start WebSocket gateway
somer agent run "msg"   # Send message to agent
somer channels list     # List channels

# Install
pip install -e ".[dev]"       # Dev install
pip install -e ".[all]"       # Full install with all extras
```

## Architecture

### Project Structure
```
Somer/                         # Project root
├── shared/                    # Types, errors, constants, protocols
├── config/                    # Pydantic config schema + loader + env overrides + default.json5
├── secrets/                   # Encrypted credential storage + SecretRef
├── gateway/                   # WebSocket JSON-RPC 2.0 control plane
├── providers/                 # LLM providers (Anthropic, OpenAI, DeepSeek, Google, Ollama, Bedrock)
├── memory/                    # Hybrid search (BM25 + vector) + SQLite backend
├── context_engine/            # Pluggable context management (bootstrap → ingest → assemble → compact)
├── sessions/                  # Session lifecycle, routing, persistence (JSONL), pub/sub events
├── agents/                    # Agent runner, context window guard, auth profiles
├── channels/                  # Channel plugin system (Telegram, Slack, Discord)
├── skills/                    # SKILL.md loader, registry, validator + bundled SKILL.md files
├── hooks/                     # Lifecycle hooks (on_startup, on_error, etc.)
├── security/                  # Config audit, skill scanner
├── cli/                       # Typer CLI commands
├── plugins/                   # Plugin runtime (future)
├── infra/                     # Env, heartbeat, net utilities
├── entry.py                   # CLI entry point
├── tests/                     # Unit + integration tests
├── pyproject.toml             # Build config
├── CLAUDE.md                  # This file
└── SOUL.md                    # Agent personality
```

### Execution Flow
User message → Channel plugin → Session router → Context engine ingest → Agent runner → Provider complete → Context after_turn → Response via channel

### Type System
All types in `shared/types.py` (Pydantic v2). Key types: `Message`, `AgentMessage`, `AgentTurn`, `SessionInfo`, `ModelDefinition`, `ProviderConfig`, `SkillMeta`, `MemoryEntry`, `IncomingMessage`, `OutgoingMessage`.

### Configuration
- `~/.somer/config.json` — Main config (JSON5 supported)
- `~/.somer/credentials/` — Encrypted credential storage
- `~/.somer/sessions/` — Session persistence (JSONL)
- `~/.somer/memory/` — SQLite memory database
- Environment vars override config (SOMER_DEFAULT_MODEL, ANTHROPIC_API_KEY, etc.)

### Key Protocols
- `ContextEngine`: bootstrap → ingest → assemble → compact → after_turn
- `ChannelPlugin`: setup → start → stop → send_message → on_message
- `BaseProvider`: complete → stream → health_check → list_models

### Entry Points
1. **CLI**: `somer` command → `entry.py` → `cli/app.py`
2. **Gateway**: `somer gateway start` → WebSocket server on ws://127.0.0.1:18789
3. **Python**: `from agents.runner import AgentRunner`

## Conventions

- Documentation and SOUL.md in **Spanish**
- asyncio throughout — pytest uses `asyncio_mode = "auto"`
- Error handling: use specific exceptions from `shared/errors.py`
- Types: always import from `shared/types.py`
- Config: Pydantic v2 models in `config/schema.py`
- Secrets: Never store API keys as literals — use env vars or CredentialStore
- Skills: SKILL.md format with YAML frontmatter
- **Response templates**: All skills MUST use standardized `TPL-*` templates from `skills/_templates/RESPONSE_FORMATS.md` — never improvise formats
- Legacy code preserved in `somer-legacy` branch
