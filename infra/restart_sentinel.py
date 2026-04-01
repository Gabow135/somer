"""Centinela de restart — coordinación entre procesos — SOMER.

Portado de OpenClaw: restart-sentinel.ts.

Proporciona un mecanismo de señalización basado en archivos
para coordinar reinicios entre procesos. Un proceso puede
solicitar un reinicio escribiendo un sentinel, y otros
procesos pueden monitorearlo.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

SENTINEL_FILENAME = "restart.sentinel"


@dataclass
class RestartRequest:
    """Solicitud de reinicio."""

    reason: str = ""
    requested_by: str = ""
    requested_at: float = 0.0
    pid: int = 0


class RestartSentinel:
    """Centinela de reinicio basado en archivos.

    Permite a un proceso solicitar un reinicio escribiendo un archivo
    sentinel, que es monitoreado por el proceso supervisor.
    """

    def __init__(self, sentinel_dir: Optional[Path] = None) -> None:
        """Inicializa el centinela.

        Args:
            sentinel_dir: Directorio para el archivo sentinel.
                Default: ~/.somer/
        """
        from shared.constants import DEFAULT_HOME
        self._dir = sentinel_dir or DEFAULT_HOME
        self._dir.mkdir(parents=True, exist_ok=True)

    @property
    def sentinel_path(self) -> Path:
        """Ruta al archivo sentinel."""
        return self._dir / SENTINEL_FILENAME

    def request_restart(
        self,
        reason: str = "",
        requested_by: str = "",
    ) -> None:
        """Solicita un reinicio escribiendo el sentinel.

        Args:
            reason: Razón del reinicio.
            requested_by: Identificador del solicitante.
        """
        request = RestartRequest(
            reason=reason,
            requested_by=requested_by,
            requested_at=time.time(),
            pid=os.getpid(),
        )

        data = {
            "reason": request.reason,
            "requested_by": request.requested_by,
            "requested_at": request.requested_at,
            "pid": request.pid,
        }

        self.sentinel_path.write_text(
            json.dumps(data, indent=2) + "\n",
            encoding="utf-8",
        )
        logger.info(
            "Reinicio solicitado: reason=%s, by=%s",
            reason,
            requested_by,
        )

    def check_restart_requested(self) -> Optional[RestartRequest]:
        """Verifica si hay una solicitud de reinicio pendiente.

        Returns:
            RestartRequest si hay solicitud, None si no.
        """
        if not self.sentinel_path.exists():
            return None

        try:
            data = json.loads(
                self.sentinel_path.read_text(encoding="utf-8")
            )
            return RestartRequest(
                reason=str(data.get("reason", "")),
                requested_by=str(data.get("requested_by", "")),
                requested_at=float(data.get("requested_at", 0)),
                pid=int(data.get("pid", 0)),
            )
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            logger.debug("Error leyendo sentinel: %s", exc)
            return None

    def acknowledge_restart(self) -> Optional[RestartRequest]:
        """Lee y elimina la solicitud de reinicio (acknowledge).

        Returns:
            La solicitud que fue reconocida, o None si no había.
        """
        request = self.check_restart_requested()
        if request is not None:
            self.clear()
        return request

    def clear(self) -> None:
        """Elimina el archivo sentinel."""
        try:
            self.sentinel_path.unlink(missing_ok=True)
            logger.debug("Sentinel de reinicio eliminado")
        except OSError as exc:
            logger.debug("Error eliminando sentinel: %s", exc)

    def is_pending(self) -> bool:
        """Verifica si hay un reinicio pendiente."""
        return self.sentinel_path.exists()

    def age_seconds(self) -> Optional[float]:
        """Retorna la edad del sentinel en segundos.

        Returns:
            Segundos desde la creación, o None si no existe.
        """
        request = self.check_restart_requested()
        if request is None or request.requested_at <= 0:
            return None
        return time.time() - request.requested_at
