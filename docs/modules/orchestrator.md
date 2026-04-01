# Orchestrator Module

**Location:** `somer/core/orchestrator/orchestrator.py`

**Status:** ✅ Implemented | 28 tests passing

---

## Overview

The Orchestrator is the central coordination engine of SOMER. It receives structured input, routes to appropriate handlers based on execution mode, and returns deterministic output.

## Architecture

```
                    ┌─────────────────┐
                    │   SomerInput    │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │   ORCHESTRATOR  │
                    ├─────────────────┤
                    │  Policy Check   │
                    │  Mode Routing   │
                    │  Skill Matching │
                    │  Agent Dispatch │
                    │  Monitoring     │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │   SomerOutput   │
                    └─────────────────┘
```

---

## Input/Output Models

### SomerInput

```python
from pydantic import BaseModel
from enum import Enum

class ExecutionMode(str, Enum):
    PLAN = "plan"
    EXECUTE = "execute"
    CODE = "code"
    ANALYZE = "analyze"

class InputContext(BaseModel):
    memory: list[dict] = []
    constraints: list[str] = []
    environment: dict = {}

class SomerInput(BaseModel):
    goal: str                           # High-level objective
    task: str                           # Specific action
    context: InputContext = InputContext()
    mode: ExecutionMode = ExecutionMode.EXECUTE
```

### SomerOutput

```python
class TaskStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    PENDING = "pending"
    IN_PROGRESS = "in_progress"

class SomerOutput(BaseModel):
    status: TaskStatus
    mode: ExecutionMode
    result: dict = {}
    next_action: Optional[str] = None
    error: Optional[str] = None
```

---

## Execution Modes

### PLAN Mode

Breaks task into minimal steps without generating code.

```python
input = SomerInput(
    goal="Build authentication system",
    task="Create user login flow",
    mode=ExecutionMode.PLAN
)

# Output
{
    "status": "success",
    "mode": "plan",
    "result": {
        "steps": [
            {"id": 1, "action": "Create user model", "depends_on": []},
            {"id": 2, "action": "Add password hashing", "depends_on": [1]},
            {"id": 3, "action": "Create login endpoint", "depends_on": [2]}
        ]
    },
    "next_action": "execute"
}
```

### EXECUTE Mode

Solves using skills first, then agents if needed.

```python
input = SomerInput(
    goal="Read file contents",
    task="read config.json",
    mode=ExecutionMode.EXECUTE
)

# Execution flow:
# 1. Try matching skills (file skill matches "read")
# 2. If no skill, route to agent
# 3. If no agent, return error
```

### CODE Mode

Generates deterministic code following strict rules.

```python
input = SomerInput(
    goal="Generate API endpoint",
    task="Create user registration endpoint",
    context=InputContext(
        constraints=["use FastAPI", "include validation"]
    ),
    mode=ExecutionMode.CODE
)

# Output
{
    "status": "success",
    "mode": "code",
    "result": {
        "files": [{"path": "api/users.py", "content": "..."}],
        "explanation": "Created FastAPI endpoint with Pydantic validation"
    }
}
```

### ANALYZE Mode

Evaluates results and suggests optimizations.

```python
input = SomerInput(
    goal="Review code quality",
    task="Analyze authentication module",
    context=InputContext(
        memory=[...many items...]
    ),
    mode=ExecutionMode.ANALYZE
)

# Output includes recommendations
{
    "status": "success",
    "mode": "analyze",
    "result": {
        "task": "Analyze authentication module",
        "context_size": 1500,
        "constraints_count": 0,
        "recommendations": [
            "Consider compressing memory - too many items",
            "No constraints defined - add boundaries"
        ]
    }
}
```

---

## Module Registration

### Register Planner

```python
async def my_planner(goal: str, task: str, context: dict) -> list:
    return [
        {"id": 1, "action": "Step 1", "depends_on": []},
        {"id": 2, "action": "Step 2", "depends_on": [1]}
    ]

orchestrator.register_module("planner", my_planner)
```

### Register Code Engine

```python
async def my_code_engine(task: str, context: dict, constraints: list) -> dict:
    return {
        "files": [{"path": "main.py", "content": "..."}],
        "explanation": "Generated code"
    }

orchestrator.register_module("code_engine", my_code_engine)
```

### Register Skill

```python
async def file_read_skill(input_data: dict) -> dict:
    # Deterministic file reading
    path = extract_path(input_data["task"])
    content = Path(path).read_text()
    return {"content": content}

orchestrator.register_skill("read", file_read_skill)
```

### Register Agent

```python
async def code_agent(input_data: dict) -> dict:
    # Agent with LLM capabilities
    return {"result": "..."}

orchestrator.register_agent("code_agent", code_agent)
```

### Register Router

```python
async def my_router(task: str) -> str:
    if "code" in task.lower():
        return "code_agent"
    return "logic_agent"

orchestrator.register_module("router", my_router)
```

---

## Policy Enforcement

```python
async def security_policy(input_data: dict) -> bool:
    # Check constraints
    task = input_data["task"].lower()

    # Block dangerous operations
    if "delete" in task and "production" in task:
        return False

    return True

orchestrator.register_module("policy", security_policy)

# Now all executions are checked
result = await orchestrator.execute(input)
# Returns error if policy returns False
```

---

## Monitoring

```python
async def my_monitor(execution_data: dict) -> None:
    print(f"Task: {execution_data['task']}")
    print(f"Status: {execution_data['status']}")
    print(f"Has Error: {execution_data['has_error']}")

    # Log to external service
    await log_service.record(execution_data)

orchestrator.register_module("monitor", my_monitor)
```

---

## Configuration

```python
from somer.core.orchestrator import OrchestratorConfig, Orchestrator

config = OrchestratorConfig(
    max_retries=3,           # Retry failed operations
    timeout_seconds=300.0,   # 5 minute timeout
    enable_logging=True,     # Log to stdout
    strict_mode=True         # Fail on policy errors
)

orchestrator = Orchestrator(config=config)
```

---

## Factory Function

```python
from somer.core.orchestrator import create_orchestrator

# Quick creation with defaults
orch = create_orchestrator()

# Or with custom settings
orch = create_orchestrator(
    strict_mode=False,
    enable_logging=True
)
```

---

## Error Handling

The orchestrator handles errors gracefully:

```python
# Timeout handling
# If execution exceeds timeout_seconds, returns error

# Exception handling
# All exceptions are caught and returned as error status

# Policy violations
# Returns error with "Policy violation" message

# Missing modules
# Returns descriptive error about missing registration
```

---

## Testing

Run orchestrator tests:

```bash
PYTHONPATH="${PYTHONPATH}:$(pwd)" python3 -m pytest somer/tests/unit/core/test_orchestrator.py -v
```

**Test coverage:**
- Creation (3 tests)
- Input validation (2 tests)
- Plan mode (3 tests)
- Execute mode (3 tests)
- Code mode (3 tests)
- Analyze mode (3 tests)
- Policy enforcement (2 tests)
- Monitoring (2 tests)
- Module registration (3 tests)
- Error handling (2 tests)
- Output format (2 tests)

---

## Best Practices

1. **Always register policy** for production use
2. **Register skills before agents** (skills are preferred)
3. **Use descriptive task strings** for better skill matching
4. **Set appropriate timeouts** based on task complexity
5. **Monitor all executions** for debugging and metrics
