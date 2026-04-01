"""Tests para el sistema de hooks."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from hooks.loader import HookManager


class TestHookManager:
    """Tests del HookManager."""

    @pytest.mark.asyncio
    async def test_register_and_trigger(self) -> None:
        mgr = HookManager()
        callback = AsyncMock()
        mgr.register("on_startup", callback)
        count = await mgr.trigger("on_startup")
        assert count == 1
        callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_trigger_with_kwargs(self) -> None:
        mgr = HookManager()
        callback = AsyncMock()
        mgr.register("on_error", callback)
        await mgr.trigger("on_error", error="test error")
        callback.assert_called_once_with(error="test error")

    @pytest.mark.asyncio
    async def test_multiple_hooks(self) -> None:
        mgr = HookManager()
        cb1 = AsyncMock()
        cb2 = AsyncMock()
        mgr.register("on_startup", cb1)
        mgr.register("on_startup", cb2)
        count = await mgr.trigger("on_startup")
        assert count == 2

    @pytest.mark.asyncio
    async def test_unregister(self) -> None:
        mgr = HookManager()
        cb = AsyncMock()
        mgr.register("on_startup", cb)
        mgr.unregister("on_startup", cb)
        count = await mgr.trigger("on_startup")
        assert count == 0

    @pytest.mark.asyncio
    async def test_no_hooks(self) -> None:
        mgr = HookManager()
        count = await mgr.trigger("nonexistent")
        assert count == 0

    def test_list_events(self) -> None:
        mgr = HookManager()
        mgr.register("on_startup", AsyncMock())
        mgr.register("on_error", AsyncMock())
        events = mgr.list_events()
        assert "on_startup" in events
        assert "on_error" in events

    def test_hook_count(self) -> None:
        mgr = HookManager()
        mgr.register("on_startup", AsyncMock())
        mgr.register("on_startup", AsyncMock())
        assert mgr.hook_count("on_startup") == 2
        assert mgr.hook_count("nonexistent") == 0

    @pytest.mark.asyncio
    async def test_error_in_hook_doesnt_crash(self) -> None:
        mgr = HookManager()
        bad_cb = AsyncMock(side_effect=RuntimeError("boom"))
        good_cb = AsyncMock()
        mgr.register("on_startup", bad_cb)
        mgr.register("on_startup", good_cb)
        count = await mgr.trigger("on_startup")
        assert count == 1  # Only good_cb succeeded
        good_cb.assert_called_once()
