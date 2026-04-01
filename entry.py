"""Entry point de SOMER 2.0.

Garantiza ejecución dentro de un virtual environment.
Si no estamos en un venv, crea uno en ~/.somer/venv y re-ejecuta.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SOMER_HOME = Path(os.environ.get("SOMER_HOME", Path.home() / ".somer"))
VENV_DIR = SOMER_HOME / "venv"


def _in_virtualenv() -> bool:
    """Detecta si estamos dentro de un virtual environment."""
    return (
        hasattr(sys, "real_prefix")  # virtualenv clásico
        or (sys.prefix != sys.base_prefix)  # venv estándar
        or os.environ.get("VIRTUAL_ENV") is not None
    )


def _ensure_venv() -> None:
    """Crea el venv si no existe y re-ejecuta SOMER dentro de él."""
    if _in_virtualenv():
        return

    # Crear venv si no existe
    venv_python = VENV_DIR / "bin" / "python3"
    if sys.platform == "win32":
        venv_python = VENV_DIR / "Scripts" / "python.exe"

    if not venv_python.exists():
        print(f"Creando virtual environment en {VENV_DIR}...")
        SOMER_HOME.mkdir(parents=True, exist_ok=True)
        subprocess.check_call(
            [sys.executable, "-m", "venv", str(VENV_DIR)],
        )
        # Instalar SOMER dentro del venv
        pip = VENV_DIR / "bin" / "pip"
        if sys.platform == "win32":
            pip = VENV_DIR / "Scripts" / "pip.exe"
        # Buscar el directorio del proyecto (donde está pyproject.toml)
        project_dir = _find_project_dir()
        if project_dir:
            print("Instalando SOMER en el virtual environment...")
            subprocess.check_call(
                [str(pip), "install", "-e", f"{project_dir}[all]"],
                stdout=subprocess.DEVNULL,
            )
        print(f"Virtual environment listo: {VENV_DIR}")

    # Re-ejecutar con el Python del venv
    os.execv(str(venv_python), [str(venv_python)] + sys.argv)


def _find_project_dir() -> "Path | None":
    """Busca el directorio del proyecto (con pyproject.toml)."""
    # Primero: directorio del propio entry.py
    entry_dir = Path(__file__).resolve().parent
    if (entry_dir / "pyproject.toml").exists():
        return entry_dir
    # Segundo: directorio de trabajo actual
    cwd = Path.cwd()
    if (cwd / "pyproject.toml").exists():
        return cwd
    return None


def _auto_detect_project_root() -> None:
    """Auto-detecta y setea SOMER_PROJECT_ROOT si no está definido.

    Busca el proyecto en orden:
    1. Ya seteado via env var
    2. Directorio de este archivo
    3. CWD
    4. /var/www/somer (producción Ubuntu)
    5. /opt/somer
    """
    if os.environ.get("SOMER_PROJECT_ROOT"):
        return

    candidates = [
        Path(__file__).resolve().parent,
        Path.cwd(),
        Path("/var/www/somer"),
        Path("/opt/somer"),
    ]

    for candidate in candidates:
        if (
            candidate.is_dir()
            and (candidate / "pyproject.toml").exists()
            and (candidate / "shared").is_dir()
        ):
            os.environ["SOMER_PROJECT_ROOT"] = str(candidate)
            return


def main() -> None:
    """Entry point principal."""
    _ensure_venv()
    _auto_detect_project_root()
    from infra.env import load_somer_env, normalize_env
    load_somer_env()
    normalize_env()
    from cli.app import app
    app()


if __name__ == "__main__":
    main()
