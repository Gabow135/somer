"""Plugin de canal Google Chat."""

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


class GoogleChatPlugin(ChannelPlugin):
    """Plugin para Google Chat usando google-auth + httpx."""

    def __init__(self) -> None:
        super().__init__(
            plugin_id="googlechat",
            meta=ChannelMeta(
                id="googlechat",
                name="Google Chat",
                version="1.0.0",
                description="Google Chat (Workspace) channel plugin",
            ),
            capabilities=ChannelCapabilities(
                supports_threads=True,
                supports_reactions=True,
                supports_media=True,
                supports_editing=False,
                supports_deletion=False,
                max_message_length=4096,
            ),
        )
        self._client: Any = None
        self._credentials: Any = None
        self._service_account_path: Optional[str] = None

    async def setup(self, config: Dict[str, Any]) -> None:
        import os

        sa_env = config.get(
            "service_account_env", "GOOGLE_CHAT_SERVICE_ACCOUNT_JSON"
        )
        self._service_account_path = config.get("service_account") or os.environ.get(
            sa_env
        )
        if not self._service_account_path:
            raise ChannelSetupError(
                f"Service account de Google Chat no encontrado. Configura {sa_env}"
            )

    async def start(self) -> None:
        if not self._service_account_path:
            raise ChannelSetupError("Ejecuta setup() primero")
        try:
            from google.oauth2 import service_account
            import httpx

            scopes = ["https://www.googleapis.com/auth/chat.bot"]
            self._credentials = (
                service_account.Credentials.from_service_account_file(
                    self._service_account_path, scopes=scopes
                )
            )
            self._client = httpx.AsyncClient(timeout=30.0)
            self._running = True
            logger.info("Google Chat plugin iniciado")
        except ImportError as exc:
            missing = []
            try:
                import google.oauth2  # noqa: F401
            except ImportError:
                missing.append("google-auth")
            try:
                import httpx  # noqa: F401
            except ImportError:
                missing.append("httpx")
            raise ChannelError(
                f"Paquetes faltantes: {', '.join(missing)}. "
                f"Ejecuta: pip install {' '.join(missing)}"
            ) from exc

    async def _get_auth_headers(self) -> Dict[str, str]:
        """Obtiene headers de autenticacion con el token actual."""
        from google.auth.transport.requests import Request

        if not self._credentials or not self._credentials.valid:
            self._credentials.refresh(Request())
        return {"Authorization": f"Bearer {self._credentials.token}"}

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
        self._running = False
        logger.info("Google Chat plugin detenido")

    async def send_message(
        self,
        target: str,
        content: str,
        media: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> None:
        if not self._client:
            raise ChannelError("Google Chat no esta iniciado")
        try:
            headers = await self._get_auth_headers()
            # target = space name, e.g. "spaces/AAAA..."
            payload = {"text": content}
            resp = await self._client.post(
                f"https://chat.googleapis.com/v1/{target}/messages",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
        except ChannelError:
            raise
        except Exception as exc:
            raise ChannelError(
                f"Error enviando mensaje Google Chat: {exc}"
            ) from exc

    async def handle_webhook(self, payload: Dict[str, Any]) -> None:
        """Procesa un evento entrante de Google Chat."""
        try:
            event_type = payload.get("type", "")
            if event_type != "MESSAGE":
                return
            message = payload.get("message", {})
            sender = message.get("sender", {})
            space = payload.get("space", {})
            thread = message.get("thread", {})
            msg = IncomingMessage(
                channel=ChannelType.GOOGLECHAT,
                channel_user_id=sender.get("name", ""),
                channel_thread_id=thread.get("name"),
                content=message.get("text", ""),
                metadata={
                    "space_name": space.get("name", ""),
                    "space_display_name": space.get("displayName", ""),
                    "message_name": message.get("name", ""),
                    "sender_display_name": sender.get("displayName", ""),
                },
            )
            await self._dispatch_message(msg)
        except Exception:
            logger.exception("Error procesando webhook de Google Chat")
