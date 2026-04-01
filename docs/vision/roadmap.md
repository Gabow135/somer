# SOMER Vision & Roadmap

## Vision

SOMER representa un cambio de paradigma en cómo los sistemas de IA ejecutan tareas. En lugar de depender completamente del LLM para cada decisión, SOMER utiliza el LLM como **último recurso**, priorizando:

1. **Ejecución determinística** sobre razonamiento probabilístico
2. **Skills codificados** sobre inferencia LLM
3. **Memoria estructurada** sobre contexto en prompt
4. **Templates validados** sobre generación libre

### Objetivo Final

Un sistema cognitivo que:
- Minimiza costos de tokens en 70-90%
- Produce outputs 100% reproducibles
- Escala horizontalmente
- Se auto-optimiza

---

## Roadmap

### Phase 1: Foundation ✅ (Current)

**Estado:** En progreso

| Componente | Estado | Archivo |
|------------|--------|---------|
| Project Structure | ✅ Completo | `somer/` |
| Configuration | ✅ Completo | `core/config/settings.py` |
| Orchestrator Core | ✅ Completo | `core/orchestrator/orchestrator.py` |
| Code Engine Base | ✅ Completo | `engine/code_engine/generator.py` |
| Master Prompt | ✅ Completo | `prompts/somer_master.md` |
| Test Framework | ✅ Completo | `tests/` (28 tests passing) |

**Deliverables:**
- [x] Estructura de proyecto
- [x] Orchestrator con 4 modos (PLAN/EXECUTE/CODE/ANALYZE)
- [x] Code Generator con reglas estrictas
- [x] Test suite con 100% coverage del orchestrator
- [x] Documentación base

---

### Phase 2: Memory System

**Estado:** Pendiente

| Componente | Descripción |
|------------|-------------|
| `memory/manager.py` | Coordinador de memoria |
| `memory/short_term/` | Redis integration |
| `memory/long_term/` | SQLite persistence |
| `memory/pipeline/` | Ingest → Compress → Store → Query → Forget |

**Tasks:**
- [ ] Redis connection wrapper
- [ ] SQLite schema + migrations
- [ ] Memory manager con routing
- [ ] Compression algorithm
- [ ] TTL-based forgetting
- [ ] Tests unitarios

---

### Phase 3: LLM Integration

**Estado:** Pendiente

| Componente | Descripción |
|------------|-------------|
| `tools/llm/claude.py` | Claude API wrapper |
| `tools/llm/router.py` | Multi-provider routing |
| `core/context/builder.py` | Context minimization |
| `core/context/compressor.py` | Token reduction |

**Tasks:**
- [ ] Claude API async wrapper
- [ ] Rate limiting + retries
- [ ] Context window management
- [ ] Token counting
- [ ] Response parsing
- [ ] Tests con mocks

---

### Phase 4: Agent System

**Estado:** Pendiente

| Componente | Descripción |
|------------|-------------|
| `agents/base_agent.py` | Base class para agentes |
| `agents/code_agent.py` | Generación de código |
| `agents/qa_agent.py` | Quality assurance |
| `agents/api_agent.py` | HTTP interactions |
| `agents/logic_agent.py` | Reasoning tasks |

**Tasks:**
- [ ] Base agent interface
- [ ] Agent lifecycle management
- [ ] Inter-agent communication
- [ ] Agent-specific prompts
- [ ] Tests por agente

---

### Phase 5: Skills Layer

**Estado:** Pendiente

| Componente | Descripción |
|------------|-------------|
| `skills/file/` | Read, Write, Search |
| `skills/db/` | Query, Insert, Update |
| `skills/http/` | REST client |
| `skills/git/` | Version control ops |
| `skills/code/` | Execute, Validate |

**Tasks:**
- [ ] Skill registry + discovery
- [ ] Async execution wrappers
- [ ] Error handling standarizado
- [ ] Skill composition
- [ ] Tests por skill

---

### Phase 6: Self-Refinement

**Estado:** Futuro

| Componente | Descripción |
|------------|-------------|
| Self-Plan | Descomposición automática de tareas |
| Self-Test | Validación automática de outputs |
| Self-Correct | Corrección de errores sin intervención |

---

### Phase 7: Rust Engine (Performance)

**Estado:** Futuro

| Componente | Descripción |
|------------|-------------|
| `rust_engine/context_compressor/` | Compresión de alta velocidad |
| `rust_engine/memory_indexer/` | Indexación semántica |
| `rust_engine/data_pipeline/` | ETL optimizado |

---

## Implementation Priority

```
HIGH PRIORITY
─────────────────────────────────────────────
1. Memory System (ENGRAM++)
   └── Foundation para todo lo demás

2. LLM Integration (Claude)
   └── Necesario para Code Engine completo

3. Skills Layer (File + DB)
   └── Reduce dependencia de LLM

MEDIUM PRIORITY
─────────────────────────────────────────────
4. Agent System
   └── Especialización de tareas

5. Context Builder
   └── Optimización de tokens

LOW PRIORITY (Future)
─────────────────────────────────────────────
6. Self-Refinement
7. Rust Engine
8. Browser Agent
```

---

## Success Metrics

| Metric | Target | Current |
|--------|--------|---------|
| Token usage reduction | 70% | N/A |
| Output determinism | 100% | N/A |
| Test coverage | >90% | 100% (orchestrator) |
| Skill-first resolution | >80% | N/A |
| Memory query latency | <50ms | N/A |

---

## Design Principles

### 1. Determinism First
- Prefer coded solutions over LLM inference
- Validate all outputs against schemas
- Use templates with strict rules

### 2. Token Economy
- Compress context before sending
- Cache repeated patterns
- Forget irrelevant memories

### 3. Modularity
- Each module independent
- Clear interfaces (Pydantic)
- Swappable implementations

### 4. Test Everything
- Unit tests por módulo
- Integration tests por flujo
- No code sin tests

### 5. Document Everything
- Architecture decisions
- API contracts
- Usage examples

---

## Contributing

### Adding a New Module

1. Create directory in appropriate location
2. Implement with Pydantic models
3. Write tests (>90% coverage)
4. Document in `docs/modules/`
5. Update roadmap

### Code Standards

```python
# Always use type hints
async def process(input: SomerInput) -> SomerOutput:
    ...

# Always handle errors
try:
    result = await operation()
except SpecificError as e:
    logger.error(f"Operation failed: {e}")
    raise

# Always log important actions
logger.info(f"Processing task: {task}")
```

---

## Timeline (Estimated)

| Phase | Duration | Dependencies |
|-------|----------|--------------|
| Phase 1 (Foundation) | ✅ Complete | None |
| Phase 2 (Memory) | 1-2 weeks | Redis, SQLite |
| Phase 3 (LLM) | 1 week | Anthropic API |
| Phase 4 (Agents) | 2 weeks | LLM Integration |
| Phase 5 (Skills) | 2 weeks | None |
| Phase 6 (Self-Refinement) | 3 weeks | All above |

---

## Questions for Future Decisions

1. **Vector DB**: Pinecone vs Chroma vs Weaviate?
2. **Multi-LLM**: Support OpenAI as fallback?
3. **Scaling**: Kubernetes vs simple async workers?
4. **UI**: CLI only vs Web dashboard?
