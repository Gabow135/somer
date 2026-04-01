"""Plugin de canal Discord."""

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


class DiscordPlugin(ChannelPlugin):
    """Plugin para Discord usando discord.py."""

    def __init__(self) -> None:
        super().__init__(
            plugin_id="discord",
            meta=ChannelMeta(
                id="discord",
                name="Discord",
                version="1.0.0",
                description="Discord Bot channel plugin",
            ),
            capabilities=ChannelCapabilities(
                supports_threads=True,
                supports_reactions=True,
                supports_media=True,
                supports_editing=True,
                supports_deletion=True,
                max_message_length=2000,
            ),
        )
        self._client: Any = None
        self._token: Optional[str] = None

    async def setup(self, config: Dict[str, Any]) -> None:
        import os
        self._token = config.get("token") or os.environ.get(
            config.get("token_env", "DISCORD_BOT_TOKEN")
        )
        if not self._token:
            raise ChannelSetupError("DISCORD_BOT_TOKEN no configurado")

    async def start(self) -> None:
        if not self._token:
            raise ChannelSetupError("Ejecuta setup() primero")
        try:
            import discord

            intents = discord.Intents.default()
            intents.message_content = True
            self._client = discord.Client(intents=intents)

            @self._client.event
            async def on_message(message):
                if message.author == self._client.user:
                    return
                msg = IncomingMessage(
                    channel=ChannelType.DISCORD,
                    channel_user_id=str(message.author.id),
                    channel_thread_id=(
                        str(message.thread.id) if hasattr(message, "thread") and message.thread else None
                    ),
                    guild_id=str(message.guild.id) if message.guild else None,
                    content=message.content,
                    metadata={
                        "channel_id": str(message.channel.id),
                        "username": message.author.name,
                    },
                )
                await self._dispatch_message(msg)

            self._running = True
            logger.info("Discord plugin iniciado")
        except ImportError:
            raise ChannelError(
                "discord.py no instalado. Ejecuta: pip install discord.py"
            )

    async def stop(self) -> None:
        if self._client:
            await self._client.close()
        self._running = False
        logger.info("Discord plugin detenido")

    async def send_message(
        self,
        target: str,
        content: str,
        media: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> None:
        if not self._client:
            raise ChannelError("Discord no está iniciado")
        try:
            channel = self._client.get_channel(int(target))
            if channel:
                await channel.send(content)
            else:
                raise ChannelError(f"Canal Discord no encontrado: {target}")
        except ChannelError:
            raise
        except Exception as exc:
            raise ChannelError(f"Error enviando mensaje Discord: {exc}") from exc

    async def send_file(
        self,
        target: str,
        file_path: str,
        filename: Optional[str] = None,
        caption: Optional[str] = None,
    ) -> bool:
        """Envía un archivo a un canal de Discord."""
        if not self._client:
            return False
        try:
            import discord as _discord

            channel = self._client.get_channel(int(target))
            if not channel:
                return False
            f = _discord.File(file_path, filename=filename or Path(file_path).name)
            await channel.send(content=caption or "", file=f)
            return True
        except Exception as exc:
            logger.error("Error enviando archivo Discord a %s: %s", target, exc)
            return False
