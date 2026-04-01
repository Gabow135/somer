"""Tests para cron.scheduler — scheduler con todas las features portadas."""

from __future__ import annotations

import asyncio
import time

import pytest

from cron.scheduler import (
    CronAction,
    CronFailureAlertConfig,
    CronJob,
    CronJobState,
    CronRetryConfig,
    CronRunStatus,
    CronScheduleKind,
    CronScheduler,
    _error_backoff_secs,
    _is_transient_error,
    _resolve_stable_stagger_offset,
)
from shared.errors import CronError, CronJobNotFoundError


# ── Helpers ─────────────────────────────────────────────────


async def _noop_action() -> None:
    """Acción noop para tests."""


async def _slow_action() -> None:
    """Acción que tarda 0.2s."""
    await asyncio.sleep(0.2)


async def _failing_action() -> None:
    """Acción que siempre falla."""
    raise RuntimeError("Error de test")


async def _timeout_action() -> None:
    """Acción que siempre hace timeout."""
    await asyncio.sleep(100)


# ── Tests de gestión de jobs ────────────────────────────────


class TestJobManagement:
    """Tests para add, remove, enable, disable, list, get, update."""

    def test_add_job(self) -> None:
        sched = CronScheduler()
        job_id = sched.add("*/5 * * * *", _noop_action, "Test job")
        assert job_id is not None
        assert len(sched.list_jobs()) == 1

    def test_add_job_custom_id(self) -> None:
        sched = CronScheduler()
        job_id = sched.add("* * * * *", _noop_action, job_id="custom-123")
        assert job_id == "custom-123"

    def test_add_duplicate_raises(self) -> None:
        sched = CronScheduler()
        sched.add("* * * * *", _noop_action, job_id="dup")
        with pytest.raises(CronError, match="Ya existe"):
            sched.add("* * * * *", _noop_action, job_id="dup")

    def test_remove_job(self) -> None:
        sched = CronScheduler()
        jid = sched.add("* * * * *", _noop_action)
        assert sched.remove(jid) is True
        assert sched.remove(jid) is False
        assert len(sched.list_jobs()) == 0

    def test_enable_disable(self) -> None:
        sched = CronScheduler()
        jid = sched.add("* * * * *", _noop_action, enabled=False)
        job = sched.get_job(jid)
        assert job is not None
        assert not job.enabled

        sched.enable(jid)
        assert job.enabled
        assert job.state.next_run_at is not None

        sched.disable(jid)
        assert not job.enabled
        assert job.state.next_run_at is None

    def test_pause_resume(self) -> None:
        sched = CronScheduler()
        jid = sched.add("* * * * *", _noop_action)
        sched.pause(jid)
        job = sched.get_job(jid)
        assert job is not None
        assert not job.enabled

        sched.resume(jid)
        assert job.enabled

    def test_enable_nonexistent_raises(self) -> None:
        sched = CronScheduler()
        with pytest.raises(CronJobNotFoundError):
            sched.enable("nonexistent")

    def test_disable_nonexistent_raises(self) -> None:
        sched = CronScheduler()
        with pytest.raises(CronJobNotFoundError):
            sched.disable("nonexistent")

    def test_get_job(self) -> None:
        sched = CronScheduler()
        jid = sched.add("*/5 * * * *", _noop_action, "Test")
        job = sched.get_job(jid)
        assert job is not None
        assert job.expression == "*/5 * * * *"

    def test_get_nonexistent(self) -> None:
        sched = CronScheduler()
        assert sched.get_job("nope") is None

    def test_list_enabled_jobs(self) -> None:
        sched = CronScheduler()
        sched.add("* * * * *", _noop_action, enabled=True, job_id="a")
        sched.add("* * * * *", _noop_action, enabled=False, job_id="b")
        sched.add("* * * * *", _noop_action, enabled=True, job_id="c")
        assert len(sched.list_enabled_jobs()) == 2

    def test_update_job(self) -> None:
        sched = CronScheduler()
        jid = sched.add("* * * * *", _noop_action, "Original")
        job = sched.update_job(jid, description="Updated", name="Nuevo nombre")
        assert job.description == "Updated"
        assert job.name == "Nuevo nombre"

    def test_update_expression(self) -> None:
        sched = CronScheduler()
        jid = sched.add("* * * * *", _noop_action)
        job = sched.update_job(jid, expression="*/10 * * * *")
        assert job.expression == "*/10 * * * *"

    def test_update_nonexistent_raises(self) -> None:
        sched = CronScheduler()
        with pytest.raises(CronJobNotFoundError):
            sched.update_job("nope", description="nope")

    def test_add_with_special_expression(self) -> None:
        sched = CronScheduler()
        jid = sched.add("@daily", _noop_action, "Daily job")
        job = sched.get_job(jid)
        assert job is not None
        assert job.expression == "@daily"

    def test_add_with_timezone(self) -> None:
        sched = CronScheduler()
        jid = sched.add(
            "0 9 * * *", _noop_action, "TZ job",
            timezone="America/Mexico_City",
        )
        job = sched.get_job(jid)
        assert job is not None
        assert job.timezone == "America/Mexico_City"

    def test_add_with_jitter(self) -> None:
        sched = CronScheduler()
        jid = sched.add(
            "* * * * *", _noop_action, "Jitter job",
            jitter_secs=5.0,
        )
        job = sched.get_job(jid)
        assert job is not None
        assert job.jitter_secs == 5.0

    def test_add_every_schedule(self) -> None:
        sched = CronScheduler()
        jid = sched.add(
            "* * * * *", _noop_action, "Every 60s",
            schedule_kind=CronScheduleKind.EVERY,
            every_secs=60.0,
        )
        job = sched.get_job(jid)
        assert job is not None
        assert job.schedule_kind == CronScheduleKind.EVERY
        assert job.every_secs == 60.0
        assert job.state.next_run_at is not None

    def test_add_at_schedule(self) -> None:
        sched = CronScheduler()
        future_ts = time.time() + 3600
        jid = sched.add(
            "* * * * *", _noop_action, "One shot",
            schedule_kind=CronScheduleKind.AT,
            at_timestamp=future_ts,
        )
        job = sched.get_job(jid)
        assert job is not None
        assert job.schedule_kind == CronScheduleKind.AT
        assert job.state.next_run_at == future_ts


# ── Tests de ejecución ──────────────────────────────────────


class TestJobExecution:
    """Tests para run_now y ejecución automática."""

    @pytest.mark.asyncio
    async def test_run_now(self) -> None:
        sched = CronScheduler()
        executed = []

        async def track_action() -> None:
            executed.append(True)

        jid = sched.add("* * * * *", track_action, "Track job")
        status = await sched.run_now(jid)
        assert status == CronRunStatus.OK
        assert len(executed) == 1

    @pytest.mark.asyncio
    async def test_run_now_disabled_skipped(self) -> None:
        sched = CronScheduler()
        jid = sched.add("* * * * *", _noop_action, enabled=False)
        status = await sched.run_now(jid)
        assert status == CronRunStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_run_now_force_on_disabled(self) -> None:
        sched = CronScheduler()
        executed = []

        async def track() -> None:
            executed.append(True)

        jid = sched.add("* * * * *", track, enabled=False)
        status = await sched.run_now(jid, force=True)
        assert status == CronRunStatus.OK
        assert len(executed) == 1

    @pytest.mark.asyncio
    async def test_run_now_with_error(self) -> None:
        sched = CronScheduler()
        jid = sched.add("* * * * *", _failing_action)
        status = await sched.run_now(jid)
        assert status == CronRunStatus.ERROR

        job = sched.get_job(jid)
        assert job is not None
        assert job.state.consecutive_errors == 1
        assert job.state.last_error is not None
        assert "Error de test" in job.state.last_error

    @pytest.mark.asyncio
    async def test_run_now_with_timeout(self) -> None:
        sched = CronScheduler()
        jid = sched.add(
            "* * * * *", _timeout_action, timeout_secs=0.1,
        )
        status = await sched.run_now(jid)
        assert status == CronRunStatus.TIMEOUT

    @pytest.mark.asyncio
    async def test_run_now_nonexistent_raises(self) -> None:
        sched = CronScheduler()
        with pytest.raises(CronJobNotFoundError):
            await sched.run_now("nonexistent")

    @pytest.mark.asyncio
    async def test_consecutive_errors_tracked(self) -> None:
        sched = CronScheduler()
        jid = sched.add("* * * * *", _failing_action)

        await sched.run_now(jid)
        job = sched.get_job(jid)
        assert job is not None
        assert job.state.consecutive_errors == 1

        await sched.run_now(jid)
        assert job.state.consecutive_errors == 2

    @pytest.mark.asyncio
    async def test_success_resets_consecutive_errors(self) -> None:
        sched = CronScheduler()
        call_count = 0

        async def sometimes_fail() -> None:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RuntimeError("fail")

        jid = sched.add("* * * * *", sometimes_fail)
        await sched.run_now(jid)
        await sched.run_now(jid)
        job = sched.get_job(jid)
        assert job is not None
        assert job.state.consecutive_errors == 2

        await sched.run_now(jid)
        assert job.state.consecutive_errors == 0


# ── Tests de overlap policy ─────────────────────────────────


class TestOverlapPolicy:
    """Tests para prevención de overlap."""

    @pytest.mark.asyncio
    async def test_skip_overlap(self) -> None:
        sched = CronScheduler()
        jid = sched.add(
            "* * * * *", _slow_action,
            overlap_policy="skip",
        )
        job = sched.get_job(jid)
        assert job is not None

        # Simular que el job está corriendo
        job.state.running_at = time.time()
        status = await sched.run_now(jid)
        assert status == CronRunStatus.SKIPPED


# ── Tests de historial ──────────────────────────────────────


class TestHistory:
    """Tests para historial de ejecución."""

    @pytest.mark.asyncio
    async def test_history_recorded(self) -> None:
        sched = CronScheduler()
        jid = sched.add("* * * * *", _noop_action)
        await sched.run_now(jid)

        history = sched.get_history(job_id=jid)
        assert len(history) == 1
        assert history[0].status == CronRunStatus.OK

    @pytest.mark.asyncio
    async def test_history_multiple_runs(self) -> None:
        sched = CronScheduler()
        jid = sched.add("* * * * *", _noop_action)
        await sched.run_now(jid)
        await sched.run_now(jid)
        await sched.run_now(jid)

        history = sched.get_history(job_id=jid)
        assert len(history) == 3

    @pytest.mark.asyncio
    async def test_history_filter_by_status(self) -> None:
        sched = CronScheduler()
        j1 = sched.add("* * * * *", _noop_action, job_id="ok")
        j2 = sched.add("* * * * *", _failing_action, job_id="err")
        await sched.run_now(j1)
        await sched.run_now(j2)

        ok_history = sched.get_history(status=CronRunStatus.OK)
        assert len(ok_history) == 1

        err_history = sched.get_history(status=CronRunStatus.ERROR)
        assert len(err_history) == 1

    @pytest.mark.asyncio
    async def test_history_pagination(self) -> None:
        sched = CronScheduler()
        jid = sched.add("* * * * *", _noop_action)
        for _ in range(5):
            await sched.run_now(jid)

        page1 = sched.get_history(limit=2)
        assert len(page1) == 2

        page2 = sched.get_history(limit=2, offset=2)
        assert len(page2) == 2

    @pytest.mark.asyncio
    async def test_clear_history(self) -> None:
        sched = CronScheduler()
        jid = sched.add("* * * * *", _noop_action)
        await sched.run_now(jid)
        assert len(sched.get_history()) == 1

        cleared = sched.clear_history()
        assert cleared == 1
        assert len(sched.get_history()) == 0

    @pytest.mark.asyncio
    async def test_clear_history_by_job(self) -> None:
        sched = CronScheduler()
        j1 = sched.add("* * * * *", _noop_action, job_id="a")
        j2 = sched.add("* * * * *", _noop_action, job_id="b")
        await sched.run_now(j1)
        await sched.run_now(j2)

        cleared = sched.clear_history(job_id="a")
        assert cleared == 1
        assert len(sched.get_history(job_id="a")) == 0
        assert len(sched.get_history(job_id="b")) == 1


# ── Tests de estadísticas ──────────────────────────────────


class TestJobStats:
    """Tests para get_job_stats."""

    @pytest.mark.asyncio
    async def test_stats_after_runs(self) -> None:
        sched = CronScheduler()
        jid = sched.add("* * * * *", _noop_action)
        await sched.run_now(jid)
        await sched.run_now(jid)

        stats = sched.get_job_stats(jid)
        assert stats["total_runs"] == 2
        assert stats["ok_count"] == 2
        assert stats["error_count"] == 0
        assert stats["consecutive_errors"] == 0

    @pytest.mark.asyncio
    async def test_stats_with_errors(self) -> None:
        sched = CronScheduler()
        jid = sched.add("* * * * *", _failing_action)
        await sched.run_now(jid)

        stats = sched.get_job_stats(jid)
        assert stats["error_count"] == 1
        assert stats["consecutive_errors"] == 1

    def test_stats_nonexistent_raises(self) -> None:
        sched = CronScheduler()
        with pytest.raises(CronJobNotFoundError):
            sched.get_job_stats("nope")


# ── Tests de status ─────────────────────────────────────────


class TestSchedulerStatus:
    """Tests para status()."""

    def test_status_initial(self) -> None:
        sched = CronScheduler()
        st = sched.status()
        assert st["running"] is False
        assert st["total_jobs"] == 0
        assert st["active_jobs"] == 0

    def test_status_with_jobs(self) -> None:
        sched = CronScheduler()
        sched.add("* * * * *", _noop_action)
        sched.add("* * * * *", _noop_action, enabled=False)
        st = sched.status()
        assert st["total_jobs"] == 2
        assert st["enabled_jobs"] == 1


# ── Tests de lifecycle ──────────────────────────────────────


class TestLifecycle:
    """Tests para start/stop."""

    @pytest.mark.asyncio
    async def test_start_stop(self) -> None:
        sched = CronScheduler(tick_interval=0.1)
        sched.add("* * * * *", _noop_action)

        await sched.start()
        assert sched.is_running
        await asyncio.sleep(0.05)

        await sched.stop()
        assert not sched.is_running

    @pytest.mark.asyncio
    async def test_start_idempotent(self) -> None:
        sched = CronScheduler(tick_interval=0.1)
        await sched.start()
        await sched.start()  # No debería fallar
        assert sched.is_running
        await sched.stop()

    @pytest.mark.asyncio
    async def test_stop_without_start(self) -> None:
        sched = CronScheduler()
        await sched.stop()  # No debería fallar

    @pytest.mark.asyncio
    async def test_clears_stale_running_markers(self) -> None:
        sched = CronScheduler(tick_interval=0.1)
        jid = sched.add("* * * * *", _noop_action)
        job = sched.get_job(jid)
        assert job is not None
        job.state.running_at = time.time() - 100

        await sched.start()
        assert job.state.running_at is None
        await sched.stop()


# ── Tests de eventos ────────────────────────────────────────


class TestEvents:
    """Tests para sistema de eventos."""

    @pytest.mark.asyncio
    async def test_events_emitted(self) -> None:
        events = []
        sched = CronScheduler(on_event=lambda e: events.append(e))
        jid = sched.add("* * * * *", _noop_action, "Event test")
        # "added" event
        assert any(e.get("action") == "added" for e in events)

        await sched.run_now(jid)
        # "started" y "finished" events
        assert any(e.get("action") == "started" for e in events)
        assert any(e.get("action") == "finished" for e in events)

    @pytest.mark.asyncio
    async def test_remove_event(self) -> None:
        events = []
        sched = CronScheduler(on_event=lambda e: events.append(e))
        jid = sched.add("* * * * *", _noop_action)
        sched.remove(jid)
        assert any(e.get("action") == "removed" for e in events)


# ── Tests de backoff y transient errors ─────────────────────


class TestBackoffAndRetry:
    """Tests para backoff exponencial y detección de errores transitorios."""

    def test_error_backoff_schedule(self) -> None:
        assert _error_backoff_secs(1) == 30.0
        assert _error_backoff_secs(2) == 60.0
        assert _error_backoff_secs(3) == 300.0
        assert _error_backoff_secs(4) == 900.0
        assert _error_backoff_secs(5) == 3600.0
        assert _error_backoff_secs(10) == 3600.0  # Capped

    def test_error_backoff_custom_schedule(self) -> None:
        custom = [10.0, 20.0]
        assert _error_backoff_secs(1, custom) == 10.0
        assert _error_backoff_secs(2, custom) == 20.0
        assert _error_backoff_secs(5, custom) == 20.0  # Capped at last

    def test_is_transient_rate_limit(self) -> None:
        assert _is_transient_error("Rate limit exceeded")
        assert _is_transient_error("429 Too Many Requests")

    def test_is_transient_network(self) -> None:
        assert _is_transient_error("ConnectionError: network unreachable")
        assert _is_transient_error("ECONNRESET")

    def test_is_transient_timeout(self) -> None:
        assert _is_transient_error("Request timeout")
        assert _is_transient_error("ETIMEDOUT")

    def test_is_transient_server_error(self) -> None:
        assert _is_transient_error("HTTP 500 Internal Server Error")
        assert _is_transient_error("502 Bad Gateway")

    def test_not_transient(self) -> None:
        assert not _is_transient_error("Invalid API key")
        assert not _is_transient_error("Model not found")
        assert not _is_transient_error("")

    def test_is_transient_custom_patterns(self) -> None:
        assert _is_transient_error("Rate limit", ["rate_limit"])
        assert not _is_transient_error("Rate limit", ["network"])


# ── Tests de stagger ────────────────────────────────────────


class TestStagger:
    """Tests para stagger estable."""

    def test_stable_offset(self) -> None:
        offset1 = _resolve_stable_stagger_offset("job-1", 5000)
        offset2 = _resolve_stable_stagger_offset("job-1", 5000)
        assert offset1 == offset2

    def test_different_jobs_different_offsets(self) -> None:
        offset1 = _resolve_stable_stagger_offset("job-1", 5000)
        offset2 = _resolve_stable_stagger_offset("job-2", 5000)
        # Muy improbable que sean iguales
        # (pero no imposible, así que solo verificamos que son números válidos)
        assert isinstance(offset1, float)
        assert isinstance(offset2, float)
        assert 0 <= offset1 < 5.0
        assert 0 <= offset2 < 5.0

    def test_zero_stagger(self) -> None:
        assert _resolve_stable_stagger_offset("job-1", 0) == 0.0
        assert _resolve_stable_stagger_offset("job-1", 1) == 0.0


# ── Tests de delete-after-run ───────────────────────────────


class TestDeleteAfterRun:
    """Tests para delete_after_run en jobs one-shot."""

    @pytest.mark.asyncio
    async def test_at_job_deleted_after_success(self) -> None:
        sched = CronScheduler()
        future_ts = time.time() + 3600
        jid = sched.add(
            "* * * * *", _noop_action,
            schedule_kind=CronScheduleKind.AT,
            at_timestamp=future_ts,
            delete_after_run=True,
        )
        assert sched.get_job(jid) is not None
        await sched.run_now(jid, force=True)
        assert sched.get_job(jid) is None

    @pytest.mark.asyncio
    async def test_at_job_not_deleted_on_error(self) -> None:
        sched = CronScheduler()
        future_ts = time.time() + 3600
        jid = sched.add(
            "* * * * *", _failing_action,
            schedule_kind=CronScheduleKind.AT,
            at_timestamp=future_ts,
            delete_after_run=True,
        )
        await sched.run_now(jid, force=True)
        # Job debe seguir existiendo después de error
        assert sched.get_job(jid) is not None


# ── Tests de concurrencia ──────────────────────────────────


class TestConcurrency:
    """Tests para control de concurrencia."""

    def test_default_concurrency(self) -> None:
        sched = CronScheduler()
        assert sched.max_concurrent_jobs == 1

    def test_set_concurrency(self) -> None:
        sched = CronScheduler(max_concurrent_jobs=5)
        assert sched.max_concurrent_jobs == 5

    def test_set_concurrency_property(self) -> None:
        sched = CronScheduler()
        sched.max_concurrent_jobs = 3
        assert sched.max_concurrent_jobs == 3

    def test_min_concurrency_is_one(self) -> None:
        sched = CronScheduler(max_concurrent_jobs=0)
        assert sched.max_concurrent_jobs == 1

    @pytest.mark.asyncio
    async def test_active_job_count(self) -> None:
        sched = CronScheduler(max_concurrent_jobs=5)
        assert sched.active_job_count == 0
        jid = sched.add("* * * * *", _noop_action)
        await sched.run_now(jid)
        # Después de ejecutar, no debe haber jobs activos
        assert sched.active_job_count == 0


# ── Tests de failure alert ──────────────────────────────────


class TestFailureAlerts:
    """Tests para alertas de fallo."""

    @pytest.mark.asyncio
    async def test_failure_alert_triggered(self) -> None:
        alerts = []

        async def alert_cb(job_id: str, text: str, count: int) -> None:
            alerts.append({"job_id": job_id, "text": text, "count": count})

        sched = CronScheduler(failure_alert_callback=alert_cb)
        jid = sched.add("* * * * *", _failing_action)

        # Después de DEFAULT_FAILURE_ALERT_AFTER (2) errores
        await sched.run_now(jid)
        assert len(alerts) == 0  # Solo 1 error, after=2

        await sched.run_now(jid)
        assert len(alerts) == 1  # 2 errores -> alerta

    @pytest.mark.asyncio
    async def test_failure_alert_custom_after(self) -> None:
        alerts = []

        async def alert_cb(job_id: str, text: str, count: int) -> None:
            alerts.append(count)

        sched = CronScheduler()
        jid = sched.add(
            "* * * * *", _failing_action,
            failure_alert=CronFailureAlertConfig(
                after=3, callback=alert_cb,
            ),
        )

        await sched.run_now(jid)
        await sched.run_now(jid)
        assert len(alerts) == 0  # Solo 2 errores, after=3

        await sched.run_now(jid)
        assert len(alerts) == 1  # 3 errores -> alerta

    @pytest.mark.asyncio
    async def test_failure_alert_cooldown(self) -> None:
        alerts = []

        async def alert_cb(job_id: str, text: str, count: int) -> None:
            alerts.append(count)

        sched = CronScheduler()
        jid = sched.add(
            "* * * * *", _failing_action,
            failure_alert=CronFailureAlertConfig(
                after=1, cooldown_secs=3600.0, callback=alert_cb,
            ),
        )

        await sched.run_now(jid)
        assert len(alerts) == 1

        await sched.run_now(jid)
        # Cooldown activo, no debería alertar
        assert len(alerts) == 1
