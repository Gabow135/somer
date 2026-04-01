# Agent System

**Location:** `somer/agents/`

**Status:** ✅ Implemented

---

## Overview

The Agent System provides specialized agents that handle specific types of tasks. Agents are the "workers" in SOMER's Delegate-First Architecture - the orchestrator delegates tasks to agents, which do the actual work.

Each agent:
- Specializes in a specific domain (code, QA, API, etc.)
- Can determine if it can handle a given task
- Uses LLM providers for complex reasoning
- Tracks execution metrics
- Supports retry logic and error handling

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Orchestrator                      │
│  (Delegates tasks, never does real work itself)     │
└─────────────────────┬───────────────────────────────┘
                      │
         ┌────────────┼────────────┐
         ▼            ▼            ▼
    ┌─────────┐  ┌─────────┐  ┌─────────┐
    │  Code   │  │   QA    │  │   API   │
    │  Agent  │  │  Agent  │  │  Agent  │
    └────┬────┘  └────┬────┘  └────┬────┘
         │            │            │
         ▼            ▼            ▼
    ┌─────────────────────────────────────┐
    │           LLM Provider              │
    │      (Claude / Mock / etc.)         │
    └─────────────────────────────────────┘
```

---

## Components

### BaseAgent

Abstract base class that all agents inherit from.

```python
from agents import BaseAgent, AgentConfig, AgentResult

class MyAgent(BaseAgent):
    def __init__(self, llm: LLMProvider):
        config = AgentConfig(
            name="my_agent",
            description="Does something useful",
            capabilities=["task1", "task2"],
            keywords=["keyword1", "keyword2"],
            max_retries=3,
            timeout=120.0,
            require_llm=True
        )
        super().__init__(config, llm)

    async def _execute(self, input_data: SomerInput) -> AgentResult:
        # Implementation here
        return AgentResult(success=True, data={"result": "done"})

    def can_handle(self, task: str) -> bool:
        return "keyword1" in task.lower()
```

### AgentConfig

Configuration for agent behavior.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | str | required | Unique agent identifier |
| `description` | str | required | What the agent does |
| `capabilities` | list[str] | [] | List of capabilities |
| `keywords` | list[str] | [] | Keywords that trigger this agent |
| `max_retries` | int | 3 | Retry attempts on failure |
| `timeout` | float | 120.0 | Execution timeout in seconds |
| `require_llm` | bool | True | Whether LLM is required |

### AgentResult

Result from agent execution.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `success` | bool | required | Whether execution succeeded |
| `data` | dict | required | Result data |
| `error` | str | None | Error message if failed |
| `execution_time_ms` | float | 0.0 | Execution time |
| `retries` | int | 0 | Number of retries used |

---

## Available Agents

### CodeAgent

Specialized agent for code-related tasks.

**Location:** `somer/agents/code_agent.py`

**Capabilities:**
- Generate code from descriptions
- Refactor existing code
- Fix bugs
- Generate tests
- Add documentation

**Supported Languages:**
- Python, TypeScript, JavaScript
- Go, Rust, Java
- C, C++, Ruby, PHP

**Usage:**

```python
from agents import CodeAgent
from tools.llm import ClaudeProvider

# Create with LLM provider
llm = ClaudeProvider()
agent = CodeAgent(llm=llm)

# Create input
input_data = SomerInput(
    goal="Create utility functions",
    task="Create a function to validate email addresses"
)

# Execute
output = await agent.execute(input_data)

# Access results
print(output.result["code"])
print(output.result["language"])
print(output.result["explanation"])
```

**Operations:**

| Keyword | Operation | Description |
|---------|-----------|-------------|
| `generate`, `create` | Generate | Create new code |
| `refactor`, `improve` | Refactor | Improve existing code |
| `fix`, `bug`, `error` | Fix | Fix bugs |
| `test`, `unittest` | Test | Generate tests |
| `document`, `docstring` | Document | Add documentation |

---

## Testing Without LLM

Use `MockCodeAgent` for testing without external dependencies:

```python
from agents import MockCodeAgent

# Default mock responses
agent = MockCodeAgent()
output = await agent.execute(input_data)

# Custom mock responses
responses = {
    "validation": {
        "code": "def validate(): return True",
        "language": "python"
    }
}
agent = MockCodeAgent(responses=responses)
```

---

## Creating Custom Agents

### Step 1: Define Agent Class

```python
from agents.base import BaseAgent, AgentConfig, AgentResult

class MyCustomAgent(BaseAgent):
    KEYWORDS = ["custom", "my", "special"]

    def __init__(self, llm: Optional[LLMProvider] = None):
        config = AgentConfig(
            name="my_custom_agent",
            description="Handles custom tasks",
            capabilities=[
                "Do something special",
                "Handle custom requests"
            ],
            keywords=self.KEYWORDS,
            max_retries=2,
            timeout=60.0,
            require_llm=True
        )
        super().__init__(config, llm)
```

### Step 2: Implement can_handle

```python
def can_handle(self, task: str) -> bool:
    """Determine if this agent can handle the task."""
    task_lower = task.lower()

    # Check keywords
    if self.matches_keywords(task):
        return True

    # Add custom logic
    if "special pattern" in task_lower:
        return True

    return False
```

### Step 3: Implement _execute

```python
async def _execute(self, input_data: SomerInput) -> AgentResult:
    """Execute the task."""
    try:
        # Build prompt
        prompt = f"Task: {input_data.task}\nGoal: {input_data.goal}"

        # Call LLM
        response = await self.generate_with_llm(
            prompt=prompt,
            system="You are a helpful assistant.",
            temperature=0.1
        )

        # Parse and return result
        return AgentResult(
            success=True,
            data={"result": response}
        )

    except Exception as e:
        return AgentResult(
            success=False,
            data={},
            error=str(e)
        )
```

---

## Agent Lifecycle

```
┌──────────────────────────────────────────────────────┐
│                      execute()                        │
│  1. Validate input                                   │
│  2. Check LLM availability                           │
│  3. Call _execute_with_retry()                       │
│  4. Track metrics                                    │
│  5. Return SomerOutput                               │
└─────────────────────┬────────────────────────────────┘
                      │
                      ▼
┌──────────────────────────────────────────────────────┐
│               _execute_with_retry()                   │
│  For attempt in range(max_retries):                  │
│    try:                                              │
│      result = await _execute(input_data)             │
│      return result                                   │
│    except Exception:                                 │
│      wait(exponential_backoff)                       │
│      continue                                        │
└─────────────────────┬────────────────────────────────┘
                      │
                      ▼
┌──────────────────────────────────────────────────────┐
│                   _execute()                          │
│  (Abstract - implemented by each agent)              │
│  - Process task                                      │
│  - Call LLM if needed                                │
│  - Return AgentResult                                │
└──────────────────────────────────────────────────────┘
```

---

## Metrics & Monitoring

Agents track execution statistics:

```python
stats = agent.get_stats()

# Returns:
{
    "name": "code_agent",
    "executions": 100,
    "errors": 5,
    "total_time_ms": 50000.0,
    "avg_time_ms": 500.0,
    "error_rate": 0.05
}
```

---

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SOMER_AGENT_TIMEOUT` | Default agent timeout | 120.0 |
| `SOMER_AGENT_RETRIES` | Default retry count | 3 |

---

## Best Practices

1. **Single Responsibility**: Each agent should handle one domain
2. **Clear Keywords**: Use specific keywords to avoid conflicts
3. **Mock for Tests**: Use mock agents for unit testing
4. **Handle Errors**: Return AgentResult with error info
5. **Track Metrics**: Use built-in stats for monitoring

---

## Testing

Run agent tests:

```bash
# All agent tests
PYTHONPATH=. python3 -m pytest tests/unit/agents/ -v

# Specific test file
PYTHONPATH=. python3 -m pytest tests/unit/agents/test_code_agent.py -v
```

**Test Count:** 64 tests

---

## API Reference

### BaseAgent Methods

| Method | Description |
|--------|-------------|
| `execute(input_data)` | Execute task with error handling |
| `can_handle(task)` | Check if agent can handle task |
| `matches_keywords(task)` | Check if task matches keywords |
| `generate_with_llm(prompt, ...)` | Generate text using LLM |
| `get_stats()` | Get execution statistics |

### CodeAgent Methods

| Method | Description |
|--------|-------------|
| `_generate_code(input, lang)` | Generate new code |
| `_refactor_code(input, lang)` | Refactor existing code |
| `_fix_code(input, lang)` | Fix bugs in code |
| `_generate_tests(input, lang)` | Generate tests |
| `_add_documentation(input, lang)` | Add documentation |
| `_detect_language(task)` | Detect programming language |

---

## Next Steps

After understanding the Agent System:

1. See [Orchestrator](orchestrator.md) for how agents are coordinated
2. See [LLM Integration](llm-integration.md) for LLM provider details
3. See [Memory System](memory-system.md) for context management
