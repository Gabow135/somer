# SOMER Documentation

Welcome to the SOMER documentation.

---

## Quick Links

| Document | Description |
|----------|-------------|
| [Installation Guide](modules/installation.md) | Setup, configuration, CLI commands |
| [Architecture Overview](architecture/overview.md) | System design, components, data flow |
| [Vision & Roadmap](vision/roadmap.md) | Project goals, timeline, phases |
| [Orchestrator](modules/orchestrator.md) | Central coordination module |
| [Agent System](modules/agent-system.md) | Specialized task agents |
| [Code Engine](modules/code-engine.md) | Code generation system |
| [LLM Integration](modules/llm-integration.md) | Claude API wrapper |
| [Memory System](modules/memory-system.md) | ENGRAM++ memory system |

---

## Documentation Structure

```
docs/
├── README.md                 # This file
├── architecture/
│   └── overview.md           # System architecture
├── vision/
│   └── roadmap.md            # Project vision & roadmap
├── modules/
│   ├── orchestrator.md       # Orchestrator documentation
│   ├── code-engine.md        # Code Engine documentation
│   └── memory.md             # Memory System (coming soon)
├── api/
│   └── README.md             # API reference (coming soon)
├── guides/
│   └── getting-started.md    # Quick start guide (coming soon)
└── assets/
    └── somer.png             # Architecture diagram
```

---

## Getting Started

1. Read the [Architecture Overview](architecture/overview.md) to understand the system
2. Check the [Roadmap](vision/roadmap.md) to see project status
3. Explore individual [module documentation](modules/)

---

## Implementation Status

| Module | Status | Tests | Documentation |
|--------|--------|-------|---------------|
| CLI & Installation | ✅ Complete | 29 | [Link](modules/installation.md) |
| Orchestrator | ✅ Complete | 28 | [Link](modules/orchestrator.md) |
| Code Engine | ✅ Complete | - | [Link](modules/code-engine.md) |
| LLM Integration | ✅ Complete | 17 | [Link](modules/llm-integration.md) |
| Memory System | ✅ Complete | 19 | [Link](modules/memory-system.md) |
| SDD Phases | ✅ Complete | - | Coming soon |
| Skill Registry | ✅ Complete | - | Coming soon |
| Agent System | ✅ Complete | 64 | [Link](modules/agent-system.md) |
| Skills Layer | ✅ Complete | - | Coming soon |
| Tools Layer | ✅ Complete | - | Coming soon |

**Total Tests: 157**

### Skills (21 registered)
- **File Skills**: read, write, list, search, delete, copy
- **HTTP Skills**: GET, POST, PUT, DELETE
- **Git Skills**: status, commit, push, pull, branch, log, diff
- **DB Skills**: query, execute, schema, create

### Agents (4 types)
- **CodeAgent**: Code generation, refactoring, testing
- **QAAgent**: Testing, code review, bug detection
- **APIAgent**: API design, endpoint generation, docs
- **LogicAgent**: Reasoning, planning, analysis

### Tools (3 types)
- **GitTool**: Low-level git command wrapper
- **ShellTool**: Safe shell command execution
- **BrowserTool**: Web page fetching and parsing

---

## Contributing to Docs

When adding documentation:

1. **Module docs** go in `docs/modules/`
2. **Architecture decisions** go in `docs/architecture/`
3. **Guides and tutorials** go in `docs/guides/`
4. **API references** go in `docs/api/`
5. **Images and diagrams** go in `docs/assets/`

### Documentation Template

```markdown
# Module Name

**Location:** `somer/path/to/module.py`

**Status:** ✅ Implemented | 🔄 In Progress | ❌ Pending

---

## Overview

Brief description of what this module does.

## Architecture

Diagram or description of internal structure.

## Usage

Code examples showing how to use the module.

## Configuration

Available configuration options.

## Testing

How to run tests for this module.

## Best Practices

Tips for using this module effectively.
```
