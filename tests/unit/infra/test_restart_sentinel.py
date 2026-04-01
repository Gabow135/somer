"""Tests para infra/restart_sentinel.py — Centinela de reinicio."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from infra.restart_sentinel import RestartSentinel


class TestRestartSentinel:
    """Tests del centinela de reinicio."""

    def setup_method(self) -> None:
        self._tmpdir = Path(tempfile.mkdtemp())
        self.sentinel = RestartSentinel(sentinel_dir=self._tmpdir)

    def teardown_method(self) -> None:
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_initial_state(self) -> None:
        """Sin solicitud pendiente al inicio."""
        assert self.sentinel.is_pending() is False
        assert self.sentinel.check_restart_requested() is None

    def test_request_restart(self) -> None:
        """Solicitar un reinicio."""
        self.sentinel.request_restart(
            reason="update",
            requested_by="cli",
        )

        assert self.sentinel.is_pending() is True
        request = self.sentinel.check_restart_requested()
        assert request is not None
        assert request.reason == "update"
        assert request.requested_by == "cli"
        assert request.pid > 0

    def test_acknowledge(self) -> None:
        """Acknowledge elimina la solicitud."""
        self.sentinel.request_restart(reason="test")

        request = self.sentinel.acknowledge_restart()
        assert request is not None
        assert request.reason == "test"

        # Ya no hay solicitud pendiente
        assert self.sentinel.is_pending() is False
        assert self.sentinel.check_restart_requested() is None

    def test_clear(self) -> None:
        """Clear elimina la solicitud."""
        self.sentinel.request_restart(reason="test")
        self.sentinel.clear()
        assert self.sentinel.is_pending() is False

    def test_age_seconds(self) -> None:
        """Calcula la edad del sentinel."""
        self.sentinel.request_restart(reason="test")
        age = self.sentinel.age_seconds()
        assert age is not None
        assert age >= 0
        assert age < 5  # Menos de 5 segundos

    def test_age_without_request(self) -> None:
        """Edad sin solicitud es None."""
        assert self.sentinel.age_seconds() is None

    def test_overwrite(self) -> None:
        """Una nueva solicitud sobrescribe la anterior."""
        self.sentinel.request_restart(reason="first")
        self.sentinel.request_restart(reason="second")

        request = self.sentinel.check_restart_requested()
        assert request is not None
        assert request.reason == "second"
