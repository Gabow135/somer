"""Tests para infra/heartbeat.py — HeartbeatRunner."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from infra.heartbeat import (
    DEFAULT_PROMPT,
    HEARTBEAT_TOKEN,
    HeartbeatRunner,
    is_heartbeat_ok,
    is_within_active_hours,
)


# ── Helpers ───────────────────────────────────────────────────────


def _make_config(
    enabled: bool = True,
    every: int = 60,
    target: str = "telegram",
    target_chat_id: str = "123",
    prompt: str = "",
    model: str = "",
    show_ok: bool = False,
    active_hours: Any = None,
    deduplicate_hours: int = 24,
) -> MagicMock:
    hb = MagicMock()
    hb.enabled = enabled
    hb.every = every
    hb.target = target
    hb.target_chat_id = target_chat_id
    hb.prompt = prompt or None
    hb.model = model or None
    hb.show_ok = show_ok
    hb.active_hours = active_hours
    hb.deduplicate_hours = deduplicate_hours

    config = MagicMock()
    config.heartbeat = hb
    config.default_model = "claude-sonnet-4-5-20250929"
    return config


def _make_turn(content: str) -> MagicMock:
    msg = MagicMock()
    msg.role.value = "assistant"
    msg.content = content

    turn = MagicMock()
    turn.messages = [msg]
    return turn


# ── TestHeartbeatOkDetection ──────────────────────────────────────


class TestHeartbeatOkDetection:
    """Detecta HEARTBEAT_OK en respuestas."""

    def test_exact_token(self) -> None:
        assert is_heartbeat_ok("HEARTBEAT_OK") is True

    def test_with_whitespace(self) -> None:
        assert is_heartbeat_ok("  HEARTBEAT_OK  ") is True

    def test_lowercase(self) -> None:
        assert is_heartbeat_ok("heartbeat_ok") is True

    def test_empty(self) -> None:
        assert is_heartbeat_ok("") is True

    def test_content_is_not_ok(self) -> None:
        assert is_heartbeat_ok("Tienes 3 tareas pendientes") is False

    def test_ok_with_extra_content(self) -> None:
        assert is_heartbeat_ok("HEARTBEAT_OK\nPero hay algo mas") is False


# ── TestActiveHours ───────────────────────────────────────────────


class TestActiveHours:
    """Verificación de horario activo."""

    def test_within_hours(self) -> None:
        now = datetime(2024, 1, 15, 14, 30)  # 14:30
        assert is_within_active_hours("08:00", "22:00", "UTC", now) is True

    def test_outside_hours(self) -> None:
        now = datetime(2024, 1, 15, 23, 30)  # 23:30
        assert is_within_active_hours("08:00", "22:00", "UTC", now) is False

    def test_before_start(self) -> None:
        now = datetime(2024, 1, 15, 6, 0)  # 06:00
        assert is_within_active_hours("08:00", "22:00", "UTC", now) is False

    def test_at_start(self) -> None:
        now = datetime(2024, 1, 15, 8, 0)  # 08:00
        assert is_within_active_hours("08:00", "22:00", "UTC", now) is True

    def test_at_end(self) -> None:
        now = datetime(2024, 1, 15, 22, 0)  # 22:00
        assert is_within_active_hours("08:00", "22:00", "UTC", now) is False

    def test_overnight_range_inside(self) -> None:
        now = datetime(2024, 1, 15, 23, 30)  # 23:30
        assert is_within_active_hours("22:00", "06:00", "UTC", now) is True

    def test_overnight_range_outside(self) -> None:
        now = datetime(2024, 1, 15, 12, 0)  # 12:00
        assert is_within_active_hours("22:00", "06:00", "UTC", now) is False

    def test_invalid_format_returns_true(self) -> None:
        now = datetime(2024, 1, 15, 12, 0)
        assert is_within_active_hours("bad", "22:00", "UTC", now) is True

    def test_same_start_end_returns_false(self) -> None:
        now = datetime(2024, 1, 15, 12, 0)
        assert is_within_active_hours("08:00", "08:00", "UTC", now) is False


# ── TestHeartbeatRunner ───────────────────────────────────────────


class TestHeartbeatRunner:
    """Tests del runner principal."""

    def setup_method(self) -> None:
        self.runner = AsyncMock()
        self.channels = MagicMock()
        self.config = _make_config()
        self.hb = HeartbeatRunner(
            runner=self.runner,
            channel_registry=self.channels,
            config=self.config,
        )

    @pytest.mark.asyncio
    async def test_run_once_ok(self) -> None:
        """LLM responde HEARTBEAT_OK → no enviar nada."""
        self.runner.run.return_value = _make_turn("HEARTBEAT_OK")
        result = await self.hb._run_once()
        assert result == "ok"
        self.channels.get.return_value.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_once_alert(self) -> None:
        """LLM responde con contenido → enviar al canal."""
        plugin = AsyncMock()
        self.channels.get.return_value = plugin
        self.runner.run.return_value = _make_turn("Tienes 3 tareas pendientes")

        result = await self.hb._run_once()
        assert result == "alert-sent"
        plugin.send_message.assert_called_once_with(
            "123", "Tienes 3 tareas pendientes"
        )

    @pytest.mark.asyncio
    async def test_run_once_no_target(self) -> None:
        """Target 'none' → no enviar."""
        self.config.heartbeat.target = "none"
        self.runner.run.return_value = _make_turn("Hay alertas")

        result = await self.hb._run_once()
        assert result == "skipped-no-target"

    @pytest.mark.asyncio
    async def test_run_once_quiet_hours(self) -> None:
        """Fuera de horario activo → skip."""
        ah = MagicMock()
        ah.start = "08:00"
        ah.end = "22:00"
        ah.timezone = "UTC"
        self.config.heartbeat.active_hours = ah

        with patch("infra.heartbeat.is_within_active_hours", return_value=False):
            result = await self.hb._run_once()
        assert result == "skipped-quiet-hours"

    @pytest.mark.asyncio
    async def test_run_once_show_ok(self) -> None:
        """show_ok=True → enviar HEARTBEAT_OK al canal."""
        self.config.heartbeat.show_ok = True
        plugin = AsyncMock()
        self.channels.get.return_value = plugin
        self.runner.run.return_value = _make_turn("HEARTBEAT_OK")

        result = await self.hb._run_once()
        assert result == "ok"
        plugin.send_message.assert_called_once_with("123", HEARTBEAT_TOKEN)

    @pytest.mark.asyncio
    async def test_run_once_llm_error(self) -> None:
        """Error en LLM → retornar 'error'."""
        self.runner.run.side_effect = Exception("provider down")

        result = await self.hb._run_once()
        assert result == "error"

    @pytest.mark.asyncio
    async def test_run_once_channel_not_found(self) -> None:
        """Canal no encontrado → skip."""
        self.channels.get.return_value = None
        self.runner.run.return_value = _make_turn("Alerta importante")

        result = await self.hb._run_once()
        assert result == "skipped-no-target"


# ── TestDeduplication ─────────────────────────────────────────────


class TestDeduplication:
    """Deduplicación de alertas repetidas."""

    def setup_method(self) -> None:
        self.runner = AsyncMock()
        self.channels = MagicMock()
        self.config = _make_config()
        self.hb = HeartbeatRunner(
            runner=self.runner,
            channel_registry=self.channels,
            config=self.config,
        )

    @pytest.mark.asyncio
    async def test_duplicate_suppressed(self) -> None:
        """Mismo texto dentro de ventana → suprimir."""
        plugin = AsyncMock()
        self.channels.get.return_value = plugin
        self.runner.run.return_value = _make_turn("3 tareas pendientes")

        # Primera vez: enviar
        result1 = await self.hb._run_once()
        assert result1 == "alert-sent"

        # Segunda vez: suprimir
        result2 = await self.hb._run_once()
        assert result2 == "skipped-duplicate"

    @pytest.mark.asyncio
    async def test_different_text_not_duplicate(self) -> None:
        """Texto diferente → no es duplicado."""
        plugin = AsyncMock()
        self.channels.get.return_value = plugin

        self.runner.run.return_value = _make_turn("3 tareas pendientes")
        await self.hb._run_once()

        self.runner.run.return_value = _make_turn("5 tareas pendientes ahora")
        result = await self.hb._run_once()
        assert result == "alert-sent"


# ── TestBuildPrompt ───────────────────────────────────────────────


class TestBuildPrompt:
    """Construcción del prompt de heartbeat."""

    def setup_method(self) -> None:
        self.config = _make_config()
        self.hb = HeartbeatRunner(
            runner=AsyncMock(),
            channel_registry=MagicMock(),
            config=self.config,
        )

    def test_default_prompt(self) -> None:
        prompt = self.hb._build_prompt("")
        assert "HEARTBEAT_OK" in prompt
        assert "HEARTBEAT.md" in prompt

    def test_custom_prompt(self) -> None:
        self.config.heartbeat.prompt = "Revisa mi email"
        prompt = self.hb._build_prompt("")
        assert "Revisa mi email" in prompt

    def test_with_heartbeat_content(self) -> None:
        prompt = self.hb._build_prompt("Revisa los PRs abiertos en GitHub")
        assert "Revisa los PRs abiertos" in prompt
        assert "HEARTBEAT.md" in prompt

    def test_includes_timestamp(self) -> None:
        prompt = self.hb._build_prompt("")
        assert "Fecha y hora actual" in prompt


# ── TestStartStop ─────────────────────────────────────────────────


class TestStartStop:
    """Ciclo de vida del runner."""

    @pytest.mark.asyncio
    async def test_start_disabled(self) -> None:
        config = _make_config(enabled=False)
        hb = HeartbeatRunner(
            runner=AsyncMock(),
            channel_registry=MagicMock(),
            config=config,
        )
        await hb.start()
        assert hb._running is False

    @pytest.mark.asyncio
    async def test_start_enabled(self) -> None:
        config = _make_config(enabled=True)
        hb = HeartbeatRunner(
            runner=AsyncMock(),
            channel_registry=MagicMock(),
            config=config,
        )
        await hb.start()
        assert hb._running is True
        await hb.stop()
        assert hb._running is False

    def test_update_config(self) -> None:
        config = _make_config()
        hb = HeartbeatRunner(
            runner=AsyncMock(),
            channel_registry=MagicMock(),
            config=config,
        )
        new_config = _make_config(every=120, target="discord")
        hb.update_config(new_config)
        assert hb._hb_config.every == 120
        assert hb._hb_config.target == "discord"
