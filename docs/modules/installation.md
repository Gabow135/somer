# Installation Guide

**Location:** Project Root

**Status:** Ready for Use

---

## Overview

SOMER includes an automatic setup wizard that handles everything:

- Installs all dependencies automatically
- Configures API keys interactively
- Creates required directories
- Validates the installation

---

## Quick Start (Recommended)

### One-Command Installation

```bash
git clone https://github.com/somer-ai/somer.git
cd somer
python3 cli.py setup
```

The setup wizard will:
1. Check Python version (>=3.9)
2. Install all dependencies automatically
3. **Install SOMER globally** (so `somer` command works from anywhere)
4. **Select LLM provider** (Anthropic Claude, OpenAI/ChatGPT, or DeepSeek)
5. Create required directories
6. Validate the installation

### Supported LLM Providers

| Provider | Models | API Key URL |
|----------|--------|-------------|
| **Anthropic Claude** | claude-sonnet-4, claude-3-5-sonnet, claude-3-haiku | https://console.anthropic.com/ |
| **OpenAI (ChatGPT)** | gpt-4o, gpt-4-turbo, gpt-3.5-turbo | https://platform.openai.com/api-keys |
| **DeepSeek** | deepseek-chat, deepseek-coder | https://platform.deepseek.com/ |

### Example Setup Output

```
╭────────────────────────────────────────────────────╮
│ SOMER Setup Wizard                                 │
│ System for Optimized Modular Execution & Reasoning │
╰────────────────────────────────────────────────────╯

Step 1/6: Checking Python version...
  ✓ Python 3.11.0 (OK)

Step 2/6: Installing dependencies...
  ✓ anthropic
  ✓ openai
  ✓ pydantic
  ✓ aiohttp
  ✓ All dependencies installed

Step 3/6: Installing SOMER globally...
  Upgrading pip for modern package support...
  ✓ Installed: /Users/you/.local/bin/somer

Step 4/6: Configuring environment...
  Select LLM Provider

    1) Anthropic Claude
       Models: claude-sonnet-4-20250514, claude-3-5-sonnet-20241022
    2) OpenAI (GPT-4/ChatGPT)
       Models: gpt-4o, gpt-4-turbo
    3) DeepSeek
       Models: deepseek-chat, deepseek-coder

  Select provider [1/2/3] (1): 1
  ✓ Selected: Anthropic Claude

  Anthropic Claude API Key
  Get your key at: https://console.anthropic.com/
  Enter API key: ****

  Select Model
    1) claude-sonnet-4-20250514 (default)
    2) claude-3-5-sonnet-20241022
  Select model [1/2] (1): 1
  ✓ Selected model: claude-sonnet-4-20250514

  ✓ Configuration saved to .env
  Provider: Anthropic Claude, Model: claude-sonnet-4-20250514

Step 5/6: Setting up directories...
  ✓ Created data/
  ✓ Created logs/
  ✓ Created cache/

Step 6/6: Validating installation...
  ✓ Orchestrator: OK
  ✓ Memory Manager: OK
  ✓ LLM Provider (Claude): OK
  ✓ LLM Provider (OpenAI): OK
  ✓ LLM Provider (DeepSeek): OK
  ✓ API Key (anthropic): Configured

╭──────────────────────────────────────────────╮
│ Setup Complete!                              │
│                                              │
│ SOMER installed at: ~/.local/bin/somer       │
│                                              │
│ You can now use SOMER from anywhere:         │
│   somer run      - Interactive mode          │
│   somer execute  - Execute a task            │
│   somer doctor   - Health check              │
│   somer demo     - Run demo                  │
╰──────────────────────────────────────────────╯
```

---

## Requirements

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | >= 3.9 | Tested on 3.9, 3.11, 3.12 |
| pip | Latest | For package installation |
| Git | Any | For cloning repository |

---

## Setup Options

### Full Wizard (Default)

```bash
python3 cli.py setup
```

### Minimal Installation

Install only core dependencies (no Redis/SQLite):

```bash
python3 cli.py setup --minimal
```

### Skip Interactive Config

Use this if you'll configure manually later:

```bash
python3 cli.py setup --skip-config
```

### Skip Dependency Installation

If deps are already installed:

```bash
python3 cli.py setup --skip-deps
```

### Skip Global Installation

If you don't want `somer` command globally:

```bash
python3 cli.py setup --skip-global
```

### Non-Interactive Installation

For CI/CD or scripts:

```bash
# Set environment variable first
export ANTHROPIC_API_KEY=your_key_here

# Run setup without interactive prompts
python3 cli.py setup --skip-config
```

### Full Non-Interactive (CI/CD)

```bash
export ANTHROPIC_API_KEY=your_key_here
python3 cli.py setup --skip-config --minimal
```

---

## Alternative Installation Methods

### Using Make

```bash
make install      # Basic installation
make install-dev  # With development tools
make install-all  # All dependencies
```

### Using pip directly

```bash
# Core dependencies
pip install -r requirements.txt

# Development dependencies
pip install -r requirements-dev.txt

# All dependencies
pip install -r requirements-all.txt
```

### Editable Installation

For development:

```bash
pip install -e .           # Basic
pip install -e ".[dev]"    # With dev tools
pip install -e ".[all]"    # All optional deps
```

---

## CLI Commands

After installation:

| Command | Description |
|---------|-------------|
| `somer setup` | Full installation wizard |
| `somer doctor` | Check system health |
| `somer run` | Interactive mode |
| `somer execute "task"` | Execute a task |
| `somer demo` | Run demo |
| `somer test` | Run tests |
| `somer upgrade` | Upgrade dependencies |
| `somer version` | Show version |

### Using Make

| Command | Description |
|---------|-------------|
| `make setup` | Run setup wizard |
| `make doctor` | Health check |
| `make run` | Interactive mode |
| `make test` | Run all tests |
| `make demo` | Run demo |

---

## Doctor Command

The `doctor` command checks your installation:

```bash
somer doctor
```

Example output:

```
                       SOMER Health Check
┏━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Component      ┃ Status        ┃ Note                         ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ Python Version │ 3.11.0        │ >=3.9 required               │
│ .env file      │ Found         │ Run 'somer setup'            │
│ API Key        │ Configured    │ Set ANTHROPIC_API_KEY        │
│ anthropic      │ Installed     │ LLM Provider                 │
│ pydantic       │ Installed     │ Data Validation              │
│ redis          │ Installed     │ Short-term Memory (optional) │
│ Orchestrator   │ OK            │ Core module                  │
│ Memory Manager │ OK            │ Core module                  │
│ LLM Provider   │ OK            │ Core module                  │
└────────────────┴───────────────┴──────────────────────────────┘

All checks passed! SOMER is ready.
```

---

## Configuration

### Environment Variables

The setup wizard creates a `.env` file with:

```bash
# SOMER Configuration
# Generated by setup wizard

# LLM Provider Configuration
SOMER_LLM_PROVIDER=anthropic  # Options: anthropic, openai, deepseek
SOMER_LLM_MODEL=claude-sonnet-4-20250514

# API Keys (set the one for your selected provider)
ANTHROPIC_API_KEY=your_key_here
# OPENAI_API_KEY=your_key_here
# DEEPSEEK_API_KEY=your_key_here

# General Settings
SOMER_LOG_LEVEL=INFO
SOMER_MODE=development

# Optional: Redis for short-term memory
REDIS_URL=redis://localhost:6379/0

# Optional: SQLite path for long-term memory
SQLITE_PATH=./data/somer_memory.db
```

### Switching Providers

To switch LLM providers, update these variables in `.env`:

```bash
# For OpenAI/ChatGPT:
SOMER_LLM_PROVIDER=openai
SOMER_LLM_MODEL=gpt-4o
OPENAI_API_KEY=sk-...

# For DeepSeek:
SOMER_LLM_PROVIDER=deepseek
SOMER_LLM_MODEL=deepseek-chat
DEEPSEEK_API_KEY=sk-...

# For Anthropic Claude:
SOMER_LLM_PROVIDER=anthropic
SOMER_LLM_MODEL=claude-sonnet-4-20250514
ANTHROPIC_API_KEY=sk-ant-...
```

### Manual Configuration

If you prefer manual setup:

```bash
cp .env.example .env
# Edit .env with your values
```

---

## Dependencies

### Core (Required)

| Package | Purpose |
|---------|---------|
| anthropic | Claude API client |
| openai | OpenAI/DeepSeek API client |
| pydantic | Data validation |
| aiohttp | Async HTTP client |
| httpx | HTTP client |
| python-dotenv | Environment loading |
| structlog | Structured logging |
| typer | CLI framework |
| rich | Terminal formatting |

### Optional

| Package | Purpose | Install |
|---------|---------|---------|
| redis | Short-term memory | `pip install redis` |
| aiosqlite | Long-term memory | `pip install aiosqlite` |

---

## Upgrading

### Upgrade Dependencies

```bash
somer upgrade
# or
make upgrade
```

### Upgrade SOMER

```bash
git pull origin main
somer setup --skip-config
```

---

## Troubleshooting

### Issue: Setup fails to install packages

```
Error: pip install failed
```

**Solution**: Upgrade pip and try again:

```bash
python3 -m pip install --upgrade pip
python3 cli.py setup
```

### Issue: API key not working

```
API Key: Missing
```

**Solution**: Run setup again:

```bash
python3 cli.py setup
```

### Issue: Module not found

```
ModuleNotFoundError: No module named '_shared'
```

**Solution**: Set PYTHONPATH:

```bash
export PYTHONPATH=.
# or run with
PYTHONPATH=. python3 cli.py doctor
```

### Issue: Permission denied

```
Permission denied: /usr/local/...
```

**Solution**: Use user installation:

```bash
pip install --user -r requirements.txt
```

---

## Project Structure

```
somer/
├── cli.py              # CLI with setup wizard
├── main.py             # Main module
├── .env                # Configuration (created by setup)
├── .env.example        # Template
├── pyproject.toml      # Package config
├── Makefile            # Development commands
├── requirements.txt    # Dependencies
│
├── data/               # Data storage (created by setup)
├── logs/               # Log files (created by setup)
├── cache/              # Cache (created by setup)
│
├── _shared/            # Shared types
├── core/               # Orchestrator
├── memory/             # ENGRAM++ memory
├── tools/              # LLM providers
├── skills/             # Skill registry
├── phases/             # SDD phases
│
└── tests/              # Test suite
```

---

## Next Steps

After installation:

1. Run `somer doctor` to verify setup
2. Run `somer demo` to see SOMER in action
3. Run `somer run` for interactive mode
4. Read [Architecture Overview](../architecture/overview.md)

---

## Uninstallation

```bash
# If installed with pip
pip uninstall somer

# Clean all generated files
make clean-all

# Remove data
rm -rf data/ logs/ cache/ .env
```
