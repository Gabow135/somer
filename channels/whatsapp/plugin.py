"""Plugin de canal WhatsApp."""

from __future__ import annotations

import logging
import mimetypes
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


class WhatsAppPlugin(ChannelPlugin):
    """Plugin para WhatsApp usando whatsapp-web.py o httpx (Cloud API REST)."""

    def __init__(self) -> None:
        super().__init__(
            plugin_id="whatsapp",
            meta=ChannelMeta(
                id="whatsapp",
                name="WhatsApp",
                version="1.0.0",
                description="WhatsApp Business Cloud API channel plugin",
            ),
            capabilities=ChannelCapabilities(
                supports_threads=False,
                supports_reactions=True,
                supports_media=True,
                supports_editing=False,
                supports_deletion=False,
                max_message_length=65536,
            ),
        )
        self._client: Any = None
        self._token: Optional[str] = None
        self._phone_number_id: Optional[str] = None

    async def setup(self, config: Dict[str, Any]) -> None:
        import os

        token_env = config.get("token_env", "WHATSAPP_API_TOKEN")
        self._token = config.get("token") or os.environ.get(token_env)
        if not self._token:
            raise ChannelSetupError(
                f"Token de WhatsApp no encontrado. Configura {token_env}"
            )
        phone_env = config.get("phone_number_id_env", "WHATSAPP_PHONE_NUMBER_ID")
        self._phone_number_id = config.get("phone_number_id") or os.environ.get(
            phone_env
        )
        if not self._phone_number_id:
            raise ChannelSetupError(
                f"Phone Number ID de WhatsApp no encontrado. Configura {phone_env}"
            )

    async def start(self) -> None:
        if not self._token:
            raise ChannelSetupError("Ejecuta setup() primero")
        try:
            import httpx

            self._client = httpx.AsyncClient(
                base_url="https://graph.facebook.com/v18.0",
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=30.0,
            )
            self._running = True
            logger.info("WhatsApp plugin iniciado")
        except ImportError:
            raise ChannelError(
                "httpx no instalado. Ejecuta: pip install httpx"
            )

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
        self._running = False
        logger.info("WhatsApp plugin detenido")

    async def send_message(
        self,
        target: str,
        content: str,
        media: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> None:
        if not self._client:
            raise ChannelError("WhatsApp no esta iniciado")
        try:
            payload: Dict[str, Any] = {
                "messaging_product": "whatsapp",
                "to": target,
                "type": "text",
                "text": {"body": content},
            }
            resp = await self._client.post(
                f"/{self._phone_number_id}/messages",
                json=payload,
            )
            resp.raise_for_status()
        except Exception as exc:
            raise ChannelError(f"Error enviando mensaje WhatsApp: {exc}") from exc

    async def send_file(
        self,
        target: str,
        file_path: str,
        filename: Optional[str] = None,
        caption: Optional[str] = None,
    ) -> bool:
        """Envía un archivo como documento por WhatsApp Cloud API."""
        if not self._client or not self._phone_number_id:
            return False
        try:
            mime = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
            fname = filename or Path(file_path).name
            # 1. Upload media
            with open(file_path, "rb") as f:
                resp = await self._client.post(
                    f"/{self._phone_number_id}/media",
                    files={"file": (fname, f, mime)},
                    data={"messaging_product": "whatsapp"},
                )
            resp.raise_for_status()
            media_id = resp.json()["id"]
            # 2. Send document message
            await self._client.post(
                f"/{self._phone_number_id}/messages",
                json={
                    "messaging_product": "whatsapp",
                    "to": target,
                    "type": "document",
                    "document": {
                        "id": media_id,
                        "caption": caption or "",
                        "filename": fname,
                    },
                },
            )
            return True
        except Exception as exc:
            logger.error("Error enviando archivo WhatsApp a %s: %s", target, exc)
            return False

    async def handle_webhook(self, payload: Dict[str, Any]) -> None:
        """Procesa un webhook entrante de WhatsApp Cloud API."""
        try:
            for entry in payload.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    for message in value.get("messages", []):
                        msg = IncomingMessage(
                            channel=ChannelType.WHATSAPP,
                            channel_user_id=message.get("from", ""),
                            channel_thread_id=None,
                            content=message.get("text", {}).get("body", ""),
                            metadata={
                                "message_id": message.get("id", ""),
                                "timestamp": message.get("timestamp", ""),
                            },
                        )
                        await self._dispatch_message(msg)
        except Exception:
            logger.exception("Error procesando webhook de WhatsApp")
