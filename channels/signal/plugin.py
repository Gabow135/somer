"""Plugin de canal Signal."""

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


class SignalPlugin(ChannelPlugin):
    """Plugin para Signal usando signal-cli (subprocess/REST API)."""

    def __init__(self) -> None:
        super().__init__(
            plugin_id="signal",
            meta=ChannelMeta(
                id="signal",
                name="Signal",
                version="1.0.0",
                description="Signal Messenger channel plugin via signal-cli REST API",
            ),
            capabilities=ChannelCapabilities(
                supports_threads=False,
                supports_reactions=False,
                supports_media=True,
                supports_editing=False,
                supports_deletion=False,
                max_message_length=4096,
            ),
        )
        self._client: Any = None
        self._api_url: Optional[str] = None
        self._phone_number: Optional[str] = None

    async def setup(self, config: Dict[str, Any]) -> None:
        import os

        url_env = config.get("api_url_env", "SIGNAL_CLI_REST_URL")
        self._api_url = config.get("api_url") or os.environ.get(url_env)
        if not self._api_url:
            raise ChannelSetupError(
                f"URL de signal-cli REST no encontrada. Configura {url_env}"
            )
        phone_env = config.get("phone_number_env", "SIGNAL_PHONE_NUMBER")
        self._phone_number = config.get("phone_number") or os.environ.get(phone_env)
        if not self._phone_number:
            raise ChannelSetupError(
                f"Numero de telefono de Signal no encontrado. Configura {phone_env}"
            )

    async def start(self) -> None:
        if not self._api_url:
            raise ChannelSetupError("Ejecuta setup() primero")
        try:
            import httpx

            self._client = httpx.AsyncClient(
                base_url=self._api_url.rstrip("/"),
                timeout=30.0,
            )
            self._running = True
            logger.info("Signal plugin iniciado")
        except ImportError:
            raise ChannelError(
                "httpx no instalado. Ejecuta: pip install httpx"
            )

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
        self._running = False
        logger.info("Signal plugin detenido")

    async def send_message(
        self,
        target: str,
        content: str,
        media: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> None:
        if not self._client:
            raise ChannelError("Signal no esta iniciado")
        try:
            payload: Dict[str, Any] = {
                "message": content,
                "number": self._phone_number,
                "recipients": [target],
            }
            if media:
                payload["base64_attachments"] = [
                    m.get("data", "") for m in media if m.get("data")
                ]
            resp = await self._client.post(
                "/v2/send",
                json=payload,
            )
            resp.raise_for_status()
        except Exception as exc:
            raise ChannelError(f"Error enviando mensaje Signal: {exc}") from exc

    async def handle_webhook(self, payload: Dict[str, Any]) -> None:
        """Procesa un mensaje entrante del REST API de signal-cli."""
        try:
            envelope = payload.get("envelope", {})
            data_message = envelope.get("dataMessage", {})
            source = envelope.get("source", "")
            text = data_message.get("message", "")
            if text:
                msg = IncomingMessage(
                    channel=ChannelType.SIGNAL,
                    channel_user_id=source,
                    channel_thread_id=None,
                    content=text,
                    metadata={
                        "timestamp": str(envelope.get("timestamp", "")),
                        "source_device": str(envelope.get("sourceDevice", "")),
                    },
                )
                await self._dispatch_message(msg)
        except Exception:
            logger.exception("Error procesando webhook de Signal")
