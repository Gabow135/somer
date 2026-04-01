"""Tests para cron.isolated_runner — ejecución aislada de agentes."""

from __future__ import annotations

import asyncio

import pytest

from cron.isolated_runner import (
    IsolatedCronRunner,
    IsolatedRunConfig,
    IsolatedRunResult,
)


# ── Helpers ─────────────────────────────────────────────────


async def _ok_agent(message: str, session_key: str, model: str = None) -> IsolatedRunResult:
    """Agente mock que siempre retorna ok."""
    return IsolatedRunResult(
        status="ok",
        summary=f"Procesado: {message[:50]}",
        output_text="Resultado exitoso",
        model=model or "test-model",
    )


async def _failing_agent(message: str, session_key: str, model: str = None) -> IsolatedRunResult:
    """Agente mock que siempre retorna error."""
    return IsolatedRunResult(
        status="error",
        error="Error simulado del agente",
    )


async def _slow_agent(message: str, session_key: str, model: str = None) -> IsolatedRunResult:
    """Agente mock que tarda mucho."""
    await asyncio.sleep(100)
    return IsolatedRunResult(status="ok")


async def _exception_agent(message: str, session_key: str, model: str = None) -> IsolatedRunResult:
    """Agente mock que lanza excepción."""
    raise RuntimeError("Error catastrófico del agente")


async def _transient_agent(message: str, session_key: str, model: str = None) -> IsolatedRunResult:
    """Agente mock que falla con error transitorio."""
    return IsolatedRunResult(
        status="error",
        error="Rate limit exceeded (429)",
    )


# ── Tests básicos ───────────────────────────────────────────


class TestIsolatedCronRunner:
    """Tests para IsolatedCronRunner."""

    @pytest.mark.asyncio
    async def test_run_ok(self) -> None:
        runner = IsolatedCronRunner(agent_fn=_ok_agent)
        config = IsolatedRunConfig(
            job_id="test-1",
            job_name="Test Job",
            message="Generar reporte",
        )
        result = await runner.run(config)
        assert result.status == "ok"
        assert result.summary is not None
        assert "Procesado" in result.summary
        assert result.session_key == "cron:test-1"

    @pytest.mark.asyncio
    async def test_run_with_custom_session_key(self) -> None:
        runner = IsolatedCronRunner(agent_fn=_ok_agent)
        config = IsolatedRunConfig(
            job_id="test-1",
            message="Test",
            session_key="custom:session:key",
        )
        result = await runner.run(config)
        assert result.session_key == "custom:session:key"

    @pytest.mark.asyncio
    async def test_run_with_model_override(self) -> None:
        runner = IsolatedCronRunner(
            agent_fn=_ok_agent,
            default_model="default-model",
        )
        config = IsolatedRunConfig(
            job_id="test-1",
            message="Test",
            model_override="custom-model",
        )
        result = await runner.run(config)
        assert result.status == "ok"

    @pytest.mark.asyncio
    async def test_run_error(self) -> None:
        runner = IsolatedCronRunner(agent_fn=_failing_agent)
        config = IsolatedRunConfig(job_id="test-1", message="Test")
        result = await runner.run(config)
        assert result.status == "error"
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_run_timeout(self) -> None:
        runner = IsolatedCronRunner(agent_fn=_slow_agent)
        config = IsolatedRunConfig(
            job_id="test-1",
            message="Test",
            timeout_secs=0.1,
        )
        result = await runner.run(config)
        assert result.status == "error"
        assert "timeout" in result.error.lower() or "excedió" in result.error.lower()

    @pytest.mark.asyncio
    async def test_run_exception(self) -> None:
        runner = IsolatedCronRunner(agent_fn=_exception_agent)
        config = IsolatedRunConfig(job_id="test-1", message="Test")
        result = await runner.run(config)
        assert result.status == "error"
        assert "catastrófico" in result.error

    @pytest.mark.asyncio
    async def test_no_agent_fn(self) -> None:
        runner = IsolatedCronRunner()
        config = IsolatedRunConfig(job_id="test-1", message="Test")
        result = await runner.run(config)
        assert result.status == "error"
        assert "No se configuró" in result.error

    @pytest.mark.asyncio
    async def test_active_runs_tracking(self) -> None:
        runner = IsolatedCronRunner(agent_fn=_ok_agent)
        assert len(runner.active_runs) == 0

        config = IsolatedRunConfig(job_id="test-1", message="Test")
        result = await runner.run(config)
        assert result.status == "ok"
        assert len(runner.active_runs) == 0  # Debe limpiarse

    @pytest.mark.asyncio
    async def test_duration_tracked(self) -> None:
        runner = IsolatedCronRunner(agent_fn=_ok_agent)
        config = IsolatedRunConfig(job_id="test-1", message="Test")
        result = await runner.run(config)
        assert result.duration_secs >= 0


# ── Tests de retry ──────────────────────────────────────────


class TestIsolatedRunnerRetry:
    """Tests para run_with_retry."""

    @pytest.mark.asyncio
    async def test_retry_on_transient_error(self) -> None:
        call_count = 0

        async def sometimes_fail(msg: str, sk: str, model: str = None) -> IsolatedRunResult:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return IsolatedRunResult(
                    status="error",
                    error="Rate limit exceeded",
                )
            return IsolatedRunResult(status="ok", summary="Success")

        runner = IsolatedCronRunner(agent_fn=sometimes_fail)
        config = IsolatedRunConfig(job_id="test-1", message="Test")
        result = await runner.run_with_retry(
            config, max_retries=3, backoff_secs=[0.01, 0.01, 0.01],
        )
        assert result.status == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_retry_gives_up_after_max(self) -> None:
        runner = IsolatedCronRunner(agent_fn=_transient_agent)
        config = IsolatedRunConfig(job_id="test-1", message="Test")
        result = await runner.run_with_retry(
            config, max_retries=2, backoff_secs=[0.01, 0.01],
        )
        assert result.status == "error"

    @pytest.mark.asyncio
    async def test_no_retry_on_permanent_error(self) -> None:
        call_count = 0

        async def permanent_fail(msg: str, sk: str, model: str = None) -> IsolatedRunResult:
            nonlocal call_count
            call_count += 1
            return IsolatedRunResult(
                status="error",
                error="Invalid API key",
            )

        runner = IsolatedCronRunner(agent_fn=permanent_fail)
        config = IsolatedRunConfig(job_id="test-1", message="Test")
        result = await runner.run_with_retry(
            config, max_retries=3, backoff_secs=[0.01],
        )
        assert result.status == "error"
        assert call_count == 1  # No reintenta errores permanentes

    @pytest.mark.asyncio
    async def test_success_no_retry(self) -> None:
        call_count = 0

        async def always_ok(msg: str, sk: str, model: str = None) -> IsolatedRunResult:
            nonlocal call_count
            call_count += 1
            return IsolatedRunResult(status="ok")

        runner = IsolatedCronRunner(agent_fn=always_ok)
        config = IsolatedRunConfig(job_id="test-1", message="Test")
        result = await runner.run_with_retry(config, max_retries=3)
        assert result.status == "ok"
        assert call_count == 1


# ── Tests de build_prompt ───────────────────────────────────


class TestBuildPrompt:
    """Tests para la construcción del prompt."""

    def test_prompt_includes_job_info(self) -> None:
        runner = IsolatedCronRunner(agent_fn=_ok_agent)
        config = IsolatedRunConfig(
            job_id="abc123",
            job_name="Reporte Diario",
            message="Generar reporte de ventas",
        )
        prompt = runner._build_prompt(config)
        assert "cron:abc123" in prompt
        assert "Reporte Diario" in prompt
        assert "Generar reporte de ventas" in prompt

    def test_prompt_without_name(self) -> None:
        runner = IsolatedCronRunner(agent_fn=_ok_agent)
        config = IsolatedRunConfig(
            job_id="abc123",
            message="Test message",
        )
        prompt = runner._build_prompt(config)
        assert "cron:abc123" in prompt
        assert "Test message" in prompt
