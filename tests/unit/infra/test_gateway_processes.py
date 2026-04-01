"""Tests para infra/gateway_processes.py — Gestión de procesos."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from infra.gateway_processes import GatewayProcessManager


class TestGatewayProcessManager:
    """Tests del gestor de procesos del gateway."""

    def setup_method(self) -> None:
        self._tmpdir = Path(tempfile.mkdtemp())
        self.mgr = GatewayProcessManager(home_dir=self._tmpdir)

    def teardown_method(self) -> None:
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_register_and_read(self) -> None:
        """Registrar y leer info de proceso."""
        info = self.mgr.register_process(
            pid=os.getpid(),
            host="127.0.0.1",
            port=18789,
            version="2.0.0",
        )

        assert info.pid == os.getpid()
        assert self.mgr.pid_file.exists()
        assert self.mgr.info_file.exists()

        read_info = self.mgr.read_process_info()
        assert read_info is not None
        assert read_info.pid == os.getpid()
        assert read_info.port == 18789
        assert read_info.version == "2.0.0"

    def test_no_registration(self) -> None:
        """Sin registro retorna None."""
        assert self.mgr.read_process_info() is None

    def test_is_process_alive(self) -> None:
        """Verifica que el proceso actual está vivo."""
        self.mgr.register_process(pid=os.getpid())
        assert self.mgr.is_process_alive() is True

    def test_dead_process(self) -> None:
        """Verifica que un PID inexistente no está vivo."""
        assert self.mgr.is_process_alive(pid=999999) is False

    def test_cleanup(self) -> None:
        """Limpieza elimina archivos."""
        self.mgr.register_process()
        assert self.mgr.pid_file.exists()

        self.mgr.cleanup()
        assert not self.mgr.pid_file.exists()
        assert not self.mgr.info_file.exists()

    def test_get_status_no_registration(self) -> None:
        """Estado sin registro."""
        status = self.mgr.get_status()
        assert status["registered"] is False
        assert status["alive"] is False

    def test_get_status_with_registration(self) -> None:
        """Estado con registro."""
        self.mgr.register_process(
            pid=os.getpid(),
            host="127.0.0.1",
            port=18789,
        )
        status = self.mgr.get_status()
        assert status["registered"] is True
        assert status["alive"] is True
        assert status["pid"] == os.getpid()
        assert status["port"] == 18789

    @pytest.mark.asyncio
    async def test_health_check_no_server(self) -> None:
        """Health check sin servidor retorna False."""
        self.mgr.register_process(port=59999)
        result = await self.mgr.health_check(port=59999, timeout=0.5)
        assert result is False
