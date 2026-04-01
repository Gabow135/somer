"""Tests para el sistema de canales."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock

import pytest

from channels.plugin import ChannelPlugin
from channels.registry import ChannelRegistry
from channels.routing import ChannelRouter
from shared.types import (
    ChannelCapabilities,
    ChannelMeta,
    ChannelType,
    IncomingMessage,
)


class DummyPlugin(ChannelPlugin):
    """Plugin dummy para tests."""

    def __init__(self, plugin_id: str = "dummy"):
        super().__init__(
            plugin_id=plugin_id,
            meta=ChannelMeta(id=plugin_id, name="Dummy"),
            capabilities=ChannelCapabilities(),
        )
        self.sent_messages: List[Dict[str, str]] = []
        self.setup_called = False

    async def setup(self, config: Dict[str, Any]) -> None:
        self.setup_called = True

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def send_message(
        self, target: str, content: str, media: Optional[List[Dict[str, Any]]] = None
    ) -> None:
        self.sent_messages.append({"target": target, "content": content})


class TestChannelPlugin:
    """Tests del plugin base."""

    @pytest.mark.asyncio
    async def test_lifecycle(self) -> None:
        plugin = DummyPlugin()
        assert not plugin.is_running
        await plugin.setup({})
        assert plugin.setup_called
        await plugin.start()
        assert plugin.is_running
        await plugin.stop()
        assert not plugin.is_running

    @pytest.mark.asyncio
    async def test_send_message(self) -> None:
        plugin = DummyPlugin()
        await plugin.send_message("chat1", "Hello")
        assert len(plugin.sent_messages) == 1
        assert plugin.sent_messages[0]["content"] == "Hello"

    @pytest.mark.asyncio
    async def test_on_message_callback(self) -> None:
        plugin = DummyPlugin()
        received = []

        async def handler(msg):
            received.append(msg)

        plugin.on_message(handler)
        msg = IncomingMessage(
            channel=ChannelType.CLI,
            channel_user_id="u1",
            content="test",
        )
        await plugin._dispatch_message(msg)
        assert len(received) == 1
        assert received[0].content == "test"


class TestChannelRegistry:
    """Tests del registry de canales."""

    def test_register(self) -> None:
        registry = ChannelRegistry()
        plugin = DummyPlugin("test")
        registry.register(plugin)
        assert registry.plugin_count == 1

    def test_get(self) -> None:
        registry = ChannelRegistry()
        plugin = DummyPlugin("test")
        registry.register(plugin)
        assert registry.get("test") is plugin

    def test_unregister(self) -> None:
        registry = ChannelRegistry()
        plugin = DummyPlugin("test")
        registry.register(plugin)
        registry.unregister("test")
        assert registry.plugin_count == 0

    @pytest.mark.asyncio
    async def test_start_all(self) -> None:
        registry = ChannelRegistry()
        p1 = DummyPlugin("p1")
        p2 = DummyPlugin("p2")
        registry.register(p1)
        registry.register(p2)
        started = await registry.start_all()
        assert started == 2
        assert len(registry.list_running()) == 2

    @pytest.mark.asyncio
    async def test_stop_all(self) -> None:
        registry = ChannelRegistry()
        p1 = DummyPlugin("p1")
        registry.register(p1)
        await registry.start_all()
        await registry.stop_all()
        assert len(registry.list_running()) == 0


class TestChannelRouter:
    """Tests del router de canales."""

    @pytest.mark.asyncio
    async def test_route(self) -> None:
        handler = AsyncMock(return_value="session-123")
        router = ChannelRouter(handler)
        msg = IncomingMessage(
            channel=ChannelType.TELEGRAM,
            channel_user_id="user1",
            content="hello",
        )
        sid = await router.route(msg)
        assert sid == "session-123"
        handler.assert_called_once_with(msg)
