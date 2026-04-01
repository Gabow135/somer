"""Tests para el sistema de sub-agentes."""

from __future__ import annotations

from typing import Dict, Optional

import pytest

from agents.subagent import (
    EndedReason,
    RunOutcome,
    SpawnMode,
    SpawnParams,
    SpawnResult,
    SubagentRegistry,
    SubagentRunRecord,
    get_spawn_depth,
    spawn_subagent,
)


class TestSubagentRunRecord:
    def test_defaults(self) -> None:
        r = SubagentRunRecord()
        assert r.is_active
        assert r.runtime_secs == 0.0

    def test_is_active(self) -> None:
        r = SubagentRunRecord()
        assert r.is_active
        r.ended_at = 1.0
        assert not r.is_active

    def test_runtime(self) -> None:
        import time
        r = SubagentRunRecord()
        r.started_at = time.time() - 5.0
        assert r.runtime_secs > 4.0


class TestSubagentRegistry:
    @pytest.mark.asyncio
    async def test_register_and_get(self) -> None:
        reg = SubagentRegistry()
        record = SubagentRunRecord(run_id="r1", task="test")
        await reg.register(record)
        assert reg.get("r1") is not None
        assert reg.get("r1").task == "test"

    @pytest.mark.asyncio
    async def test_start_and_end(self) -> None:
        reg = SubagentRegistry()
        record = SubagentRunRecord(run_id="r1")
        await reg.register(record)
        await reg.start("r1")
        assert reg.get("r1").started_at is not None

        await reg.end("r1", RunOutcome.COMPLETE)
        assert not reg.get("r1").is_active
        assert reg.get("r1").outcome == RunOutcome.COMPLETE

    @pytest.mark.asyncio
    async def test_active_count(self) -> None:
        reg = SubagentRegistry()
        r1 = SubagentRunRecord(
            run_id="r1", requester_session_key="s1"
        )
        r2 = SubagentRunRecord(
            run_id="r2", requester_session_key="s1"
        )
        r3 = SubagentRunRecord(
            run_id="r3", requester_session_key="s2"
        )
        await reg.register(r1)
        await reg.register(r2)
        await reg.register(r3)

        assert reg.active_count() == 3
        assert reg.active_count("s1") == 2
        assert reg.active_count("s2") == 1

    @pytest.mark.asyncio
    async def test_can_spawn_depth_limit(self) -> None:
        reg = SubagentRegistry(max_depth=2)
        can, reason = reg.can_spawn("s1", depth=2)
        assert not can
        assert "Profundidad" in reason

    @pytest.mark.asyncio
    async def test_can_spawn_concurrency_limit(self) -> None:
        reg = SubagentRegistry(max_concurrent=2)
        for i in range(2):
            r = SubagentRunRecord(
                run_id=f"r{i}", requester_session_key="s1"
            )
            await reg.register(r)

        can, reason = reg.can_spawn("s1", depth=0)
        assert not can
        assert "concurrentes" in reason

    @pytest.mark.asyncio
    async def test_cleanup_expired(self) -> None:
        import time

        reg = SubagentRegistry()
        record = SubagentRunRecord(run_id="r1")
        record.ended_at = time.time() - 1000
        await reg.register(record)

        removed = await reg.cleanup_expired(max_age_secs=1)
        assert removed == 1
        assert reg.get("r1") is None

    @pytest.mark.asyncio
    async def test_kill_all(self) -> None:
        reg = SubagentRegistry()
        await reg.register(SubagentRunRecord(run_id="r1"))
        await reg.register(SubagentRunRecord(run_id="r2"))

        killed = await reg.kill_all()
        assert killed == 2
        assert not reg.get("r1").is_active
        assert not reg.get("r2").is_active

    @pytest.mark.asyncio
    async def test_remove(self) -> None:
        reg = SubagentRegistry()
        await reg.register(SubagentRunRecord(run_id="r1"))
        removed = await reg.remove("r1")
        assert removed is not None
        assert reg.get("r1") is None

    @pytest.mark.asyncio
    async def test_status_summary(self) -> None:
        reg = SubagentRegistry()
        await reg.register(SubagentRunRecord(run_id="r1", task="test task"))
        summary = reg.status_summary()
        assert summary["total"] == 1
        assert summary["active"] == 1


class TestGetSpawnDepth:
    def test_empty_key(self) -> None:
        assert get_spawn_depth("") == 0

    def test_root_session(self) -> None:
        assert get_spawn_depth("agent:main:some-session") == 0

    def test_subagent_depth(self) -> None:
        assert get_spawn_depth("agent:main:subagent:2:abc") == 2

    def test_from_store(self) -> None:
        store = {"my-session": 3}
        assert get_spawn_depth("my-session", store) == 3


class TestSpawnSubagent:
    @pytest.mark.asyncio
    async def test_successful_spawn(self) -> None:
        reg = SubagentRegistry()
        params = SpawnParams(task="Do something")
        result = await spawn_subagent(
            params,
            "agent:main:session1",
            reg,
        )
        assert result.status == "accepted"
        assert result.child_session_key is not None
        assert result.run_id is not None
        assert reg.active_count() == 1

    @pytest.mark.asyncio
    async def test_depth_exceeded(self) -> None:
        reg = SubagentRegistry(max_depth=1)
        params = SpawnParams(task="Too deep")
        result = await spawn_subagent(
            params,
            "agent:main:session1",
            reg,
            depth=1,
        )
        assert result.status == "forbidden"
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_session_mode(self) -> None:
        reg = SubagentRegistry()
        params = SpawnParams(task="Thread", mode=SpawnMode.SESSION)
        result = await spawn_subagent(
            params,
            "agent:main:session1",
            reg,
        )
        assert result.status == "accepted"
        assert result.mode == SpawnMode.SESSION
