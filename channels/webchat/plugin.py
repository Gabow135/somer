"""Plugin de canal WebChat."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set

from channels.plugin import ChannelPlugin
from shared.errors import ChannelError, ChannelSetupError
from shared.types import (
    ChannelCapabilities,
    ChannelMeta,
    ChannelType,
    IncomingMessage,
)

logger = logging.getLogger(__name__)


class WebChatPlugin(ChannelPlugin):
    """Plugin para WebChat embebido usando websockets built-in."""

    def __init__(self) -> None:
        super().__init__(
            plugin_id="webchat",
            meta=ChannelMeta(
                id="webchat",
                name="WebChat",
                version="1.0.0",
                description="Embedded WebChat channel plugin via WebSockets",
            ),
            capabilities=ChannelCapabilities(
                supports_threads=True,
                supports_reactions=True,
                supports_media=True,
                supports_editing=True,
                supports_deletion=True,
                max_message_length=100000,
            ),
        )
        self._server: Any = None
        self._host: str = "0.0.0.0"
        self._port: int = 8765
        self._api_key: Optional[str] = None
        self._connections: Dict[str, Any] = {}
        self._allowed_origins: Set[str] = set()

    async def setup(self, config: Dict[str, Any]) -> None:
        import os

        self._host = config.get("host") or os.environ.get(
            "WEBCHAT_HOST", "0.0.0.0"
        )
        self._port = int(
            config.get("port") or os.environ.get("WEBCHAT_PORT", "8765")
        )
        key_env = config.get("api_key_env", "WEBCHAT_API_KEY")
        self._api_key = config.get("api_key") or os.environ.get(key_env)
        origins_env = config.get("allowed_origins_env", "WEBCHAT_ALLOWED_ORIGINS")
        raw_origins = config.get("allowed_origins") or os.environ.get(
            origins_env, "*"
        )
        if isinstance(raw_origins, str):
            self._allowed_origins = {
                o.strip() for o in raw_origins.split(",") if o.strip()
            }
        else:
            self._allowed_origins = set(raw_origins)

    async def start(self) -> None:
        try:
            import websockets

            async def handler(websocket: Any, path: str = "/") -> None:
                connection_id: Optional[str] = None
                try:
                    import json

                    async for raw_message in websocket:
                        data = json.loads(raw_message)
                        msg_type = data.get("type", "message")

                        if msg_type == "auth":
                            # Autenticacion opcional con API key
                            if self._api_key and data.get("api_key") != self._api_key:
                                await websocket.send(
                                    json.dumps({
                                        "type": "error",
                                        "message": "API key invalida",
                                    })
                                )
                                await websocket.close()
                                return
                            connection_id = data.get("user_id", websocket.id.hex)
                            self._connections[connection_id] = websocket
                            await websocket.send(
                                json.dumps({
                                    "type": "auth_ok",
                                    "connection_id": connection_id,
                                })
                            )
                            continue

                        if msg_type == "message":
                            user_id = data.get(
                                "user_id",
                                connection_id or websocket.id.hex,
                            )
                            msg = IncomingMessage(
                                channel=ChannelType.WEBCHAT,
                                channel_user_id=user_id,
                                channel_thread_id=data.get("thread_id"),
                                content=data.get("content", ""),
                                metadata={
                                    "connection_id": connection_id or "",
                                    "message_id": data.get("message_id", ""),
                                    "origin": data.get("origin", ""),
                                },
                            )
                            await self._dispatch_message(msg)
                except Exception:
                    logger.exception("Error en conexion WebChat")
                finally:
                    if connection_id and connection_id in self._connections:
                        del self._connections[connection_id]

            self._server = await websockets.serve(
                handler,
                self._host,
                self._port,
            )
            self._running = True
            logger.info(
                "WebChat plugin iniciado en ws://%s:%d",
                self._host,
                self._port,
            )
        except ImportError:
            raise ChannelError(
                "websockets no instalado. Ejecuta: pip install websockets"
            )

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        self._connections.clear()
        self._running = False
        logger.info("WebChat plugin detenido")

    async def send_message(
        self,
        target: str,
        content: str,
        media: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> None:
        if not self._running:
            raise ChannelError("WebChat no esta iniciado")
        try:
            import json

            ws = self._connections.get(target)
            if not ws:
                raise ChannelError(
                    f"Conexion WebChat '{target}' no encontrada"
                )
            payload: Dict[str, Any] = {
                "type": "message",
                "content": content,
            }
            if media:
                payload["media"] = media
            await ws.send(json.dumps(payload))
        except ChannelError:
            raise
        except Exception as exc:
            raise ChannelError(
                f"Error enviando mensaje WebChat: {exc}"
            ) from exc

    async def broadcast(
        self,
        content: str,
        exclude: Optional[List[str]] = None,
    ) -> None:
        """Envia un mensaje a todas las conexiones activas."""
        import json

        exclude_set = set(exclude or [])
        payload = json.dumps({"type": "message", "content": content})
        for conn_id, ws in list(self._connections.items()):
            if conn_id in exclude_set:
                continue
            try:
                await ws.send(payload)
            except Exception:
                logger.warning("Error enviando broadcast a %s", conn_id)
