# SOMER Structure v2

Estructura mejorada incorporando patrones de agent-teams-lite y preparación para Rust Engine.

---

## Principios de Diseño

### 1. Delegate-First Architecture
El orchestrator **NUNCA** ejecuta trabajo real. Solo:
- Delega a sub-agentes/skills
- Recolecta y sintetiza resultados
- Mantiene contexto mínimo
- Trackea estado entre transiciones

### 2. SDD DAG (Spec-Driven Development)
Flujo de fases secuenciales:
```
explore → propose → spec → design → tasks → apply → verify → archive
```

### 3. Skill Registry Pattern
Registro centralizado de skills con:
- Auto-discovery
- Inyección automática de estándares
- Composición de skills

### 4. Rust-Ready Architecture
Estructura preparada para migrar componentes críticos a Rust:
- Interfaces bien definidas (traits)
- Separación clara de concerns
- Bindings Python ↔ Rust via PyO3

---

## Nueva Estructura

```
somer/
│
├── _shared/                      # 🔗 Recursos compartidos
│   ├── __init__.py
│   ├── types.py                  # Tipos base (Pydantic)
│   ├── errors.py                 # Excepciones custom
│   ├── protocols.py              # Interfaces/Protocols
│   └── constants.py              # Constantes globales
│
├── core/                         # 🧠 Núcleo del sistema
│   ├── __init__.py
│   ├── orchestrator/
│   │   ├── __init__.py
│   │   ├── orchestrator.py       # Coordinator principal
│   │   ├── delegator.py          # Delegate-first logic
│   │   ├── state.py              # State machine
│   │   └── dag.py                # DAG de ejecución
│   │
│   ├── context/
│   │   ├── __init__.py
│   │   ├── builder.py            # Context assembly
│   │   ├── compressor.py         # Token reduction
│   │   └── selector.py           # Relevance selection
│   │
│   └── config/
│       ├── __init__.py
│       ├── settings.py           # Configuration
│       └── registry.py           # Central registry
│
├── phases/                       # 📋 SDD Phases (DAG)
│   ├── __init__.py
│   ├── _base.py                  # Base phase class
│   ├── explore.py                # 1. Exploración
│   ├── propose.py                # 2. Propuesta
│   ├── spec.py                   # 3. Especificación
│   ├── design.py                 # 4. Diseño
│   ├── tasks.py                  # 5. Breakdown de tareas
│   ├── apply.py                  # 6. Implementación
│   ├── verify.py                 # 7. Verificación
│   └── archive.py                # 8. Archivo/Cierre
│
├── skills/                       # 🧰 Skill Registry
│   ├── __init__.py
│   ├── registry.py               # Skill discovery & registry
│   ├── _base.py                  # Base skill class
│   │
│   ├── file/                     # File operations
│   │   ├── __init__.py
│   │   ├── SKILL.md              # Skill definition
│   │   ├── read.py
│   │   ├── write.py
│   │   └── search.py
│   │
│   ├── db/                       # Database operations
│   │   ├── __init__.py
│   │   ├── SKILL.md
│   │   └── query.py
│   │
│   ├── http/                     # HTTP client
│   │   ├── __init__.py
│   │   ├── SKILL.md
│   │   └── client.py
│   │
│   ├── git/                      # Git operations
│   │   ├── __init__.py
│   │   ├── SKILL.md
│   │   ├── commit.py
│   │   ├── branch.py
│   │   └── pr.py
│   │
│   └── code/                     # Code operations
│       ├── __init__.py
│       ├── SKILL.md
│       ├── execute.py
│       └── validate.py
│
├── agents/                       # 🤖 Sub-agents (delegados)
│   ├── __init__.py
│   ├── _base.py                  # Base agent class
│   ├── registry.py               # Agent registry
│   ├── code_agent.py             # Code generation
│   ├── qa_agent.py               # Quality assurance
│   ├── api_agent.py              # API interactions
│   ├── browser_agent.py          # Browser automation
│   └── logic_agent.py            # Reasoning
│
├── engine/                       # ⚙️ Code Generation
│   ├── __init__.py
│   ├── generator.py              # Main generator
│   ├── validator.py              # Code validation
│   ├── templates/
│   │   ├── __init__.py
│   │   ├── registry.py           # Template registry
│   │   ├── python/
│   │   ├── typescript/
│   │   └── rust/
│   └── rules/
│       ├── __init__.py
│       ├── style.py
│       ├── security.py
│       └── constraints.py
│
├── memory/                       # 🧬 ENGRAM++ Memory System
│   ├── __init__.py
│   ├── manager.py                # Memory coordinator
│   ├── types.py                  # Memory types
│   │
│   ├── stores/                   # Storage backends
│   │   ├── __init__.py
│   │   ├── _base.py              # Store interface
│   │   ├── redis.py              # Short-term (Redis)
│   │   ├── sqlite.py             # Long-term (SQLite)
│   │   └── vector.py             # Semantic (Vector DB)
│   │
│   └── pipeline/                 # Memory pipeline
│       ├── __init__.py
│       ├── ingest.py             # Canvas
│       ├── compress.py           # Compress
│       ├── store.py              # Store
│       ├── query.py              # Query
│       └── forget.py             # Forget
│
├── llm/                          # 🤖 LLM Providers
│   ├── __init__.py
│   ├── _base.py                  # Provider interface
│   ├── router.py                 # Multi-provider routing
│   ├── claude.py                 # Anthropic Claude
│   ├── openai.py                 # OpenAI (fallback)
│   └── cache.py                  # Response caching
│
├── runtime/                      # ⚡ Execution Layer
│   ├── __init__.py
│   ├── executor.py               # Task executor
│   ├── scheduler.py              # Task scheduling
│   └── worker.py                 # Worker pool
│
├── rust_engine/                  # 🦀 Rust Performance Layer
│   ├── Cargo.toml                # Rust project config
│   ├── src/
│   │   ├── lib.rs                # Library entry
│   │   ├── compressor/           # High-speed compression
│   │   │   ├── mod.rs
│   │   │   └── text.rs
│   │   ├── indexer/              # Memory indexing
│   │   │   ├── mod.rs
│   │   │   └── semantic.rs
│   │   ├── pipeline/             # Data pipeline
│   │   │   ├── mod.rs
│   │   │   └── transform.rs
│   │   └── tokenizer/            # Fast tokenization
│   │       ├── mod.rs
│   │       └── bpe.rs
│   │
│   └── python/                   # PyO3 bindings
│       ├── __init__.py
│       └── bindings.py
│
├── prompts/                      # 🧾 Versioned Prompts
│   ├── somer_master.md
│   ├── code_engine.md
│   ├── phases/
│   │   ├── explore.md
│   │   ├── propose.md
│   │   ├── spec.md
│   │   ├── design.md
│   │   ├── tasks.md
│   │   ├── apply.md
│   │   ├── verify.md
│   │   └── archive.md
│   └── agents/
│       ├── code_agent.md
│       └── qa_agent.md
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── unit/
│   │   ├── core/
│   │   ├── phases/
│   │   ├── skills/
│   │   ├── agents/
│   │   ├── engine/
│   │   └── memory/
│   └── integration/
│       ├── test_full_dag.py
│       └── test_delegate_flow.py
│
├── scripts/
│   ├── setup.py
│   ├── migrate.py
│   └── build_rust.py
│
├── docker/
│   ├── Dockerfile
│   ├── Dockerfile.rust
│   └── docker-compose.yml
│
├── pyproject.toml
├── Cargo.toml                    # Workspace for Rust
└── README.md
```

---

## Flujo de Ejecución (SDD DAG)

```
┌─────────────────────────────────────────────────────────────────┐
│                        ORCHESTRATOR                              │
│                    (Delegate-First)                              │
└─────────────────────────────────────────────────────────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         │                    │                    │
         ▼                    ▼                    ▼
   ┌──────────┐        ┌──────────┐        ┌──────────┐
   │  PHASES  │        │  SKILLS  │        │  AGENTS  │
   │   (DAG)  │        │(Registry)│        │(Delegated)│
   └────┬─────┘        └────┬─────┘        └────┬─────┘
        │                   │                   │
        ▼                   ▼                   ▼
┌───────────────────────────────────────────────────────────┐
│                                                           │
│  explore → propose → spec → design → tasks → apply →     │
│                                                           │
│                    → verify → archive                     │
│                                                           │
└───────────────────────────────────────────────────────────┘
```

---

## Skill Registry Pattern

Cada skill tiene un archivo `SKILL.md` que define:

```markdown
# Skill: file/read

## Trigger
Keywords: read, open, load, fetch file

## Capabilities
- Read text files
- Read binary files
- Read with encoding

## Input
- path: string (required)
- encoding: string (optional, default: utf-8)

## Output
- content: string
- metadata: FileMetadata

## Dependencies
- None (pure Python)
```

El registry auto-descubre skills y los inyecta según el contexto.

---

## Rust Engine Integration

### Python → Rust (Hot Path)

```python
# Python code calls Rust for performance-critical operations
from somer.rust_engine.python import compress_text, tokenize

# Fast compression
compressed = compress_text(large_context)

# Fast tokenization
tokens = tokenize(text, model="claude")
```

### Build Process

```bash
# Build Rust engine
cd somer/rust_engine
cargo build --release

# Install Python bindings
maturin develop
```

---

## Migration Path

### Phase 1: Reorganize Python
1. Crear `_shared/` con tipos comunes
2. Crear `phases/` con SDD phases
3. Actualizar `skills/` con registry pattern
4. Añadir `SKILL.md` a cada skill

### Phase 2: Add Rust Engine (stub)
1. Crear estructura `rust_engine/`
2. Implementar compressor básico
3. Crear bindings PyO3

### Phase 3: Gradual Migration
1. Identificar hot paths
2. Migrar a Rust
3. Benchmark y optimizar

---

## Comparación

| Aspecto | v1 (actual) | v2 (mejorado) |
|---------|-------------|---------------|
| Orchestrator | Hace trabajo | Solo delega |
| Skills | Lista plana | Registry + SKILL.md |
| Phases | Implícitas | DAG explícito |
| Rust | Futuro | Estructura lista |
| Shared | Disperso | `_shared/` centralizado |
