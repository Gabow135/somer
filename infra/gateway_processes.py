"""Gestión de procesos del gateway — SOMER.

Portado de OpenClaw: gateway-processes.ts.

Maneja el ciclo de vida de procesos del gateway:
inicio, detención, verificación de salud, y limpieza.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class GatewayProcessInfo:
    """Información de un proceso de gateway."""

    pid: int
    host: str = "127.0.0.1"
    port: int = 18789
    started_at: float = 0.0
    version: str = ""
    status: str = "unknown"  # "running" | "stopped" | "unknown"


PID_FILE_NAME = "gateway.pid"
INFO_FILE_NAME = "gateway.json"


class GatewayProcessManager:
    """Gestor de procesos del gateway de SOMER.

    Maneja el registro, verificación y limpieza de procesos
    del gateway usando archivos PID/info en el directorio home.
    """

    def __init__(self, home_dir: Optional[Path] = None) -> None:
        from shared.constants import DEFAULT_HOME
        self._home = home_dir or DEFAULT_HOME
        self._home.mkdir(parents=True, exist_ok=True)

    @property
    def pid_file(self) -> Path:
        """Ruta al archivo PID del gateway."""
        return self._home / PID_FILE_NAME

    @property
    def info_file(self) -> Path:
        """Ruta al archivo de info del gateway."""
        return self._home / INFO_FILE_NAME

    def register_process(
        self,
        pid: Optional[int] = None,
        host: str = "127.0.0.1",
        port: int = 18789,
        version: str = "",
    ) -> GatewayProcessInfo:
        """Registra el proceso actual del gateway.

        Escribe archivos PID e info para que otros procesos
        puedan detectar y comunicarse con el gateway.

        Args:
            pid: PID del proceso (default: PID actual).
            host: Host del gateway.
            port: Puerto del gateway.
            version: Versión del gateway.

        Returns:
            Información del proceso registrado.
        """
        actual_pid = pid or os.getpid()

        info = GatewayProcessInfo(
            pid=actual_pid,
            host=host,
            port=port,
            started_at=time.time(),
            version=version,
            status="running",
        )

        # Escribir archivo PID
        self.pid_file.write_text(str(actual_pid), encoding="utf-8")

        # Escribir archivo info
        info_data = {
            "pid": info.pid,
            "host": info.host,
            "port": info.port,
            "started_at": info.started_at,
            "version": info.version,
            "status": info.status,
        }
        self.info_file.write_text(
            json.dumps(info_data, indent=2) + "\n",
            encoding="utf-8",
        )

        logger.info(
            "Proceso de gateway registrado: PID=%d, %s:%d",
            actual_pid,
            host,
            port,
        )
        return info

    def read_process_info(self) -> Optional[GatewayProcessInfo]:
        """Lee la información del proceso de gateway registrado.

        Returns:
            Info del proceso o None si no hay registro.
        """
        if not self.info_file.exists():
            return None

        try:
            data = json.loads(self.info_file.read_text(encoding="utf-8"))
            return GatewayProcessInfo(
                pid=int(data.get("pid", 0)),
                host=str(data.get("host", "127.0.0.1")),
                port=int(data.get("port", 18789)),
                started_at=float(data.get("started_at", 0)),
                version=str(data.get("version", "")),
                status=str(data.get("status", "unknown")),
            )
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            logger.debug("Error leyendo info de gateway: %s", exc)
            return None

    def is_process_alive(self, pid: Optional[int] = None) -> bool:
        """Verifica si un proceso está vivo.

        Args:
            pid: PID a verificar. Si es None, usa el del registro.

        Returns:
            True si el proceso existe y responde.
        """
        if pid is None:
            info = self.read_process_info()
            if info is None:
                return False
            pid = info.pid

        if pid <= 0:
            return False

        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            # El proceso existe pero no tenemos permiso
            return True
        except OSError:
            return False

    async def health_check(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        timeout: float = 5.0,
    ) -> bool:
        """Verifica la salud del gateway intentando conectar al WebSocket.

        Args:
            host: Host del gateway (default: del registro).
            port: Puerto del gateway (default: del registro).
            timeout: Timeout en segundos.

        Returns:
            True si el gateway responde.
        """
        if host is None or port is None:
            info = self.read_process_info()
            if info is None:
                return False
            host = host or info.host
            port = port or info.port

        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=timeout,
            )
            writer.close()
            await writer.wait_closed()
            return True
        except (ConnectionRefusedError, asyncio.TimeoutError, OSError):
            return False

    def stop_process(self, pid: Optional[int] = None, force: bool = False) -> bool:
        """Envía señal de detención al proceso del gateway.

        Args:
            pid: PID del proceso. Si es None, usa el del registro.
            force: Si True, usa SIGKILL en lugar de SIGTERM.

        Returns:
            True si la señal fue enviada exitosamente.
        """
        if pid is None:
            info = self.read_process_info()
            if info is None:
                logger.warning("No hay proceso de gateway registrado")
                return False
            pid = info.pid

        if not self.is_process_alive(pid):
            logger.info("Proceso %d ya no está activo", pid)
            self.cleanup()
            return False

        try:
            sig = signal.SIGKILL if force else signal.SIGTERM
            os.kill(pid, sig)
            logger.info(
                "Señal %s enviada al proceso %d",
                sig.name,
                pid,
            )
            return True
        except (ProcessLookupError, PermissionError, OSError) as exc:
            logger.warning("Error enviando señal al proceso %d: %s", pid, exc)
            return False

    def cleanup(self) -> None:
        """Limpia archivos de registro del gateway."""
        for f in (self.pid_file, self.info_file):
            try:
                if f.exists():
                    f.unlink()
            except OSError:
                pass
        logger.debug("Archivos de gateway limpiados")

    def get_status(self) -> Dict[str, Any]:
        """Obtiene un diccionario con el estado completo del gateway.

        Returns:
            Dict con pid, host, port, alive, uptime, etc.
        """
        info = self.read_process_info()
        if info is None:
            return {"registered": False, "alive": False}

        alive = self.is_process_alive(info.pid)
        uptime = time.time() - info.started_at if info.started_at > 0 else 0

        return {
            "registered": True,
            "alive": alive,
            "pid": info.pid,
            "host": info.host,
            "port": info.port,
            "version": info.version,
            "started_at": info.started_at,
            "uptime_seconds": uptime if alive else 0,
            "status": "running" if alive else "stopped",
        }
