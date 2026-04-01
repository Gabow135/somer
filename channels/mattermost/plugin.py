"""Plugin de canal Mattermost."""

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


class MattermostPlugin(ChannelPlugin):
    """Plugin para Mattermost usando httpx + websockets."""

    def __init__(self) -> None:
        super().__init__(
            plugin_id="mattermost",
            meta=ChannelMeta(
                id="mattermost",
                name="Mattermost",
                version="1.0.0",
                description="Mattermost channel plugin via REST API + WebSocket",
            ),
            capabilities=ChannelCapabilities(
                supports_threads=True,
                supports_reactions=True,
                supports_media=True,
                supports_editing=True,
                supports_deletion=False,
                max_message_length=16383,
            ),
        )
        self._client: Any = None
        self._ws: Any = None
        self._url: Optional[str] = None
        self._token: Optional[str] = None
        self._bot_user_id: Optional[str] = None

    async def setup(self, config: Dict[str, Any]) -> None:
        import os

        url_env = config.get("url_env", "MATTERMOST_URL")
        self._url = config.get("url") or os.environ.get(url_env)
        if not self._url:
            raise ChannelSetupError(
                f"URL de Mattermost no encontrada. Configura {url_env}"
            )
        token_env = config.get("token_env", "MATTERMOST_BOT_TOKEN")
        self._token = config.get("token") or os.environ.get(token_env)
        if not self._token:
            raise ChannelSetupError(
                f"Token de Mattermost no encontrado. Configura {token_env}"
            )

    async def start(self) -> None:
        if not self._url or not self._token:
            raise ChannelSetupError("Ejecuta setup() primero")
        try:
            import httpx

            base_url = self._url.rstrip("/")
            self._client = httpx.AsyncClient(
                base_url=f"{base_url}/api/v4",
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=30.0,
            )
            # Verificar conexion y obtener bot user ID
            resp = await self._client.get("/users/me")
            resp.raise_for_status()
            self._bot_user_id = resp.json().get("id")

            self._running = True
            logger.info("Mattermost plugin iniciado")
        except ImportError:
            raise ChannelError(
                "httpx no instalado. Ejecuta: pip install httpx"
            )
        except Exception as exc:
            raise ChannelError(
                f"Error conectando a Mattermost: {exc}"
            ) from exc

    async def _connect_websocket(self) -> None:
        """Conecta al WebSocket de Mattermost para eventos en tiempo real."""
        try:
            import websockets

            base_url = self._url.rstrip("/")
            ws_url = base_url.replace("http", "ws", 1)
            self._ws = await websockets.connect(
                f"{ws_url}/api/v4/websocket"
            )
            import json

            auth = json.dumps({
                "seq": 1,
                "action": "authentication_challenge",
                "data": {"token": self._token},
            })
            await self._ws.send(auth)
        except ImportError:
            logger.warning(
                "websockets no instalado. WebSocket deshabilitado. "
                "Ejecuta: pip install websockets"
            )
        except Exception:
            logger.exception("Error conectando WebSocket de Mattermost")

    async def _ws_listen_loop(self) -> None:
        """Loop de escucha del WebSocket de Mattermost."""
        import json

        if not self._ws:
            return
        while self._running:
            try:
                raw = await self._ws.recv()
                event = json.loads(raw)
                if event.get("event") == "posted":
                    data = json.loads(event.get("data", {}).get("post", "{}"))
                    if data.get("user_id") == self._bot_user_id:
                        continue
                    msg = IncomingMessage(
                        channel=ChannelType.MATTERMOST,
                        channel_user_id=data.get("user_id", ""),
                        channel_thread_id=data.get("root_id") or None,
                        content=data.get("message", ""),
                        metadata={
                            "channel_id": data.get("channel_id", ""),
                            "post_id": data.get("id", ""),
                            "team_id": event.get("data", {}).get(
                                "team_id", ""
                            ),
                        },
                    )
                    await self._dispatch_message(msg)
            except Exception:
                logger.exception("Error en WebSocket de Mattermost")
                break

    async def stop(self) -> None:
        if self._ws:
            await self._ws.close()
        if self._client:
            await self._client.aclose()
        self._running = False
        logger.info("Mattermost plugin detenido")

    async def send_message(
        self,
        target: str,
        content: str,
        media: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> None:
        if not self._client:
            raise ChannelError("Mattermost no esta iniciado")
        try:
            payload: Dict[str, Any] = {
                "channel_id": target,
                "message": content,
            }
            resp = await self._client.post("/posts", json=payload)
            resp.raise_for_status()
        except Exception as exc:
            raise ChannelError(
                f"Error enviando mensaje Mattermost: {exc}"
            ) from exc
