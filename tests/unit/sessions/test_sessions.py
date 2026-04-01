"""Tests para el sistema de sesiones."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from sessions.events import SessionEventBus
from sessions.manager import SessionManager
from sessions.persistence import SessionPersistence
from sessions.routing import SessionRouter
from shared.types import (
    AgentMessage,
    ChannelType,
    IncomingMessage,
    Role,
    SessionInfo,
)


class TestSessionRouter:
    """Tests del SessionRouter."""

    def test_resolve_creates_session(self) -> None:
        router = SessionRouter()
        msg = IncomingMessage(
            channel=ChannelType.TELEGRAM,
            channel_user_id="user1",
            content="hello",
        )
        sid = router.resolve(msg)
        assert sid is not None
        assert len(sid) > 0

    def test_resolve_same_user_same_session(self) -> None:
        router = SessionRouter()
        msg1 = IncomingMessage(
            channel=ChannelType.TELEGRAM, channel_user_id="user1", content="hi"
        )
        msg2 = IncomingMessage(
            channel=ChannelType.TELEGRAM, channel_user_id="user1", content="hello"
        )
        sid1 = router.resolve(msg1)
        sid2 = router.resolve(msg2)
        assert sid1 == sid2

    def test_resolve_different_users(self) -> None:
        router = SessionRouter()
        msg1 = IncomingMessage(
            channel=ChannelType.TELEGRAM, channel_user_id="user1", content="hi"
        )
        msg2 = IncomingMessage(
            channel=ChannelType.TELEGRAM, channel_user_id="user2", content="hi"
        )
        assert router.resolve(msg1) != router.resolve(msg2)

    def test_resolve_thread(self) -> None:
        router = SessionRouter()
        msg = IncomingMessage(
            channel=ChannelType.SLACK,
            channel_user_id="user1",
            channel_thread_id="thread1",
            content="hi",
        )
        sid = router.resolve(msg)
        assert sid is not None

    def test_close_session(self) -> None:
        router = SessionRouter()
        msg = IncomingMessage(
            channel=ChannelType.CLI, channel_user_id="u1", content="hi"
        )
        sid = router.resolve(msg)
        assert router.close_session(sid)

    def test_active_sessions(self) -> None:
        router = SessionRouter()
        msg = IncomingMessage(
            channel=ChannelType.CLI, channel_user_id="u1", content="hi"
        )
        router.resolve(msg)
        assert len(router.active_sessions()) == 1


class TestSessionEventBus:
    """Tests del event bus."""

    @pytest.mark.asyncio
    async def test_emit_and_receive(self) -> None:
        bus = SessionEventBus()
        received = []

        async def handler(event_type, data):
            received.append((event_type, data))

        bus.subscribe("test", handler)
        count = await bus.emit("test", {"key": "value"})
        assert count == 1
        assert len(received) == 1
        assert received[0][1]["key"] == "value"

    @pytest.mark.asyncio
    async def test_unsubscribe(self) -> None:
        bus = SessionEventBus()

        async def handler(et, d):
            pass

        bus.subscribe("test", handler)
        bus.unsubscribe("test", handler)
        assert bus.subscriber_count("test") == 0

    @pytest.mark.asyncio
    async def test_no_subscribers(self) -> None:
        bus = SessionEventBus()
        count = await bus.emit("nobody", {})
        assert count == 0


class TestSessionPersistence:
    """Tests de persistencia."""

    def test_save_and_load(self, tmp_path: Path) -> None:
        pers = SessionPersistence(sessions_dir=tmp_path)
        msg = AgentMessage(role=Role.USER, content="hello")
        pers.save_message("s1", msg)

        messages = pers.load_messages("s1")
        assert len(messages) == 1
        assert messages[0].content == "hello"

    def test_session_exists(self, tmp_path: Path) -> None:
        pers = SessionPersistence(sessions_dir=tmp_path)
        assert not pers.session_exists("nope")
        pers.save_event("exists", {"type": "test"})
        assert pers.session_exists("exists")

    def test_list_sessions(self, tmp_path: Path) -> None:
        pers = SessionPersistence(sessions_dir=tmp_path)
        pers.save_event("s1", {"type": "test"})
        pers.save_event("s2", {"type": "test"})
        sessions = pers.list_sessions()
        assert "s1" in sessions
        assert "s2" in sessions

    def test_delete(self, tmp_path: Path) -> None:
        pers = SessionPersistence(sessions_dir=tmp_path)
        pers.save_event("del", {"type": "test"})
        assert pers.delete_session("del")
        assert not pers.session_exists("del")


class TestSessionManager:
    """Tests del SessionManager."""

    @pytest.mark.asyncio
    async def test_handle_message(self, tmp_path: Path) -> None:
        mgr = SessionManager(
            persistence=SessionPersistence(sessions_dir=tmp_path),
        )
        msg = IncomingMessage(
            channel=ChannelType.TELEGRAM,
            channel_user_id="user1",
            content="hello",
        )
        sid = await mgr.handle_message(msg)
        assert sid is not None
        assert mgr.get_turn_count(sid) == 1

    @pytest.mark.asyncio
    async def test_same_user_increments_turns(self, tmp_path: Path) -> None:
        mgr = SessionManager(
            persistence=SessionPersistence(sessions_dir=tmp_path),
        )
        msg = IncomingMessage(
            channel=ChannelType.CLI, channel_user_id="u1", content="hi"
        )
        sid = await mgr.handle_message(msg)
        msg2 = IncomingMessage(
            channel=ChannelType.CLI, channel_user_id="u1", content="again"
        )
        await mgr.handle_message(msg2)
        assert mgr.get_turn_count(sid) == 2
