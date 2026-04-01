"""Webhook receiver — servidor HTTP para triggers externos."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple

from shared.errors import SomerError

logger = logging.getLogger(__name__)

# Type alias para callbacks de webhook
WebhookCallback = Callable[[Dict[str, Any]], Coroutine[Any, Any, Dict[str, Any]]]


class WebhookError(SomerError):
    """Error en el sistema de webhooks."""


@dataclass
class WebhookHandler:
    """Handler registrado para un path específico."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    path: str = "/"
    description: str = ""
    callback: Optional[WebhookCallback] = None
    secret: Optional[str] = None
    call_count: int = 0
    enabled: bool = True


class WebhookServer:
    """Servidor HTTP ligero para recibir webhooks.

    Usa ``asyncio.start_server`` para evitar dependencias externas.
    Soporta solo POST con body JSON.

    Uso::

        server = WebhookServer()
        server.register("/github", on_github_event, "GitHub webhooks")
        await server.start("0.0.0.0", 8080)
        # ... el servidor corre en background ...
        await server.stop()
    """

    def __init__(self) -> None:
        self._handlers: Dict[str, WebhookHandler] = {}
        self._server: Optional[asyncio.AbstractServer] = None
        self._host: str = "127.0.0.1"
        self._port: int = 9090

    # ── Registro ────────────────────────────────────────────

    def register(
        self,
        path: str,
        callback: WebhookCallback,
        description: str = "",
        *,
        secret: Optional[str] = None,
        handler_id: Optional[str] = None,
    ) -> str:
        """Registra un handler para un path. Retorna el ID del handler."""
        # Normalizar path
        if not path.startswith("/"):
            path = "/" + path

        if path in self._handlers:
            raise WebhookError(f"Ya existe un handler para '{path}'")

        handler = WebhookHandler(
            id=handler_id or uuid.uuid4().hex[:12],
            path=path,
            description=description,
            callback=callback,
            secret=secret,
        )
        self._handlers[path] = handler
        logger.info("Webhook registrado: %s -> '%s'", path, description)
        return handler.id

    def unregister(self, path: str) -> bool:
        """Desregistra un handler. Retorna True si existía."""
        if not path.startswith("/"):
            path = "/" + path
        removed = self._handlers.pop(path, None)
        if removed:
            logger.info("Webhook desregistrado: %s", path)
        return removed is not None

    def list_handlers(self) -> List[WebhookHandler]:
        """Lista todos los handlers registrados."""
        return list(self._handlers.values())

    # ── Servidor ────────────────────────────────────────────

    async def start(self, host: str = "127.0.0.1", port: int = 9090) -> None:
        """Inicia el servidor HTTP."""
        if self._server is not None:
            logger.warning("Servidor de webhooks ya está corriendo")
            return

        self._host = host
        self._port = port
        self._server = await asyncio.start_server(
            self._handle_connection, host, port
        )
        logger.info("WebhookServer escuchando en %s:%d", host, port)

    async def stop(self) -> None:
        """Detiene el servidor."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            logger.info("WebhookServer detenido")

    @property
    def is_running(self) -> bool:
        return self._server is not None

    # ── HTTP handling ───────────────────────────────────────

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Procesa una conexión HTTP entrante."""
        try:
            method, path, headers, body = await self._parse_request(reader)

            if method != "POST":
                await self._send_response(writer, 405, {"error": "Method not allowed"})
                return

            handler = self._handlers.get(path)
            if handler is None or not handler.enabled:
                await self._send_response(writer, 404, {"error": "Not found"})
                return

            # Parsear body JSON
            try:
                payload = json.loads(body) if body else {}
            except json.JSONDecodeError:
                await self._send_response(writer, 400, {"error": "Invalid JSON"})
                return

            # Ejecutar callback
            handler.call_count += 1
            if handler.callback is not None:
                try:
                    result = await handler.callback(payload)
                    await self._send_response(writer, 200, result or {"ok": True})
                except Exception:
                    logger.exception("Error en webhook handler '%s'", path)
                    await self._send_response(
                        writer, 500, {"error": "Internal handler error"}
                    )
            else:
                await self._send_response(writer, 200, {"ok": True})

        except Exception:
            logger.exception("Error procesando request de webhook")
            try:
                await self._send_response(writer, 500, {"error": "Server error"})
            except Exception:
                pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _parse_request(
        self, reader: asyncio.StreamReader
    ) -> Tuple[str, str, Dict[str, str], str]:
        """Parsea un request HTTP simple. Retorna (method, path, headers, body)."""
        # Leer request line
        request_line = await reader.readline()
        parts = request_line.decode("utf-8", errors="replace").strip().split(" ")
        method = parts[0] if len(parts) >= 1 else ""
        path = parts[1] if len(parts) >= 2 else "/"

        # Strip query string
        if "?" in path:
            path = path.split("?", 1)[0]

        # Leer headers
        headers: Dict[str, str] = {}
        while True:
            line = await reader.readline()
            decoded = line.decode("utf-8", errors="replace").strip()
            if not decoded:
                break
            if ":" in decoded:
                key, val = decoded.split(":", 1)
                headers[key.strip().lower()] = val.strip()

        # Leer body si hay Content-Length
        body = ""
        content_length = int(headers.get("content-length", "0"))
        if content_length > 0:
            raw = await reader.readexactly(content_length)
            body = raw.decode("utf-8", errors="replace")

        return method, path, headers, body

    @staticmethod
    async def _send_response(
        writer: asyncio.StreamWriter,
        status: int,
        data: Dict[str, Any],
    ) -> None:
        """Envía una respuesta HTTP JSON."""
        status_text = {200: "OK", 400: "Bad Request", 404: "Not Found",
                       405: "Method Not Allowed", 500: "Internal Server Error"}
        body = json.dumps(data)
        response = (
            f"HTTP/1.1 {status} {status_text.get(status, 'Error')}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
            f"{body}"
        )
        writer.write(response.encode("utf-8"))
        await writer.drain()
