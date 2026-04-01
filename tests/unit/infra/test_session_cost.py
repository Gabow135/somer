"""Tests para infra/session_cost.py — Seguimiento de costos."""

from __future__ import annotations

import pytest

from infra.session_cost import (
    SessionCostTracker,
    TokenUsage,
    clamp_percent,
    estimate_cost,
    estimate_cost_from_model,
    format_reset_remaining,
    get_cost_tracker,
    reset_cost_tracker,
)
from shared.types import ModelCostConfig


class TestTokenUsage:
    """Tests de uso de tokens."""

    def test_add(self) -> None:
        """Suma dos TokenUsage."""
        a = TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15)
        b = TokenUsage(input_tokens=20, output_tokens=10, total_tokens=30)
        a.add(b)

        assert a.input_tokens == 30
        assert a.output_tokens == 15
        assert a.total_tokens == 45


class TestSessionCostTracker:
    """Tests del rastreador de costos por sesión."""

    def setup_method(self) -> None:
        self.tracker = SessionCostTracker()

    def test_record_and_get(self) -> None:
        """Registrar y obtener costo de sesión."""
        usage = TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150)
        self.tracker.record_usage(
            session_id="sess-1",
            provider="anthropic",
            model="claude-sonnet",
            usage=usage,
            cost_usd=0.01,
        )

        entry = self.tracker.get_session_cost("sess-1")
        assert entry is not None
        assert entry.usage.total_tokens == 150
        assert entry.cost_usd == 0.01
        assert entry.call_count == 1

    def test_accumulate(self) -> None:
        """Acumula múltiples llamadas."""
        usage1 = TokenUsage(input_tokens=100, total_tokens=100)
        usage2 = TokenUsage(input_tokens=200, total_tokens=200)

        self.tracker.record_usage("sess-1", "a", "b", usage1, cost_usd=0.01)
        self.tracker.record_usage("sess-1", "a", "b", usage2, cost_usd=0.02)

        entry = self.tracker.get_session_cost("sess-1")
        assert entry is not None
        assert entry.usage.total_tokens == 300
        assert entry.cost_usd == pytest.approx(0.03)
        assert entry.call_count == 2

    def test_total_cost(self) -> None:
        """Costo total de todas las sesiones."""
        self.tracker.record_usage(
            "s1", "a", "b",
            TokenUsage(total_tokens=100),
            cost_usd=0.05,
        )
        self.tracker.record_usage(
            "s2", "a", "b",
            TokenUsage(total_tokens=200),
            cost_usd=0.10,
        )

        assert self.tracker.total_cost_usd == pytest.approx(0.15)
        assert self.tracker.total_tokens == 300

    def test_missing_session(self) -> None:
        """Sesión inexistente retorna None."""
        assert self.tracker.get_session_cost("nonexistent") is None

    def test_summary_lines(self) -> None:
        """Genera resumen en texto."""
        self.tracker.record_usage(
            "s1", "anthropic", "claude",
            TokenUsage(total_tokens=1000),
            cost_usd=0.05,
        )
        lines = self.tracker.summary_lines()
        assert any("$" in line for line in lines)
        assert any("1,000" in line or "1000" in line for line in lines)

    def test_summary_empty(self) -> None:
        """Resumen vacío."""
        lines = self.tracker.summary_lines()
        assert len(lines) == 1
        assert "Sin uso" in lines[0]

    def test_reset(self) -> None:
        """Reiniciar tracker."""
        self.tracker.record_usage(
            "s1", "a", "b", TokenUsage(total_tokens=100)
        )
        self.tracker.reset()
        assert self.tracker.get_session_cost("s1") is None


class TestEstimateCost:
    """Tests de estimación de costo."""

    def test_basic(self) -> None:
        cost = estimate_cost(
            input_tokens=1000,
            output_tokens=500,
            cost_per_input=0.000003,
            cost_per_output=0.000015,
        )
        assert cost == pytest.approx(0.003 + 0.0075)

    def test_zero(self) -> None:
        assert estimate_cost(0, 0, 0.001, 0.001) == 0.0


class TestEstimateCostFromModel:
    """Tests de estimación con ModelCostConfig."""

    def test_basic_input_output(self) -> None:
        cost = ModelCostConfig(input=3.0, output=15.0)
        result = estimate_cost_from_model(1_000_000, 500_000, cost)
        assert result == pytest.approx(3.0 + 7.5)

    def test_with_cache(self) -> None:
        cost = ModelCostConfig(input=3.0, output=15.0, cache_read=0.3, cache_write=3.75)
        result = estimate_cost_from_model(
            input_tokens=100_000,
            output_tokens=50_000,
            model_cost=cost,
            cache_read_tokens=200_000,
            cache_write_tokens=100_000,
        )
        expected = (
            100_000 * 3.0 / 1_000_000
            + 50_000 * 15.0 / 1_000_000
            + 200_000 * 0.3 / 1_000_000
            + 100_000 * 3.75 / 1_000_000
        )
        assert result == pytest.approx(expected)

    def test_zero_tokens(self) -> None:
        cost = ModelCostConfig(input=3.0, output=15.0)
        assert estimate_cost_from_model(0, 0, cost) == 0.0

    def test_zero_cost(self) -> None:
        cost = ModelCostConfig()
        assert estimate_cost_from_model(1_000_000, 1_000_000, cost) == 0.0

    def test_cache_only(self) -> None:
        cost = ModelCostConfig(cache_read=0.3, cache_write=3.75)
        result = estimate_cost_from_model(
            0, 0, cost, cache_read_tokens=1_000_000, cache_write_tokens=1_000_000
        )
        assert result == pytest.approx(0.3 + 3.75)


class TestClampPercent:
    """Tests de clamp de porcentaje."""

    def test_normal(self) -> None:
        assert clamp_percent(50.0) == 50.0

    def test_below_zero(self) -> None:
        assert clamp_percent(-10.0) == 0.0

    def test_above_hundred(self) -> None:
        assert clamp_percent(150.0) == 100.0

    def test_nan(self) -> None:
        assert clamp_percent(float("nan")) == 0.0


class TestFormatResetRemaining:
    """Tests de formato de tiempo restante."""

    def test_none(self) -> None:
        assert format_reset_remaining(None) is None

    def test_past(self) -> None:
        assert format_reset_remaining(1000, now=2000) == "ahora"

    def test_minutes(self) -> None:
        now = 1000000
        target = now + 30 * 60_000  # 30 minutos
        result = format_reset_remaining(target, now=now)
        assert "30m" in result or "29m" in result

    def test_hours(self) -> None:
        now = 1000000
        target = now + 3 * 3600_000  # 3 horas
        result = format_reset_remaining(target, now=now)
        assert "3h" in result or "2h" in result


class TestGlobalTracker:
    """Tests del singleton global."""

    def setup_method(self) -> None:
        reset_cost_tracker()

    def teardown_method(self) -> None:
        reset_cost_tracker()

    def test_singleton(self) -> None:
        t1 = get_cost_tracker()
        t2 = get_cost_tracker()
        assert t1 is t2

    def test_reset(self) -> None:
        t1 = get_cost_tracker()
        reset_cost_tracker()
        t2 = get_cost_tracker()
        assert t1 is not t2
