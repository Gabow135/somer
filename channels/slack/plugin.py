"""Plugin de canal Slack."""

from __future__ import annotations

import logging
from pathlib import Path
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


class SlackPlugin(ChannelPlugin):
    """Plugin para Slack usando slack-bolt."""

    def __init__(self) -> None:
        super().__init__(
            plugin_id="slack",
            meta=ChannelMeta(
                id="slack",
                name="Slack",
                version="1.0.0",
                description="Slack Bot channel plugin",
            ),
            capabilities=ChannelCapabilities(
                supports_threads=True,
                supports_reactions=True,
                supports_media=True,
                supports_editing=True,
                supports_deletion=True,
                max_message_length=40000,
            ),
        )
        self._app: Any = None
        self._token: Optional[str] = None
        self._signing_secret: Optional[str] = None

    async def setup(self, config: Dict[str, Any]) -> None:
        import os
        self._token = config.get("token") or os.environ.get(
            config.get("token_env", "SLACK_BOT_TOKEN")
        )
        self._signing_secret = config.get("signing_secret") or os.environ.get(
            config.get("signing_secret_env", "SLACK_SIGNING_SECRET")
        )
        if not self._token:
            raise ChannelSetupError("SLACK_BOT_TOKEN no configurado")

    async def start(self) -> None:
        if not self._token:
            raise ChannelSetupError("Ejecuta setup() primero")
        try:
            from slack_bolt.async_app import AsyncApp

            self._app = AsyncApp(
                token=self._token,
                signing_secret=self._signing_secret or "",
            )

            @self._app.message("")
            async def handle_message(message, say):
                msg = IncomingMessage(
                    channel=ChannelType.SLACK,
                    channel_user_id=message.get("user", ""),
                    channel_thread_id=message.get("thread_ts"),
                    team_id=message.get("team", ""),
                    content=message.get("text", ""),
                    metadata={
                        "channel_id": message.get("channel", ""),
                        "ts": message.get("ts", ""),
                    },
                )
                await self._dispatch_message(msg)

            self._running = True
            logger.info("Slack plugin iniciado")
        except ImportError:
            raise ChannelError(
                "slack-bolt no instalado. Ejecuta: pip install slack-bolt"
            )

    async def stop(self) -> None:
        self._running = False
        logger.info("Slack plugin detenido")

    async def send_message(
        self,
        target: str,
        content: str,
        media: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> None:
        if not self._app:
            raise ChannelError("Slack no está iniciado")
        try:
            await self._app.client.chat_postMessage(
                channel=target,
                text=content,
            )
        except Exception as exc:
            raise ChannelError(f"Error enviando mensaje Slack: {exc}") from exc

    async def send_file(
        self,
        target: str,
        file_path: str,
        filename: Optional[str] = None,
        caption: Optional[str] = None,
    ) -> bool:
        """Envía un archivo a un canal de Slack."""
        if not self._app:
            return False
        try:
            await self._app.client.files_upload_v2(
                channel=target,
                file=file_path,
                filename=filename or Path(file_path).name,
                initial_comment=caption or "",
            )
            return True
        except Exception as exc:
            logger.error("Error enviando archivo Slack a %s: %s", target, exc)
            return False
