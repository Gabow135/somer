"""Tests para cron.parser — parser de expresiones cron."""

from __future__ import annotations

import pytest
from datetime import datetime

from cron.parser import (
    describe_cron,
    is_top_of_hour_cron,
    matches_cron,
    next_cron_datetime,
    parse_absolute_time,
    parse_cron_expression,
    prev_cron_datetime,
)
from shared.errors import CronExpressionError


# ── parse_cron_expression ───────────────────────────────────


class TestParseCronExpression:
    """Tests para parse_cron_expression."""

    def test_every_minute(self) -> None:
        fields = parse_cron_expression("* * * * *")
        assert len(fields) == 5
        assert fields[0] == list(range(0, 60))  # minutos
        assert fields[1] == list(range(0, 24))  # horas

    def test_specific_minute_hour(self) -> None:
        fields = parse_cron_expression("30 14 * * *")
        assert fields[0] == [30]
        assert fields[1] == [14]

    def test_step_expression(self) -> None:
        fields = parse_cron_expression("*/5 * * * *")
        assert fields[0] == [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55]

    def test_range_expression(self) -> None:
        fields = parse_cron_expression("0 9-17 * * *")
        assert fields[0] == [0]
        assert fields[1] == list(range(9, 18))

    def test_range_with_step(self) -> None:
        fields = parse_cron_expression("0 0-12/3 * * *")
        assert fields[1] == [0, 3, 6, 9, 12]

    def test_list_expression(self) -> None:
        fields = parse_cron_expression("0 8,12,18 * * *")
        assert fields[1] == [8, 12, 18]

    def test_weekday_expression(self) -> None:
        fields = parse_cron_expression("0 9 * * 1-5")
        assert fields[4] == [1, 2, 3, 4, 5]

    def test_special_daily(self) -> None:
        fields = parse_cron_expression("@daily")
        assert fields[0] == [0]
        assert fields[1] == [0]
        assert fields[2] == list(range(1, 32))

    def test_special_hourly(self) -> None:
        fields = parse_cron_expression("@hourly")
        assert fields[0] == [0]
        assert fields[1] == list(range(0, 24))

    def test_special_weekly(self) -> None:
        fields = parse_cron_expression("@weekly")
        assert fields[4] == [0]  # domingo

    def test_special_monthly(self) -> None:
        fields = parse_cron_expression("@monthly")
        assert fields[2] == [1]

    def test_special_yearly(self) -> None:
        fields = parse_cron_expression("@yearly")
        assert fields[2] == [1]  # día 1
        assert fields[3] == [1]  # enero

    def test_special_every_minute(self) -> None:
        fields = parse_cron_expression("@every_minute")
        assert fields[0] == list(range(0, 60))

    def test_month_names(self) -> None:
        fields = parse_cron_expression("0 0 1 jan,jun *")
        assert fields[3] == [1, 6]

    def test_dow_names(self) -> None:
        fields = parse_cron_expression("0 9 * * mon-fri")
        assert fields[4] == [1, 2, 3, 4, 5]

    def test_invalid_too_few_fields(self) -> None:
        with pytest.raises(CronExpressionError, match="5 campos"):
            parse_cron_expression("* * *")

    def test_invalid_too_many_fields(self) -> None:
        with pytest.raises(CronExpressionError, match="5 campos"):
            parse_cron_expression("* * * * * *")

    def test_invalid_special(self) -> None:
        with pytest.raises(CronExpressionError, match="desconocida"):
            parse_cron_expression("@invalid")

    def test_invalid_range_out_of_bounds(self) -> None:
        with pytest.raises(CronExpressionError, match="fuera de límites"):
            parse_cron_expression("70 * * * *")

    def test_invalid_non_numeric(self) -> None:
        with pytest.raises(CronExpressionError, match="no numérico"):
            parse_cron_expression("abc * * * *")

    def test_invalid_step_zero(self) -> None:
        with pytest.raises(CronExpressionError, match="Step inválido"):
            parse_cron_expression("*/0 * * * *")


# ── matches_cron ────────────────────────────────────────────


class TestMatchesCron:
    """Tests para matches_cron."""

    def test_every_minute_always_matches(self) -> None:
        assert matches_cron("* * * * *", datetime(2025, 1, 1, 12, 30))

    def test_specific_time_matches(self) -> None:
        assert matches_cron("30 14 * * *", datetime(2025, 1, 1, 14, 30))

    def test_specific_time_no_match(self) -> None:
        assert not matches_cron("30 14 * * *", datetime(2025, 1, 1, 14, 31))

    def test_step_matches(self) -> None:
        assert matches_cron("*/15 * * * *", datetime(2025, 1, 1, 12, 0))
        assert matches_cron("*/15 * * * *", datetime(2025, 1, 1, 12, 15))
        assert matches_cron("*/15 * * * *", datetime(2025, 1, 1, 12, 30))
        assert not matches_cron("*/15 * * * *", datetime(2025, 1, 1, 12, 7))

    def test_weekday_match(self) -> None:
        # 2025-01-06 es lunes (isoweekday=1, %7=1)
        assert matches_cron("0 9 * * 1", datetime(2025, 1, 6, 9, 0))
        assert not matches_cron("0 9 * * 1", datetime(2025, 1, 7, 9, 0))  # martes

    def test_special_daily_at_midnight(self) -> None:
        assert matches_cron("@daily", datetime(2025, 6, 15, 0, 0))
        assert not matches_cron("@daily", datetime(2025, 6, 15, 0, 1))

    def test_month_match(self) -> None:
        assert matches_cron("0 0 1 1 *", datetime(2025, 1, 1, 0, 0))
        assert not matches_cron("0 0 1 1 *", datetime(2025, 2, 1, 0, 0))

    def test_range_match(self) -> None:
        assert matches_cron("0 9-17 * * *", datetime(2025, 1, 1, 12, 0))
        assert not matches_cron("0 9-17 * * *", datetime(2025, 1, 1, 18, 0))

    def test_list_match(self) -> None:
        assert matches_cron("0 8,12,18 * * *", datetime(2025, 1, 1, 12, 0))
        assert not matches_cron("0 8,12,18 * * *", datetime(2025, 1, 1, 10, 0))

    def test_sunday_is_zero(self) -> None:
        # 2025-01-05 es domingo (isoweekday=7, %7=0)
        assert matches_cron("0 0 * * 0", datetime(2025, 1, 5, 0, 0))


# ── next_cron_datetime ──────────────────────────────────────


class TestNextCronDatetime:
    """Tests para next_cron_datetime."""

    def test_next_minute(self) -> None:
        now = datetime(2025, 1, 1, 12, 30, 0)
        result = next_cron_datetime("* * * * *", now)
        assert result is not None
        assert result == datetime(2025, 1, 1, 12, 31, 0)

    def test_next_specific_time(self) -> None:
        now = datetime(2025, 1, 1, 12, 0, 0)
        result = next_cron_datetime("30 14 * * *", now)
        assert result is not None
        assert result.hour == 14
        assert result.minute == 30

    def test_next_daily(self) -> None:
        now = datetime(2025, 1, 1, 0, 1, 0)
        result = next_cron_datetime("@daily", now)
        assert result is not None
        assert result.day == 2
        assert result.hour == 0
        assert result.minute == 0

    def test_next_step(self) -> None:
        now = datetime(2025, 1, 1, 12, 3, 0)
        result = next_cron_datetime("*/5 * * * *", now)
        assert result is not None
        assert result.minute == 5

    def test_returns_none_invalid(self) -> None:
        with pytest.raises(CronExpressionError):
            next_cron_datetime("invalid", datetime(2025, 1, 1))


# ── prev_cron_datetime ──────────────────────────────────────


class TestPrevCronDatetime:
    """Tests para prev_cron_datetime."""

    def test_prev_minute(self) -> None:
        now = datetime(2025, 1, 1, 12, 30, 0)
        result = prev_cron_datetime("* * * * *", now)
        assert result is not None
        assert result == datetime(2025, 1, 1, 12, 29, 0)

    def test_prev_specific_time(self) -> None:
        now = datetime(2025, 1, 1, 15, 0, 0)
        result = prev_cron_datetime("30 14 * * *", now)
        assert result is not None
        assert result.hour == 14
        assert result.minute == 30

    def test_prev_daily(self) -> None:
        now = datetime(2025, 1, 2, 12, 0, 0)
        result = prev_cron_datetime("@daily", now)
        assert result is not None
        assert result.day == 2
        assert result.hour == 0
        assert result.minute == 0


# ── parse_absolute_time ─────────────────────────────────────


class TestParseAbsoluteTime:
    """Tests para parse_absolute_time."""

    def test_epoch_seconds(self) -> None:
        result = parse_absolute_time("1704067200")
        assert result is not None
        assert abs(result - 1704067200.0) < 1

    def test_epoch_milliseconds(self) -> None:
        result = parse_absolute_time("1704067200000")
        assert result is not None
        assert abs(result - 1704067200.0) < 1

    def test_iso_with_tz(self) -> None:
        result = parse_absolute_time("2025-01-01T00:00:00Z")
        assert result is not None
        assert result > 0

    def test_iso_date_only(self) -> None:
        result = parse_absolute_time("2025-01-01")
        assert result is not None

    def test_iso_datetime_no_tz(self) -> None:
        result = parse_absolute_time("2025-01-01T12:00:00")
        assert result is not None

    def test_empty_returns_none(self) -> None:
        assert parse_absolute_time("") is None
        assert parse_absolute_time("  ") is None

    def test_invalid_returns_none(self) -> None:
        assert parse_absolute_time("not-a-date") is None


# ── is_top_of_hour_cron ────────────────────────────────────


class TestIsTopOfHourCron:
    """Tests para is_top_of_hour_cron."""

    def test_every_hour(self) -> None:
        assert is_top_of_hour_cron("0 * * * *")

    def test_every_2_hours(self) -> None:
        assert is_top_of_hour_cron("0 */2 * * *")

    def test_not_top_of_hour(self) -> None:
        assert not is_top_of_hour_cron("*/5 * * * *")

    def test_specific_minute(self) -> None:
        assert not is_top_of_hour_cron("30 * * * *")


# ── describe_cron ───────────────────────────────────────────


class TestDescribeCron:
    """Tests para describe_cron."""

    def test_describe_daily(self) -> None:
        desc = describe_cron("@daily")
        assert "medianoche" in desc

    def test_describe_hourly(self) -> None:
        desc = describe_cron("@hourly")
        assert "hora" in desc

    def test_describe_every_5_minutes(self) -> None:
        desc = describe_cron("*/5 * * * *")
        assert "5" in desc and "minuto" in desc

    def test_describe_specific_time(self) -> None:
        desc = describe_cron("30 14 * * *")
        assert "14" in desc and "30" in desc
