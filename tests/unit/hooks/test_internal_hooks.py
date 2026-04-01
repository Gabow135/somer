"""Tests para el sistema de hooks internos de SOMER 2.0."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from hooks.internal import (
    AgentBootstrapContext,
    CanonicalInboundContext,
    CanonicalSentContext,
    ContextCompactContext,
    ErrorContext,
    GatewayStartupContext,
    HookEvent,
    HookEventType,
    MessagePreprocessedContext,
    MessageReceivedContext,
    MessageSentContext,
    MessageTranscribedContext,
    ProviderSwitchContext,
    SessionLifecycleContext,
    SkillExecutionContext,
    clear_internal_hooks,
    create_agent_bootstrap_event,
    create_context_compact_event,
    create_error_event,
    create_gateway_startup_event,
    create_hook_event,
    create_message_preprocessed_event,
    create_message_received_event,
    create_message_sent_event,
    create_message_transcribed_event,
    create_provider_switch_event,
    create_session_event,
    create_skill_event,
    derive_conversation_id,
    derive_parent_conversation_id,
    get_handler_count,
    get_registered_event_keys,
    inbound_to_preprocessed_context,
    inbound_to_received_context,
    inbound_to_transcribed_context,
    install_builtin_hooks,
    is_agent_bootstrap_event,
    is_error_event,
    is_gateway_startup_event,
    is_message_preprocessed_event,
    is_message_received_event,
    is_message_sent_event,
    is_message_transcribed_event,
    is_provider_switch_event,
    is_session_event,
    register_internal_hook,
    sent_to_sent_context,
    trigger_hook,
    trigger_internal_hook,
    uninstall_builtin_hooks,
    unregister_internal_hook,
)


@pytest.fixture(autouse=True)
def _clean_hooks():
    """Limpia hooks antes y despues de cada test."""
    clear_internal_hooks()
    yield
    clear_internal_hooks()


# ============================================================================
# Registro y ejecucion basica
# ============================================================================

class TestRegisterAndTrigger:
    """Tests de registro y disparo de hooks internos."""

    @pytest.mark.asyncio
    async def test_register_and_trigger_by_type(self) -> None:
        handler = AsyncMock()
        register_internal_hook("message", handler)
        event = create_hook_event(HookEventType.MESSAGE, "received")
        count = await trigger_internal_hook(event)
        assert count == 1
        handler.assert_called_once_with(event)

    @pytest.mark.asyncio
    async def test_register_and_trigger_by_type_action(self) -> None:
        handler = AsyncMock()
        register_internal_hook("message:received", handler)
        event = create_hook_event(HookEventType.MESSAGE, "received")
        count = await trigger_internal_hook(event)
        assert count == 1
        handler.assert_called_once_with(event)

    @pytest.mark.asyncio
    async def test_both_type_and_specific_handlers_fire(self) -> None:
        type_handler = AsyncMock()
        specific_handler = AsyncMock()
        register_internal_hook("message", type_handler)
        register_internal_hook("message:received", specific_handler)

        event = create_hook_event(HookEventType.MESSAGE, "received")
        count = await trigger_internal_hook(event)
        assert count == 2
        type_handler.assert_called_once_with(event)
        specific_handler.assert_called_once_with(event)

    @pytest.mark.asyncio
    async def test_specific_handler_doesnt_fire_for_other_action(self) -> None:
        handler = AsyncMock()
        register_internal_hook("message:sent", handler)
        event = create_hook_event(HookEventType.MESSAGE, "received")
        count = await trigger_internal_hook(event)
        assert count == 0
        handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_handlers_returns_zero(self) -> None:
        event = create_hook_event(HookEventType.MESSAGE, "received")
        count = await trigger_internal_hook(event)
        assert count == 0

    @pytest.mark.asyncio
    async def test_sync_handler_supported(self) -> None:
        calls = []

        def sync_handler(event: HookEvent) -> None:
            calls.append(event.action)

        register_internal_hook("session:create", sync_handler)
        event = create_hook_event(HookEventType.SESSION, "create")
        count = await trigger_internal_hook(event)
        assert count == 1
        assert calls == ["create"]


# ============================================================================
# Prioridad de ejecucion
# ============================================================================

class TestPriority:
    """Tests de ordenamiento por prioridad."""

    @pytest.mark.asyncio
    async def test_lower_priority_runs_first(self) -> None:
        order: list = []

        async def handler_a(event: HookEvent) -> None:
            order.append("a")

        async def handler_b(event: HookEvent) -> None:
            order.append("b")

        register_internal_hook("test:order", handler_b, priority=10)
        register_internal_hook("test:order", handler_a, priority=-5)

        event = create_hook_event(HookEventType.COMMAND, "order")
        # Nota: "test:order" no matchea con "command:order", los registramos
        # directamente bajo "test:order" pero disparamos con la key correcta
        # Vamos a usar directamente "command:order"
        clear_internal_hooks()
        register_internal_hook("command:order", handler_b, priority=10)
        register_internal_hook("command:order", handler_a, priority=-5)
        count = await trigger_internal_hook(event)
        assert count == 2
        assert order == ["a", "b"]

    @pytest.mark.asyncio
    async def test_same_priority_preserves_registration_order(self) -> None:
        order: list = []

        async def handler_first(event: HookEvent) -> None:
            order.append("first")

        async def handler_second(event: HookEvent) -> None:
            order.append("second")

        register_internal_hook("command:test", handler_first, priority=0)
        register_internal_hook("command:test", handler_second, priority=0)
        event = create_hook_event(HookEventType.COMMAND, "test")
        await trigger_internal_hook(event)
        assert order == ["first", "second"]


# ============================================================================
# Unregister y clear
# ============================================================================

class TestUnregisterAndClear:
    """Tests de desregistro y limpieza."""

    @pytest.mark.asyncio
    async def test_unregister_specific_handler(self) -> None:
        handler = AsyncMock()
        register_internal_hook("message:received", handler)
        assert unregister_internal_hook("message:received", handler) is True
        event = create_hook_event(HookEventType.MESSAGE, "received")
        count = await trigger_internal_hook(event)
        assert count == 0

    def test_unregister_nonexistent_returns_false(self) -> None:
        handler = AsyncMock()
        assert unregister_internal_hook("nonexistent", handler) is False

    def test_unregister_wrong_handler_returns_false(self) -> None:
        handler_a = AsyncMock()
        handler_b = AsyncMock()
        register_internal_hook("test", handler_a)
        assert unregister_internal_hook("test", handler_b) is False

    def test_clear_removes_all(self) -> None:
        register_internal_hook("a", AsyncMock())
        register_internal_hook("b", AsyncMock())
        clear_internal_hooks()
        assert get_registered_event_keys() == []

    def test_get_registered_event_keys(self) -> None:
        register_internal_hook("message:received", AsyncMock())
        register_internal_hook("session:create", AsyncMock())
        keys = get_registered_event_keys()
        assert "message:received" in keys
        assert "session:create" in keys

    def test_get_handler_count(self) -> None:
        register_internal_hook("test", AsyncMock())
        register_internal_hook("test", AsyncMock())
        assert get_handler_count("test") == 2
        assert get_handler_count("nonexistent") == 0


# ============================================================================
# Manejo de errores
# ============================================================================

class TestErrorHandling:
    """Tests de manejo de errores en hooks."""

    @pytest.mark.asyncio
    async def test_error_in_handler_doesnt_stop_others(self) -> None:
        bad_handler = AsyncMock(side_effect=RuntimeError("boom"))
        good_handler = AsyncMock()
        register_internal_hook("message:received", bad_handler, priority=-1)
        register_internal_hook("message:received", good_handler, priority=0)

        event = create_hook_event(HookEventType.MESSAGE, "received")
        count = await trigger_internal_hook(event)
        assert count == 1
        good_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_error_is_logged(self, caplog) -> None:
        bad_handler = AsyncMock(side_effect=ValueError("test error"))
        register_internal_hook("session:create", bad_handler)

        event = create_hook_event(HookEventType.SESSION, "create")
        with caplog.at_level("ERROR"):
            await trigger_internal_hook(event)
        assert "test error" in caplog.text


# ============================================================================
# Factory de eventos
# ============================================================================

class TestEventFactories:
    """Tests de creacion de eventos."""

    def test_create_hook_event(self) -> None:
        event = create_hook_event(
            HookEventType.MESSAGE,
            "received",
            session_key="sess-123",
            context={"foo": "bar"},
        )
        assert event.type == HookEventType.MESSAGE
        assert event.action == "received"
        assert event.session_key == "sess-123"
        assert event.context["foo"] == "bar"
        assert event.timestamp > 0
        assert event.messages == []

    def test_create_agent_bootstrap_event(self) -> None:
        ctx = AgentBootstrapContext(
            workspace_dir="/tmp/ws",
            session_id="sess-1",
            bootstrap_files=["a.py", "b.py"],
        )
        event = create_agent_bootstrap_event(ctx, session_key="key-1")
        assert event.type == HookEventType.AGENT
        assert event.action == "bootstrap"
        assert event.context["workspace_dir"] == "/tmp/ws"
        assert event.context["bootstrap_files"] == ["a.py", "b.py"]

    def test_create_gateway_startup_event(self) -> None:
        ctx = GatewayStartupContext(host="0.0.0.0", port=9000)
        event = create_gateway_startup_event(ctx)
        assert event.type == HookEventType.GATEWAY
        assert event.action == "startup"
        assert event.context["host"] == "0.0.0.0"
        assert event.context["port"] == 9000

    def test_create_message_received_event(self) -> None:
        ctx = MessageReceivedContext(
            sender="user-1",
            content="hola",
            channel_id="telegram",
        )
        event = create_message_received_event(ctx, session_key="s1")
        assert event.type == HookEventType.MESSAGE
        assert event.action == "received"
        assert event.context["sender"] == "user-1"
        assert event.context["content"] == "hola"

    def test_create_message_sent_event(self) -> None:
        ctx = MessageSentContext(
            recipient="user-2",
            content="respuesta",
            success=True,
            channel_id="slack",
        )
        event = create_message_sent_event(ctx)
        assert event.context["recipient"] == "user-2"
        assert event.context["success"] is True

    def test_create_message_transcribed_event(self) -> None:
        ctx = MessageTranscribedContext(
            transcript="texto transcrito",
            channel_id="telegram",
        )
        event = create_message_transcribed_event(ctx)
        assert event.action == "transcribed"
        assert event.context["transcript"] == "texto transcrito"

    def test_create_message_preprocessed_event(self) -> None:
        ctx = MessagePreprocessedContext(
            channel_id="discord",
            is_group=True,
            group_id="guild-1",
        )
        event = create_message_preprocessed_event(ctx)
        assert event.action == "preprocessed"
        assert event.context["is_group"] is True

    def test_create_session_event(self) -> None:
        ctx = SessionLifecycleContext(
            session_id="sess-42",
            channel="telegram",
            channel_user_id="user-5",
        )
        event = create_session_event("create", ctx)
        assert event.type == HookEventType.SESSION
        assert event.action == "create"
        assert event.context["session_id"] == "sess-42"

    def test_create_error_event(self) -> None:
        ctx = ErrorContext(
            error_type="ProviderError",
            error_message="API key invalid",
            source="anthropic",
            recoverable=False,
        )
        event = create_error_event(ctx)
        assert event.type == HookEventType.AGENT
        assert event.action == "error"
        assert event.context["recoverable"] is False

    def test_create_provider_switch_event(self) -> None:
        ctx = ProviderSwitchContext(
            old_provider="anthropic",
            new_provider="openai",
            old_model="claude-3",
            new_model="gpt-4",
            reason="fallback",
        )
        event = create_provider_switch_event(ctx)
        assert event.type == HookEventType.PROVIDER
        assert event.action == "switch"
        assert event.context["reason"] == "fallback"

    def test_create_context_compact_event(self) -> None:
        ctx = ContextCompactContext(
            session_id="s1",
            messages_before=100,
            messages_after=20,
            tokens_saved=5000,
            strategy="summarize",
        )
        event = create_context_compact_event(ctx)
        assert event.type == HookEventType.CONTEXT
        assert event.action == "compact"
        assert event.context["tokens_saved"] == 5000

    def test_create_skill_event(self) -> None:
        ctx = SkillExecutionContext(
            skill_name="web_search",
            session_id="s1",
            trigger="/search",
            duration_ms=350.5,
            success=True,
        )
        event = create_skill_event("complete", ctx)
        assert event.type == HookEventType.SKILL
        assert event.action == "complete"
        assert event.context["skill_name"] == "web_search"


# ============================================================================
# trigger_hook shortcut
# ============================================================================

class TestTriggerHookShortcut:
    """Tests del atajo trigger_hook."""

    @pytest.mark.asyncio
    async def test_trigger_hook_creates_and_fires(self) -> None:
        handler = AsyncMock()
        register_internal_hook("gateway:startup", handler)
        event = await trigger_hook(
            HookEventType.GATEWAY,
            "startup",
            context={"host": "localhost"},
        )
        assert event.type == HookEventType.GATEWAY
        handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_trigger_hook_returns_event_with_messages(self) -> None:
        async def add_message(event: HookEvent) -> None:
            event.messages.append("respuesta automatica")

        register_internal_hook("session:create", add_message)
        event = await trigger_hook(HookEventType.SESSION, "create")
        assert "respuesta automatica" in event.messages


# ============================================================================
# Type guards
# ============================================================================

class TestTypeGuards:
    """Tests de funciones de validacion de tipo de evento."""

    def test_is_agent_bootstrap_event(self) -> None:
        ctx = AgentBootstrapContext(
            workspace_dir="/tmp",
            bootstrap_files=["a.py"],
        )
        event = create_agent_bootstrap_event(ctx)
        assert is_agent_bootstrap_event(event) is True

    def test_is_agent_bootstrap_event_missing_files(self) -> None:
        event = create_hook_event(
            HookEventType.AGENT,
            "bootstrap",
            context={"workspace_dir": "/tmp"},
        )
        assert is_agent_bootstrap_event(event) is False

    def test_is_gateway_startup_event(self) -> None:
        ctx = GatewayStartupContext()
        event = create_gateway_startup_event(ctx)
        assert is_gateway_startup_event(event) is True

    def test_is_gateway_startup_event_wrong_type(self) -> None:
        event = create_hook_event(HookEventType.MESSAGE, "startup")
        assert is_gateway_startup_event(event) is False

    def test_is_message_received_event(self) -> None:
        ctx = MessageReceivedContext(sender="u1", channel_id="tg")
        event = create_message_received_event(ctx)
        assert is_message_received_event(event) is True

    def test_is_message_received_event_missing_sender(self) -> None:
        event = create_hook_event(
            HookEventType.MESSAGE,
            "received",
            context={"channel_id": "tg"},
        )
        assert is_message_received_event(event) is False

    def test_is_message_sent_event(self) -> None:
        ctx = MessageSentContext(
            recipient="u2",
            channel_id="slack",
            success=True,
        )
        event = create_message_sent_event(ctx)
        assert is_message_sent_event(event) is True

    def test_is_message_sent_event_missing_success(self) -> None:
        event = create_hook_event(
            HookEventType.MESSAGE,
            "sent",
            context={"recipient": "u2", "channel_id": "slack"},
        )
        assert is_message_sent_event(event) is False

    def test_is_message_transcribed_event(self) -> None:
        ctx = MessageTranscribedContext(transcript="hola", channel_id="tg")
        event = create_message_transcribed_event(ctx)
        assert is_message_transcribed_event(event) is True

    def test_is_message_preprocessed_event(self) -> None:
        ctx = MessagePreprocessedContext(channel_id="discord")
        event = create_message_preprocessed_event(ctx)
        assert is_message_preprocessed_event(event) is True

    def test_is_session_event(self) -> None:
        ctx = SessionLifecycleContext(session_id="s1")
        event = create_session_event("create", ctx)
        assert is_session_event(event) is True
        assert is_session_event(event, action="create") is True
        assert is_session_event(event, action="close") is False

    def test_is_error_event(self) -> None:
        ctx = ErrorContext(error_type="TestError")
        event = create_error_event(ctx)
        assert is_error_event(event) is True

    def test_is_provider_switch_event(self) -> None:
        ctx = ProviderSwitchContext(
            new_provider="openai",
            new_model="gpt-4",
        )
        event = create_provider_switch_event(ctx)
        assert is_provider_switch_event(event) is True


# ============================================================================
# Message hook mappers
# ============================================================================

class TestMessageHookMappers:
    """Tests de transformacion de contextos de mensajes."""

    def test_inbound_to_received_context(self) -> None:
        canonical = CanonicalInboundContext(
            sender="user-1",
            content="hola mundo",
            channel_id="telegram",
            account_id="acc-1",
            sender_name="Juan",
        )
        result = inbound_to_received_context(canonical)
        assert result.sender == "user-1"
        assert result.content == "hola mundo"
        assert result.channel_id == "telegram"
        assert result.metadata["sender_name"] == "Juan"
        # None values should be excluded from metadata
        assert "media_path" not in result.metadata

    def test_inbound_to_transcribed_context(self) -> None:
        canonical = CanonicalInboundContext(
            sender="user-1",
            transcript="texto del audio",
            channel_id="telegram",
            media_path="/tmp/audio.ogg",
            media_type="audio/ogg",
        )
        result = inbound_to_transcribed_context(canonical)
        assert result.transcript == "texto del audio"
        assert result.media_path == "/tmp/audio.ogg"

    def test_inbound_to_preprocessed_context(self) -> None:
        canonical = CanonicalInboundContext(
            sender="user-1",
            channel_id="discord",
            is_group=True,
            group_id="guild-1",
        )
        result = inbound_to_preprocessed_context(canonical)
        assert result.is_group is True
        assert result.group_id == "guild-1"

    def test_sent_to_sent_context(self) -> None:
        canonical = CanonicalSentContext(
            recipient="user-2",
            content="respuesta",
            success=True,
            channel_id="slack",
        )
        result = sent_to_sent_context(canonical)
        assert result.recipient == "user-2"
        assert result.success is True
        assert result.conversation_id == "user-2"  # Fallback

    def test_sent_to_sent_context_with_conversation(self) -> None:
        canonical = CanonicalSentContext(
            recipient="user-2",
            content="ok",
            success=True,
            channel_id="slack",
            conversation_id="conv-5",
        )
        result = sent_to_sent_context(canonical)
        assert result.conversation_id == "conv-5"


# ============================================================================
# derive_conversation_id
# ============================================================================

class TestDeriveConversationId:
    """Tests de derivacion de ID de conversacion."""

    def test_generic_channel_strips_prefix(self) -> None:
        ctx = CanonicalInboundContext(
            channel_id="whatsapp",
            recipient="whatsapp:+1234567890",
        )
        result = derive_conversation_id(ctx)
        assert result == "+1234567890"

    def test_telegram_with_thread(self) -> None:
        ctx = CanonicalInboundContext(
            channel_id="telegram",
            recipient="telegram:12345",
            thread_id="99",
        )
        result = derive_conversation_id(ctx)
        assert result == "12345:topic:99"

    def test_telegram_without_thread(self) -> None:
        ctx = CanonicalInboundContext(
            channel_id="telegram",
            recipient="telegram:12345",
        )
        result = derive_conversation_id(ctx)
        assert result == "12345"

    def test_discord_dm(self) -> None:
        ctx = CanonicalInboundContext(
            channel_id="discord",
            sender="discord:user:456",
            is_group=False,
        )
        result = derive_conversation_id(ctx)
        assert result == "user:456"

    def test_discord_group_channel(self) -> None:
        ctx = CanonicalInboundContext(
            channel_id="discord",
            recipient="discord:channel:789",
            is_group=True,
        )
        result = derive_conversation_id(ctx)
        assert result == "channel:789"

    def test_discord_user_prefix(self) -> None:
        ctx = CanonicalInboundContext(
            channel_id="discord",
            sender="discord:111",
            recipient="discord:user:222",
            is_group=True,
        )
        result = derive_conversation_id(ctx)
        assert result == "user:222"

    def test_discord_no_target_returns_none(self) -> None:
        ctx = CanonicalInboundContext(
            channel_id="discord",
            sender="discord:user:456",
            is_group=True,
        )
        result = derive_conversation_id(ctx)
        assert result is None

    def test_generic_prefix_stripping(self) -> None:
        ctx = CanonicalInboundContext(
            channel_id="slack",
            recipient="channel:C12345",
        )
        result = derive_conversation_id(ctx)
        assert result == "C12345"


class TestDeriveParentConversationId:
    """Tests de derivacion de ID de conversacion padre."""

    def test_telegram_with_thread(self) -> None:
        ctx = CanonicalInboundContext(
            channel_id="telegram",
            recipient="telegram:12345",
            thread_id="99",
        )
        result = derive_parent_conversation_id(ctx)
        assert result == "12345"

    def test_non_telegram_returns_none(self) -> None:
        ctx = CanonicalInboundContext(
            channel_id="discord",
            thread_id="99",
        )
        result = derive_parent_conversation_id(ctx)
        assert result is None

    def test_telegram_without_thread_returns_none(self) -> None:
        ctx = CanonicalInboundContext(
            channel_id="telegram",
            recipient="telegram:12345",
        )
        result = derive_parent_conversation_id(ctx)
        assert result is None


# ============================================================================
# Built-in hooks
# ============================================================================

class TestBuiltinHooks:
    """Tests de hooks built-in de SOMER."""

    def test_install_builtin_hooks(self) -> None:
        count = install_builtin_hooks()
        assert count == 8
        assert get_handler_count("gateway:startup") >= 1
        assert get_handler_count("gateway:shutdown") >= 1
        assert get_handler_count("session:create") >= 1
        assert get_handler_count("session:close") >= 1
        assert get_handler_count("agent:error") >= 1
        assert get_handler_count("message:received") >= 1
        assert get_handler_count("message:sent") >= 1
        assert get_handler_count("provider:switch") >= 1

    def test_uninstall_builtin_hooks(self) -> None:
        install_builtin_hooks()
        removed = uninstall_builtin_hooks()
        assert removed == 8
        assert get_handler_count("gateway:startup") == 0

    @pytest.mark.asyncio
    async def test_builtin_startup_logs(self, caplog) -> None:
        install_builtin_hooks()
        import logging

        with caplog.at_level(logging.INFO):
            await trigger_hook(
                HookEventType.GATEWAY,
                "startup",
                context={"host": "localhost", "port": 9000},
            )
        assert "SOMER 2.0 iniciado" in caplog.text

    @pytest.mark.asyncio
    async def test_builtin_error_logs(self, caplog) -> None:
        install_builtin_hooks()
        import logging

        with caplog.at_level(logging.ERROR):
            ctx = ErrorContext(
                error_type="ProviderError",
                error_message="API key invalid",
                source="anthropic",
            )
            event = create_error_event(ctx)
            await trigger_internal_hook(event)
        assert "API key invalid" in caplog.text

    @pytest.mark.asyncio
    async def test_builtin_message_sent_failure_logs_warning(self, caplog) -> None:
        install_builtin_hooks()
        import logging

        with caplog.at_level(logging.WARNING):
            ctx = MessageSentContext(
                recipient="user-1",
                content="hola",
                success=False,
                error="timeout",
                channel_id="telegram",
            )
            event = create_message_sent_event(ctx)
            await trigger_internal_hook(event)
        assert "Fallo envio" in caplog.text

    @pytest.mark.asyncio
    async def test_user_hooks_run_before_builtins(self) -> None:
        """Los hooks de usuario (priority=0) se ejecutan antes que los builtin (priority=100)."""
        order: list = []

        async def user_handler(event: HookEvent) -> None:
            order.append("user")

        install_builtin_hooks()
        register_internal_hook("gateway:startup", user_handler, priority=0, name="user")

        await trigger_hook(
            HookEventType.GATEWAY,
            "startup",
            context={"host": "localhost", "port": 9000},
        )
        # User handler (priority 0) should run before builtin (priority 100)
        assert order[0] == "user"
