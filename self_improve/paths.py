"""Resolución multi-path del proyecto SOMER.

Soporta ubicar el repositorio en múltiples entornos:
- Desarrollo local: ~/Documents/Proyectos/Somer (o donde esté clonado)
- Producción Ubuntu: /var/www/somer
- Custom: via SOMER_PROJECT_ROOT env var
- Home: ~/.somer (siempre disponible para config/env)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List, Optional

from shared.constants import DEFAULT_HOME

logger = logging.getLogger(__name__)

# Paths candidatos donde puede estar el repo
_KNOWN_PROJECT_PATHS = [
    "/var/www/somer",
    "/opt/somer",
]


def get_somer_home() -> Path:
    """Retorna ~/.somer (config, .env, credentials)."""
    custom = os.environ.get("SOMER_HOME")
    if custom:
        return Path(custom)
    return DEFAULT_HOME


def get_project_root() -> Optional[Path]:
    """Detecta la raíz del proyecto SOMER (donde está el código fuente).

    Orden de búsqueda:
    1. SOMER_PROJECT_ROOT env var
    2. Directorio de trabajo actual (si tiene pyproject.toml con somer)
    3. Paths conocidos (/var/www/somer, /opt/somer)
    4. Busca hacia arriba desde este archivo

    Returns:
        Path al root del proyecto, o None si no se encuentra.
    """
    # 1. Env var explícita
    env_root = os.environ.get("SOMER_PROJECT_ROOT")
    if env_root:
        p = Path(env_root)
        if _is_somer_root(p):
            return p

    # 2. CWD
    cwd = Path.cwd()
    if _is_somer_root(cwd):
        return cwd

    # 3. Paths conocidos
    for known in _KNOWN_PROJECT_PATHS:
        p = Path(known)
        if _is_somer_root(p):
            return p

    # 4. Buscar hacia arriba desde este archivo
    here = Path(__file__).resolve().parent.parent
    if _is_somer_root(here):
        return here

    return None


def get_all_env_paths() -> List[Path]:
    """Retorna todos los paths donde puede haber un .env relevante.

    Returns:
        Lista de paths .env existentes, en orden de prioridad.
    """
    paths = []

    # 1. Home .env (siempre prioritario)
    home_env = get_somer_home() / ".env"
    if home_env.exists():
        paths.append(home_env)

    # 2. Project .env
    root = get_project_root()
    if root:
        proj_env = root / ".env"
        if proj_env.exists() and proj_env != home_env:
            paths.append(proj_env)

    return paths


def get_project_file(relative: str) -> Optional[Path]:
    """Obtiene un archivo del proyecto por path relativo.

    Args:
        relative: Path relativo desde la raíz (ej: "skills/trello/SKILL.md")

    Returns:
        Path absoluto si existe, None si no.
    """
    root = get_project_root()
    if not root:
        return None
    full = root / relative
    return full if full.exists() else None


def list_project_skills() -> List[Path]:
    """Lista todos los SKILL.md del proyecto.

    Returns:
        Lista de paths a archivos SKILL.md encontrados.
    """
    root = get_project_root()
    if not root:
        return []
    skills_dir = root / "skills"
    if not skills_dir.exists():
        return []
    return sorted(skills_dir.rglob("SKILL.md"))


def _is_somer_root(path: Path) -> bool:
    """Verifica si un directorio es la raíz del proyecto SOMER."""
    if not path.is_dir():
        return False
    # Debe tener pyproject.toml y shared/
    return (path / "pyproject.toml").exists() and (path / "shared").is_dir()
