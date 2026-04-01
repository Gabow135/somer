"""Tests para infra/system_events.py — Bus de eventos del sistema."""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from infra.system_events import (
    EventPayload,
    RunContext,
    clear_run_context,
    emit_agent_event,
    emit_diagnostic_event,
    get_run_context,
    matches_diagnostic_flag,
    on_agent_event,
    on_diagnostic_event,
    parse_diagnostic_flags,
    register_run_context,
    reset_agent_events,
    reset_diagnostic_events,
    resolve_diagnostic_flags,
)


# ── Agent Events ─────────────────────────────────────────────


class TestAgentEvents:
    """Tests del bus de eventos de agente."""

    def setup_method(self) -> None:
        reset_agent_events()

    def teardown_method(self) -> None:
        reset_agent_events()

    def test_emit_and_receive(self) -> None:
        """Emitir un evento y recibirlo con listener."""
        received: List[EventPayload] = []
        on_agent_event(lambda evt: received.append(evt))

        emit_agent_event("run-1", "lifecycle", {"action": "start"})

        assert len(received) == 1
        assert received[0].run_id == "run-1"
        assert received[0].stream == "lifecycle"
        assert received[0].seq == 1
        assert received[0].data["action"] == "start"
        assert received[0].ts > 0

    def test_sequential_seq(self) -> None:
        """Los seq son secuenciales por run_id."""
        received: List[EventPayload] = []
        on_agent_event(lambda evt: received.append(evt))

        emit_agent_event("run-1", "tool", {"name": "a"})
        emit_agent_event("run-1", "tool", {"name": "b"})
        emit_agent_event("run-2", "tool", {"name": "c"})

        assert received[0].seq == 1
        assert received[1].seq == 2
        assert received[2].seq == 1  # Diferente run_id

    def test_unsubscribe(self) -> None:
        """Desuscribir un listener."""
        received: List[EventPayload] = []
        unsub = on_agent_event(lambda evt: received.append(evt))

        emit_agent_event("run-1", "lifecycle", {})
        assert len(received) == 1

        unsub()
        emit_agent_event("run-1", "lifecycle", {})
        assert len(received) == 1  # No recibió más

    def test_listener_error_ignored(self) -> None:
        """Errores en listeners no afectan a otros."""
        received: List[EventPayload] = []

        on_agent_event(lambda evt: 1 / 0)  # Error
        on_agent_event(lambda evt: received.append(evt))

        emit_agent_event("run-1", "error", {})
        assert len(received) == 1

    def test_multiple_listeners(self) -> None:
        """Múltiples listeners reciben el mismo evento."""
        counts = [0, 0]

        on_agent_event(lambda evt: counts.__setitem__(0, counts[0] + 1))
        on_agent_event(lambda evt: counts.__setitem__(1, counts[1] + 1))

        emit_agent_event("run-1", "assistant", {})
        assert counts == [1, 1]


# ── Run Context ──────────────────────────────────────────────


class TestRunContext:
    """Tests de contexto de ejecución."""

    def setup_method(self) -> None:
        reset_agent_events()

    def teardown_method(self) -> None:
        reset_agent_events()

    def test_register_and_get(self) -> None:
        """Registrar y obtener contexto."""
        ctx = RunContext(session_key="sess-1", is_heartbeat=True)
        register_run_context("run-1", ctx)

        result = get_run_context("run-1")
        assert result is not None
        assert result.session_key == "sess-1"
        assert result.is_heartbeat is True

    def test_update_existing(self) -> None:
        """Actualizar un contexto existente."""
        register_run_context("run-1", RunContext(session_key="a"))
        register_run_context("run-1", RunContext(session_key="b"))

        result = get_run_context("run-1")
        assert result is not None
        assert result.session_key == "b"

    def test_clear(self) -> None:
        """Limpiar un contexto."""
        register_run_context("run-1", RunContext())
        clear_run_context("run-1")
        assert get_run_context("run-1") is None

    def test_empty_run_id_ignored(self) -> None:
        """run_id vacío no registra nada."""
        register_run_context("", RunContext(session_key="x"))
        assert get_run_context("") is None

    def test_session_key_in_event(self) -> None:
        """El session_key del contexto se incluye en eventos."""
        received: List[EventPayload] = []
        on_agent_event(lambda evt: received.append(evt))

        register_run_context("run-1", RunContext(session_key="sess-A"))
        emit_agent_event("run-1", "lifecycle", {})

        assert received[0].session_key == "sess-A"

    def test_control_ui_invisible(self) -> None:
        """Si is_control_ui_visible=False, session_key es None."""
        received: List[EventPayload] = []
        on_agent_event(lambda evt: received.append(evt))

        register_run_context(
            "run-1",
            RunContext(session_key="sess-A", is_control_ui_visible=False),
        )
        emit_agent_event("run-1", "lifecycle", {})

        assert received[0].session_key is None


# ── Diagnostic Events ────────────────────────────────────────


class TestDiagnosticEvents:
    """Tests del bus de eventos de diagnóstico."""

    def setup_method(self) -> None:
        reset_diagnostic_events()

    def teardown_method(self) -> None:
        reset_diagnostic_events()

    def test_emit_and_receive(self) -> None:
        """Emitir y recibir evento de diagnóstico."""
        received: list = []
        on_diagnostic_event(lambda evt: received.append(evt))

        emit_diagnostic_event("model.usage", {"tokens": 100})

        assert len(received) == 1
        assert received[0].type == "model.usage"
        assert received[0].seq == 1
        assert received[0].data["tokens"] == 100

    def test_incremental_seq(self) -> None:
        """Los seq son incrementales globales."""
        received: list = []
        on_diagnostic_event(lambda evt: received.append(evt))

        emit_diagnostic_event("a", {})
        emit_diagnostic_event("b", {})

        assert received[0].seq == 1
        assert received[1].seq == 2

    def test_unsubscribe(self) -> None:
        """Desuscribir listener de diagnóstico."""
        received: list = []
        unsub = on_diagnostic_event(lambda evt: received.append(evt))

        emit_diagnostic_event("x", {})
        unsub()
        emit_diagnostic_event("y", {})

        assert len(received) == 1


# ── Diagnostic Flags ─────────────────────────────────────────


class TestDiagnosticFlags:
    """Tests de flags de diagnóstico."""

    def test_parse_empty(self) -> None:
        assert parse_diagnostic_flags("") == []
        assert parse_diagnostic_flags(None) == []

    def test_parse_truthy(self) -> None:
        assert parse_diagnostic_flags("1") == ["*"]
        assert parse_diagnostic_flags("true") == ["*"]
        assert parse_diagnostic_flags("all") == ["*"]

    def test_parse_falsy(self) -> None:
        assert parse_diagnostic_flags("0") == []
        assert parse_diagnostic_flags("false") == []
        assert parse_diagnostic_flags("off") == []

    def test_parse_csv(self) -> None:
        result = parse_diagnostic_flags("model.usage, webhook.received")
        assert "model.usage" in result
        assert "webhook.received" in result

    def test_matches_wildcard(self) -> None:
        assert matches_diagnostic_flag("anything", ["*"]) is True
        assert matches_diagnostic_flag("anything", ["all"]) is True

    def test_matches_exact(self) -> None:
        assert matches_diagnostic_flag("model.usage", ["model.usage"]) is True
        assert matches_diagnostic_flag("model.usage", ["webhook"]) is False

    def test_matches_prefix_wildcard(self) -> None:
        assert matches_diagnostic_flag("model.usage", ["model.*"]) is True
        assert matches_diagnostic_flag("model", ["model.*"]) is True
        assert matches_diagnostic_flag("webhook", ["model.*"]) is False

    def test_matches_glob_wildcard(self) -> None:
        assert matches_diagnostic_flag("model.usage", ["model*"]) is True
        assert matches_diagnostic_flag("webhook", ["model*"]) is False

    def test_empty_flag(self) -> None:
        assert matches_diagnostic_flag("", ["*"]) is False
