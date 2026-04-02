"""Unit tests for the somer_taskqueue Rust module and AsyncTaskManager."""

from __future__ import annotations

import json
import time
import asyncio
import pytest
from typing import Any, Dict

# ---------------------------------------------------------------------------
# Rust module tests (synchronous)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def queue():
    """Create a TaskQueue connected to local Redis."""
    from somer_taskqueue import TaskQueue
    q = TaskQueue("redis://localhost:6379")
    return q


@pytest.fixture(autouse=True)
def _cleanup_redis():
    """Flush test keys before each test."""
    import redis
    r = redis.Redis()
    for key in r.keys("somer:tasks:*"):
        r.delete(key)
    for key in r.keys("somer:queue:*"):
        r.delete(key)
    yield
    for key in r.keys("somer:tasks:*"):
        r.delete(key)
    for key in r.keys("somer:queue:*"):
        r.delete(key)


def _make_task(**overrides):
    """Helper to create a TaskItem with defaults."""
    from somer_taskqueue import TaskItem
    t = TaskItem()
    t.title = overrides.get("title", "Test task")
    t.description = overrides.get("description", "A test task")
    t.task_type = overrides.get("task_type", "custom")
    t.payload = overrides.get("payload", '{"foo": "bar"}')
    t.channel = overrides.get("channel", "telegram")
    t.user_id = overrides.get("user_id", "user-123")
    t.session_id = overrides.get("session_id", "session-1")
    t.priority = overrides.get("priority", 5)
    t.max_retries = overrides.get("max_retries", 3)
    t.status = "pending"
    t.created_at = time.time()
    t.retries = 0
    if "id" in overrides:
        t.id = overrides["id"]
    return t


class TestTaskItem:
    def test_create(self):
        from somer_taskqueue import TaskItem
        t = TaskItem()
        assert t.status == "pending"
        assert t.priority == 5
        assert len(t.id) == 36  # UUID format

    def test_setters(self):
        from somer_taskqueue import TaskItem
        t = TaskItem()
        t.title = "My task"
        t.priority = 1
        assert t.title == "My task"
        assert t.priority == 1

    def test_repr(self):
        t = _make_task(title="hello")
        r = repr(t)
        assert "hello" in r
        assert "pending" in r


class TestTaskQueue:
    def test_submit_and_get(self, queue):
        task = _make_task(title="submit test")
        task_id = queue.submit(task)
        assert task_id == task.id

        fetched = queue.get_task(task_id)
        assert fetched is not None
        assert fetched.title == "submit test"
        assert fetched.status == "pending"

    def test_dequeue_priority(self, queue):
        """Higher priority (lower number) should dequeue first."""
        t_low = _make_task(title="low", priority=8)
        t_high = _make_task(title="high", priority=2)
        queue.submit(t_low)
        queue.submit(t_high)

        first = queue.dequeue()
        assert first is not None
        assert first.title == "high"

        second = queue.dequeue()
        assert second is not None
        assert second.title == "low"

    def test_dequeue_empty(self, queue):
        result = queue.dequeue()
        assert result is None

    def test_update_status(self, queue):
        task = _make_task()
        queue.submit(task)
        ok = queue.update_status(task.id, "running", None, None)
        assert ok is True

        fetched = queue.get_task(task.id)
        assert fetched.status == "running"
        assert fetched.started_at is not None

    def test_update_status_done_with_result(self, queue):
        task = _make_task()
        queue.submit(task)
        queue.update_status(task.id, "done", '{"answer": 42}', None)

        fetched = queue.get_task(task.id)
        assert fetched.status == "done"
        assert fetched.result == '{"answer": 42}'
        assert fetched.completed_at is not None

    def test_update_status_nonexistent(self, queue):
        ok = queue.update_status("nonexistent-id", "done", None, None)
        assert ok is False

    def test_cancel(self, queue):
        task = _make_task()
        queue.submit(task)
        ok = queue.cancel(task.id)
        assert ok is True

        fetched = queue.get_task(task.id)
        assert fetched.status == "cancelled"

        # Should not be dequeue-able
        result = queue.dequeue()
        assert result is None

    def test_list_tasks_by_status(self, queue):
        t1 = _make_task(title="a")
        t2 = _make_task(title="b")
        queue.submit(t1)
        queue.submit(t2)
        queue.update_status(t1.id, "done", None, None)

        pending = queue.list_tasks("pending", None, 10)
        done = queue.list_tasks("done", None, 10)
        assert len(pending) == 1
        assert len(done) == 1
        assert done[0].title == "a"

    def test_list_tasks_by_user(self, queue):
        t1 = _make_task(user_id="alice")
        t2 = _make_task(user_id="bob")
        queue.submit(t1)
        queue.submit(t2)

        alice_tasks = queue.list_tasks(None, "alice", 10)
        assert len(alice_tasks) == 1
        assert alice_tasks[0].user_id == "alice"

    def test_stats(self, queue):
        t1 = _make_task()
        t2 = _make_task()
        queue.submit(t1)
        queue.submit(t2)
        queue.update_status(t1.id, "done", None, None)

        stats = json.loads(queue.stats())
        assert stats["pending"] == 1
        assert stats["done"] == 1
        assert "queue_depth" in stats

    def test_cleanup(self, queue):
        task = _make_task()
        queue.submit(task)
        # Mark as done
        queue.update_status(task.id, "done", None, None)

        # Wait briefly so the task is "older than 1 second"
        time.sleep(1.1)
        removed = queue.cleanup(1)
        assert removed >= 1

    def test_get_nonexistent(self, queue):
        result = queue.get_task("does-not-exist")
        assert result is None


# ---------------------------------------------------------------------------
# AsyncTaskManager tests
# ---------------------------------------------------------------------------

class TestAsyncTaskManager:
    @pytest.fixture
    def manager(self):
        from tasks.manager import AsyncTaskManager
        return AsyncTaskManager("redis://localhost:6379")

    @pytest.mark.asyncio
    async def test_submit(self, manager):
        task_id = await manager.submit(
            title="async test",
            description="test desc",
            task_type="custom",
            payload={"key": "value"},
            channel="telegram",
            user_id="user-1",
            session_id="sess-1",
        )
        assert len(task_id) == 36

        status = manager.get_status(task_id)
        assert status is not None
        assert status["title"] == "async test"
        assert status["status"] == "pending"

    @pytest.mark.asyncio
    async def test_cancel(self, manager):
        task_id = await manager.submit(
            title="cancel me",
            description="",
            task_type="custom",
            payload={},
            channel="test",
            user_id="u1",
            session_id="s1",
        )
        ok = manager.cancel(task_id)
        assert ok is True

        status = manager.get_status(task_id)
        assert status["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_stats(self, manager):
        await manager.submit(
            title="stats test",
            description="",
            task_type="custom",
            payload={},
            channel="test",
            user_id="u1",
            session_id="s1",
        )
        stats = manager.stats()
        assert "pending" in stats
        assert "queue_depth" in stats

    @pytest.mark.asyncio
    async def test_worker_processes_task(self, manager):
        """Test that a worker picks up and processes a task."""
        results = []

        async def custom_handler(payload):
            results.append(payload)
            return {"processed": True}

        manager.register_handler("custom", custom_handler)

        task_id = await manager.submit(
            title="worker test",
            description="",
            task_type="custom",
            payload={"data": 123},
            channel="test",
            user_id="u1",
            session_id="s1",
        )

        await manager.start(num_workers=1)
        # Give worker time to process
        await asyncio.sleep(2)
        await manager.stop()

        assert len(results) == 1
        assert results[0]["data"] == 123

        status = manager.get_status(task_id)
        assert status["status"] == "done"
