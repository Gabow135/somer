"""Plugin installer — instalación/desinstalación de plugins.

Portado desde OpenClaw install.ts. Soporta instalación desde:
- Directorio local
- Repositorio Git
- Paquete pip (PyPI)
- Archivo Python individual
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from shared.errors import SomerError

logger = logging.getLogger(__name__)


# ── Errores ──────────────────────────────────────────────────

class PluginInstallError(SomerError):
    """Error durante la instalación de un plugin."""


class PluginUninstallError(SomerError):
    """Error durante la desinstalación de un plugin."""


# ── Códigos de error ─────────────────────────────────────────

INSTALL_ERROR_CODES = {
    "INVALID_SOURCE": "invalid_source",
    "SOURCE_NOT_FOUND": "source_not_found",
    "MISSING_MANIFEST": "missing_manifest",
    "PIP_FAILED": "pip_failed",
    "GIT_FAILED": "git_failed",
    "ALREADY_INSTALLED": "already_installed",
    "COPY_FAILED": "copy_failed",
    "PERMISSION_DENIED": "permission_denied",
}


# ── Resultado de instalación ─────────────────────────────────

class InstallResult:
    """Resultado de una operación de instalación."""

    def __init__(
        self,
        ok: bool,
        plugin_id: str = "",
        target_dir: str = "",
        version: Optional[str] = None,
        error: Optional[str] = None,
        error_code: Optional[str] = None,
        source_type: Optional[str] = None,
    ) -> None:
        self.ok = ok
        self.plugin_id = plugin_id
        self.target_dir = target_dir
        self.version = version
        self.error = error
        self.error_code = error_code
        self.source_type = source_type


# ── Helpers ──────────────────────────────────────────────────

def _get_extensions_dir() -> Path:
    """Obtiene el directorio de extensiones de SOMER."""
    return Path.home() / ".somer" / "extensions"


def _safe_dir_name(name: str) -> str:
    """Genera un nombre de directorio seguro."""
    cleaned = name.replace("/", "_").replace("\\", "_")
    cleaned = cleaned.replace("..", "_").replace(" ", "_")
    return "".join(c for c in cleaned if c.isalnum() or c in "-_.")


def _validate_plugin_id(plugin_id: str) -> Optional[str]:
    """Valida un ID de plugin.

    Returns:
        Mensaje de error o None si es válido.
    """
    trimmed = plugin_id.strip()
    if not trimmed:
        return "ID de plugin vacío"
    if "\\" in trimmed:
        return "ID de plugin contiene separadores de ruta inválidos"
    if ".." in trimmed:
        return "ID de plugin contiene segmentos de ruta reservados"
    return None


def _detect_source_type(source: str) -> str:
    """Detecta el tipo de fuente de instalación.

    Returns:
        "local_dir", "local_file", "git", "pip", o "unknown".
    """
    source = source.strip()

    # Git URL
    if source.startswith(("git+", "git://", "https://github.com")):
        return "git"
    if source.endswith(".git"):
        return "git"

    # Local directory
    path = Path(source).expanduser()
    if path.is_dir():
        return "local_dir"

    # Local file
    if path.is_file() and path.suffix == ".py":
        return "local_file"

    # Pip package (asumido si no es nada de lo anterior)
    return "pip"


# ── Funciones de instalación ─────────────────────────────────

async def install_from_directory(
    source_dir: str,
    plugin_id: Optional[str] = None,
    extensions_dir: Optional[str] = None,
    mode: Literal["install", "update"] = "install",
) -> InstallResult:
    """Instala un plugin desde un directorio local.

    Copia el directorio al directorio de extensiones de SOMER.

    Args:
        source_dir: Ruta al directorio fuente.
        plugin_id: ID del plugin (se infiere del directorio si no se da).
        extensions_dir: Directorio destino (default: ~/.somer/extensions).
        mode: "install" o "update".

    Returns:
        InstallResult con el resultado.
    """
    source_path = Path(source_dir).expanduser().resolve()
    if not source_path.is_dir():
        return InstallResult(
            ok=False,
            error=f"Directorio no encontrado: {source_dir}",
            error_code=INSTALL_ERROR_CODES["SOURCE_NOT_FOUND"],
            source_type="local_dir",
        )

    pid = plugin_id or source_path.name
    validation_error = _validate_plugin_id(pid)
    if validation_error:
        return InstallResult(
            ok=False,
            error=validation_error,
            error_code=INSTALL_ERROR_CODES["INVALID_SOURCE"],
            source_type="local_dir",
        )

    ext_dir = Path(extensions_dir) if extensions_dir else _get_extensions_dir()
    target_dir = ext_dir / _safe_dir_name(pid)

    if target_dir.exists() and mode == "install":
        return InstallResult(
            ok=False,
            plugin_id=pid,
            error=f"Plugin ya instalado: {target_dir} (usa mode='update')",
            error_code=INSTALL_ERROR_CODES["ALREADY_INSTALLED"],
            source_type="local_dir",
        )

    try:
        ext_dir.mkdir(parents=True, exist_ok=True)
        if target_dir.exists():
            shutil.rmtree(target_dir)
        shutil.copytree(str(source_path), str(target_dir))
    except PermissionError as exc:
        return InstallResult(
            ok=False,
            plugin_id=pid,
            error=f"Sin permiso para escribir: {exc}",
            error_code=INSTALL_ERROR_CODES["PERMISSION_DENIED"],
            source_type="local_dir",
        )
    except Exception as exc:
        return InstallResult(
            ok=False,
            plugin_id=pid,
            error=f"Error al copiar directorio: {exc}",
            error_code=INSTALL_ERROR_CODES["COPY_FAILED"],
            source_type="local_dir",
        )

    # Buscar versión
    version: Optional[str] = None
    manifest_path = target_dir / "manifest.json"
    if manifest_path.exists():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            version = data.get("version")
        except Exception:
            pass

    logger.info("Plugin '%s' instalado desde directorio: %s", pid, target_dir)
    return InstallResult(
        ok=True,
        plugin_id=pid,
        target_dir=str(target_dir),
        version=version,
        source_type="local_dir",
    )


async def install_from_pip(
    package: str,
    plugin_id: Optional[str] = None,
    timeout_seconds: int = 120,
) -> InstallResult:
    """Instala un plugin como paquete pip.

    Ejecuta `pip install <package>` y luego intenta descubrir
    los entry points del plugin.

    Args:
        package: Nombre o especificación del paquete pip.
        plugin_id: ID del plugin (se infiere del paquete si no se da).
        timeout_seconds: Timeout para pip install.

    Returns:
        InstallResult con el resultado.
    """
    pid = plugin_id or package.split("[")[0].split(">=")[0].split("==")[0].strip()
    validation_error = _validate_plugin_id(pid)
    if validation_error:
        return InstallResult(
            ok=False,
            error=validation_error,
            error_code=INSTALL_ERROR_CODES["INVALID_SOURCE"],
            source_type="pip",
        )

    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pip", "install", package,
            "--quiet", "--no-input",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout_seconds,
        )

        if proc.returncode != 0:
            error_output = stderr.decode("utf-8", errors="replace").strip()
            return InstallResult(
                ok=False,
                plugin_id=pid,
                error=f"pip install falló: {error_output}",
                error_code=INSTALL_ERROR_CODES["PIP_FAILED"],
                source_type="pip",
            )

    except asyncio.TimeoutError:
        return InstallResult(
            ok=False,
            plugin_id=pid,
            error=f"pip install timeout ({timeout_seconds}s)",
            error_code=INSTALL_ERROR_CODES["PIP_FAILED"],
            source_type="pip",
        )
    except Exception as exc:
        return InstallResult(
            ok=False,
            plugin_id=pid,
            error=f"Error ejecutando pip: {exc}",
            error_code=INSTALL_ERROR_CODES["PIP_FAILED"],
            source_type="pip",
        )

    # Intentar descubrir versión instalada
    version: Optional[str] = None
    try:
        proc2 = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pip", "show", pid,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout2, _ = await proc2.communicate()
        for line in stdout2.decode("utf-8").split("\n"):
            if line.startswith("Version:"):
                version = line.split(":", 1)[1].strip()
                break
    except Exception:
        pass

    logger.info("Plugin '%s' instalado desde pip: %s", pid, package)
    return InstallResult(
        ok=True,
        plugin_id=pid,
        target_dir="",  # pip-managed
        version=version,
        source_type="pip",
    )


async def install_from_git(
    repo_url: str,
    plugin_id: Optional[str] = None,
    branch: Optional[str] = None,
    extensions_dir: Optional[str] = None,
    timeout_seconds: int = 120,
) -> InstallResult:
    """Instala un plugin desde un repositorio Git.

    Clona el repositorio y lo copia al directorio de extensiones.

    Args:
        repo_url: URL del repositorio Git.
        plugin_id: ID del plugin.
        branch: Branch específico a clonar.
        extensions_dir: Directorio destino.
        timeout_seconds: Timeout para git clone.

    Returns:
        InstallResult con el resultado.
    """
    # Limpiar URL
    url = repo_url.strip()
    if url.startswith("git+"):
        url = url[4:]

    # Inferir plugin_id del URL
    pid = plugin_id
    if not pid:
        pid = url.rstrip("/").split("/")[-1]
        if pid.endswith(".git"):
            pid = pid[:-4]

    validation_error = _validate_plugin_id(pid)
    if validation_error:
        return InstallResult(
            ok=False,
            error=validation_error,
            error_code=INSTALL_ERROR_CODES["INVALID_SOURCE"],
            source_type="git",
        )

    with tempfile.TemporaryDirectory() as tmp_dir:
        clone_dir = Path(tmp_dir) / pid

        # Git clone
        cmd = ["git", "clone", "--depth", "1"]
        if branch:
            cmd.extend(["--branch", branch])
        cmd.extend([url, str(clone_dir)])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout_seconds,
            )

            if proc.returncode != 0:
                error_output = stderr.decode("utf-8", errors="replace").strip()
                return InstallResult(
                    ok=False,
                    plugin_id=pid,
                    error=f"git clone falló: {error_output}",
                    error_code=INSTALL_ERROR_CODES["GIT_FAILED"],
                    source_type="git",
                )

        except asyncio.TimeoutError:
            return InstallResult(
                ok=False,
                plugin_id=pid,
                error=f"git clone timeout ({timeout_seconds}s)",
                error_code=INSTALL_ERROR_CODES["GIT_FAILED"],
                source_type="git",
            )
        except FileNotFoundError:
            return InstallResult(
                ok=False,
                plugin_id=pid,
                error="git no está instalado o no está en PATH",
                error_code=INSTALL_ERROR_CODES["GIT_FAILED"],
                source_type="git",
            )

        # Copiar al directorio de extensiones
        return await install_from_directory(
            str(clone_dir),
            plugin_id=pid,
            extensions_dir=extensions_dir,
        )


async def install_from_file(
    source_file: str,
    plugin_id: Optional[str] = None,
    extensions_dir: Optional[str] = None,
) -> InstallResult:
    """Instala un plugin desde un archivo Python individual.

    Args:
        source_file: Ruta al archivo .py.
        plugin_id: ID del plugin.
        extensions_dir: Directorio destino.

    Returns:
        InstallResult con el resultado.
    """
    source_path = Path(source_file).expanduser().resolve()
    if not source_path.is_file():
        return InstallResult(
            ok=False,
            error=f"Archivo no encontrado: {source_file}",
            error_code=INSTALL_ERROR_CODES["SOURCE_NOT_FOUND"],
            source_type="local_file",
        )

    if source_path.suffix != ".py":
        return InstallResult(
            ok=False,
            error=f"Archivo debe ser .py: {source_file}",
            error_code=INSTALL_ERROR_CODES["INVALID_SOURCE"],
            source_type="local_file",
        )

    pid = plugin_id or source_path.stem
    ext_dir = Path(extensions_dir) if extensions_dir else _get_extensions_dir()
    target_dir = ext_dir / _safe_dir_name(pid)

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / source_path.name
        shutil.copy2(str(source_path), str(target_file))
    except Exception as exc:
        return InstallResult(
            ok=False,
            plugin_id=pid,
            error=f"Error al copiar archivo: {exc}",
            error_code=INSTALL_ERROR_CODES["COPY_FAILED"],
            source_type="local_file",
        )

    logger.info("Plugin '%s' instalado desde archivo: %s", pid, target_dir)
    return InstallResult(
        ok=True,
        plugin_id=pid,
        target_dir=str(target_dir),
        source_type="local_file",
    )


# ── Instalación automática ───────────────────────────────────

async def install_plugin(
    source: str,
    plugin_id: Optional[str] = None,
    extensions_dir: Optional[str] = None,
    mode: Literal["install", "update"] = "install",
    timeout_seconds: int = 120,
) -> InstallResult:
    """Instala un plugin detectando automáticamente el tipo de fuente.

    Args:
        source: Fuente del plugin (directorio, URL, paquete pip, archivo).
        plugin_id: ID del plugin (se infiere si no se da).
        extensions_dir: Directorio destino.
        mode: "install" o "update".
        timeout_seconds: Timeout para operaciones de red.

    Returns:
        InstallResult con el resultado.
    """
    source_type = _detect_source_type(source)

    if source_type == "local_dir":
        return await install_from_directory(
            source, plugin_id=plugin_id,
            extensions_dir=extensions_dir, mode=mode,
        )
    elif source_type == "local_file":
        return await install_from_file(
            source, plugin_id=plugin_id,
            extensions_dir=extensions_dir,
        )
    elif source_type == "git":
        return await install_from_git(
            source, plugin_id=plugin_id,
            extensions_dir=extensions_dir,
            timeout_seconds=timeout_seconds,
        )
    elif source_type == "pip":
        return await install_from_pip(
            source, plugin_id=plugin_id,
            timeout_seconds=timeout_seconds,
        )
    else:
        return InstallResult(
            ok=False,
            error=f"Tipo de fuente no reconocido: {source}",
            error_code=INSTALL_ERROR_CODES["INVALID_SOURCE"],
        )


# ── Desinstalación ───────────────────────────────────────────

async def uninstall_plugin(
    plugin_id: str,
    extensions_dir: Optional[str] = None,
    remove_pip: bool = False,
) -> InstallResult:
    """Desinstala un plugin.

    Args:
        plugin_id: ID del plugin a desinstalar.
        extensions_dir: Directorio de extensiones.
        remove_pip: También desinstalar con pip si es un paquete pip.

    Returns:
        InstallResult con el resultado.
    """
    validation_error = _validate_plugin_id(plugin_id)
    if validation_error:
        return InstallResult(
            ok=False,
            error=validation_error,
            error_code=INSTALL_ERROR_CODES["INVALID_SOURCE"],
        )

    ext_dir = Path(extensions_dir) if extensions_dir else _get_extensions_dir()
    target_dir = ext_dir / _safe_dir_name(plugin_id)

    removed_dir = False
    if target_dir.exists():
        try:
            shutil.rmtree(str(target_dir))
            removed_dir = True
        except PermissionError as exc:
            return InstallResult(
                ok=False,
                plugin_id=plugin_id,
                error=f"Sin permiso para eliminar: {exc}",
                error_code=INSTALL_ERROR_CODES["PERMISSION_DENIED"],
            )

    removed_pip = False
    if remove_pip:
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "pip", "uninstall", "-y", plugin_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            if proc.returncode == 0:
                removed_pip = True
        except Exception:
            pass

    if not removed_dir and not removed_pip:
        return InstallResult(
            ok=False,
            plugin_id=plugin_id,
            error=f"Plugin '{plugin_id}' no encontrado",
            error_code=INSTALL_ERROR_CODES["SOURCE_NOT_FOUND"],
        )

    logger.info("Plugin '%s' desinstalado", plugin_id)
    return InstallResult(
        ok=True,
        plugin_id=plugin_id,
        target_dir=str(target_dir) if removed_dir else "",
    )


# ── Listado de plugins instalados ────────────────────────────

def list_installed_plugins(
    extensions_dir: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Lista los plugins instalados en el directorio de extensiones.

    Args:
        extensions_dir: Directorio de extensiones.

    Returns:
        Lista de dicts con info de cada plugin.
    """
    ext_dir = Path(extensions_dir) if extensions_dir else _get_extensions_dir()
    if not ext_dir.exists():
        return []

    results: List[Dict[str, Any]] = []
    for child in sorted(ext_dir.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue

        info: Dict[str, Any] = {
            "id": child.name,
            "path": str(child),
            "has_manifest": False,
        }

        # Buscar manifiesto
        for manifest_name in ("manifest.json", "somer.plugin.json", "plugin.json"):
            manifest_path = child / manifest_name
            if manifest_path.exists():
                info["has_manifest"] = True
                try:
                    data = json.loads(manifest_path.read_text(encoding="utf-8"))
                    info["name"] = data.get("name", child.name)
                    info["version"] = data.get("version")
                    info["description"] = data.get("description")
                except Exception:
                    pass
                break

        results.append(info)

    return results


# Necesario para install_from_pip y uninstall_plugin
import sys
