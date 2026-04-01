"""Tests para infra/runtime_status.py — Rastreo de estado del runtime."""

from __future__ import annotations

import pytest

from infra.runtime_status import (
    ComponentHealth,
    ComponentStatus,
    RuntimeStatusTracker,
    _format_uptime,
    get_runtime_tracker,
    reset_runtime_tracker,
)


class TestRuntimeStatusTracker:
    """Tests del rastreador de estado del runtime."""

    def setup_method(self) -> None:
        self.tracker = RuntimeStatusTracker(version="2.0.0-test")

    def test_version(self) -> None:
        assert self.tracker.version == "2.0.0-test"

    def test_uptime(self) -> None:
        assert self.tracker.uptime >= 0

    def test_register_component(self) -> None:
        """Registrar componentes."""
        self.tracker.register_component("gateway")
        self.tracker.register_component("memory")

        assert len(self.tracker.components) == 2
        assert "gateway" in self.tracker.components
        assert "memory" in self.tracker.components

    def test_update_health(self) -> None:
        """Actualizar salud de componente."""
        self.tracker.update_health(
            "gateway",
            ComponentHealth.HEALTHY,
            message="WebSocket activo",
        )

        comp = self.tracker.get_component("gateway")
        assert comp is not None
        assert comp.health == ComponentHealth.HEALTHY
        assert comp.message == "WebSocket activo"

    def test_auto_register_on_update(self) -> None:
        """update_health registra automáticamente si no existe."""
        self.tracker.update_health("new-comp", ComponentHealth.DEGRADED)
        assert "new-comp" in self.tracker.components

    def test_overall_health_all_healthy(self) -> None:
        """Todos saludables → HEALTHY."""
        self.tracker.update_health("a", ComponentHealth.HEALTHY)
        self.tracker.update_health("b", ComponentHealth.HEALTHY)
        assert self.tracker.compute_overall_health() == ComponentHealth.HEALTHY

    def test_overall_health_one_degraded(self) -> None:
        """Un degradado → DEGRADED."""
        self.tracker.update_health("a", ComponentHealth.HEALTHY)
        self.tracker.update_health("b", ComponentHealth.DEGRADED)
        assert self.tracker.compute_overall_health() == ComponentHealth.DEGRADED

    def test_overall_health_one_unhealthy(self) -> None:
        """Un no saludable → UNHEALTHY."""
        self.tracker.update_health("a", ComponentHealth.HEALTHY)
        self.tracker.update_health("b", ComponentHealth.UNHEALTHY)
        assert self.tracker.compute_overall_health() == ComponentHealth.UNHEALTHY

    def test_overall_health_empty(self) -> None:
        """Sin componentes → UNKNOWN."""
        assert self.tracker.compute_overall_health() == ComponentHealth.UNKNOWN

    def test_snapshot(self) -> None:
        """Generar snapshot del runtime."""
        self.tracker.update_health("gateway", ComponentHealth.HEALTHY)
        snap = self.tracker.snapshot()

        assert snap.info.version == "2.0.0-test"
        assert snap.overall_health == ComponentHealth.HEALTHY
        assert "gateway" in snap.components
        assert snap.checked_at > 0

    def test_runtime_info(self) -> None:
        """Info del runtime tiene campos esperados."""
        info = self.tracker.get_runtime_info()
        assert info.version == "2.0.0-test"
        assert info.python_version  # No vacío
        assert info.platform  # No vacío
        assert info.pid > 0

    def test_summary_lines(self) -> None:
        """Genera resumen en texto."""
        self.tracker.update_health("gateway", ComponentHealth.HEALTHY, "OK")
        lines = self.tracker.summary_lines()
        assert any("SOMER" in line for line in lines)
        assert any("gateway" in line for line in lines)


class TestFormatUptime:
    """Tests del formateo de uptime."""

    def test_seconds(self) -> None:
        assert _format_uptime(30) == "30s"

    def test_minutes(self) -> None:
        assert _format_uptime(120) == "2m 0s"

    def test_hours(self) -> None:
        assert _format_uptime(7200) == "2h 0m"

    def test_days(self) -> None:
        assert _format_uptime(86400 + 3600 + 60) == "1d 1h 1m"


class TestGlobalTracker:
    """Tests del singleton global."""

    def setup_method(self) -> None:
        reset_runtime_tracker()

    def teardown_method(self) -> None:
        reset_runtime_tracker()

    def test_singleton(self) -> None:
        t1 = get_runtime_tracker("1.0")
        t2 = get_runtime_tracker("2.0")
        assert t1 is t2  # Primera creación gana

    def test_reset(self) -> None:
        t1 = get_runtime_tracker()
        reset_runtime_tracker()
        t2 = get_runtime_tracker()
        assert t1 is not t2
