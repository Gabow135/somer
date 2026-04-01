"""Tests para infra/file_lock.py — Bloqueo basado en archivos."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from infra.file_lock import FileLock


class TestFileLock:
    """Tests del mecanismo de file lock."""

    def setup_method(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self._lock_path = Path(self._tmpdir) / "test.lock"

    def teardown_method(self) -> None:
        self._lock_path.unlink(missing_ok=True)
        try:
            os.rmdir(self._tmpdir)
        except OSError:
            pass

    def test_acquire_and_release(self) -> None:
        """Adquirir y liberar lock."""
        lock = FileLock(self._lock_path)
        assert lock.acquire(timeout=1.0)
        assert lock.is_acquired
        assert self._lock_path.exists()

        lock.release()
        assert not lock.is_acquired
        assert not self._lock_path.exists()

    def test_context_manager(self) -> None:
        """Usar como context manager."""
        with FileLock(self._lock_path) as lock:
            assert lock.is_acquired
            assert self._lock_path.exists()

        assert not self._lock_path.exists()

    def test_double_acquire_fails(self) -> None:
        """No se puede adquirir dos veces el mismo lock."""
        lock1 = FileLock(self._lock_path)
        lock2 = FileLock(self._lock_path)

        assert lock1.acquire(timeout=1.0)
        # Lock2 no puede adquirir (timeout corto)
        assert not lock2.acquire(timeout=0.2)

        lock1.release()
        # Ahora sí
        assert lock2.acquire(timeout=1.0)
        lock2.release()

    def test_stale_lock_cleanup(self) -> None:
        """Lock huérfano se limpia automáticamente."""
        # Crear un lock con PID inexistente
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path.write_text("999999\n0\n")

        lock = FileLock(self._lock_path, stale_timeout=0)
        assert lock.acquire(timeout=1.0)
        lock.release()

    def test_lock_file_contains_pid(self) -> None:
        """El archivo de lock contiene el PID."""
        lock = FileLock(self._lock_path)
        lock.acquire(timeout=1.0)

        content = self._lock_path.read_text()
        assert str(os.getpid()) in content

        lock.release()

    def test_release_without_acquire(self) -> None:
        """Liberar sin adquirir no hace nada."""
        lock = FileLock(self._lock_path)
        lock.release()  # No debería lanzar error

    def test_missing_parent_directory(self) -> None:
        """Crea directorios padre si no existen."""
        deep_path = Path(self._tmpdir) / "a" / "b" / "test.lock"
        lock = FileLock(deep_path)
        assert lock.acquire(timeout=1.0)
        lock.release()

        # Limpiar
        deep_path.unlink(missing_ok=True)
        try:
            deep_path.parent.rmdir()
            deep_path.parent.parent.rmdir()
        except OSError:
            pass
