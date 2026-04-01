# Code Engine Module

**Location:** `somer/engine/code_engine/generator.py`

**Status:** ✅ Implemented | Tests pending

---

## Overview

The Code Engine is a deterministic code generator that uses LLM in a controlled manner. It follows strict rules, templates, and constraints to produce production-ready code.

## Core Principle

```
The LLM is the execution engine, NOT the decision maker.
Rules and templates define the output.
```

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│               CODE ENGINE                        │
├─────────────────────────────────────────────────┤
│                                                  │
│  ┌──────────────┐    ┌──────────────────────┐   │
│  │   INPUT      │    │   HARD RULES         │   │
│  │   Validation │───▶│   Style Rules        │   │
│  └──────────────┘    │   Library Whitelist  │   │
│                      └──────────┬───────────┘   │
│                                 │               │
│                      ┌──────────▼───────────┐   │
│                      │   SYSTEM PROMPT      │   │
│                      │   Construction       │   │
│                      └──────────┬───────────┘   │
│                                 │               │
│                      ┌──────────▼───────────┐   │
│                      │   LLM GENERATION     │   │
│                      │   (Low Temperature)  │   │
│                      └──────────┬───────────┘   │
│                                 │               │
│                      ┌──────────▼───────────┐   │
│                      │   POST-PROCESSING    │   │
│                      │   Validation         │   │
│                      └──────────────────────┘   │
│                                                  │
└─────────────────────────────────────────────────┘
```

---

## Input/Output Models

### CodeGenerationInput

```python
from pydantic import BaseModel
from enum import Enum

class CodeType(str, Enum):
    BACKEND = "backend"
    FRONTEND = "frontend"
    SCRIPT = "script"

class Language(str, Enum):
    PYTHON = "python"
    TYPESCRIPT = "typescript"
    JAVASCRIPT = "javascript"
    GO = "go"
    RUST = "rust"

class CodeGenerationInput(BaseModel):
    task: str                           # What to generate
    type: CodeType                      # backend/frontend/script
    language: Language                  # Target language
    framework: Optional[str] = None     # FastAPI, Express, etc.
    constraints: list[str] = []         # Additional rules
    context: dict = {}                  # Extra context
```

### CodeGenerationOutput

```python
class GeneratedFile(BaseModel):
    path: str
    content: str
    language: Language

class CodeGenerationOutput(BaseModel):
    files: list[GeneratedFile]
    explanation: str
```

---

## Hard Rules (Non-Negotiable)

```python
HARD_RULES = [
    "ALWAYS follow template structure",
    "ALWAYS use consistent naming conventions",
    "NO unnecessary abstractions",
    "NO duplicated logic",
    "ALL code must be clean and modular",
    "ALWAYS include error handling",
    "ALWAYS include minimal logging",
    "NO hallucinated libraries",
    "DO NOT invent patterns",
    "OUTPUT must be deterministic",
]
```

---

## Style Rules by Language

### Python
```python
{
    "naming": "snake_case",
    "max_line_length": 88,
    "docstrings": "google",
    "imports": "isort",
}
```

### TypeScript
```python
{
    "naming": "camelCase",
    "max_line_length": 100,
    "semicolons": True,
}
```

---

## Library Whitelist

Only whitelisted libraries are allowed:

### Python
```python
{
    "standard": [
        "os", "sys", "json", "logging", "asyncio",
        "typing", "pathlib", "re", "datetime",
        "dataclasses", "enum", "abc", "functools",
        "itertools", "collections"
    ],
    "common": [
        "pydantic", "httpx", "aiohttp", "fastapi",
        "sqlalchemy", "redis", "pytest", "structlog",
        "anthropic", "openai"
    ],
}
```

### TypeScript
```python
{
    "standard": [
        "fs", "path", "http", "https", "crypto", "util"
    ],
    "common": [
        "express", "zod", "axios", "prisma", "jest",
        "typescript"
    ],
}
```

---

## Usage

### Basic Usage

```python
from somer.engine.code_engine.generator import (
    CodeGenerator,
    CodeGenerationInput,
    CodeType,
    Language
)

# Create generator with LLM provider
generator = CodeGenerator(llm_provider=claude_client)

# Define input
input_data = CodeGenerationInput(
    task="Create a REST endpoint for user registration",
    type=CodeType.BACKEND,
    language=Language.PYTHON,
    framework="fastapi",
    constraints=[
        "Include email validation",
        "Hash passwords with bcrypt"
    ]
)

# Generate
output = await generator.generate(input_data)

for file in output.files:
    print(f"=== {file.path} ===")
    print(file.content)
```

### Orchestrator Integration

```python
from somer.engine.code_engine.generator import generate_code

# This function is designed for orchestrator integration
result = await generate_code(
    task="Create user model",
    context={"database": "postgresql"},
    constraints=["use SQLAlchemy"],
    llm_provider=claude_client,
    code_type=CodeType.BACKEND,
    language=Language.PYTHON,
    framework="sqlalchemy"
)

# Returns dict compatible with SomerOutput.result
# {
#     "files": [{"path": "...", "content": "...", "language": "python"}],
#     "explanation": "..."
# }
```

---

## LLM Provider Protocol

The generator expects an LLM provider implementing this protocol:

```python
from typing import Protocol

class LLMProvider(Protocol):
    async def generate(self, prompt: str, system: str) -> str:
        """
        Generate text from prompt.

        Args:
            prompt: User message
            system: System instructions

        Returns:
            Generated text response
        """
        ...
```

### Example Implementation

```python
import anthropic

class ClaudeProvider:
    def __init__(self, api_key: str):
        self.client = anthropic.AsyncAnthropic(api_key=api_key)

    async def generate(self, prompt: str, system: str) -> str:
        response = await self.client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=4096,
            temperature=0.1,  # Low for determinism
            system=system,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text
```

---

## Custom Rules

### Adding Post-Processing Rules

```python
from somer.engine.code_engine.generator import CodeGenerator, CodeRule

generator = CodeGenerator(llm_provider=provider)

# Add custom rule
rule = CodeRule(
    name="remove_print_statements",
    pattern=r"print\(.+\)",
    replacement="# print removed",
    applies_to=[Language.PYTHON]
)

generator.add_rule(rule)
```

### Loading Templates

```python
# Load a code template
generator.load_template("fastapi_endpoint", """
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

class {model_name}Request(BaseModel):
    pass

class {model_name}Response(BaseModel):
    pass

@router.post("/{endpoint_path}")
async def {function_name}(request: {model_name}Request) -> {model_name}Response:
    # Implementation here
    pass
""")

# Get template
template = generator.get_template("fastapi_endpoint")
```

---

## Configuration

```python
from somer.engine.code_engine.generator import GeneratorConfig, CodeGenerator

config = GeneratorConfig(
    max_tokens=4096,           # Max output tokens
    temperature=0.1,           # Low for determinism
    strict_validation=True,    # Validate libraries
    templates_path=Path("./templates")
)

generator = CodeGenerator(
    llm_provider=provider,
    config=config
)
```

---

## System Prompt Structure

The generator builds a system prompt with:

1. **Role Definition**
   ```
   You are SOMER Code Engine.
   You are a deterministic code generator. NOT a creative AI.
   ```

2. **Hard Rules**
   - Template adherence
   - Naming conventions
   - No abstractions
   - Error handling required

3. **Style Rules**
   - Language-specific formatting
   - Line length limits
   - Documentation style

4. **Constraints**
   - User-provided constraints
   - Project-specific rules

5. **Output Format**
   ```json
   {
     "files": [{"path": "string", "content": "code"}],
     "explanation": "short and technical"
   }
   ```

---

## Validation Steps

1. **Parse Response**
   - Clean markdown wrappers
   - Parse JSON

2. **Apply Rules**
   - Post-processing patterns
   - Line ending normalization
   - Trailing whitespace removal

3. **Validate Libraries**
   - Extract imports
   - Check against whitelist
   - Warn on unknown libraries

---

## Error Handling

```python
try:
    output = await generator.generate(input_data)
except ValueError as e:
    # Invalid JSON response from LLM
    print(f"Parse error: {e}")

# Library warnings are logged but don't fail
# [WARNING] somer.code_engine: Potentially unknown library: some_lib
```

---

## Testing

```bash
# Run code engine tests (when implemented)
PYTHONPATH="${PYTHONPATH}:$(pwd)" python3 -m pytest somer/tests/unit/engine/ -v
```

**Test areas:**
- Input validation
- Rule application
- Library validation
- Template loading
- JSON parsing
- Error handling

---

## Best Practices

1. **Always provide constraints** for consistent output
2. **Use low temperature** (0.1) for determinism
3. **Whitelist new libraries** before using them
4. **Load templates** for common patterns
5. **Add custom rules** for project-specific formatting
6. **Validate output** before using in production
