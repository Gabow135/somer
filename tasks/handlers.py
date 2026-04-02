"""Built-in task handlers for common task types."""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class TaskHandlers:
    """Provides handler coroutines for the built-in task types."""

    def __init__(self, agent_runner: Any, tool_registry: Any):
        self._agent_runner = agent_runner
        self._tool_registry = tool_registry

    async def handle_agent_run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Run an agent prompt as a background task."""
        prompt = payload.get("prompt", "")
        model = payload.get("model")
        session_id = payload.get("session_id", "background-task")

        result = await self._agent_runner.run(
            session_id=session_id,
            user_message=prompt,
            model=model,
        )
        return {"response": result.content if result else "No response"}

    async def handle_tool_call(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a specific tool as a background task."""
        tool_name = payload.get("tool_name")
        tool_args = payload.get("tool_args", {})

        tool = self._tool_registry.get(tool_name)
        if not tool or not tool.handler:
            return {"error": "Tool {} not found".format(tool_name)}

        result = await tool.handler(tool_args)
        if isinstance(result, dict):
            return result
        return {"result": str(result)}

    async def handle_custom(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Custom task placeholder -- returns payload as-is."""
        return {"payload": payload, "note": "Custom handler - override me"}
