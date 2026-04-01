"""Sondeo y disponibilidad de puertos — SOMER.

Portado de OpenClaw: ports-probe.ts, ports-lsof.ts.

Utilidades para verificar disponibilidad de puertos,
encontrar procesos usando puertos específicos, y
detectar conflictos.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import subprocess
import sys
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PortOwner:
    """Información del proceso que usa un puerto."""

    pid: int
    command: str = ""
    user: str = ""


def is_port_available(host: str = "127.0.0.1", port: int = 0) -> bool:
    """Verifica si un puerto está disponible para bind.

    Args:
        host: Host a verificar.
        port: Puerto a verificar.

    Returns:
        True si el puerto está libre.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
            return True
    except OSError:
        return False


def find_free_port(
    host: str = "127.0.0.1",
    start: int = 0,
    end: int = 0,
) -> int:
    """Encuentra un puerto libre.

    Si start y end son 0, deja al OS elegir un puerto efímero.
    Si se especifica rango, busca secuencialmente.

    Args:
        host: Host donde buscar.
        start: Inicio del rango (0 = OS elige).
        end: Fin del rango (0 = OS elige).

    Returns:
        Número de puerto libre.

    Raises:
        OSError: Si no se encuentra puerto disponible en el rango.
    """
    if start == 0 and end == 0:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((host, 0))
            return s.getsockname()[1]

    for port in range(start, end + 1):
        if is_port_available(host, port):
            return port

    raise OSError(f"No se encontró puerto libre en rango {start}-{end}")


async def wait_for_port(
    host: str,
    port: int,
    timeout: float = 10.0,
    interval: float = 0.1,
) -> bool:
    """Espera hasta que un puerto acepte conexiones.

    Args:
        host: Host a conectar.
        port: Puerto a conectar.
        timeout: Timeout en segundos.
        interval: Intervalo entre reintentos.

    Returns:
        True si el puerto está disponible para conexión.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=min(1.0, timeout),
            )
            writer.close()
            await writer.wait_closed()
            return True
        except (ConnectionRefusedError, asyncio.TimeoutError, OSError):
            await asyncio.sleep(interval)
    return False


async def wait_for_port_free(
    host: str = "127.0.0.1",
    port: int = 0,
    timeout: float = 10.0,
    interval: float = 0.2,
) -> bool:
    """Espera hasta que un puerto esté libre (no acepte conexiones).

    Args:
        host: Host a verificar.
        port: Puerto a verificar.
        timeout: Timeout en segundos.
        interval: Intervalo entre reintentos.

    Returns:
        True si el puerto quedó libre antes del timeout.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if is_port_available(host, port):
            return True
        await asyncio.sleep(interval)
    return False


def find_port_owner(port: int) -> Optional[PortOwner]:
    """Busca el proceso que está usando un puerto.

    Usa lsof (Unix/macOS) o netstat (fallback).

    Args:
        port: Puerto a investigar.

    Returns:
        Info del proceso propietario o None.
    """
    if sys.platform == "win32":
        return _find_port_owner_windows(port)
    return _find_port_owner_unix(port)


def _resolve_lsof_command() -> str:
    """Encuentra el comando lsof en el sistema."""
    candidates = (
        ["/usr/sbin/lsof", "/usr/bin/lsof"]
        if sys.platform == "darwin"
        else ["/usr/bin/lsof", "/usr/sbin/lsof"]
    )
    for candidate in candidates:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return "lsof"


def _find_port_owner_unix(port: int) -> Optional[PortOwner]:
    """Busca propietario de puerto usando lsof."""
    lsof = _resolve_lsof_command()
    try:
        result = subprocess.run(
            [lsof, "-i", f":{port}", "-t", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None

        pid = int(result.stdout.strip().splitlines()[0])

        # Obtener nombre del comando
        command = ""
        try:
            ps_result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "comm="],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if ps_result.returncode == 0:
                command = ps_result.stdout.strip()
        except (subprocess.TimeoutExpired, OSError):
            pass

        return PortOwner(pid=pid, command=command)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None


def _find_port_owner_windows(port: int) -> Optional[PortOwner]:
    """Busca propietario de puerto usando netstat (Windows)."""
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None

        for line in result.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.split()
                if parts:
                    pid = int(parts[-1])
                    return PortOwner(pid=pid)
        return None
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None


def probe_ports(
    ports: List[int],
    host: str = "127.0.0.1",
) -> List[int]:
    """Sondea una lista de puertos y retorna los que están en uso.

    Args:
        ports: Lista de puertos a verificar.
        host: Host contra el cual verificar.

    Returns:
        Lista de puertos que están en uso (no disponibles).
    """
    in_use = []
    for port in ports:
        if not is_port_available(host, port):
            in_use.append(port)
    return in_use
