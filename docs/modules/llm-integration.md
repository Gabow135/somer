# LLM Integration Module

**Location:** `tools/llm/claude.py`

**Status:** ✅ Implemented | Tests: 15+

---

## Overview

The LLM Integration module provides an async wrapper for the Anthropic Claude API with:

- Automatic retries with exponential backoff
- Response caching
- Token counting
- Rate limit handling
- Mock provider for testing

## Architecture

```
┌─────────────────────────────────────────────────┐
│              LLM INTEGRATION                     │
├─────────────────────────────────────────────────┤
│                                                  │
│  ┌──────────────┐    ┌──────────────────────┐   │
│  │   Request    │    │   ClaudeConfig       │   │
│  │   Handler    │───▶│   - api_key          │   │
│  └──────────────┘    │   - model            │   │
│                      │   - temperature      │   │
│  ┌──────────────┐    │   - max_retries      │   │
│  │   Response   │    └──────────────────────┘   │
│  │   Cache      │                               │
│  └──────────────┘    ┌──────────────────────┐   │
│                      │   Retry Logic        │   │
│  ┌──────────────┐    │   - Exponential      │   │
│  │   Token      │    │   - Rate limit aware │   │
│  │   Counter    │    └──────────────────────┘   │
│  └──────────────┘                               │
│                                                  │
└─────────────────────────────────────────────────┘
```

---

## Installation

```bash
# Install anthropic package
pip install anthropic

# Configure API key
export ANTHROPIC_API_KEY=your_api_key_here
```

---

## Usage

### Basic Usage

```python
from tools.llm.claude import create_claude_provider

# Create provider
provider = create_claude_provider(
    api_key="your_api_key",
    model="claude-sonnet-4-20250514",
    temperature=0.1  # Low for deterministic output
)

# Generate text
response = await provider.generate(
    prompt="Create a REST API endpoint for users",
    system="You are a code generator. Return valid JSON."
)

print(response)
```

### With Custom Configuration

```python
from tools.llm.claude import ClaudeProvider, ClaudeConfig

config = ClaudeConfig(
    api_key="your_api_key",
    model="claude-sonnet-4-20250514",
    max_tokens=4096,
    temperature=0.1,
    timeout=60.0,
    max_retries=3,
    retry_delay=1.0,
    enable_cache=True,
    cache_ttl=3600  # 1 hour
)

provider = ClaudeProvider(config)

response = await provider.generate(
    prompt="Your prompt",
    system="Your system instructions",
    max_tokens=2000,  # Override for this call
    temperature=0.0   # Override for this call
)
```

### Token Counting

```python
# Estimate tokens in text
token_count = await provider.count_tokens("Your text here")
print(f"Estimated tokens: {token_count}")
```

### Caching

```python
# Responses are cached automatically
response1 = await provider.generate("same prompt", "same system")
response2 = await provider.generate("same prompt", "same system")
# response2 comes from cache (instant)

# Clear cache
cleared = provider.clear_cache()
print(f"Cleared {cleared} cache entries")
```

### Statistics

```python
stats = provider.get_stats()
# {
#     "provider": "claude",
#     "model": "claude-sonnet-4-20250514",
#     "request_count": 10,
#     "total_tokens": 5000,
#     "cache_entries": 5,
#     "cache_enabled": True
# }
```

---

## Mock Provider for Testing

```python
from tools.llm.claude import MockClaudeProvider

# Create mock with predefined responses
mock = MockClaudeProvider(responses={
    "code": '{"files": [{"path": "main.py", "content": "..."}]}',
    "fix": '{"action": "fixed", "changes": [...]}',
    "analyze": '{"issues": [], "suggestions": [...]}'
})

# Use like real provider
response = await mock.generate(
    prompt="Generate code for API",
    system="You are a coder"
)
# Returns: '{"files": [{"path": "main.py", "content": "..."}]}'

# Check calls made
print(mock.calls)  # List of all calls with prompts, systems, etc.
```

---

## Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `api_key` | str | required | Anthropic API key |
| `model` | str | claude-sonnet-4-20250514 | Model to use |
| `max_tokens` | int | 4096 | Max output tokens |
| `temperature` | float | 0.1 | Output randomness (0-1) |
| `timeout` | float | 60.0 | Request timeout (seconds) |
| `max_retries` | int | 3 | Max retry attempts |
| `retry_delay` | float | 1.0 | Base delay between retries |
| `enable_cache` | bool | True | Enable response caching |
| `cache_ttl` | int | 3600 | Cache TTL (seconds) |

---

## Error Handling

```python
from _shared.errors import LLMError, LLMRateLimitError, LLMResponseError

try:
    response = await provider.generate(prompt, system)
except LLMRateLimitError as e:
    print(f"Rate limited, retry after: {e.details.get('retry_after')}")
except LLMResponseError as e:
    print(f"Invalid response: {e.message}")
except LLMError as e:
    print(f"LLM error: {e.message}")
```

---

## Best Practices

### 1. Use Low Temperature for Code

```python
# For code generation, use temperature 0.1 or lower
provider = create_claude_provider(
    api_key=key,
    temperature=0.1  # Deterministic output
)
```

### 2. Structure System Prompts

```python
system = """You are SOMER Code Engine.
You are a deterministic code generator.

RULES:
1. Return valid JSON only
2. No markdown wrappers
3. Include error handling

OUTPUT FORMAT:
{"files": [{"path": "string", "content": "code"}]}
"""
```

### 3. Use Caching for Repeated Prompts

```python
# Enable caching for repeated operations
config = ClaudeConfig(
    api_key=key,
    enable_cache=True,
    cache_ttl=3600  # Cache for 1 hour
)
```

### 4. Handle Errors Gracefully

```python
async def safe_generate(provider, prompt, system):
    try:
        return await provider.generate(prompt, system)
    except LLMRateLimitError:
        await asyncio.sleep(60)
        return await provider.generate(prompt, system)
    except LLMError as e:
        logger.error(f"LLM error: {e}")
        return None
```

---

## Integration with Orchestrator

```python
from core.orchestrator.orchestrator import create_orchestrator
from tools.llm.claude import create_claude_provider

# Create LLM provider
llm = create_claude_provider(api_key="your_key")

# Create code engine using LLM
async def llm_code_engine(task: str, context: dict, constraints: list) -> dict:
    system = """You are a code generator. Return JSON:
    {"files": [{"path": "...", "content": "..."}], "explanation": "..."}"""

    prompt = f"Task: {task}\nConstraints: {constraints}"
    response = await llm.generate(prompt, system)

    return json.loads(response)

# Register with orchestrator
orch = create_orchestrator()
orch.register_module("code_engine", llm_code_engine)
```

---

## Testing

```bash
# Run LLM tests
PYTHONPATH="${PYTHONPATH}:$(pwd)" python3 -m pytest tests/unit/llm/ -v
```
