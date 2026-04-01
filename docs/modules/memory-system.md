# Memory System (ENGRAM++)

**Location:** `memory/`

**Status:** ✅ Implemented | Tests: 19

---

## Overview

ENGRAM++ is SOMER's multi-tier memory system that provides:

- Short-term memory (Redis)
- Long-term memory (SQLite)
- Semantic memory (Vector DB - future)
- Memory pipeline (ingest → compress → store → query → forget)

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    MEMORY MANAGER                            │
│                     (ENGRAM++)                               │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                  MEMORY TYPES                         │   │
│  ├────────────┬────────────┬────────────┬───────────────┤   │
│  │   SHORT    │    LONG    │  SEMANTIC  │  PROCEDURAL   │   │
│  │   Redis    │   SQLite   │  Vector DB │    SQLite     │   │
│  │   1 hour   │   7 days   │  Permanent │   Permanent   │   │
│  └────────────┴────────────┴────────────┴───────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                 MEMORY PIPELINE                       │   │
│  │                                                       │   │
│  │   INGEST → COMPRESS → STORE → QUERY → FORGET         │   │
│  │                                                       │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## Installation

```bash
# For Redis support
pip install redis

# For SQLite async support
pip install aiosqlite

# Both are optional - InMemoryStore works as fallback
```

---

## Memory Types

| Type | Storage | TTL | Use Case |
|------|---------|-----|----------|
| SHORT | Redis | 1 hour | Current session context |
| LONG | SQLite | 7 days | Persistent task data |
| SEMANTIC | Vector DB | Permanent | Knowledge base |
| PROCEDURAL | SQLite | Permanent | How-to patterns |
| EPISODIC | SQLite | Variable | Task-specific memories |

---

## Usage

### Basic Operations

```python
from memory.manager import get_memory_manager, MemoryQuery
from _shared.types import MemoryType

# Get global manager
memory = get_memory_manager()

# Store a value
item = await memory.store(
    key="user:preferences",
    value={"theme": "dark", "language": "es"},
    memory_type=MemoryType.SHORT,
    ttl=3600,  # 1 hour
    tags=["user", "config"],
    priority=5
)

# Retrieve a value
value = await memory.retrieve("user:preferences")
print(value)  # {"theme": "dark", "language": "es"}

# Delete a value
deleted = await memory.delete("user:preferences")
```

### Search Operations

```python
from memory.manager import MemoryQuery

# Search by pattern
query = MemoryQuery(
    pattern="user",
    memory_type=MemoryType.SHORT,
    min_priority=3,
    limit=10
)
results = await memory.search(query)

for item in results:
    print(f"{item.key}: {item.value}")
```

### Memory Compression

```python
# Compress memory (removes low-priority items)
removed = await memory.compress()
print(f"Removed {removed} items")
```

### Forget Operations

```python
from datetime import datetime, timedelta

# Forget by type
await memory.forget(memory_type=MemoryType.SHORT)

# Forget by age
old_date = datetime.utcnow() - timedelta(days=7)
await memory.forget(older_than=old_date)

# Forget by tags
await memory.forget(tags=["temporary"])
```

---

## Storage Backends

### InMemoryStore (Default Fallback)

```python
from memory.stores.redis_store import InMemoryStore

store = InMemoryStore(default_ttl=3600)

await store.store("key", {"data": "value"}, ttl=60)
value = await store.retrieve("key")
await store.delete("key")
```

### Redis Store

```python
from memory.stores.redis_store import RedisStore

store = RedisStore(
    url="redis://localhost:6379/0",
    prefix="somer:",
    default_ttl=3600
)

await store.connect()
await store.store("key", {"data": "value"})
value = await store.retrieve("key")
await store.disconnect()
```

### SQLite Store

```python
from memory.stores.sqlite_store import SQLiteStore

store = SQLiteStore(
    db_path="./data/memory.db",
    table_name="memories"
)

await store.connect()
await store.store("key", {"data": "value"})
value = await store.retrieve("key")

# Search by type
results = await store.search_by_type("long", limit=100)

# Cleanup expired
cleaned = await store.cleanup_expired()

await store.disconnect()
```

---

## Registering Stores

```python
from memory.manager import MemoryManager
from memory.stores.redis_store import RedisStore, InMemoryStore
from memory.stores.sqlite_store import SQLiteStore
from _shared.types import MemoryType

# Create manager
memory = MemoryManager()

# Register Redis for short-term
redis_store = RedisStore(url="redis://localhost:6379/0")
memory.register_store(MemoryType.SHORT, redis_store)

# Register SQLite for long-term
sqlite_store = SQLiteStore(db_path="./data/memory.db")
memory.register_store(MemoryType.LONG, sqlite_store)

# Or use InMemory as fallback
fallback = InMemoryStore()
memory.register_store(MemoryType.SHORT, fallback)
```

---

## MemoryItem Structure

```python
@dataclass
class MemoryItem:
    id: UUID                    # Unique identifier
    key: str                    # Storage key
    value: Any                  # Stored value
    memory_type: MemoryType     # Type of memory
    created_at: datetime        # Creation time
    accessed_at: datetime       # Last access time
    access_count: int           # Number of accesses
    ttl: Optional[int]          # Time to live (seconds)
    tags: list[str]             # Tags for searching
    priority: int               # Priority (higher = more important)
    compressed: bool            # Is compressed?
```

---

## Statistics

```python
stats = memory.get_stats()
# {
#     "stores": 2,
#     "reads": 150,
#     "writes": 50,
#     "deletes": 10,
#     "compressions": 2,
#     "in_memory_items": 25,
#     "registered_stores": ["short", "long"]
# }
```

---

## Integration with Orchestrator

```python
from core.orchestrator.orchestrator import create_orchestrator
from memory.manager import get_memory_manager
from _shared.types import MemoryType

# Get memory manager
memory = get_memory_manager()

# Create planner that uses memory
async def memory_planner(goal: str, task: str, context: dict) -> list:
    # Store task in memory
    await memory.store(
        key=f"task:{task[:20]}",
        value={"goal": goal, "task": task},
        memory_type=MemoryType.SHORT,
        tags=["planning"]
    )

    # Check for similar past tasks
    query = MemoryQuery(pattern="task", limit=5)
    similar = await memory.search(query)

    # Generate steps
    steps = [
        {"id": 1, "action": f"Analyze: {task}"},
        {"id": 2, "action": "Design solution"},
    ]

    if similar:
        steps.insert(1, {
            "id": 3,
            "action": f"Review {len(similar)} similar tasks"
        })

    return steps

# Register with orchestrator
orch = create_orchestrator()
orch.register_module("planner", memory_planner)
```

---

## Best Practices

### 1. Use Appropriate Memory Types

```python
# Session data → SHORT
await memory.store("session:user", data, memory_type=MemoryType.SHORT)

# Task history → LONG
await memory.store("task:completed", data, memory_type=MemoryType.LONG)

# Knowledge → SEMANTIC (when available)
await memory.store("knowledge:api", data, memory_type=MemoryType.SEMANTIC)
```

### 2. Use Tags for Searching

```python
await memory.store(
    key="context:123",
    value=data,
    tags=["context", "project:somer", "priority:high"]
)

# Later, search by tags
query = MemoryQuery(tags=["project:somer"])
results = await memory.search(query)
```

### 3. Set Priorities

```python
# Critical data: high priority
await memory.store("error:critical", data, priority=10)

# Nice to have: low priority
await memory.store("log:debug", data, priority=1)

# During compression, low priority items are removed first
```

### 4. Regular Cleanup

```python
# Periodically compress memory
await memory.compress()

# Forget old memories
await memory.forget(memory_type=MemoryType.SHORT)
```

---

## Testing

```bash
# Run memory tests
PYTHONPATH="${PYTHONPATH}:$(pwd)" python3 -m pytest tests/unit/memory/ -v
```

---

## Configuration

Environment variables:

```bash
# Redis
REDIS_URL=redis://localhost:6379/0

# SQLite
SQLITE_PATH=./data/somer_memory.db

# Memory limits
MEMORY_MAX_ITEMS=100
MEMORY_COMPRESSION_THRESHOLD=50
```
