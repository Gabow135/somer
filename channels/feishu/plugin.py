"""Plugin de canal Feishu (Lark)."""

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


class FeishuPlugin(ChannelPlugin):
    """Plugin para Feishu/Lark usando lark SDK o httpx."""

    def __init__(self) -> None:
        super().__init__(
            plugin_id="feishu",
            meta=ChannelMeta(
                id="feishu",
                name="Feishu",
                version="1.0.0",
                description="Feishu/Lark Messenger channel plugin",
            ),
            capabilities=ChannelCapabilities(
                supports_threads=True,
                supports_reactions=True,
                supports_media=True,
                supports_editing=False,
                supports_deletion=False,
                max_message_length=30000,
            ),
        )
        self._client: Any = None
        self._app_id: Optional[str] = None
        self._app_secret: Optional[str] = None
        self._tenant_access_token: Optional[str] = None

    async def setup(self, config: Dict[str, Any]) -> None:
        import os

        app_id_env = config.get("app_id_env", "FEISHU_APP_ID")
        self._app_id = config.get("app_id") or os.environ.get(app_id_env)
        if not self._app_id:
            raise ChannelSetupError(
                f"App ID de Feishu no encontrado. Configura {app_id_env}"
            )
        app_secret_env = config.get("app_secret_env", "FEISHU_APP_SECRET")
        self._app_secret = config.get("app_secret") or os.environ.get(app_secret_env)
        if not self._app_secret:
            raise ChannelSetupError(
                f"App Secret de Feishu no encontrado. Configura {app_secret_env}"
            )

    async def start(self) -> None:
        if not self._app_id:
            raise ChannelSetupError("Ejecuta setup() primero")
        try:
            import httpx

            # Obtener tenant_access_token
            async with httpx.AsyncClient() as temp_client:
                resp = await temp_client.post(
                    "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                    json={
                        "app_id": self._app_id,
                        "app_secret": self._app_secret,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                self._tenant_access_token = data.get("tenant_access_token")

            if not self._tenant_access_token:
                raise ChannelError("No se pudo obtener tenant_access_token de Feishu")

            self._client = httpx.AsyncClient(
                base_url="https://open.feishu.cn/open-apis",
                headers={
                    "Authorization": f"Bearer {self._tenant_access_token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                timeout=30.0,
            )
            self._running = True
            logger.info("Feishu plugin iniciado")
        except ImportError:
            raise ChannelError(
                "httpx no instalado. Ejecuta: pip install httpx"
            )

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
        self._running = False
        logger.info("Feishu plugin detenido")

    async def send_message(
        self,
        target: str,
        content: str,
        media: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> None:
        if not self._client:
            raise ChannelError("Feishu no esta iniciado")
        try:
            import json as json_mod

            payload = {
                "receive_id": target,
                "msg_type": "text",
                "content": json_mod.dumps({"text": content}),
            }
            resp = await self._client.post(
                "/im/v1/messages",
                params={"receive_id_type": "chat_id"},
                json=payload,
            )
            resp.raise_for_status()
            result = resp.json()
            if result.get("code") != 0:
                raise ChannelError(
                    f"Error Feishu API: {result.get('msg', 'unknown')}"
                )
        except ChannelError:
            raise
        except Exception as exc:
            raise ChannelError(f"Error enviando mensaje Feishu: {exc}") from exc

    async def handle_webhook(self, payload: Dict[str, Any]) -> None:
        """Procesa un evento entrante de Feishu Event Subscription."""
        try:
            # Verificacion de URL (challenge)
            if "challenge" in payload:
                return  # Debe manejarse en la capa HTTP

            header = payload.get("header", {})
            event_type = header.get("event_type", "")
            if event_type != "im.message.receive_v1":
                return

            event = payload.get("event", {})
            message = event.get("message", {})
            sender = event.get("sender", {}).get("sender_id", {})

            import json as json_mod

            content_str = message.get("content", "{}")
            content_data = json_mod.loads(content_str)
            text = content_data.get("text", "")

            msg = IncomingMessage(
                channel=ChannelType.FEISHU,
                channel_user_id=sender.get("open_id", ""),
                channel_thread_id=message.get("root_id") or message.get("parent_id"),
                content=text,
                metadata={
                    "chat_id": message.get("chat_id", ""),
                    "message_id": message.get("message_id", ""),
                    "message_type": message.get("message_type", ""),
                    "sender_type": event.get("sender", {}).get("sender_type", ""),
                },
            )
            await self._dispatch_message(msg)
        except Exception:
            logger.exception("Error procesando webhook de Feishu")
