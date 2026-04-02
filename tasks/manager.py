"""High-level async task manager wrapping the Rust-based Redis queue."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class AsyncTaskManager:
    """High-level async task manager wrapping the Rust queue.

    The Rust ``somer_taskqueue`` crate handles all Redis operations
    synchronously; this Python layer adds async workers, handlers,
    and pub/sub notifications.
    """

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        from somer_taskqueue import TaskQueue
        self._queue = TaskQueue(redis_url)
        self._redis_url = redis_url
        self._redis = None  # type: Any  # async redis for pub/sub
        self._handlers = {}  # type: Dict[str, Callable]
        self._workers = []  # type: List[asyncio.Task]
        self._running = False
        self._on_complete_callback = None  # type: Optional[Callable]

    async def start(self, num_workers: int = 2) -> None:
        """Start background worker tasks."""
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(self._redis_url)
        except Exception as exc:
            logger.warning("Async redis not available for pub/sub: %s", exc)
            self._redis = None

        self._running = True
        for i in range(num_workers):
            worker = asyncio.ensure_future(self._worker_loop("worker-{}".format(i)))
            self._workers.append(worker)
        logger.info("Task queue started with %d workers", num_workers)

    async def stop(self) -> None:
        """Graceful shutdown of all workers."""
        self._running = False
        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        if self._redis:
            await self._redis.close()
            self._redis = None
        logger.info("Task queue stopped")

    def register_handler(self, task_type: str, handler: Callable) -> None:
        """Register a handler coroutine for a given task type."""
        self._handlers[task_type] = handler

    def set_completion_callback(self, callback: Callable) -> None:
        """Set callback invoked when a task completes (for user notification)."""
        self._on_complete_callback = callback

    async def submit(
        self,
        title: str,
        description: str,
        task_type: str,
        payload: Any,
        channel: str,
        user_id: str,
        session_id: str,
        priority: int = 5,
        max_retries: int = 3,
    ) -> str:
        """Submit a task to the queue. Returns the task ID."""
        from somer_taskqueue import TaskItem

        task = TaskItem()
        task.id = str(uuid.uuid4())
        task.title = title
        task.description = description
        task.task_type = task_type
        task.payload = json.dumps(payload) if isinstance(payload, dict) else str(payload)
        task.channel = channel
        task.user_id = user_id
        task.session_id = session_id
        task.priority = priority
        task.max_retries = max_retries
        task.status = "pending"
        task.created_at = time.time()
        task.retries = 0

        self._queue.submit(task)
        logger.info("Task submitted: %s (%s) [priority=%d]", task.id, title, priority)
        return task.id

    async def _worker_loop(self, worker_name: str) -> None:
        """Worker loop that dequeues and processes tasks."""
        logger.debug("Worker %s started", worker_name)
        while self._running:
            try:
                task = self._queue.dequeue()
                if task is None:
                    await asyncio.sleep(0.5)
                    continue

                logger.info("[%s] Processing task %s (%s)", worker_name, task.id, task.title)
                self._queue.update_status(task.id, "running", None, None)

                handler = self._handlers.get(task.task_type)
                if not handler:
                    err_msg = "No handler for type: {}".format(task.task_type)
                    logger.warning("[%s] %s", worker_name, err_msg)
                    self._queue.update_status(task.id, "failed", None, err_msg)
                    continue

                try:
                    result = await handler(json.loads(task.payload))
                    if isinstance(result, (dict, list)):
                        result_str = json.dumps(result)
                    else:
                        result_str = str(result)
                    self._queue.update_status(task.id, "done", result_str, None)
                    logger.info("[%s] Task %s completed", worker_name, task.id)

                    # Notify completion via callback
                    if self._on_complete_callback:
                        try:
                            await self._on_complete_callback(task, result_str)
                        except Exception as cb_exc:
                            logger.warning("Completion callback error: %s", cb_exc)

                    # Publish via Redis pub/sub
                    if self._redis:
                        try:
                            await self._redis.publish(
                                "somer:notify:{}".format(task.id),
                                json.dumps({
                                    "task_id": task.id,
                                    "status": "done",
                                    "result": result_str,
                                }),
                            )
                        except Exception as pub_exc:
                            logger.debug("Pub/sub notify error: %s", pub_exc)

                except Exception as e:
                    if task.retries < task.max_retries:
                        task.retries += 1
                        task.status = "pending"
                        logger.info(
                            "[%s] Task %s failed (retry %d/%d): %s",
                            worker_name, task.id, task.retries, task.max_retries, e,
                        )
                        self._queue.submit(task)  # re-enqueue
                    else:
                        error_str = str(e)
                        logger.warning("[%s] Task %s failed permanently: %s", worker_name, task.id, error_str)
                        self._queue.update_status(task.id, "failed", None, error_str)
                        if self._on_complete_callback:
                            try:
                                await self._on_complete_callback(task, None, error_str)
                            except Exception:
                                pass

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("[%s] Unexpected worker error: %s", worker_name, e)
                await asyncio.sleep(1)

        logger.debug("Worker %s stopped", worker_name)

    def get_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get task status as a dictionary."""
        task = self._queue.get_task(task_id)
        if not task:
            return None
        return self._task_to_dict(task)

    def list_tasks(
        self,
        status: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """List tasks, optionally filtered by status and/or user."""
        tasks = self._queue.list_tasks(status, user_id, limit)
        return [self._task_to_dict(t) for t in tasks]

    def cancel(self, task_id: str) -> bool:
        """Cancel a pending or running task."""
        return self._queue.cancel(task_id)

    def stats(self) -> Dict[str, Any]:
        """Return queue statistics."""
        return json.loads(self._queue.stats())

    def cleanup(self, older_than_secs: int = 86400) -> int:
        """Remove completed tasks older than N seconds."""
        return self._queue.cleanup(older_than_secs)

    @staticmethod
    def _task_to_dict(task: Any) -> Dict[str, Any]:
        """Convert a TaskItem to a plain dict."""
        return {
            "id": task.id,
            "title": task.title,
            "description": task.description,
            "status": task.status,
            "priority": task.priority,
            "created_at": task.created_at,
            "started_at": task.started_at,
            "completed_at": task.completed_at,
            "result": task.result,
            "error": task.error,
            "channel": task.channel,
            "user_id": task.user_id,
            "session_id": task.session_id,
            "retries": task.retries,
            "max_retries": task.max_retries,
            "task_type": task.task_type,
        }
