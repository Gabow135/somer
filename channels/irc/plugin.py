"""Plugin de canal IRC."""

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


class IRCPlugin(ChannelPlugin):
    """Plugin para IRC usando asyncirc o raw sockets."""

    def __init__(self) -> None:
        super().__init__(
            plugin_id="irc",
            meta=ChannelMeta(
                id="irc",
                name="IRC",
                version="1.0.0",
                description="IRC channel plugin via asyncio sockets",
            ),
            capabilities=ChannelCapabilities(
                supports_threads=False,
                supports_reactions=False,
                supports_media=False,
                supports_editing=False,
                supports_deletion=False,
                max_message_length=512,
            ),
        )
        self._reader: Any = None
        self._writer: Any = None
        self._server: Optional[str] = None
        self._port: int = 6667
        self._nickname: Optional[str] = None
        self._channels_to_join: List[str] = []

    async def setup(self, config: Dict[str, Any]) -> None:
        import os

        server_env = config.get("server_env", "IRC_SERVER")
        self._server = config.get("server") or os.environ.get(server_env)
        if not self._server:
            raise ChannelSetupError(
                f"Servidor IRC no encontrado. Configura {server_env}"
            )
        self._port = int(
            config.get("port") or os.environ.get("IRC_PORT", "6667")
        )
        nick_env = config.get("nickname_env", "IRC_NICKNAME")
        self._nickname = config.get("nickname") or os.environ.get(nick_env, "somer-bot")
        channels_env = config.get("channels_env", "IRC_CHANNELS")
        raw_channels = config.get("channels") or os.environ.get(channels_env, "")
        if isinstance(raw_channels, str):
            self._channels_to_join = [
                c.strip() for c in raw_channels.split(",") if c.strip()
            ]
        else:
            self._channels_to_join = list(raw_channels)

    async def start(self) -> None:
        if not self._server:
            raise ChannelSetupError("Ejecuta setup() primero")
        try:
            import asyncio

            self._reader, self._writer = await asyncio.open_connection(
                self._server, self._port
            )
            self._writer.write(f"NICK {self._nickname}\r\n".encode())
            self._writer.write(
                f"USER {self._nickname} 0 * :{self._nickname}\r\n".encode()
            )
            await self._writer.drain()

            for channel in self._channels_to_join:
                if not channel.startswith("#"):
                    channel = f"#{channel}"
                self._writer.write(f"JOIN {channel}\r\n".encode())
            await self._writer.drain()

            self._running = True
            logger.info("IRC plugin iniciado en %s:%d", self._server, self._port)
        except Exception as exc:
            raise ChannelError(
                f"Error conectando a IRC {self._server}:{self._port}: {exc}"
            ) from exc

    async def stop(self) -> None:
        if self._writer:
            try:
                self._writer.write(b"QUIT :SOMER bot desconectandose\r\n")
                await self._writer.drain()
                self._writer.close()
            except Exception:
                pass
        self._running = False
        logger.info("IRC plugin detenido")

    async def send_message(
        self,
        target: str,
        content: str,
        media: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> None:
        if not self._writer:
            raise ChannelError("IRC no esta iniciado")
        try:
            # IRC messages limited to 512 bytes including CRLF
            max_len = 512 - len(f"PRIVMSG {target} :".encode()) - 2
            for line in content.split("\n"):
                while line:
                    chunk = line[:max_len]
                    line = line[max_len:]
                    self._writer.write(
                        f"PRIVMSG {target} :{chunk}\r\n".encode()
                    )
            await self._writer.drain()
        except Exception as exc:
            raise ChannelError(f"Error enviando mensaje IRC: {exc}") from exc

    async def _read_loop(self) -> None:
        """Loop de lectura de mensajes IRC (ejecutar como tarea asyncio)."""
        if not self._reader:
            return
        buffer = ""
        while self._running:
            try:
                data = await self._reader.read(4096)
                if not data:
                    break
                buffer += data.decode("utf-8", errors="replace")
                while "\r\n" in buffer:
                    line, buffer = buffer.split("\r\n", 1)
                    await self._process_line(line)
            except Exception:
                logger.exception("Error en IRC read loop")
                break

    async def _process_line(self, line: str) -> None:
        """Procesa una linea IRC raw."""
        if line.startswith("PING"):
            if self._writer:
                self._writer.write(f"PONG {line[5:]}\r\n".encode())
                await self._writer.drain()
            return

        parts = line.split(" ")
        if len(parts) >= 4 and parts[1] == "PRIVMSG":
            prefix = parts[0]
            nick = prefix.split("!")[0].lstrip(":")
            channel = parts[2]
            text = " ".join(parts[3:])[1:]
            msg = IncomingMessage(
                channel=ChannelType.IRC,
                channel_user_id=nick,
                channel_thread_id=channel,
                content=text,
                metadata={
                    "raw_prefix": prefix,
                    "irc_channel": channel,
                },
            )
            await self._dispatch_message(msg)
