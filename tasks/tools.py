"""Register task queue tools with SOMER's ToolRegistry."""

from __future__ import annotations

import json
from typing import Any, Dict


def register_task_tools(tool_registry: Any, task_manager: Any) -> None:
    """Register task_submit, task_status, task_cancel, task_stats tools."""

    async def task_submit(args: Dict[str, Any]) -> Dict[str, Any]:
        task_id = await task_manager.submit(
            title=args["title"],
            description=args.get("description", ""),
            task_type=args.get("task_type", "agent_run"),
            payload=args.get("payload", {}),
            channel=args.get("channel", "unknown"),
            user_id=args.get("user_id", "unknown"),
            session_id=args.get("session_id", ""),
            priority=args.get("priority", 5),
            max_retries=args.get("max_retries", 3),
        )
        return {"task_id": task_id, "status": "submitted"}

    async def task_status(args: Dict[str, Any]) -> Dict[str, Any]:
        task_id = args.get("task_id")
        if task_id:
            result = task_manager.get_status(task_id)
            return result if result else {"error": "Task not found"}
        return {
            "tasks": task_manager.list_tasks(
                status=args.get("status"),
                user_id=args.get("user_id"),
                limit=args.get("limit", 20),
            )
        }

    async def task_cancel(args: Dict[str, Any]) -> Dict[str, Any]:
        success = task_manager.cancel(args["task_id"])
        return {"cancelled": success}

    async def task_stats(args: Dict[str, Any]) -> Dict[str, Any]:
        return task_manager.stats()

    tool_registry.register_simple(
        name="task_submit",
        description=(
            "Submit a background task for async execution. "
            "The task runs in the background and you'll be notified when it completes. "
            "Use for long-running operations."
        ),
        handler=task_submit,
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short task title"},
                "description": {"type": "string", "description": "What the task should do"},
                "task_type": {
                    "type": "string",
                    "enum": ["agent_run", "tool_call", "custom"],
                    "description": "Type of task",
                },
                "payload": {
                    "type": "object",
                    "description": "Task-specific data (prompt for agent_run, tool args for tool_call)",
                },
                "priority": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                    "description": "Priority (1=highest, 10=lowest, default=5)",
                },
                "max_retries": {
                    "type": "integer",
                    "description": "Max retry attempts (default: 3)",
                },
            },
            "required": ["title", "task_type", "payload"],
        },
    )

    tool_registry.register_simple(
        name="task_status",
        description=(
            "Check status of background tasks. Query by task_id for specific task, "
            "or by status/user_id for filtered list."
        ),
        handler=task_status,
        parameters={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Specific task ID to check"},
                "status": {
                    "type": "string",
                    "enum": ["pending", "running", "done", "failed", "cancelled"],
                },
                "user_id": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
            },
        },
    )

    tool_registry.register_simple(
        name="task_cancel",
        description="Cancel a pending or running background task.",
        handler=task_cancel,
        parameters={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID to cancel"},
            },
            "required": ["task_id"],
        },
    )

    tool_registry.register_simple(
        name="task_stats",
        description="Get task queue statistics: counts by status, queue depth, worker status.",
        handler=task_stats,
        parameters={"type": "object", "properties": {}},
    )
