"""Resumen del sistema operativo y detección de plataforma — SOMER.

Portado de OpenClaw: os-summary.ts.

Proporciona información detallada sobre el sistema operativo,
arquitectura y entorno de ejecución.
"""

from __future__ import annotations

import logging
import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class OsSummary:
    """Resumen del sistema operativo."""

    platform: str  # "darwin", "linux", "win32"
    arch: str  # "x86_64", "arm64", etc.
    release: str  # Versión del kernel
    label: str  # Etiqueta legible
    hostname: str = ""
    python_version: str = ""


@dataclass
class SystemResources:
    """Recursos del sistema."""

    cpu_count: int = 0
    total_memory_mb: int = 0
    available_memory_mb: int = 0
    disk_total_mb: int = 0
    disk_free_mb: int = 0


def _safe_command(args: list, timeout: int = 5) -> str:
    """Ejecuta un comando y retorna la salida, o string vacío si falla."""
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        return ""


def _macos_version() -> str:
    """Obtiene la versión de macOS."""
    version = _safe_command(["sw_vers", "-productVersion"])
    return version or platform.mac_ver()[0] or platform.release()


def _linux_distro() -> str:
    """Obtiene la distribución de Linux."""
    # Intentar leer /etc/os-release
    try:
        from pathlib import Path
        os_release = Path("/etc/os-release")
        if os_release.exists():
            content = os_release.read_text(encoding="utf-8")
            for line in content.splitlines():
                if line.startswith("PRETTY_NAME="):
                    value = line.split("=", 1)[1].strip().strip('"')
                    return value
    except (OSError, UnicodeDecodeError):
        pass

    # Fallback: lsb_release
    name = _safe_command(["lsb_release", "-ds"])
    if name:
        return name.strip('"')

    return ""


def resolve_os_summary() -> OsSummary:
    """Resuelve un resumen completo del sistema operativo.

    Returns:
        OsSummary con información de la plataforma.
    """
    plat = sys.platform
    arch = platform.machine()
    release = platform.release()

    if plat == "darwin":
        version = _macos_version()
        label = f"macOS {version} ({arch})"
    elif plat == "win32":
        label = f"Windows {release} ({arch})"
    elif plat == "linux":
        distro = _linux_distro()
        if distro:
            label = f"{distro} ({arch})"
        else:
            label = f"Linux {release} ({arch})"
    else:
        label = f"{plat} {release} ({arch})"

    return OsSummary(
        platform=plat,
        arch=arch,
        release=release,
        label=label,
        hostname=platform.node(),
        python_version=platform.python_version(),
    )


def get_system_resources() -> SystemResources:
    """Obtiene información de recursos del sistema.

    Returns:
        SystemResources con CPU, memoria y disco.
    """
    resources = SystemResources()

    # CPU count
    cpu_count = os.cpu_count()
    resources.cpu_count = cpu_count or 0

    # Memoria
    try:
        if sys.platform == "darwin":
            output = _safe_command(["sysctl", "-n", "hw.memsize"])
            if output:
                resources.total_memory_mb = int(output) // (1024 * 1024)
        elif sys.platform == "linux":
            from pathlib import Path
            meminfo = Path("/proc/meminfo")
            if meminfo.exists():
                for line in meminfo.read_text().splitlines():
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        resources.total_memory_mb = kb // 1024
                    elif line.startswith("MemAvailable:"):
                        kb = int(line.split()[1])
                        resources.available_memory_mb = kb // 1024
    except (OSError, ValueError):
        pass

    # Disco
    try:
        import shutil
        usage = shutil.disk_usage("/")
        resources.disk_total_mb = usage.total // (1024 * 1024)
        resources.disk_free_mb = usage.free // (1024 * 1024)
    except (OSError, AttributeError):
        pass

    return resources


def is_docker() -> bool:
    """Detecta si estamos corriendo dentro de Docker."""
    # Verificar /.dockerenv
    if os.path.exists("/.dockerenv"):
        return True

    # Verificar cgroup
    try:
        from pathlib import Path
        cgroup = Path("/proc/1/cgroup")
        if cgroup.exists():
            content = cgroup.read_text()
            if "docker" in content or "containerd" in content:
                return True
    except (OSError, UnicodeDecodeError):
        pass

    return False


def is_wsl() -> bool:
    """Detecta si estamos en Windows Subsystem for Linux."""
    if sys.platform != "linux":
        return False
    try:
        release = platform.release().lower()
        return "microsoft" in release or "wsl" in release
    except Exception:
        return False


def environment_summary() -> Dict[str, str]:
    """Retorna un diccionario con resumen del entorno.

    Útil para logs de inicio y diagnóstico.

    Returns:
        Dict con información del entorno.
    """
    os_info = resolve_os_summary()
    resources = get_system_resources()

    summary = {
        "os": os_info.label,
        "platform": os_info.platform,
        "arch": os_info.arch,
        "hostname": os_info.hostname,
        "python": os_info.python_version,
        "cpus": str(resources.cpu_count),
        "memory_mb": str(resources.total_memory_mb),
        "docker": str(is_docker()),
        "wsl": str(is_wsl()),
        "ci": str(any(
            os.environ.get(v)
            for v in ("CI", "GITHUB_ACTIONS", "GITLAB_CI", "JENKINS_URL")
        )),
    }

    return summary
