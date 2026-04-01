"""Tests para infra/ports.py — Sondeo de puertos."""

from __future__ import annotations

import socket

import pytest

from infra.ports import (
    find_free_port,
    is_port_available,
    probe_ports,
    wait_for_port,
    wait_for_port_free,
)


class TestPortAvailability:
    """Tests de disponibilidad de puertos."""

    def test_available_port(self) -> None:
        """Un puerto libre está disponible."""
        port = find_free_port()
        assert is_port_available("127.0.0.1", port)

    def test_in_use_port(self) -> None:
        """Un puerto ocupado no está disponible."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
            assert not is_port_available("127.0.0.1", port)

    def test_find_free_port(self) -> None:
        """Encuentra un puerto libre."""
        port = find_free_port()
        assert isinstance(port, int)
        assert port > 0

    def test_find_free_port_in_range(self) -> None:
        """Encuentra un puerto en un rango."""
        port = find_free_port(start=49152, end=65535)
        assert 49152 <= port <= 65535

    def test_probe_ports(self) -> None:
        """Sondea puertos y reporta los que están en uso."""
        free_port = find_free_port()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", 0))
            busy_port = s.getsockname()[1]

            in_use = probe_ports([free_port, busy_port])
            assert busy_port in in_use
            assert free_port not in in_use


class TestWaitForPort:
    """Tests de espera de puertos."""

    @pytest.mark.asyncio
    async def test_wait_for_port_timeout(self) -> None:
        """Timeout cuando el puerto no está disponible."""
        free_port = find_free_port()
        result = await wait_for_port("127.0.0.1", free_port, timeout=0.3)
        assert result is False

    @pytest.mark.asyncio
    async def test_wait_for_port_free(self) -> None:
        """Espera que un puerto se libere."""
        free_port = find_free_port()
        # Ya está libre
        result = await wait_for_port_free("127.0.0.1", free_port, timeout=0.3)
        assert result is True
