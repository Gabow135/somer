"""Loader de SKILL.md — parsea YAML frontmatter + Markdown."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from shared.errors import SkillValidationError
from shared.types import SkillMeta

logger = logging.getLogger(__name__)

# Regex para frontmatter YAML entre ---
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.+?)\n---\s*\n", re.DOTALL)


def parse_skill_md(content: str) -> Dict[str, Any]:
    """Parsea un archivo SKILL.md.

    Returns:
        Dict con 'meta' (frontmatter) y 'body' (markdown).
    """
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return {"meta": {}, "body": content}

    frontmatter_raw = match.group(1)
    body = content[match.end():]

    meta = _parse_frontmatter(frontmatter_raw)
    return {"meta": meta, "body": body}


def load_skill_file(path: Path) -> SkillMeta:
    """Carga un SKILL.md y retorna SkillMeta.

    Soporta tanto formato SOMER como formato OpenClaw.

    Args:
        path: Ruta al archivo SKILL.md.

    Returns:
        SkillMeta con la información del skill.

    Raises:
        SkillValidationError: Si el archivo no es válido.
    """
    if not path.exists():
        raise SkillValidationError(f"Skill file no encontrado: {path}")

    content = path.read_text(encoding="utf-8")
    parsed = parse_skill_md(content)
    meta = parsed["meta"]

    name = meta.get("name", path.parent.name)
    if not name:
        raise SkillValidationError(f"Skill sin nombre: {path}")

    # Extraer campos — soportar formato SOMER (metadata.somer)
    # Backward compat: también acepta formato OpenClaw (metadata.openclaw)
    triggers = meta.get("triggers", [])
    required_credentials: List[str] = meta.get("required_credentials", [])
    tags = meta.get("tags", [])
    tools = meta.get("tools", [])

    # SOMER: metadata.somer.requires.env → required_credentials
    # Backward compat: cae a metadata.openclaw si metadata.somer no existe
    oc_meta = meta.get("metadata", {})
    if isinstance(oc_meta, dict):
        oc = oc_meta.get("somer", {}) or oc_meta.get("openclaw", {})
        if isinstance(oc, dict):
            requires = oc.get("requires", {})
            if isinstance(requires, dict):
                env_keys = requires.get("env", [])
                if isinstance(env_keys, list) and not required_credentials:
                    required_credentials = env_keys

    # Si no hay triggers, generar del nombre
    if not triggers and name:
        triggers = [name.replace("-", " "), name]

    return SkillMeta(
        name=name,
        description=meta.get("description", ""),
        version=meta.get("version", "1.0.0"),
        triggers=triggers,
        required_credentials=required_credentials,
        tools=tools,
        tags=tags,
        enabled=meta.get("enabled", True),
        body=parsed.get("body", ""),
    )


def discover_skills(dirs: List[str]) -> List[Path]:
    """Descubre archivos SKILL.md en los directorios dados.

    Returns:
        Lista de paths a SKILL.md encontrados.
    """
    found = []
    for dir_str in dirs:
        dir_path = Path(dir_str)
        if not dir_path.exists():
            continue
        for skill_file in dir_path.rglob("SKILL.md"):
            found.append(skill_file)
    return sorted(found)


def _parse_frontmatter(text: str) -> Dict[str, Any]:
    """Parsea frontmatter YAML.

    Intenta json-like primero (para metadata: { ... }),
    luego cae a parser YAML simple.
    """
    # Intentar parsear con el simple parser
    result = _parse_simple_yaml(text)

    # Si hay campos con JSON inline ({ ... }), parsearlos
    for key, value in list(result.items()):
        if isinstance(value, str) and value.strip().startswith("{"):
            try:
                result[key] = json.loads(_clean_json(value))
            except (json.JSONDecodeError, ValueError):
                pass

    return result


def _clean_json(text: str) -> str:
    """Limpia JSON con trailing commas y otros problemas comunes."""
    # Eliminar trailing commas antes de } o ]
    cleaned = re.sub(r",\s*([}\]])", r"\1", text)
    return cleaned


def _parse_simple_yaml(text: str) -> Dict[str, Any]:
    """Parser YAML simplificado (key: value, listas, JSON inline)."""
    result: Dict[str, Any] = {}
    current_key: Optional[str] = None
    current_list: Optional[List[str]] = None
    json_buffer: Optional[str] = None
    json_key: Optional[str] = None
    brace_depth = 0

    for line in text.split("\n"):
        stripped = line.strip()

        # Acumulando JSON multi-línea
        if json_buffer is not None and json_key is not None:
            json_buffer += "\n" + line
            brace_depth += line.count("{") - line.count("}")
            if brace_depth <= 0:
                try:
                    result[json_key] = json.loads(_clean_json(json_buffer))
                except (json.JSONDecodeError, ValueError):
                    result[json_key] = json_buffer
                json_buffer = None
                json_key = None
                current_key = None
                current_list = None
            continue

        if not stripped or stripped.startswith("#"):
            continue

        # Línea que empieza con { — puede ser continuación de key anterior
        if stripped.startswith("{") and current_key is not None:
            brace_depth = stripped.count("{") - stripped.count("}")
            if brace_depth <= 0:
                try:
                    result[current_key] = json.loads(_clean_json(stripped))
                except (json.JSONDecodeError, ValueError):
                    result[current_key] = stripped
                current_key = None
                current_list = None
            else:
                json_key = current_key
                json_buffer = stripped
                current_list = None
            continue

        # List item
        if stripped.startswith("- "):
            if current_key and current_list is not None:
                current_list.append(stripped[2:].strip().strip("'\""))
            continue

        # Key: value
        if ":" in stripped:
            if current_key and current_list is not None:
                result[current_key] = current_list

            parts = stripped.split(":", 1)
            key = parts[0].strip()
            value = parts[1].strip() if len(parts) > 1 else ""

            if not value:
                # Could be start of a list or JSON block
                current_key = key
                current_list = []
            elif value.startswith("{"):
                # JSON inline — puede ser multi-línea
                brace_depth = value.count("{") - value.count("}")
                if brace_depth <= 0:
                    try:
                        result[key] = json.loads(_clean_json(value))
                    except (json.JSONDecodeError, ValueError):
                        result[key] = value.strip("'\"")
                    current_key = None
                    current_list = None
                else:
                    json_key = key
                    json_buffer = value
                    current_key = None
                    current_list = None
            elif value.startswith("[") and value.endswith("]"):
                # Inline YAML list: [item1, item2, item3]
                inner = value[1:-1].strip()
                if inner:
                    items = [
                        item.strip().strip("'\"")
                        for item in inner.split(",")
                    ]
                    result[key] = items
                else:
                    result[key] = []
                current_key = None
                current_list = None
            else:
                current_key = None
                current_list = None
                value = value.strip("'\"")
                if value.lower() == "true":
                    result[key] = True
                elif value.lower() == "false":
                    result[key] = False
                else:
                    try:
                        result[key] = int(value)
                    except ValueError:
                        result[key] = value

    if current_key and current_list is not None:
        result[current_key] = current_list

    return result
