"""Tests para el Gateway WebSocket."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict
from unittest.mock import AsyncMock

import pytest

from gateway.protocol import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    PROTOCOL_VERSION,
    ErrorCode,
    ErrorShape,
    EventFrame,
    GatewayEvent,
    JsonRpcBatchRequest,
    JsonRpcNotification,
    JsonRpcRequest,
    JsonRpcResponse,
    MethodRegistry,
    RequestFrame,
    ResponseFrame,
    SessionsListParams,
    StateVersion,
    error_shape,
    format_validation_errors,
    is_batch_request,
    parse_gateway_frame,
)
from gateway.server import GatewayServer
from gateway.session_utils import (
    ConnectionSessionMap,
    GatewaySessionRow,
    GatewaySessionsDefaults,
    SessionEntry,
    SessionKind,
    SessionStore,
    append_to_session,
    build_gateway_session_row,
    canonicalize_session_key_for_agent,
    classify_session_key,
    delete_session,
    derive_session_title,
    find_store_keys_ignore_case,
    find_store_match,
    format_session_id_prefix,
    list_sessions_from_store,
    normalize_agent_id,
    normalize_main_key,
    parse_agent_session_key,
    parse_group_key,
    prune_legacy_store_keys,
    read_session,
    resolve_session_store_agent_id,
    resolve_session_store_key,
    session_exists,
    truncate_title,
    validate_session_key,
)


# ═══════════════════════════════════════════════════════════════
# Protocolo JSON-RPC
# ═══════════════════════════════════════════════════════════════


class TestJsonRpcProtocol:
    """Tests del protocolo JSON-RPC."""

    def test_request_creation(self) -> None:
        req = JsonRpcRequest(method="ping")
        assert req.jsonrpc == "2.0"
        assert req.method == "ping"
        assert req.id is not None

    def test_success_response(self) -> None:
        resp = JsonRpcResponse.success({"ok": True}, "123")
        assert resp.result == {"ok": True}
        assert resp.error is None
        assert resp.id == "123"

    def test_error_response(self) -> None:
        resp = JsonRpcResponse.error_response(-32601, "Not found", req_id="456")
        assert resp.result is None
        assert resp.error is not None
        assert resp.error["code"] == -32601
        assert resp.error["message"] == "Not found"
        assert resp.id == "456"

    def test_gateway_event(self) -> None:
        event = GatewayEvent(type="message", data={"text": "hello"})
        assert event.type == "message"
        assert event.timestamp > 0

    def test_notification(self) -> None:
        notif = JsonRpcNotification(method="update", params={"x": 1})
        assert notif.jsonrpc == "2.0"
        assert notif.method == "update"


class TestFrameProtocol:
    """Tests del protocolo de frames (portado de OpenClaw)."""

    def test_request_frame(self) -> None:
        frame = RequestFrame(id="r1", method="ping", params={"x": 1})
        assert frame.type == "req"
        assert frame.id == "r1"
        assert frame.method == "ping"

    def test_response_frame_success(self) -> None:
        frame = ResponseFrame.success("r1", {"ok": True})
        assert frame.ok is True
        assert frame.payload == {"ok": True}
        assert frame.error is None
        assert frame.id == "r1"

    def test_response_frame_failure(self) -> None:
        frame = ResponseFrame.failure(
            "r1", ErrorCode.INVALID_REQUEST, "bad request"
        )
        assert frame.ok is False
        assert frame.error is not None
        assert frame.error.code == "INVALID_REQUEST"
        assert frame.error.message == "bad request"

    def test_event_frame(self) -> None:
        frame = EventFrame(event="tick", payload={"ts": 123}, seq=1)
        assert frame.type == "event"
        assert frame.event == "tick"
        assert frame.seq == 1

    def test_state_version(self) -> None:
        sv = StateVersion(health=1, presence=2, sessions=3)
        assert sv.health == 1
        assert sv.presence == 2
        assert sv.sessions == 3

    def test_parse_gateway_frame_req(self) -> None:
        frame = parse_gateway_frame({
            "type": "req", "id": "1", "method": "ping"
        })
        assert isinstance(frame, RequestFrame)
        assert frame.method == "ping"

    def test_parse_gateway_frame_res(self) -> None:
        frame = parse_gateway_frame({
            "type": "res", "id": "1", "ok": True, "payload": {}
        })
        assert isinstance(frame, ResponseFrame)
        assert frame.ok is True

    def test_parse_gateway_frame_event(self) -> None:
        frame = parse_gateway_frame({
            "type": "event", "event": "tick"
        })
        assert isinstance(frame, EventFrame)
        assert frame.event == "tick"

    def test_parse_gateway_frame_invalid(self) -> None:
        assert parse_gateway_frame({"type": "bogus"}) is None
        assert parse_gateway_frame({}) is None

    def test_is_batch_request(self) -> None:
        assert is_batch_request([{"method": "ping"}]) is True
        assert is_batch_request([]) is False
        assert is_batch_request({"method": "ping"}) is False


class TestErrorShape:
    """Tests de ErrorShape."""

    def test_error_shape_basic(self) -> None:
        shape = error_shape(ErrorCode.UNAVAILABLE, "service down")
        assert shape.code == "UNAVAILABLE"
        assert shape.message == "service down"

    def test_error_shape_with_details(self) -> None:
        shape = error_shape(
            ErrorCode.RATE_LIMITED,
            "rate limit",
            retryable=True,
            retry_after_ms=5000,
        )
        assert shape.retryable is True
        assert shape.retry_after_ms == 5000

    def test_error_shape_string_code(self) -> None:
        shape = error_shape("CUSTOM_ERROR", "something custom")
        assert shape.code == "CUSTOM_ERROR"


class TestMethodRegistry:
    """Tests del registro de métodos."""

    def test_register_and_get(self) -> None:
        registry = MethodRegistry()
        handler = AsyncMock(return_value={"ok": True})
        registry.register("test.method", handler, description="Test")
        assert registry.has("test.method")
        assert registry.get("test.method") is handler
        meta = registry.get_meta("test.method")
        assert meta is not None
        assert meta.description == "Test"

    def test_unregister(self) -> None:
        registry = MethodRegistry()
        handler = AsyncMock()
        registry.register("test.method", handler)
        registry.unregister("test.method")
        assert not registry.has("test.method")
        assert registry.get("test.method") is None

    def test_names_and_count(self) -> None:
        registry = MethodRegistry()
        registry.register("a", AsyncMock())
        registry.register("b", AsyncMock())
        assert registry.count == 2
        assert set(registry.names) == {"a", "b"}

    def test_merge(self) -> None:
        r1 = MethodRegistry()
        r2 = MethodRegistry()
        r1.register("a", AsyncMock())
        r2.register("b", AsyncMock())
        r1.merge(r2)
        assert r1.has("a")
        assert r1.has("b")
        assert r1.count == 2

    def test_list_methods(self) -> None:
        registry = MethodRegistry()
        registry.register("ping", AsyncMock(), description="Ping")
        methods = registry.list_methods()
        assert len(methods) == 1
        assert methods[0].name == "ping"


class TestSessionParamModels:
    """Tests de modelos de parámetros de sesiones."""

    def test_sessions_list_params(self) -> None:
        params = SessionsListParams(limit=10, search="test")
        assert params.limit == 10
        assert params.search == "test"

    def test_sessions_list_params_defaults(self) -> None:
        params = SessionsListParams()
        assert params.limit is None
        assert params.include_global is None


class TestFormatValidationErrors:
    """Tests de formateo de errores de validación."""

    def test_empty(self) -> None:
        assert format_validation_errors([]) == "error de validación desconocido"

    def test_single_error(self) -> None:
        errors = [{"loc": ["field"], "msg": "requerido"}]
        result = format_validation_errors(errors)
        assert "field" in result
        assert "requerido" in result

    def test_dedup(self) -> None:
        errors = [
            {"loc": ["x"], "msg": "bad"},
            {"loc": ["x"], "msg": "bad"},
        ]
        result = format_validation_errors(errors)
        assert result.count("bad") == 1


# ═══════════════════════════════════════════════════════════════
# Gateway Server
# ═══════════════════════════════════════════════════════════════


class TestGatewayServer:
    """Tests del servidor Gateway (sin WebSocket real)."""

    def test_register_method(self) -> None:
        server = GatewayServer()
        handler = AsyncMock(return_value={"ok": True})
        server.register_method("test.method", handler)
        assert "test.method" in server.method_names

    def test_unregister_method(self) -> None:
        server = GatewayServer()
        handler = AsyncMock()
        server.register_method("test.method", handler)
        server.unregister_method("test.method")
        assert "test.method" not in server.method_names

    def test_status(self) -> None:
        server = GatewayServer(host="0.0.0.0", port=9999)
        status = server.status()
        assert status["started"] is False
        assert status["host"] == "0.0.0.0"
        assert status["port"] == 9999
        assert status["clients"] == 0
        assert "protocol_version" in status
        assert "state_version" in status

    def test_state_version(self) -> None:
        server = GatewayServer()
        sv = server.state_version
        assert sv.health == 0
        assert sv.presence == 0
        assert sv.sessions == 0

    def test_increment_versions(self) -> None:
        server = GatewayServer()
        server.increment_health_version()
        server.increment_presence_version()
        server.increment_sessions_version()
        sv = server.state_version
        assert sv.health == 1
        assert sv.presence == 1
        assert sv.sessions == 1

    @pytest.mark.asyncio
    async def test_process_valid_message(self) -> None:
        server = GatewayServer()
        handler = AsyncMock(return_value={"result": "ok"})
        server.register_method("test", handler)

        req = JsonRpcRequest(method="test", params={"key": "val"}, id="1")
        raw = req.model_dump_json()
        resp_raw = await server._process_message(raw, None)
        resp = json.loads(resp_raw)
        assert resp["result"] == {"result": "ok"}
        handler.assert_called_once_with({"key": "val"})

    @pytest.mark.asyncio
    async def test_process_unknown_method(self) -> None:
        server = GatewayServer()
        req = JsonRpcRequest(method="nonexistent", id="2")
        resp_raw = await server._process_message(req.model_dump_json(), None)
        resp = json.loads(resp_raw)
        assert resp["error"]["code"] == METHOD_NOT_FOUND

    @pytest.mark.asyncio
    async def test_process_invalid_json(self) -> None:
        server = GatewayServer()
        resp_raw = await server._process_message("{bad json", None)
        resp = json.loads(resp_raw)
        assert resp["error"]["code"] == -32700  # PARSE_ERROR

    @pytest.mark.asyncio
    async def test_subscribe(self) -> None:
        server = GatewayServer()
        mock_ws = AsyncMock()
        req = JsonRpcRequest(
            method="subscribe", params={"event": "message"}, id="3"
        )
        resp_raw = await server._process_message(req.model_dump_json(), mock_ws)
        resp = json.loads(resp_raw)
        assert resp["result"]["subscribed"] == "message"

    @pytest.mark.asyncio
    async def test_process_request_frame(self) -> None:
        server = GatewayServer()
        handler = AsyncMock(return_value={"pong": True})
        server.register_method("ping", handler)

        frame_data = json.dumps({
            "type": "req", "id": "f1", "method": "ping", "params": {}
        })
        resp_raw = await server._process_message(frame_data, None)
        resp = json.loads(resp_raw)
        assert resp["type"] == "res"
        assert resp["id"] == "f1"
        assert resp["ok"] is True
        assert resp["payload"] == {"pong": True}

    @pytest.mark.asyncio
    async def test_process_batch_request(self) -> None:
        server = GatewayServer()
        handler = AsyncMock(return_value={"ok": True})
        server.register_method("test", handler)

        batch = json.dumps([
            {"jsonrpc": "2.0", "method": "test", "id": "b1"},
            {"jsonrpc": "2.0", "method": "test", "id": "b2"},
        ])
        resp_raw = await server._process_message(batch, None)
        responses = json.loads(resp_raw)
        assert isinstance(responses, list)
        assert len(responses) == 2

    def test_hello_ok(self) -> None:
        server = GatewayServer()
        hello = server.build_hello_ok("conn-123")
        assert hello.type == "hello-ok"
        assert hello.protocol == PROTOCOL_VERSION
        assert hello.server["connId"] == "conn-123"
        assert "methods" in hello.features
        assert "events" in hello.features


# ═══════════════════════════════════════════════════════════════
# Session Utils — Resolución de claves
# ═══════════════════════════════════════════════════════════════


class TestSessionKeyResolution:
    """Tests de resolución de claves de sesión."""

    def test_normalize_agent_id(self) -> None:
        assert normalize_agent_id("  MyAgent  ") == "myagent"
        assert normalize_agent_id("ops") == "ops"

    def test_normalize_main_key(self) -> None:
        assert normalize_main_key(None) == "work"
        assert normalize_main_key("") == "work"
        assert normalize_main_key("custom") == "custom"

    def test_parse_agent_session_key(self) -> None:
        result = parse_agent_session_key("agent:ops:work")
        assert result is not None
        assert result == ("ops", "work")

    def test_parse_agent_session_key_no_match(self) -> None:
        assert parse_agent_session_key("global") is None
        assert parse_agent_session_key("simple-key") is None

    def test_parse_agent_session_key_short(self) -> None:
        assert parse_agent_session_key("agent:ops") is None

    def test_canonicalize_session_key(self) -> None:
        assert canonicalize_session_key_for_agent("ops", "work") == "agent:ops:work"
        assert canonicalize_session_key_for_agent("ops", "global") == "global"
        assert canonicalize_session_key_for_agent("ops", "unknown") == "unknown"
        assert (
            canonicalize_session_key_for_agent("ops", "agent:myagent:foo")
            == "agent:myagent:foo"
        )

    def test_resolve_session_store_key(self) -> None:
        assert resolve_session_store_key("global") == "global"
        assert resolve_session_store_key("unknown") == "unknown"
        assert resolve_session_store_key("main") == "agent:default:work"
        assert resolve_session_store_key("agent:ops:foo") == "agent:ops:foo"
        assert resolve_session_store_key("custom-key") == "agent:default:custom-key"

    def test_resolve_session_store_agent_id(self) -> None:
        assert resolve_session_store_agent_id("global") == "default"
        assert resolve_session_store_agent_id("agent:ops:work") == "ops"
        assert resolve_session_store_agent_id("simple") == "default"


class TestSessionKeyClassification:
    """Tests de clasificación de claves de sesión."""

    def test_classify_global(self) -> None:
        assert classify_session_key("global") == SessionKind.GLOBAL

    def test_classify_unknown(self) -> None:
        assert classify_session_key("unknown") == SessionKind.UNKNOWN

    def test_classify_group_by_entry(self) -> None:
        entry = SessionEntry(chat_type="group")
        assert classify_session_key("some-key", entry) == SessionKind.GROUP

    def test_classify_group_by_key(self) -> None:
        assert classify_session_key("telegram:group:123") == SessionKind.GROUP
        assert classify_session_key("slack:channel:general") == SessionKind.GROUP

    def test_classify_direct(self) -> None:
        assert classify_session_key("agent:ops:work") == SessionKind.DIRECT

    def test_parse_group_key(self) -> None:
        result = parse_group_key("telegram:group:12345")
        assert result is not None
        assert result["channel"] == "telegram"
        assert result["kind"] == "group"
        assert result["id"] == "12345"

    def test_parse_group_key_with_agent_prefix(self) -> None:
        result = parse_group_key("agent:ops:telegram:group:12345")
        assert result is not None
        assert result["channel"] == "telegram"

    def test_parse_group_key_not_group(self) -> None:
        assert parse_group_key("agent:ops:work") is None
        assert parse_group_key("simple") is None


class TestSessionTitleDerivation:
    """Tests de derivación de títulos de sesión."""

    def test_derive_from_display_name(self) -> None:
        entry = SessionEntry(display_name="Mi sesión de trabajo")
        assert derive_session_title(entry) == "Mi sesión de trabajo"

    def test_derive_from_subject(self) -> None:
        entry = SessionEntry(subject="Bug en producción")
        assert derive_session_title(entry) == "Bug en producción"

    def test_derive_from_first_message(self) -> None:
        entry = SessionEntry(session_id="abc123")
        title = derive_session_title(entry, "Hola, necesito ayuda con el deploy")
        assert title == "Hola, necesito ayuda con el deploy"

    def test_derive_from_session_id(self) -> None:
        entry = SessionEntry(session_id="abc12345678")
        title = derive_session_title(entry)
        assert title is not None
        assert "abc12345" in title

    def test_derive_none_entry(self) -> None:
        assert derive_session_title(None) is None

    def test_truncate_title_short(self) -> None:
        assert truncate_title("Hola", 60) == "Hola"

    def test_truncate_title_long(self) -> None:
        long_text = "Esta es una oración muy larga que debería ser truncada en algún punto"
        result = truncate_title(long_text, 30)
        assert len(result) <= 30
        assert result.endswith("\u2026")

    def test_format_session_id_prefix(self) -> None:
        prefix = format_session_id_prefix("abc12345678")
        assert prefix == "abc12345"

    def test_format_session_id_prefix_with_date(self) -> None:
        prefix = format_session_id_prefix("abc12345678", 1700000000.0)
        assert "abc12345" in prefix
        assert "(" in prefix


# ═══════════════════════════════════════════════════════════════
# Session Utils — Store operations
# ═══════════════════════════════════════════════════════════════


class TestStoreOperations:
    """Tests de operaciones de store de sesiones."""

    def test_find_store_match_exact(self) -> None:
        store = {
            "agent:ops:work": SessionEntry(session_id="s1"),
            "agent:ops:test": SessionEntry(session_id="s2"),
        }
        result = find_store_match(store, "agent:ops:work")
        assert result is not None
        assert result[0] == "agent:ops:work"
        assert result[1].session_id == "s1"

    def test_find_store_match_case_insensitive(self) -> None:
        store = {
            "Agent:Ops:Work": SessionEntry(session_id="s1"),
        }
        result = find_store_match(store, "agent:ops:work")
        assert result is not None
        assert result[0] == "Agent:Ops:Work"

    def test_find_store_match_not_found(self) -> None:
        store = {"agent:ops:work": SessionEntry(session_id="s1")}
        result = find_store_match(store, "agent:ops:other")
        assert result is None

    def test_find_store_keys_ignore_case(self) -> None:
        store = {"Agent:Ops:WORK": None, "AGENT:OPS:WORK": None, "other": None}
        keys = find_store_keys_ignore_case(store, "agent:ops:work")
        assert len(keys) == 2
        assert "other" not in keys

    def test_prune_legacy_store_keys(self) -> None:
        store = {
            "agent:ops:work": {"data": 1},
            "Agent:Ops:Work": {"data": 2},
            "AGENT:OPS:WORK": {"data": 3},
        }
        prune_legacy_store_keys(
            store,
            "agent:ops:work",
            ["Agent:Ops:Work", "AGENT:OPS:WORK"],
        )
        assert "agent:ops:work" in store
        assert "Agent:Ops:Work" not in store
        assert "AGENT:OPS:WORK" not in store


class TestBuildGatewaySessionRow:
    """Tests de construcción de GatewaySessionRow."""

    def test_basic_row(self) -> None:
        entry = SessionEntry(
            session_id="abc123",
            label="test",
            model="claude-sonnet-4-5-20250929",
            model_provider="anthropic",
            updated_at=1700000000.0,
        )
        row = build_gateway_session_row("agent:ops:work", entry)
        assert row.key == "agent:ops:work"
        assert row.label == "test"
        assert row.model == "claude-sonnet-4-5-20250929"
        assert row.kind == SessionKind.DIRECT
        assert row.session_id == "abc123"

    def test_row_without_entry(self) -> None:
        row = build_gateway_session_row("global")
        assert row.key == "global"
        assert row.kind == SessionKind.GLOBAL
        assert row.session_id is None

    def test_row_with_derived_title(self) -> None:
        entry = SessionEntry(
            session_id="abc123",
            display_name="Test session",
        )
        row = build_gateway_session_row(
            "agent:ops:work",
            entry,
            include_derived_titles=True,
        )
        assert row.derived_title == "Test session"


class TestListSessionsFromStore:
    """Tests de listado de sesiones."""

    def test_list_basic(self) -> None:
        store = {
            "agent:ops:work": SessionEntry(
                session_id="s1", updated_at=1000.0
            ),
            "agent:ops:test": SessionEntry(
                session_id="s2", updated_at=2000.0
            ),
        }
        result = list_sessions_from_store(store)
        assert result.count == 2
        # Ordenado por updated_at desc
        assert result.sessions[0].session_id == "s2"

    def test_list_with_limit(self) -> None:
        store = {
            f"agent:ops:s{i}": SessionEntry(
                session_id=f"s{i}", updated_at=float(i)
            )
            for i in range(10)
        }
        result = list_sessions_from_store(store, limit=3)
        assert result.count == 3

    def test_list_exclude_global(self) -> None:
        store = {
            "global": SessionEntry(session_id="g"),
            "agent:ops:work": SessionEntry(session_id="s1"),
        }
        result = list_sessions_from_store(store, include_global=False)
        assert result.count == 1
        assert result.sessions[0].key != "global"

    def test_list_with_search(self) -> None:
        store = {
            "agent:ops:deploy": SessionEntry(
                session_id="s1", label="deploy-fix"
            ),
            "agent:ops:chat": SessionEntry(
                session_id="s2", label="general-chat"
            ),
        }
        result = list_sessions_from_store(store, search="deploy")
        assert result.count == 1
        assert result.sessions[0].label == "deploy-fix"

    def test_list_by_agent_id(self) -> None:
        store = {
            "agent:ops:work": SessionEntry(session_id="s1"),
            "agent:dev:work": SessionEntry(session_id="s2"),
        }
        result = list_sessions_from_store(store, agent_id="ops")
        assert result.count == 1
        assert result.sessions[0].key == "agent:ops:work"


# ═══════════════════════════════════════════════════════════════
# Session Utils — ConnectionSessionMap
# ═══════════════════════════════════════════════════════════════


class TestConnectionSessionMap:
    """Tests del mapa de conexiones a sesiones."""

    def test_bind_and_get(self) -> None:
        csm = ConnectionSessionMap()
        csm.bind("conn1", "agent:ops:work")
        assert "agent:ops:work" in csm.get_sessions("conn1")
        assert "conn1" in csm.get_connections("agent:ops:work")

    def test_unbind(self) -> None:
        csm = ConnectionSessionMap()
        csm.bind("conn1", "agent:ops:work")
        csm.unbind("conn1", "agent:ops:work")
        assert csm.get_sessions("conn1") == []
        assert csm.get_connections("agent:ops:work") == []

    def test_unbind_connection(self) -> None:
        csm = ConnectionSessionMap()
        csm.bind("conn1", "s1")
        csm.bind("conn1", "s2")
        sessions = csm.unbind_connection("conn1")
        assert set(sessions) == {"s1", "s2"}
        assert csm.connection_count == 0

    def test_multiple_connections_per_session(self) -> None:
        csm = ConnectionSessionMap()
        csm.bind("conn1", "s1")
        csm.bind("conn2", "s1")
        assert csm.has_connections("s1")
        conns = csm.get_connections("s1")
        assert set(conns) == {"conn1", "conn2"}

    def test_metadata(self) -> None:
        csm = ConnectionSessionMap()
        csm.set_metadata("conn1", {"user": "alice"})
        meta = csm.get_metadata("conn1")
        assert meta["user"] == "alice"

    def test_cleanup_stale(self) -> None:
        csm = ConnectionSessionMap()
        csm.bind("conn1", "s1")
        csm.bind("conn2", "s2")
        stale = csm.cleanup_stale({"conn1"})  # conn2 is stale
        assert "conn2" in stale
        assert csm.connection_count == 1

    def test_counts(self) -> None:
        csm = ConnectionSessionMap()
        csm.bind("c1", "s1")
        csm.bind("c2", "s2")
        csm.bind("c2", "s1")
        assert csm.connection_count == 2
        assert csm.session_count == 2


# ═══════════════════════════════════════════════════════════════
# Session Utils — Validación
# ═══════════════════════════════════════════════════════════════


class TestSessionValidation:
    """Tests de validación de sesiones."""

    def test_valid_key(self) -> None:
        assert validate_session_key("agent:ops:work") is None
        assert validate_session_key("global") is None
        assert validate_session_key("telegram:group:12345") is None

    def test_empty_key(self) -> None:
        result = validate_session_key("")
        assert result is not None
        assert "vacía" in result

    def test_long_key(self) -> None:
        result = validate_session_key("a" * 257)
        assert result is not None
        assert "256" in result

    def test_invalid_chars(self) -> None:
        result = validate_session_key("agent ops work")
        assert result is not None
        assert "inválidos" in result


# ═══════════════════════════════════════════════════════════════
# Session Utils — Archivos JSONL (compatibilidad)
# ═══════════════════════════════════════════════════════════════


class TestSessionFiles:
    """Tests de utilidades de archivo de sesión."""

    def test_append_and_read(self, tmp_path) -> None:
        append_to_session("s1", {"type": "msg", "text": "hello"}, tmp_path)
        append_to_session("s1", {"type": "msg", "text": "world"}, tmp_path)
        events = read_session("s1", tmp_path)
        assert len(events) == 2
        assert events[0]["text"] == "hello"
        assert events[1]["text"] == "world"

    def test_session_exists(self, tmp_path) -> None:
        assert not session_exists("nope", tmp_path)
        append_to_session("exists", {"data": 1}, tmp_path)
        assert session_exists("exists", tmp_path)

    def test_delete_session(self, tmp_path) -> None:
        append_to_session("delete-me", {"data": 1}, tmp_path)
        assert delete_session("delete-me", tmp_path)
        assert not session_exists("delete-me", tmp_path)

    def test_delete_nonexistent(self, tmp_path) -> None:
        assert not delete_session("nope", tmp_path)

    def test_read_empty(self, tmp_path) -> None:
        events = read_session("empty", tmp_path)
        assert events == []


class TestSessionStore:
    """Tests de SessionStore (store basado en índice JSON)."""

    def test_set_and_get(self, tmp_path) -> None:
        store = SessionStore(tmp_path)
        entry = SessionEntry(session_id="s1", label="test")
        store.set("agent:ops:work", entry)
        retrieved = store.get("agent:ops:work")
        assert retrieved is not None
        assert retrieved.session_id == "s1"

    def test_delete(self, tmp_path) -> None:
        store = SessionStore(tmp_path)
        store.set("key", SessionEntry(session_id="s1"))
        assert store.delete("key")
        assert store.get("key") is None

    def test_keys(self, tmp_path) -> None:
        store = SessionStore(tmp_path)
        store.set("k1", SessionEntry(session_id="s1"))
        store.set("k2", SessionEntry(session_id="s2"))
        assert set(store.keys()) == {"k1", "k2"}

    def test_save_and_reload(self, tmp_path) -> None:
        store = SessionStore(tmp_path)
        store.set("k1", SessionEntry(session_id="s1", label="test"))
        store.save()

        store2 = SessionStore(tmp_path)
        store2.load()
        entry = store2.get("k1")
        assert entry is not None
        assert entry.session_id == "s1"
        assert entry.label == "test"
