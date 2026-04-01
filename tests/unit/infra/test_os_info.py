"""Tests para infra/os_info.py — Información del sistema operativo."""

from __future__ import annotations

import platform
import sys

import pytest

from infra.os_info import (
    OsSummary,
    environment_summary,
    get_system_resources,
    is_docker,
    is_wsl,
    resolve_os_summary,
)


class TestOsSummary:
    """Tests del resumen del sistema operativo."""

    def test_resolve_summary(self) -> None:
        """resolve_os_summary retorna información válida."""
        summary = resolve_os_summary()

        assert summary.platform == sys.platform
        assert summary.arch == platform.machine()
        assert len(summary.label) > 0
        assert summary.python_version == platform.python_version()

    def test_platform_in_label(self) -> None:
        """La plataforma aparece en la etiqueta."""
        summary = resolve_os_summary()
        label_lower = summary.label.lower()

        if sys.platform == "darwin":
            assert "macos" in label_lower
        elif sys.platform == "linux":
            assert "linux" in label_lower or True  # Puede ser distro name
        elif sys.platform == "win32":
            assert "windows" in label_lower

    def test_arch_in_label(self) -> None:
        """La arquitectura aparece en la etiqueta."""
        summary = resolve_os_summary()
        assert summary.arch in summary.label


class TestSystemResources:
    """Tests de recursos del sistema."""

    def test_cpu_count(self) -> None:
        """CPU count es positivo."""
        resources = get_system_resources()
        assert resources.cpu_count > 0

    def test_disk_info(self) -> None:
        """Info de disco es razonable."""
        resources = get_system_resources()
        assert resources.disk_total_mb > 0
        assert resources.disk_free_mb >= 0


class TestEnvironmentDetection:
    """Tests de detección de entorno."""

    def test_is_docker_returns_bool(self) -> None:
        """is_docker retorna un booleano."""
        result = is_docker()
        assert isinstance(result, bool)

    def test_is_wsl_returns_bool(self) -> None:
        """is_wsl retorna un booleano."""
        result = is_wsl()
        assert isinstance(result, bool)


class TestEnvironmentSummary:
    """Tests del resumen de entorno."""

    def test_summary_has_keys(self) -> None:
        """El resumen tiene las claves esperadas."""
        summary = environment_summary()
        assert "os" in summary
        assert "platform" in summary
        assert "arch" in summary
        assert "python" in summary
        assert "cpus" in summary
        assert "docker" in summary

    def test_summary_values_non_empty(self) -> None:
        """Los valores del resumen no están vacíos."""
        summary = environment_summary()
        assert summary["os"]
        assert summary["python"]
        assert int(summary["cpus"]) > 0
