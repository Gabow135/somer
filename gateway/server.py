"""Gateway WebSocket Server — control plane de SOMER 2.0.

Portado de OpenClaw: server.impl.ts + server-ws-runtime.ts.
Implementa tanto JSON-RPC 2.0 clásico (compatibilidad) como
el protocolo de frames OpenClaw (req/res/event).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set

from gateway.protocol import (
    BASE_METHODS,
    GATEWAY_EVENTS,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    PROTOCOL_VERSION,
    ConnectParams,
    ErrorCode,
    EventFrame,
    GatewayEvent,
    GatewayFrame,
    HelloOk,
    JsonRpcBatchResponse,
    JsonRpcRequest,
    JsonRpcResponse,
    MethodHandler,
    MethodRegistry,
    RequestFrame,
    ResponseFrame,
    StateVersion,
    TickEvent,
    error_shape,
    is_batch_request,
    parse_gateway_frame,
)
from gateway.session_utils import ConnectionSessionMap
from shared.constants import GATEWAY_HOST, GATEWAY_PORT, VERSION
from shared.errors import GatewayError, GatewayMethodNotFoundError

logger = logging.getLogger(__name__)


class GatewayServer:
    """WebSocket server que actúa como control plane.

    Expone una API JSON-RPC 2.0 sobre WebSocket.
    Soporta pub/sub para notificaciones a clientes.
    Soporta tanto el formato JSON-RPC clásico como el frame protocol de OpenClaw.
    """

    def __init__(
        self,
        host: str = GATEWAY_HOST,
        port: int = GATEWAY_PORT,
        ping_interval: float = 30.0,
        ping_timeout: float = 10.0,
        max_payload_bytes: int = 1_048_576,
        tick_interval_secs: float = 30.0,
    ):
        self.host = host
        self.port = port
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self.max_payload_bytes = max_payload_bytes
        self.tick_interval_secs = tick_interval_secs

        # Registro de métodos
        self._registry = MethodRegistry()

        # Estado de conexiones
        self._clients: Set[Any] = set()
        self._client_ids: Dict[Any, str] = {}  # websocket → conn_id
        self._subscriptions: Dict[str, Set[Any]] = {}  # event_type → clients
        self._session_map = ConnectionSessionMap()

        # Estado del servidor
        self._server: Optional[Any] = None
        self._started = False
        self._start_time: Optional[float] = None
        self._tick_task: Optional[asyncio.Task[None]] = None
        self._event_seq = 0

        # Report manager para descargas HTTP
        self._report_manager: Any = None

        # Versiones de estado (OpenClaw pattern)
        self._health_version = 0
        self._presence_version = 0
        self._sessions_version = 0

    # ── Registro de métodos ──────────────────────────────────

    def register_method(
        self,
        name: str,
        handler: MethodHandler,
        *,
        description: Optional[str] = None,
        auth_required: bool = False,
    ) -> None:
        """Registra un método RPC."""
        self._registry.register(
            name,
            handler,
            description=description,
            auth_required=auth_required,
        )
        logger.debug("Método registrado: %s", name)

    def unregister_method(self, name: str) -> None:
        """Desregistra un método RPC."""
        self._registry.unregister(name)

    @property
    def method_names(self) -> List[str]:
        """Lista de métodos registrados."""
        return self._registry.names

    @property
    def method_registry(self) -> MethodRegistry:
        """Acceso al registro de métodos."""
        return self._registry

    @property
    def client_count(self) -> int:
        """Número de clientes conectados."""
        return len(self._clients)

    @property
    def session_map(self) -> ConnectionSessionMap:
        """Mapa de conexiones a sesiones."""
        return self._session_map

    @property
    def state_version(self) -> StateVersion:
        """Versión actual del estado del gateway."""
        return StateVersion(
            health=self._health_version,
            presence=self._presence_version,
            sessions=self._sessions_version,
        )

    # ── Lifecycle ────────────────────────────────────────────

    async def start(self) -> None:
        """Inicia el servidor WebSocket."""
        try:
            import websockets  # type: ignore[import-untyped]
        except ImportError:
            raise GatewayError(
                "websockets no instalado. Ejecuta: pip install websockets"
            )

        # Suprimir errores de handshake inválidos (health checks, port scanners, etc.)
        # websockets 15 los loguea a ERROR en "websockets.server", no podemos
        # bajar el nivel sin perder errores reales → usamos un filtro
        class _HandshakeFilter(logging.Filter):
            def filter(self, record: logging.LogRecord) -> bool:
                msg = record.getMessage()
                return "opening handshake failed" not in msg

        for name in ("websockets", "websockets.server"):
            lg = logging.getLogger(name)
            lg.addFilter(_HandshakeFilter())

        self._server = await websockets.serve(
            self._handle_client,
            self.host,
            self.port,
            ping_interval=self.ping_interval,
            ping_timeout=self.ping_timeout,
            max_size=self.max_payload_bytes,
            process_request=self._process_http_request,
        )
        self._started = True
        self._start_time = time.monotonic()

        # Iniciar tick periódico
        if self.tick_interval_secs > 0:
            self._tick_task = asyncio.create_task(self._tick_loop())

        logger.info("Gateway iniciado en ws://%s:%d", self.host, self.port)

    def set_report_manager(self, manager: Any) -> None:
        """Establece el ReportManager para servir descargas HTTP."""
        self._report_manager = manager

    async def _process_http_request(
        self, connection: Any, request: Any
    ) -> Any:
        """Intercepta requests HTTP antes del handshake WebSocket.

        Compatible con websockets >= 13 (recibe connection, request).
        Responde con HTTP 200 para health checks (/health, /).
        Sirve archivos de reportes en /reports/{token}/{filename}.
        Retorna None para proceder con el upgrade a WebSocket.
        """
        from websockets.datastructures import Headers as WsHeaders
        from websockets.http11 import Response

        path = request.path

        if path == "/health" or path == "/healthz":
            return Response(200, "OK", WsHeaders(), b"OK\n")

        # Descargas de reportes: /reports/{token}/{filename}
        if path.startswith("/reports/") and self._report_manager:
            parts = path.split("/")
            # /reports/token/filename → ["", "reports", "token", "filename"]
            if len(parts) >= 3:
                token = parts[2]
                resolved = self._report_manager.resolve_download(token)
                if resolved and resolved.exists():
                    import mimetypes as _mt
                    mime = _mt.guess_type(str(resolved))[0] or "application/octet-stream"
                    filename = resolved.name
                    file_bytes = resolved.read_bytes()
                    return Response(
                        200, "OK",
                        WsHeaders([
                            ("Content-Type", mime),
                            ("Content-Disposition", f'attachment; filename="{filename}"'),
                            ("Content-Length", str(len(file_bytes))),
                        ]),
                        file_bytes,
                    )
                return Response(404, "Not Found", WsHeaders(), b"Not found\n")

        # Todas las demás rutas: proceder con WebSocket handshake
        return None

    async def stop(self, reason: str = "shutdown") -> None:
        """Detiene el servidor."""
        self._started = False

        # Enviar evento de shutdown a clientes
        await self.broadcast_event(
            "shutdown",
            {"reason": reason},
        )

        # Cancelar tick
        if self._tick_task and not self._tick_task.done():
            self._tick_task.cancel()
            try:
                await self._tick_task
            except asyncio.CancelledError:
                pass
            self._tick_task = None

        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        self._clients.clear()
        self._client_ids.clear()
        self._subscriptions.clear()
        logger.info("Gateway detenido: %s", reason)

    # ── Broadcast ────────────────────────────────────────────

    async def broadcast(self, event: GatewayEvent) -> int:
        """Envía un GatewayEvent a clientes suscritos (compatibilidad).

        Returns:
            Número de clientes que recibieron el evento.
        """
        data = event.model_dump_json()
        subscribers = self._subscriptions.get(event.type, set())
        targets = subscribers or self._clients
        sent = 0
        for client in list(targets):
            try:
                await client.send(data)
                sent += 1
            except Exception:
                self._remove_client(client)
        return sent

    async def broadcast_event(
        self,
        event_name: str,
        payload: Optional[Any] = None,
        *,
        state_version: Optional[StateVersion] = None,
    ) -> int:
        """Envía un EventFrame a clientes suscritos (frame protocol).

        Returns:
            Número de clientes que recibieron el evento.
        """
        self._event_seq += 1
        frame = EventFrame(
            event=event_name,
            payload=payload,
            seq=self._event_seq,
            state_version=state_version or self.state_version,
        )
        data = frame.model_dump_json()
        subscribers = self._subscriptions.get(event_name, set())
        targets = subscribers or self._clients
        sent = 0
        for client in list(targets):
            try:
                await client.send(data)
                sent += 1
            except Exception:
                self._remove_client(client)
        return sent

    async def send_to_connection(
        self, conn_id: str, data: str
    ) -> bool:
        """Envía datos a una conexión específica por su ID."""
        for ws, cid in self._client_ids.items():
            if cid == conn_id:
                try:
                    await ws.send(data)
                    return True
                except Exception:
                    self._remove_client(ws)
                    return False
        return False

    # ── Versiones de estado ──────────────────────────────────

    def increment_health_version(self) -> int:
        """Incrementa la versión de health."""
        self._health_version += 1
        return self._health_version

    def increment_presence_version(self) -> int:
        """Incrementa la versión de presence."""
        self._presence_version += 1
        return self._presence_version

    def increment_sessions_version(self) -> int:
        """Incrementa la versión de sessions."""
        self._sessions_version += 1
        return self._sessions_version

    # ── Manejo de clientes ───────────────────────────────────

    async def _handle_client(
        self, websocket: Any, path: str = "/"
    ) -> None:
        """Maneja la conexión de un cliente WebSocket."""
        conn_id = uuid.uuid4().hex[:12]
        self._clients.add(websocket)
        self._client_ids[websocket] = conn_id
        logger.debug(
            "Cliente conectado: %s (%d total)", conn_id, len(self._clients)
        )
        try:
            async for raw_message in websocket:
                response = await self._process_message(
                    raw_message, websocket, conn_id
                )
                if response:
                    await websocket.send(response)
        except Exception as exc:
            logger.debug("Cliente desconectado: %s (%s)", conn_id, exc)
        finally:
            self._remove_client(websocket)
            logger.debug(
                "Cliente removido: %s (%d total)",
                conn_id,
                len(self._clients),
            )

    def _remove_client(self, websocket: Any) -> None:
        """Remueve un cliente y limpia sus suscripciones."""
        conn_id = self._client_ids.pop(websocket, None)
        self._clients.discard(websocket)
        for subs in self._subscriptions.values():
            subs.discard(websocket)
        if conn_id:
            sessions = self._session_map.unbind_connection(conn_id)
            if sessions:
                logger.debug(
                    "Conexión %s desvinculada de sesiones: %s",
                    conn_id,
                    sessions,
                )

    # ── Procesamiento de mensajes ────────────────────────────

    async def _process_message(
        self, raw: str, websocket: Any, conn_id: str = ""
    ) -> Optional[str]:
        """Procesa un mensaje entrante (JSON-RPC o frame protocol)."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return JsonRpcResponse.error_response(
                PARSE_ERROR, "Parse error"
            ).model_dump_json()

        # Detectar batch request
        if is_batch_request(data):
            return await self._process_batch(data, websocket, conn_id)

        # Detectar frame protocol (tiene campo "type")
        if isinstance(data, dict) and "type" in data:
            return await self._process_frame(data, websocket, conn_id)

        # JSON-RPC 2.0 clásico
        return await self._process_jsonrpc(data, websocket, conn_id)

    async def _process_frame(
        self, data: Dict[str, Any], websocket: Any, conn_id: str
    ) -> Optional[str]:
        """Procesa un frame del protocolo OpenClaw."""
        frame_type = data.get("type")

        if frame_type == "req":
            return await self._handle_request_frame(data, websocket, conn_id)
        elif frame_type == "res":
            # Los clientes no deberían enviar response frames
            logger.warning("Response frame inesperado de %s", conn_id)
            return None
        elif frame_type == "event":
            # Los clientes pueden enviar ciertos eventos
            return await self._handle_client_event(data, websocket, conn_id)
        else:
            return ResponseFrame.failure(
                data.get("id", "0"),
                ErrorCode.INVALID_REQUEST,
                f"Tipo de frame desconocido: {frame_type}",
            ).model_dump_json()

    async def _handle_request_frame(
        self, data: Dict[str, Any], websocket: Any, conn_id: str
    ) -> Optional[str]:
        """Procesa un RequestFrame."""
        try:
            frame = RequestFrame.model_validate(data)
        except Exception:
            return ResponseFrame.failure(
                data.get("id", "0"),
                ErrorCode.INVALID_REQUEST,
                "Frame de request inválido",
            ).model_dump_json()

        # Dispatch del método
        handler = self._registry.get(frame.method)
        if not handler:
            return ResponseFrame.failure(
                frame.id,
                ErrorCode.INVALID_REQUEST,
                f"Método no encontrado: {frame.method}",
            ).model_dump_json()

        try:
            params = frame.params if isinstance(frame.params, dict) else {}
            result = await handler(params)
            return ResponseFrame.success(frame.id, result).model_dump_json()
        except Exception as exc:
            logger.exception("Error en método %s", frame.method)
            return ResponseFrame.failure(
                frame.id,
                ErrorCode.UNAVAILABLE,
                str(exc),
            ).model_dump_json()

    async def _handle_client_event(
        self, data: Dict[str, Any], websocket: Any, conn_id: str
    ) -> Optional[str]:
        """Procesa un evento enviado por el cliente."""
        event_name = data.get("event", "")
        payload = data.get("payload")

        # Manejar eventos especiales del cliente
        if event_name == "system-presence":
            self._presence_version += 1
            logger.debug("Presence update de %s", conn_id)

        return None

    async def _process_jsonrpc(
        self, data: Dict[str, Any], websocket: Any, conn_id: str
    ) -> Optional[str]:
        """Procesa un mensaje JSON-RPC 2.0 clásico."""
        try:
            request = JsonRpcRequest.model_validate(data)
        except Exception:
            return JsonRpcResponse.error_response(
                INVALID_REQUEST,
                "Invalid request",
                req_id=data.get("id"),
            ).model_dump_json()

        # Handle subscribe/unsubscribe
        if request.method == "subscribe":
            event_type = (request.params or {}).get("event", "")
            if event_type:
                self._subscriptions.setdefault(
                    event_type, set()
                ).add(websocket)
            return JsonRpcResponse.success(
                {"subscribed": event_type}, request.id
            ).model_dump_json()

        if request.method == "unsubscribe":
            event_type = (request.params or {}).get("event", "")
            if event_type in self._subscriptions:
                self._subscriptions[event_type].discard(websocket)
            return JsonRpcResponse.success(
                {"unsubscribed": event_type}, request.id
            ).model_dump_json()

        # Dispatch method
        handler = self._registry.get(request.method)
        if not handler:
            return JsonRpcResponse.error_response(
                METHOD_NOT_FOUND,
                f"Method not found: {request.method}",
                req_id=request.id,
            ).model_dump_json()

        try:
            result = await handler(request.params or {})
            return JsonRpcResponse.success(result, request.id).model_dump_json()
        except Exception as exc:
            logger.exception("Error en método %s", request.method)
            return JsonRpcResponse.error_response(
                INTERNAL_ERROR,
                str(exc),
                req_id=request.id,
            ).model_dump_json()

    async def _process_batch(
        self, data: List[Any], websocket: Any, conn_id: str
    ) -> str:
        """Procesa un batch de requests JSON-RPC.

        Ejecuta todos los requests en paralelo y retorna un array de responses.
        """
        tasks = []
        for item in data:
            if isinstance(item, dict):
                tasks.append(
                    self._process_jsonrpc(item, websocket, conn_id)
                )
            else:
                tasks.append(
                    asyncio.coroutine(lambda: JsonRpcResponse.error_response(
                        INVALID_REQUEST, "Invalid batch item"
                    ).model_dump_json())()
                )

        results = await asyncio.gather(*tasks, return_exceptions=True)
        responses = []
        for r in results:
            if isinstance(r, str):
                responses.append(json.loads(r))
            elif isinstance(r, Exception):
                responses.append(
                    json.loads(
                        JsonRpcResponse.error_response(
                            INTERNAL_ERROR, str(r)
                        ).model_dump_json()
                    )
                )
        return json.dumps(responses)

    # ── Tick loop ────────────────────────────────────────────

    async def _tick_loop(self) -> None:
        """Loop de tick periódico — envía TickEvent a clientes."""
        while self._started:
            try:
                await asyncio.sleep(self.tick_interval_secs)
                if not self._started:
                    break
                tick = TickEvent()
                await self.broadcast_event("tick", {"ts": tick.ts})
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("Error en tick loop: %s", exc)

    # ── Hello handshake ──────────────────────────────────────

    def build_hello_ok(self, conn_id: str) -> HelloOk:
        """Construye un HelloOk para el handshake de conexión."""
        return HelloOk(
            protocol=PROTOCOL_VERSION,
            server={
                "version": VERSION,
                "connId": conn_id,
            },
            features={
                "methods": self.method_names,
                "events": list(GATEWAY_EVENTS),
            },
            policy={
                "max_payload": self.max_payload_bytes,
                "max_buffered_bytes": self.max_payload_bytes * 4,
                "tick_interval_ms": int(self.tick_interval_secs * 1000),
            },
        )

    # ── Status ───────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        """Retorna el estado del gateway."""
        uptime = 0.0
        if self._start_time:
            uptime = time.monotonic() - self._start_time
        return {
            "started": self._started,
            "host": self.host,
            "port": self.port,
            "clients": self.client_count,
            "methods": self.method_names,
            "uptime_secs": round(uptime, 1),
            "protocol_version": PROTOCOL_VERSION,
            "sessions_bound": self._session_map.session_count,
            "event_seq": self._event_seq,
            "state_version": {
                "health": self._health_version,
                "presence": self._presence_version,
                "sessions": self._sessions_version,
            },
        }
