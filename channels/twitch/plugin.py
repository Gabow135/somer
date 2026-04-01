"""Plugin de canal Twitch."""

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


class TwitchPlugin(ChannelPlugin):
    """Plugin para Twitch IRC chat usando twitchio."""

    def __init__(self) -> None:
        super().__init__(
            plugin_id="twitch",
            meta=ChannelMeta(
                id="twitch",
                name="Twitch",
                version="1.0.0",
                description="Twitch IRC chat channel plugin via twitchio",
            ),
            capabilities=ChannelCapabilities(
                supports_threads=False,
                supports_reactions=False,
                supports_media=False,
                supports_editing=False,
                supports_deletion=False,
                max_message_length=500,
            ),
        )
        self._bot: Any = None
        self._token: Optional[str] = None
        self._client_id: Optional[str] = None
        self._channels_to_join: List[str] = []
        self._nick: Optional[str] = None

    async def setup(self, config: Dict[str, Any]) -> None:
        import os

        token_env = config.get("token_env", "TWITCH_OAUTH_TOKEN")
        self._token = config.get("token") or os.environ.get(token_env)
        if not self._token:
            raise ChannelSetupError(
                f"Token OAuth de Twitch no encontrado. Configura {token_env}"
            )
        client_id_env = config.get("client_id_env", "TWITCH_CLIENT_ID")
        self._client_id = config.get("client_id") or os.environ.get(client_id_env)
        nick_env = config.get("nick_env", "TWITCH_BOT_NICK")
        self._nick = config.get("nick") or os.environ.get(nick_env, "somer_bot")
        channels_env = config.get("channels_env", "TWITCH_CHANNELS")
        raw_channels = config.get("channels") or os.environ.get(channels_env, "")
        if isinstance(raw_channels, str):
            self._channels_to_join = [
                c.strip() for c in raw_channels.split(",") if c.strip()
            ]
        else:
            self._channels_to_join = list(raw_channels)

    async def start(self) -> None:
        if not self._token:
            raise ChannelSetupError("Ejecuta setup() primero")
        try:
            from twitchio.ext import commands

            plugin_ref = self

            class SomerTwitchBot(commands.Bot):
                def __init__(bot_self) -> None:
                    super().__init__(
                        token=plugin_ref._token,
                        client_id=plugin_ref._client_id,
                        nick=plugin_ref._nick,
                        prefix="!",
                        initial_channels=plugin_ref._channels_to_join,
                    )

                async def event_message(bot_self, message: Any) -> None:
                    if message.echo:
                        return
                    msg = IncomingMessage(
                        channel=ChannelType.TWITCH,
                        channel_user_id=message.author.name if message.author else "",
                        channel_thread_id=message.channel.name if message.channel else None,
                        content=message.content or "",
                        metadata={
                            "channel_name": (
                                message.channel.name if message.channel else ""
                            ),
                            "message_id": message.id or "",
                            "author_id": (
                                str(message.author.id) if message.author else ""
                            ),
                        },
                    )
                    await plugin_ref._dispatch_message(msg)

            self._bot = SomerTwitchBot()
            self._running = True
            logger.info("Twitch plugin iniciado")
        except ImportError:
            raise ChannelError(
                "twitchio no instalado. Ejecuta: pip install twitchio"
            )

    async def stop(self) -> None:
        if self._bot:
            await self._bot.close()
        self._running = False
        logger.info("Twitch plugin detenido")

    async def send_message(
        self,
        target: str,
        content: str,
        media: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> None:
        if not self._bot:
            raise ChannelError("Twitch no esta iniciado")
        try:
            # target = channel name
            channel = self._bot.get_channel(target)
            if not channel:
                raise ChannelError(f"Canal de Twitch '{target}' no encontrado")
            # Twitch max 500 chars per message
            for i in range(0, len(content), 500):
                chunk = content[i : i + 500]
                await channel.send(chunk)
        except ChannelError:
            raise
        except Exception as exc:
            raise ChannelError(f"Error enviando mensaje Twitch: {exc}") from exc
