"""Plugin de canal LINE."""

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


class LINEPlugin(ChannelPlugin):
    """Plugin para LINE Messaging API usando line-bot-sdk."""

    def __init__(self) -> None:
        super().__init__(
            plugin_id="line",
            meta=ChannelMeta(
                id="line",
                name="LINE",
                version="1.0.0",
                description="LINE Messaging API channel plugin via line-bot-sdk",
            ),
            capabilities=ChannelCapabilities(
                supports_threads=False,
                supports_reactions=True,
                supports_media=True,
                supports_editing=False,
                supports_deletion=False,
                max_message_length=5000,
            ),
        )
        self._api: Any = None
        self._channel_secret: Optional[str] = None
        self._channel_access_token: Optional[str] = None

    async def setup(self, config: Dict[str, Any]) -> None:
        import os

        secret_env = config.get("channel_secret_env", "LINE_CHANNEL_SECRET")
        self._channel_secret = config.get("channel_secret") or os.environ.get(
            secret_env
        )
        if not self._channel_secret:
            raise ChannelSetupError(
                f"Channel Secret de LINE no encontrado. Configura {secret_env}"
            )
        token_env = config.get("channel_access_token_env", "LINE_CHANNEL_ACCESS_TOKEN")
        self._channel_access_token = config.get(
            "channel_access_token"
        ) or os.environ.get(token_env)
        if not self._channel_access_token:
            raise ChannelSetupError(
                f"Channel Access Token de LINE no encontrado. Configura {token_env}"
            )

    async def start(self) -> None:
        if not self._channel_access_token:
            raise ChannelSetupError("Ejecuta setup() primero")
        try:
            from linebot.v3.messaging import (
                AsyncApiClient,
                AsyncMessagingApi,
                Configuration,
            )

            configuration = Configuration(
                access_token=self._channel_access_token
            )
            api_client = AsyncApiClient(configuration)
            self._api = AsyncMessagingApi(api_client)
            self._running = True
            logger.info("LINE plugin iniciado")
        except ImportError:
            raise ChannelError(
                "line-bot-sdk no instalado. Ejecuta: pip install line-bot-sdk"
            )

    async def stop(self) -> None:
        self._api = None
        self._running = False
        logger.info("LINE plugin detenido")

    async def send_message(
        self,
        target: str,
        content: str,
        media: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> None:
        if not self._api:
            raise ChannelError("LINE no esta iniciado")
        try:
            from linebot.v3.messaging import (
                PushMessageRequest,
                TextMessage,
            )

            request = PushMessageRequest(
                to=target,
                messages=[TextMessage(text=content)],
            )
            await self._api.push_message(request)
        except ImportError:
            raise ChannelError("line-bot-sdk no instalado")
        except Exception as exc:
            raise ChannelError(f"Error enviando mensaje LINE: {exc}") from exc

    async def handle_webhook(self, payload: Dict[str, Any]) -> None:
        """Procesa un webhook entrante de LINE Messaging API."""
        try:
            for event in payload.get("events", []):
                event_type = event.get("type", "")
                if event_type != "message":
                    continue
                message = event.get("message", {})
                if message.get("type") != "text":
                    continue
                source = event.get("source", {})
                msg = IncomingMessage(
                    channel=ChannelType.LINE,
                    channel_user_id=source.get("userId", ""),
                    channel_thread_id=source.get("groupId") or source.get("roomId"),
                    content=message.get("text", ""),
                    metadata={
                        "reply_token": event.get("replyToken", ""),
                        "message_id": message.get("id", ""),
                        "source_type": source.get("type", ""),
                        "timestamp": str(event.get("timestamp", "")),
                    },
                )
                await self._dispatch_message(msg)
        except Exception:
            logger.exception("Error procesando webhook de LINE")
