# Changelog

All notable changes to SOMER will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.5.4] - 2025-03-20 - "Process Guardian"

### Added
- **Process Cleanup System** (`cli.py`): Robust child process management
  - `_cleanup_all_processes()` - Kills all SOMER child processes on shutdown
  - Handles PID files for telegram bot and main daemon
  - Uses `pkill` as fallback for orphan processes
  - Graceful SIGTERM followed by SIGKILL if needed

- **Force Stop Option**: `somer stop -f/--force`
  - Immediately kills all SOMER-related processes
  - Cleans up all PID files

### Changed
- **`somer start`** (`cli.py`): Now properly cleans up on Ctrl+C
  - Added `finally` block that calls `_cleanup_all_processes()`
  - Ensures no orphan telegram bot processes remain

- **`somer stop`** (`cli.py`): Always cleans up child processes
  - Calls `_cleanup_all_processes()` after stopping main daemon
  - Added `-f/--force` flag for emergency kills

- **TelegramService** (`runtime/service_manager.py`): Improved cleanup
  - Registers `atexit` handler to clean PID file on exit
  - Only removes PID file if it belongs to current process

- **DaemonManager** (`runtime/daemon.py`): Enhanced signal handling
  - Added `_cleanup_child_pids()` method
  - Signal handler now kills child processes before shutdown
  - `_cleanup_sync()` includes child process cleanup

### Fixed
- `telegram.error.Conflict: terminated by other getUpdates request` - Multiple bot instances no longer possible
- Orphan telegram bot processes after Ctrl+C on `somer start`
- PID files not being cleaned up on abnormal exit
- Child processes surviving parent process termination

## [0.5.1] - 2025-03-19 - "Dynamic Intelligence"

### Added
- **Dynamic Service Detection** (`agents/orchestrator.py`): Intelligent service recognition
  - Expanded to 25+ service patterns (Discord, Stripe, Twilio, Firebase, AWS, WhatsApp, Spotify, YouTube, Dropbox, Trello, Jira, Asana, Monday, Airtable, Zapier, Make, etc.)
  - Smart "how to get token" detection with multi-language patterns (Spanish/English)
  - Regex-based service matching with confidence scoring

- **LLM-Powered Instruction Generation** (`_get_dynamic_instructions()`):
  - Falls back to LLM when hardcoded instructions not available
  - Generates step-by-step token acquisition guides for any service
  - Persists learned instructions for future use

- **Learning Persistence System** (`_save_learning()`):
  - Saves generated instructions to `somer_memory.json`
  - Learns from user interactions
  - Builds knowledge base over time

- **Hardcoded Service Configurations** (`_get_hardcoded_service_config()`):
  - Detailed configurations for 15+ popular services
  - Includes: Google Calendar, Gmail, Google Drive, Notion, Telegram, Slack, GitHub, Trello, Spotify, OpenAI, Discord, Stripe, Twilio, SendGrid, Firebase
  - Each with: name, env_var, instructions, example values, documentation links

- **Conversation Focus Rules** (`main.py`):
  - "FOCO EN LA PREGUNTA ESPECÍFICA" - Responds only to what user asks
  - "CONTINUIDAD DE CONVERSACIÓN" - Maintains conversation thread
  - Prevents information dumping about unrelated services

### Changed
- **System Prompt** (`main.py`): Enhanced with explicit focus rules
  - If user asks about Google Calendar, respond ONLY about Google Calendar
  - Never provide info about services not mentioned
  - Continue conversation thread instead of changing topics

- **AgentOrchestrator** (`agents/orchestrator.py`): More intelligent routing
  - Dynamic detection before static patterns
  - LLM fallback when service unknown
  - Better context awareness

### Architecture
```
User Task
    │
    ▼
┌─────────────────────────────────────────┐
│         AgentOrchestrator               │
│  ┌─────────────────────────────────┐    │
│  │   Dynamic Service Detection     │    │
│  │   (25+ service patterns)        │    │
│  └──────────────┬──────────────────┘    │
│                 │                        │
│  ┌──────────────▼──────────────────┐    │
│  │   "How to get token?" Detection │    │
│  │   (Spanish/English patterns)    │    │
│  └──────────────┬──────────────────┘    │
│                 │                        │
│    ┌────────────┴────────────┐          │
│    ▼                         ▼          │
│ ┌────────────┐      ┌────────────┐      │
│ │ Hardcoded  │      │ LLM-Based  │      │
│ │ Config     │      │ Generation │      │
│ └────────────┘      └─────┬──────┘      │
│                           │             │
│                    ┌──────▼──────┐      │
│                    │ Save to     │      │
│                    │ Memory      │      │
│                    └─────────────┘      │
└─────────────────────────────────────────┘
```

### Usage
```python
# SOMER now handles ANY service intelligently
"como consigo el token de google calendar"
→ Returns step-by-step instructions for Google Calendar

"how do I get a Stripe API key"
→ Returns instructions for Stripe (LLM-generated if not hardcoded)

# Conversation focus maintained
User: "Quiero configurar telegram"
SOMER: [Instructions for Telegram only]
User: "Y el token?"
SOMER: [Continues about Telegram token, doesn't switch topics]
```

## [0.5.0] - 2025-03-19 - "Multi-Agent Orchestration"

### Added
- **Agent Orchestrator** (`agents/orchestrator.py`): Central coordination engine
  - `AgentOrchestrator` - Routes tasks to specialized agents
  - `OrchestratorConfig` - Configure execution mode, timeouts, multi-agent
  - `OrchestratorResult` - Unified result with agent metadata
  - Skill fast-path for atomic operations
  - Multi-agent coordination for complex tasks
  - Automatic fallback to LLM when no agent matches

- **Agent Registry** (`agents/registry.py`): Centralized agent management
  - `AgentRegistry` - Register, discover, and match agents
  - `RegisteredAgent` - Agent with priority, domains, and keywords
  - `AgentMatch` - Matching result with confidence score
  - Priority-based agent selection
  - Domain and keyword matching
  - Execution metrics per agent

- **Agent Router** (`agents/router.py`): Intelligent task routing
  - `AgentRouter` - LLM-powered routing decisions
  - `RoutingDecision` - Primary agent, supporting agents, execution plan
  - `TaskAnalysis` - Task complexity and domain detection
  - Fast path for keyword-based routing
  - Multi-agent detection for complex tasks
  - Execution strategies: SINGLE, SEQUENTIAL, PARALLEL, PIPELINE

- **New Specialized Agents**:
  - `DataAgent` (`agents/data_agent.py`) - SQL, schemas, ORM, migrations
  - `InfraAgent` (`agents/infra_agent.py`) - Docker, CI/CD, Kubernetes, cloud
  - `ResearchAgent` (`agents/research_agent.py`) - Documentation, tutorials, comparisons
  - `FileAgent` (`agents/file_agent.py`) - File operations, project scaffolding

- **Agent Initialization** (`agents/__init__.py`):
  - `initialize_agents()` - One-call setup for all agents
  - All agents registered with priorities and domains
  - Ready-to-use orchestrator returned

### Changed
- **main.py**: Integrated AgentOrchestrator into `think_and_act()`
  - Orchestrator is the primary routing mechanism
  - Falls back to legacy methods if orchestrator unavailable
  - Agent metadata included in response
  - File creation handled after agent execution

### Architecture
```
User Task
    ↓
┌─────────────────────────────────────┐
│         AgentOrchestrator           │
│  ┌─────────┐  ┌─────────┐           │
│  │ Router  │──│ Planner │           │
│  └────┬────┘  └─────────┘           │
│       │                              │
│  ┌────▼────┐  ┌──────────────────┐  │
│  │Registry │──│   SkillRegistry  │  │
│  └────┬────┘  └──────────────────┘  │
└───────│─────────────────────────────┘
        │
   ┌────┴────┬────────┬────────┬────────┐
   ▼         ▼        ▼        ▼        ▼
┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐
│ Code │ │ API  │ │ Data │ │Infra │ │ File │
│Agent │ │Agent │ │Agent │ │Agent │ │Agent │
└──────┘ └──────┘ └──────┘ └──────┘ └──────┘
```

### Usage
```python
from agents import initialize_agents
from tools.llm import create_llm_provider

# Initialize
llm = create_llm_provider()
orchestrator = initialize_agents(llm)

# Single agent task
result = await orchestrator.execute("Create a fibonacci function")
print(f"Agent: {result.agent_used}")

# Multi-agent task
result = await orchestrator.execute("Create REST API with PostgreSQL and Docker")
print(f"Agents: {result.agents_involved}")
```

## [0.4.5] - 2025-03-19 - "Real-Time Execution"

### Added
- **API Connector** (`engine/api_connector.py`): Universal REST API integration
  - `APIConnector` - Config-driven API client for any REST service
  - `KNOWN_APIS` - Pre-configured APIs: Notion, Telegram, GitHub, Slack, OpenWeather, SendGrid
  - `call()` - Execute API calls with path/query/body params
  - `is_configured()` - Check if API has required credentials
  - `request_access()` - Generate instructions for missing API keys
  - Automatic auth header injection (Bearer, Bot, token)
  - Response normalization with `APIResponse` dataclass

### Changed
- **Behavior shift**: SOMER now EXECUTES actions instead of showing code
  - Direct API calls instead of code generation
  - Internal bash/shell execution (not shown to users)
  - File creation without displaying code
- `main.py`: New LLM system prompt for real-time execution mode
  - "YO ACTÚO, NO SOLO INFORMO" philosophy
  - Explicit rules against sending code/bash to chat
  - API availability awareness in responses
- `SOUL.md`: Updated to reflect execution-first capabilities
  - New "EJECUCIÓN EN TIEMPO REAL" section
  - API availability table
  - Clear distinction between what SOMER does vs. delegates

### Philosophy
```
Before: User asks → SOMER generates code → User runs it
After:  User asks → SOMER executes directly → User sees result
```

## [0.4.4] - 2025-03-19 - "Proactive Skills"

### Added
- **Skill Factory** (`engine/skill_factory.py`): Dynamic skill generation
  - `SkillFactory` - Create, persist, and execute dynamic skills
  - `auto_create_skill_if_needed()` - Auto-generate skills for new tasks
  - `suggest_skills()` - Suggest skills based on task patterns
  - Skills stored in `skills/generated/` with registry
  - Auto-execution of simple skills without user confirmation
- **Solution Finder** (`engine/solution_finder.py`): Proactive problem solving
  - `SolutionFinder` - Find solutions from knowledge base
  - `find_and_suggest_solution()` - Search integrations and LLM
  - Known integrations: Calendar, Email, Weather, Translation, Search
  - Knowledge base persisted in `data/knowledge_base.json`
  - Proactive suggestions when SOMER can't directly help

### Changed
- `main.py`: Integrated skill factory and solution finder in `think_and_act()`
- `main.py`: Proactive skill creation for simple patterns
- `main.py`: Solution suggestions in fallback path
- SOMER now suggests creating skills when it encounters unknown task types
- Skills are auto-created and persisted for future use

### Flow
```
User request → Check dynamic skills → Code pipeline → LLM →
Builtin → Solution Finder → Suggest skill creation
```

## [0.4.3] - 2025-03-19 - "Claude Code & File Handler"

### Added
- **Claude Code Integration** (`tools/claude_code/`): Full integration with Anthropic's CLI
  - `is_claude_code_installed()` - Check if claude CLI is available
  - `generate_with_claude_code()` - Generate code using Claude Code
  - `run_claude_code_task()` - Run tasks with SOMER context
  - `get_claude_code_status()` - Get installation status and version
  - Commands: `claude code status`, `usa claude code para [task]`
- **File Handler** (`engine/file_handler.py`): Direct file creation on disk
  - `should_create_file()` - Detect if user wants file vs code display
  - `handle_file_creation_request()` - Create files and return confirmation
  - `extract_filename()` - Extract or generate filename from task
  - Files saved to `outputs/` directory (configurable via `SOMER_OUTPUT_DIR`)
- **Code Pipeline** (`engine/code_pipeline.py`): Unified code generation
  - `generate_code()` - Main entry point for all code generation
  - `detect_language()` - Auto-detect programming language from task
  - `detect_code_type()` - Detect if backend/frontend/script
  - `apply_style_rules()` - Apply engine style rules
  - `validate_imports()` - Check for allowed libraries
  - `clean_code()` - Remove markdown blocks, normalize formatting
- **Heartbeat improvements**: Always report to Telegram every 30 min
  - `ALWAYS_REPORT: true` configuration option
  - Enhanced Telegram messages with version and next check time
  - Auto-configured when Telegram is set up

### Changed
- `main.py`: Uses unified code pipeline for all code generation
- `main.py`: Added `handle_claude_code()` for CLI integration
- `main.py`: Code requests routed through `engine.code_pipeline`
- `runtime/services/heartbeat.py`: `is_configured()` returns True if Telegram configured
- `runtime/services/heartbeat.py`: `suppress_ok = False` by default (always notify)
- `HEARTBEAT.md`: `NOTIFY: telegram,console` enabled by default
- Code generation flow: Claude Code → LLM → Engine rules → File creation

### Fixed
- Heartbeat not sending notifications to Telegram
- Code being sent to chat instead of saved as file when requested

## [0.4.2] - 2025-03-18 - "Notion Integration"

### Added
- **Notion Skill** (`skills/notion/`): Full integration with Notion API
  - `NotionSearchSkill` - Search pages and databases in workspace
  - `NotionCreatePageSkill` - Create new pages in pages or databases
  - `NotionUpdatePageSkill` - Update page properties, archive, append content
  - `NotionQueryDatabaseSkill` - Query databases with filters and sorts
  - `NotionGetPageSkill` - Get page details by ID
  - `NotionClient` - Reusable API client for Notion operations
- **Configuration**: `NOTION_API_KEY` or `NOTION_TOKEN` environment variable
- **Auto-registration**: Skills register automatically if Notion is configured

### Changed
- `_shared/constants.py`: Added "notion" to SKILL_CATEGORIES
- `skills/__init__.py`: Exports Notion skills, conditional registration
- VERSION = "0.4.2", VERSION_NAME = "Notion Integration"

### Usage
```bash
# Configure
export NOTION_API_KEY="secret_xxx..."

# Use via SOMER
somer "buscar en notion proyectos"
somer "crear página en notion titulo: Mi Nota"
somer "consultar base de datos notion id: abc123"
```

## [0.4.1] - 2025-03-18 - "Singleton Services"

### Added
- **Singleton pattern for all services**: Prevents multiple instances from running
  - `main.py`: `is_telegram_bot_running()` - Check if bot process is alive via PID
  - `main.py`: `stop_telegram_bot()` - Gracefully stop existing bot instances
  - `main.py`: `diagnose_telegram_bot()` - Autonomous problem detection
  - PID file: `logs/telegram_bot.pid` - Track running bot process
- **Auto-diagnosis for Telegram**: Bot executes diagnostics internally
  - Checks process status, reads logs, detects errors
  - No bash commands shown to users (autonomous resolution)
  - Auto-starts bot if not running when problems detected
- **ServiceManager singleton** (`runtime/service_manager.py`):
  - `__new__()` - Python singleton pattern ensures one instance
  - `is_already_running()` - Check PID file for existing process
  - `force_stop_existing()` - SIGTERM/SIGKILL existing instance
  - PID file: `data/pids/somer.pid`
- **TelegramService singleton** (`runtime/service_manager.py`):
  - `is_bot_running()` - Check for running bot process
  - PID file written on start, cleaned on stop
  - Skips start if another instance detected

### Changed
- `main.py`: LLM system prompt now includes "REGLAS CRÍTICAS" section
  - NUNCA sugieras comandos bash/shell
  - NUNCA muestres "ps aux", "grep", "tail", etc.
  - Responde con soluciones concretas, no instrucciones técnicas
- `main.py`: `start_telegram_bot_daemon()` checks `is_telegram_bot_running()` first
- `main.py`: Bot runner script (`/.telegram_bot_runner.py`) now:
  - Writes PID on start
  - Handles SIGTERM/SIGINT for graceful cleanup
  - Removes PID file on exit
- `runtime/service_manager.py`: `start_all()` returns early if already running
- `_shared/constants.py`: VERSION = "0.4.1", VERSION_NAME = "Singleton Services"

### Fixed
- `telegram.error.Conflict: terminated by other getUpdates request` - Only one bot instance can run
- Multiple `somer start` calls no longer create duplicate processes
- Stale PID files are automatically cleaned up when process is dead

## [0.4.0] - 2025-03-18 - "Service Manager"

### Added
- **Service Manager**: Auto-start all configured services on boot
- `somer start` - Start all configured services (Telegram, Redis, etc.)
- `somer stop` - Stop all running services
- `somer status` - Show status of all services
- `somer start -d` - Run services in daemon/background mode
- **Heartbeat Service**: Periodic automated check-ins (like OpenClaw)
  - `somer heartbeat check` - Run a single heartbeat check now
  - `somer heartbeat start` - Start heartbeat service (runs every 30 min)
  - `somer heartbeat status` - Show heartbeat configuration
  - `somer heartbeat edit` - Open HEARTBEAT.md for editing
  - `HEARTBEAT.md` - Checklist file for configuring what to monitor
  - LLM-powered intelligent task analysis
  - Multi-channel notifications (console, log, telegram)
- **Runtime module**: Complete service orchestration system
  - `runtime/daemon.py` - Process management with PID files
  - `runtime/service_manager.py` - Service orchestration
  - `runtime/services/heartbeat.py` - Heartbeat service implementation
  - `DaemonManager` - Background process lifecycle
  - `ServiceManager` - Auto-detect and start configured services
  - `TelegramService` - Telegram bot as managed service
  - `RedisService` - Redis connection as managed service
  - `HealthMonitorService` - Automatic health checks
  - `HeartbeatService` - Periodic automated check-ins
- **Token-optimized memory**: SQLite + FTS5 for smart context retrieval
  - `memory/conversation_memory.py` - Engram-style memory
  - Full-text search for relevant context
  - Session management
  - Topic keys for grouping
  - ~90% token reduction via selective retrieval
- **Engine rules and templates**:
  - `engine/code_engine/rules/` - Python, TypeScript, common rules
  - `engine/code_engine/templates/` - FastAPI, Pydantic, Zod templates
  - Rule loader with priority and categories
  - Template renderer with variable substitution
- **ARCHITECTURE.md**: Complete system diagram and comparison with OpenClaw

### Changed
- Services now auto-start when configured (like OpenClaw)
- Memory system uses SQLite + FTS5 instead of in-memory
- `think_and_act()` now uses optimized context retrieval
- Conversation memory persists across sessions
- Updated VERSION to 0.4.0, VERSION_NAME to "Service Manager"

### Fixed
- Telegram not starting automatically after setup
- Context lost between messages (now persisted in SQLite)
- LLM import error (`create_llm_provider` was missing)

## [0.3.4] - 2025-03-18 - "LLM Brain"

### Added
- **LLM as primary brain**: Orchestrator uses LLM automatically when uncertain
- `ask_llm()` function for direct LLM queries
- `ask_llm_with_context()` for retry with additional context
- `try_answer_question()` for basic concept explanations
- **Autonomous Telegram management**: Active API verification and auto-start
- `verify_telegram_connection()` verifies connection with Telegram API
- `start_telegram_bot_daemon()` starts bot in background automatically
- **SOUL.md**: Archivo que define la identidad, principios y personalidad de SOMER
- `get_soul_summary()` - Extrae resumen del alma para prompts del LLM
- `get_full_soul()` - Lee el archivo SOUL.md completo
- Detección de preguntas de identidad ("quién eres", "tu alma", etc.)

### Changed
- **Refactored intelligence flow**: LLM → builtin → retry with LLM
- `builtin_intelligence()` now returns `uncertain: True` when it doesn't know
- Telegram bot uses `think_and_act()` for consistent intelligence
- System commands handled locally (fast path) before LLM
- Updated VERSION_NAME to "LLM Brain"

## [0.3.3] - 2025-03-18 - "Self-Improving"

### Added
- **Self-improvement engine**: SOMER can now modify and enhance its own code
- `self_improve()` function for autonomous code modifications
- `add_new_capability()` to create new skills dynamically
- `improve_capability()` to optimize existing functions
- `learn_from_feedback()` to store learnings in `somer_memory.json`
- `show_capabilities()` to list current abilities
- Auto-generated skills stored in `somer_custom_skills.py`
- Memory persistence for learnings and preferences
- **Changelog management**: Proper version tracking with CHANGELOG.md
- `somer changelog` command to view version history
- `_shared/versioning.py` module for programmatic version management
- `bump_version()` function to update version across all files
- `add_changelog_entry()` for automated changelog updates

### Changed
- Updated VERSION_NAME to "Self-Improving"
- Enhanced autonomous decision-making capabilities
- `somer upgrade` now shows changelog for current version
- `somer version` shows version name and changelog hint

## [0.3.2] - 2025-03-18 - "Automatic Mode"

### Added
- **Automatic mode detection**: User just asks, SOMER decides what to do
- LLM-as-brain architecture: LLM decides, skills are tools
- `think_and_act()` function for LLM-powered reasoning
- `builtin_intelligence()` fallback when API key not available
- Greeting detection and friendly responses
- Help/capabilities command support
- Spanish and English language support

### Changed
- Refactored from hardcoded skills to LLM-first approach
- Mode selection is now automatic based on user input
- Improved natural language understanding

### Fixed
- "crea una funcion fibonacci" now correctly generates code
- "que puedes hacer?" returns proper capabilities list

## [0.3.1] - 2025-03-18

### Added
- **Telegram bot integration** via `python-telegram-bot`
- `TelegramBot` class with session management
- Telegram commands: `/start`, `/help`, `/mode`, `/status`, `/clear`
- `somer telegram` CLI command (setup, start, status)
- Optional Telegram setup in main setup wizard
- Environment variables for Telegram configuration

### Changed
- Updated `requirements-all.txt` with Telegram dependency
- Added `.env.example` Telegram configuration section

## [0.3.0] - 2025-03-18

### Added
- **GOAL/INPUT architecture**: Unified entry point for user input
- `GoalInput` class combining parser, validator, and builder
- Input parsing with multiple formats (simple, goal/task, structured)
- Input validation with injection detection
- Sensitive data filtering
- DAG-based phase execution system
- Core orchestrator with phase transitions
- Memory system (short-term, long-term, semantic)
- Skills framework (file, db, http, code, parsing, validation)
- Agent types (code, qa, api, browser, logic, eval)
- CLI commands: `run`, `setup`, `doctor`, `upgrade`

### Technical
- Python 3.9+ compatibility
- Pydantic v2 for data validation
- Async/await architecture throughout
- Structured logging with structlog

## [0.2.x] and earlier

Initial development versions. See git history for details.

---

## Version Naming Convention

| Version | Name | Focus |
|---------|------|-------|
| 0.5.4 | Process Guardian | Robust process cleanup, no orphan processes |
| 0.5.1 | Dynamic Intelligence | LLM-powered service detection, learning persistence |
| 0.5.0 | Multi-Agent Orchestration | Agent routing, specialized agents, execution strategies |
| 0.4.5 | Real-Time Execution | API Connector, execute actions directly |
| 0.4.4 | Proactive Skills | Dynamic skill creation, solution finder |
| 0.4.3 | Claude Code | CLI integration, file handler, code pipeline |
| 0.4.2 | Notion Integration | Full Notion API skill set |
| 0.4.1 | Singleton Services | Process management, duplicate prevention |
| 0.4.0 | Service Manager | Auto-start services, token optimization, daemon |
| 0.3.4 | LLM Brain | LLM as primary intelligence with auto-retry |
| 0.3.3 | Self-Improving | Auto-programming capabilities |
| 0.3.2 | Automatic Mode | LLM-first autonomous operation |
| 0.3.1 | - | Telegram integration |
| 0.3.0 | - | Core architecture & DAG phases |
