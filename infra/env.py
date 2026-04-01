"""Normalización de entorno y utilidades.

Portado de OpenClaw: env.ts, dotenv.ts, shell-env.ts.

Gestiona variables de entorno, archivos .env, normalización
de keys de API y detección de entorno.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Set

from shared.constants import DEFAULT_HOME

logger = logging.getLogger(__name__)

ENV_FILE_NAME = ".env"

# Variables de entorno ya logueadas (para evitar duplicados)
_logged_env: Set[str] = set()


def ensure_somer_home(home: Optional[Path] = None) -> Path:
    """Asegura que el directorio home de SOMER exista."""
    h = home or DEFAULT_HOME
    h.mkdir(parents=True, exist_ok=True)
    for subdir in ("sessions", "credentials", "memory", "logs", "security"):
        (h / subdir).mkdir(exist_ok=True)

    # Crear HEARTBEAT.md por defecto si no existe
    heartbeat_path = h / "HEARTBEAT.md"
    if not heartbeat_path.exists():
        from infra.heartbeat import DEFAULT_HEARTBEAT_CONTENT
        try:
            heartbeat_path.write_text(DEFAULT_HEARTBEAT_CONTENT, encoding="utf-8")
        except Exception:
            pass  # No fatal si falla la escritura

    return h


def is_ci() -> bool:
    """Detecta si estamos en un entorno CI."""
    return any(
        os.environ.get(v)
        for v in ("CI", "GITHUB_ACTIONS", "GITLAB_CI", "JENKINS_URL")
    )


def get_somer_home() -> Path:
    """Retorna el path de home de SOMER, respetando SOMER_HOME env var."""
    custom = os.environ.get("SOMER_HOME")
    if custom:
        return Path(custom)
    return DEFAULT_HOME


def get_env_file_path() -> Path:
    """Retorna la ruta al archivo .env de SOMER."""
    return get_somer_home() / ENV_FILE_NAME


def load_somer_env() -> Dict[str, str]:
    """Carga variables desde ~/.somer/.env al entorno del proceso.

    No sobreescribe variables que ya existan en el entorno.
    Returns: dict con las variables cargadas.
    """
    env_path = get_env_file_path()
    loaded = {}

    if not env_path.exists():
        return loaded

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and value:
            if not os.environ.get(key):
                os.environ[key] = value
                loaded[key] = value
            else:
                loaded[key] = os.environ[key]

    if loaded:
        logger.debug("Cargadas %d variables desde %s", len(loaded), env_path)
    return loaded


def save_env_var(key: str, value: str) -> None:
    """Guarda o actualiza una variable en ~/.somer/.env.

    Crea el archivo si no existe. Actualiza la línea si la key ya existe.
    """
    env_path = get_env_file_path()
    env_path.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    found = False

    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                existing_key = stripped.partition("=")[0].strip()
                if existing_key == key:
                    lines.append(f'{key}="{value}"')
                    found = True
                    continue
            lines.append(line)

    if not found:
        lines.append(f'{key}="{value}"')

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # Proteger permisos (solo owner)
    try:
        env_path.chmod(0o600)
    except OSError:
        pass  # Windows no soporta chmod igual
    # También poner en entorno actual
    os.environ[key] = value


def delete_env_var(key: str) -> bool:
    """Elimina una variable del archivo .env.

    Args:
        key: Nombre de la variable a eliminar.

    Returns:
        True si la variable fue encontrada y eliminada.
    """
    env_path = get_env_file_path()
    if not env_path.exists():
        return False

    lines = []
    found = False

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            existing_key = stripped.partition("=")[0].strip()
            if existing_key == key:
                found = True
                continue
        lines.append(line)

    if found:
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.environ.pop(key, None)

    return found


def list_env_vars() -> Dict[str, str]:
    """Lista todas las variables definidas en el archivo .env.

    Returns:
        Dict con key→value de todas las variables.
    """
    env_path = get_env_file_path()
    result: Dict[str, str] = {}

    if not env_path.exists():
        return result

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            result[key] = value

    return result


def is_truthy_env(value: Optional[str]) -> bool:
    """Verifica si un valor de variable de entorno es truthy.

    Considera truthy: "1", "true", "yes", "on"
    Considera falsy: "0", "false", "no", "off", None, ""
    """
    if not value:
        return False
    return value.strip().lower() in ("1", "true", "yes", "on")


def log_accepted_env(
    key: str,
    description: str,
    redact: bool = False,
    value: Optional[str] = None,
) -> None:
    """Loguea una variable de entorno aceptada (una sola vez).

    Útil para documentar qué variables de entorno están siendo usadas.

    Args:
        key: Nombre de la variable.
        description: Descripción de su propósito.
        redact: Si ocultar el valor en los logs.
        value: Valor a loguear (default: lee del entorno).
    """
    # No loguear en tests
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("CI"):
        return

    if key in _logged_env:
        return

    raw = value if value is not None else os.environ.get(key, "")
    if not raw or not raw.strip():
        return

    _logged_env.add(key)
    display = _format_env_value(raw, redact)
    logger.info("env: %s=%s (%s)", key, display, description)


def _format_env_value(value: str, redact: bool) -> str:
    """Formatea un valor de entorno para logging."""
    if redact:
        return "<redacted>"
    single_line = re.sub(r"\s+", " ", value).strip()
    if len(single_line) <= 160:
        return single_line
    return single_line[:160] + "..."


def normalize_env() -> None:
    """Normaliza variables de entorno con aliases conocidos.

    Resuelve aliases comunes de variables de API para
    que el sistema pueda encontrarlas de forma consistente.
    """
    # Aliases de API keys
    aliases = {
        "OPENAI_API_KEY": ["OPENAI_KEY"],
        "ANTHROPIC_API_KEY": ["ANTHROPIC_KEY", "CLAUDE_API_KEY"],
        "GOOGLE_API_KEY": ["GOOGLE_GENERATIVE_AI_API_KEY", "GEMINI_API_KEY"],
        "DEEPSEEK_API_KEY": ["DEEPSEEK_KEY"],
    }

    for canonical, alt_keys in aliases.items():
        if os.environ.get(canonical, "").strip():
            continue
        for alt in alt_keys:
            alt_val = os.environ.get(alt, "").strip()
            if alt_val:
                os.environ[canonical] = alt_val
                logger.debug("Env normalizado: %s ← %s", canonical, alt)
                break


def get_required_env(key: str, description: str = "") -> str:
    """Obtiene una variable de entorno requerida.

    Args:
        key: Nombre de la variable.
        description: Descripción para el error.

    Returns:
        Valor de la variable.

    Raises:
        EnvironmentError: Si la variable no está definida.
    """
    value = os.environ.get(key, "").strip()
    if not value:
        desc = f" ({description})" if description else ""
        raise EnvironmentError(
            f"Variable de entorno requerida no definida: {key}{desc}"
        )
    return value


def mask_secret(value: str, visible_chars: int = 4) -> str:
    """Enmascara un secreto mostrando solo los últimos caracteres.

    Args:
        value: Valor a enmascarar.
        visible_chars: Cantidad de caracteres visibles al final.

    Returns:
        String enmascarado (ej: "sk-****abcd").
    """
    if not value:
        return ""
    if len(value) <= visible_chars:
        return "*" * len(value)
    prefix = value[:3] if len(value) > 10 else ""
    suffix = value[-visible_chars:]
    masked = "*" * max(4, len(value) - len(prefix) - visible_chars)
    return f"{prefix}{masked}{suffix}"
