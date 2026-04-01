"""Plugin de canal Matrix."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from channels.plugin import ChannelPlugin
from shared.errors import ChannelError, ChannelSetupError
from shared.types import (
    ChannelCapabilities,
    ChannelMeta,
    ChannelType,
    IncomingMessage,
)

logger = logging.getLogger(__name__)


class MatrixPlugin(ChannelPlugin):
    """Plugin para Matrix usando matrix-nio."""

    def __init__(self) -> None:
        super().__init__(
            plugin_id="matrix",
            meta=ChannelMeta(
                id="matrix",
                name="Matrix",
                version="1.0.0",
                description="Matrix protocol channel plugin via matrix-nio",
            ),
            capabilities=ChannelCapabilities(
                supports_threads=True,
                supports_reactions=True,
                supports_media=True,
                supports_editing=True,
                supports_deletion=True,
                max_message_length=65536,
            ),
        )
        self._client: Any = None
        self._homeserver: Optional[str] = None
        self._user_id: Optional[str] = None
        self._access_token: Optional[str] = None

    async def setup(self, config: Dict[str, Any]) -> None:
        import os

        hs_env = config.get("homeserver_env", "MATRIX_HOMESERVER")
        self._homeserver = config.get("homeserver") or os.environ.get(hs_env)
        if not self._homeserver:
            raise ChannelSetupError(
                f"Homeserver de Matrix no encontrado. Configura {hs_env}"
            )
        user_env = config.get("user_id_env", "MATRIX_USER_ID")
        self._user_id = config.get("user_id") or os.environ.get(user_env)
        if not self._user_id:
            raise ChannelSetupError(
                f"User ID de Matrix no encontrado. Configura {user_env}"
            )
        token_env = config.get("token_env", "MATRIX_ACCESS_TOKEN")
        self._access_token = config.get("access_token") or os.environ.get(token_env)
        if not self._access_token:
            raise ChannelSetupError(
                f"Access token de Matrix no encontrado. Configura {token_env}"
            )

    async def start(self) -> None:
        if not self._homeserver:
            raise ChannelSetupError("Ejecuta setup() primero")
        try:
            from nio import AsyncClient, MatrixRoom, RoomMessageText

            self._client = AsyncClient(self._homeserver, self._user_id)
            self._client.access_token = self._access_token

            async def message_callback(
                room: MatrixRoom, event: RoomMessageText
            ) -> None:
                if event.sender == self._user_id:
                    return
                msg = IncomingMessage(
                    channel=ChannelType.MATRIX,
                    channel_user_id=event.sender,
                    channel_thread_id=room.room_id,
                    content=event.body,
                    metadata={
                        "room_id": room.room_id,
                        "room_name": room.display_name,
                        "event_id": event.event_id,
                    },
                )
                await self._dispatch_message(msg)

            self._client.add_event_callback(message_callback, RoomMessageText)
            self._running = True
            logger.info("Matrix plugin iniciado")
        except ImportError:
            raise ChannelError(
                "matrix-nio no instalado. Ejecuta: pip install matrix-nio"
            )

    async def stop(self) -> None:
        if self._client:
            await self._client.close()
        self._running = False
        logger.info("Matrix plugin detenido")

    async def send_message(
        self,
        target: str,
        content: str,
        media: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> None:
        if not self._client:
            raise ChannelError("Matrix no esta iniciado")
        try:
            from nio import RoomSendResponse

            resp = await self._client.room_send(
                room_id=target,
                message_type="m.room.message",
                content={
                    "msgtype": "m.text",
                    "body": content,
                    "format": "org.matrix.custom.html",
                    "formatted_body": content,
                },
            )
            if not isinstance(resp, RoomSendResponse):
                raise ChannelError(f"Error Matrix room_send: {resp}")
        except ImportError:
            raise ChannelError("matrix-nio no instalado")
        except ChannelError:
            raise
        except Exception as exc:
            raise ChannelError(f"Error enviando mensaje Matrix: {exc}") from exc
