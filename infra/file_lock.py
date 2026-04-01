"""Mecanismo de bloqueo basado en archivos — SOMER.

Portado de OpenClaw: file-lock.ts.

Proporciona bloqueo cooperativo basado en archivos para
coordinar acceso entre procesos. Usa archivos .lock con PID
y detección de procesos huérfanos.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_STALE_TIMEOUT = 60.0  # Segundos antes de considerar un lock huérfano
DEFAULT_RETRY_INTERVAL = 0.1  # Segundos entre reintentos
DEFAULT_ACQUIRE_TIMEOUT = 10.0  # Timeout máximo para adquirir lock


class FileLock:
    """Bloqueo cooperativo basado en archivos.

    Usa archivos .lock que contienen el PID del proceso propietario.
    Detecta y limpia locks huérfanos automáticamente.
    """

    def __init__(
        self,
        lock_path: Path,
        stale_timeout: float = DEFAULT_STALE_TIMEOUT,
    ) -> None:
        """Inicializa el file lock.

        Args:
            lock_path: Ruta al archivo de lock.
            stale_timeout: Segundos después de los cuales un lock
                se considera huérfano si el proceso no existe.
        """
        self._lock_path = lock_path
        self._stale_timeout = stale_timeout
        self._acquired = False
        self._pid = os.getpid()

    @property
    def lock_path(self) -> Path:
        """Ruta al archivo de lock."""
        return self._lock_path

    @property
    def is_acquired(self) -> bool:
        """Indica si este proceso tiene el lock adquirido."""
        return self._acquired

    def acquire(self, timeout: float = DEFAULT_ACQUIRE_TIMEOUT) -> bool:
        """Intenta adquirir el lock.

        Espera hasta timeout si otro proceso lo tiene. Limpia
        locks huérfanos automáticamente.

        Args:
            timeout: Tiempo máximo de espera en segundos.

        Returns:
            True si el lock fue adquirido.
        """
        deadline = time.monotonic() + timeout

        while True:
            # Intentar adquirir
            if self._try_acquire():
                self._acquired = True
                logger.debug("Lock adquirido: %s (PID=%d)", self._lock_path, self._pid)
                return True

            # Verificar lock huérfano
            if self._is_stale():
                logger.info(
                    "Limpiando lock huérfano: %s",
                    self._lock_path,
                )
                self._force_remove()
                continue

            # Verificar timeout
            if time.monotonic() >= deadline:
                logger.warning(
                    "Timeout adquiriendo lock: %s (%.1fs)",
                    self._lock_path,
                    timeout,
                )
                return False

            time.sleep(DEFAULT_RETRY_INTERVAL)

    def release(self) -> None:
        """Libera el lock si lo tenemos adquirido."""
        if not self._acquired:
            return

        try:
            # Solo borrar si somos el propietario
            owner_pid = self._read_owner_pid()
            if owner_pid == self._pid:
                self._lock_path.unlink(missing_ok=True)
                logger.debug("Lock liberado: %s", self._lock_path)
            else:
                logger.warning(
                    "Lock no es nuestro (owner=%s, self=%d): %s",
                    owner_pid,
                    self._pid,
                    self._lock_path,
                )
        except OSError as exc:
            logger.debug("Error liberando lock: %s", exc)
        finally:
            self._acquired = False

    def _try_acquire(self) -> bool:
        """Intenta crear el archivo de lock atómicamente."""
        try:
            self._lock_path.parent.mkdir(parents=True, exist_ok=True)
            # O_CREAT | O_EXCL garantiza creación atómica
            fd = os.open(
                str(self._lock_path),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o644,
            )
            try:
                content = f"{self._pid}\n{time.time()}\n"
                os.write(fd, content.encode("utf-8"))
            finally:
                os.close(fd)
            return True
        except FileExistsError:
            return False
        except OSError as exc:
            logger.debug("Error creando lock file: %s", exc)
            return False

    def _read_owner_pid(self) -> Optional[int]:
        """Lee el PID del propietario del lock."""
        try:
            content = self._lock_path.read_text(encoding="utf-8").strip()
            if not content:
                return None
            first_line = content.splitlines()[0].strip()
            return int(first_line)
        except (OSError, ValueError, IndexError):
            return None

    def _read_lock_time(self) -> Optional[float]:
        """Lee el timestamp de creación del lock."""
        try:
            content = self._lock_path.read_text(encoding="utf-8").strip()
            lines = content.splitlines()
            if len(lines) >= 2:
                return float(lines[1].strip())
            # Fallback: usar mtime del archivo
            return self._lock_path.stat().st_mtime
        except (OSError, ValueError, IndexError):
            return None

    def _is_stale(self) -> bool:
        """Verifica si el lock es huérfano.

        Un lock es huérfano si:
        - El proceso propietario no existe
        - El lock lleva más de stale_timeout sin el proceso vivo
        """
        if not self._lock_path.exists():
            return False

        owner_pid = self._read_owner_pid()
        if owner_pid is None:
            # Lock corrupto → considerar huérfano
            return True

        # Verificar si el proceso existe
        if not _is_process_alive(owner_pid):
            return True

        # Verificar timeout
        lock_time = self._read_lock_time()
        if lock_time is not None:
            elapsed = time.time() - lock_time
            if elapsed > self._stale_timeout:
                # Lock viejo → verificar proceso de nuevo
                return not _is_process_alive(owner_pid)

        return False

    def _force_remove(self) -> None:
        """Fuerza la eliminación del archivo de lock."""
        try:
            self._lock_path.unlink(missing_ok=True)
        except OSError:
            pass

    def __enter__(self) -> FileLock:
        """Context manager: adquiere el lock."""
        if not self.acquire():
            raise TimeoutError(
                f"No se pudo adquirir lock: {self._lock_path}"
            )
        return self

    def __exit__(self, *args: object) -> None:
        """Context manager: libera el lock."""
        self.release()

    def __del__(self) -> None:
        """Limpieza: liberar lock si se olvidó."""
        if self._acquired:
            try:
                self.release()
            except Exception:
                pass


def _is_process_alive(pid: int) -> bool:
    """Verifica si un proceso existe."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
