"""Plugin de canal Microsoft Teams."""

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


class MSTeamsPlugin(ChannelPlugin):
    """Plugin para Microsoft Teams usando botframework-connector / httpx."""

    def __init__(self) -> None:
        super().__init__(
            plugin_id="msteams",
            meta=ChannelMeta(
                id="msteams",
                name="Microsoft Teams",
                version="1.0.0",
                description="Microsoft Teams Bot Framework channel plugin",
            ),
            capabilities=ChannelCapabilities(
                supports_threads=True,
                supports_reactions=True,
                supports_media=True,
                supports_editing=False,
                supports_deletion=False,
                max_message_length=28000,
            ),
        )
        self._client: Any = None
        self._app_id: Optional[str] = None
        self._app_password: Optional[str] = None
        self._access_token: Optional[str] = None

    async def setup(self, config: Dict[str, Any]) -> None:
        import os

        app_id_env = config.get("app_id_env", "MSTEAMS_APP_ID")
        self._app_id = config.get("app_id") or os.environ.get(app_id_env)
        if not self._app_id:
            raise ChannelSetupError(
                f"App ID de Teams no encontrado. Configura {app_id_env}"
            )
        app_pw_env = config.get("app_password_env", "MSTEAMS_APP_PASSWORD")
        self._app_password = config.get("app_password") or os.environ.get(app_pw_env)
        if not self._app_password:
            raise ChannelSetupError(
                f"App Password de Teams no encontrado. Configura {app_pw_env}"
            )

    async def start(self) -> None:
        if not self._app_id:
            raise ChannelSetupError("Ejecuta setup() primero")
        try:
            import httpx

            # Obtener token OAuth2 de Bot Framework
            token_resp = await self._get_bot_token()
            self._access_token = token_resp

            self._client = httpx.AsyncClient(
                headers={"Authorization": f"Bearer {self._access_token}"},
                timeout=30.0,
            )
            self._running = True
            logger.info("MS Teams plugin iniciado")
        except ImportError:
            raise ChannelError(
                "httpx no instalado. Ejecuta: pip install httpx"
            )

    async def _get_bot_token(self) -> str:
        """Obtiene token OAuth2 del Bot Framework."""
        import httpx

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._app_id,
                    "client_secret": self._app_password,
                    "scope": "https://api.botframework.com/.default",
                },
            )
            resp.raise_for_status()
            return resp.json()["access_token"]

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
        self._running = False
        logger.info("MS Teams plugin detenido")

    async def send_message(
        self,
        target: str,
        content: str,
        media: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> None:
        if not self._client:
            raise ChannelError("MS Teams no esta iniciado")
        try:
            # target format: "service_url|conversation_id"
            parts = target.split("|", 1)
            if len(parts) != 2:
                raise ChannelError(
                    "Target de Teams debe ser 'service_url|conversation_id'"
                )
            service_url, conversation_id = parts
            payload = {
                "type": "message",
                "text": content,
            }
            resp = await self._client.post(
                f"{service_url.rstrip('/')}/v3/conversations/{conversation_id}/activities",
                json=payload,
            )
            resp.raise_for_status()
        except ChannelError:
            raise
        except Exception as exc:
            raise ChannelError(f"Error enviando mensaje Teams: {exc}") from exc

    async def handle_webhook(self, payload: Dict[str, Any]) -> None:
        """Procesa una actividad entrante del Bot Framework."""
        try:
            activity_type = payload.get("type", "")
            if activity_type != "message":
                return
            text = payload.get("text", "")
            from_data = payload.get("from", {})
            conversation = payload.get("conversation", {})
            msg = IncomingMessage(
                channel=ChannelType.MSTEAMS,
                channel_user_id=from_data.get("id", ""),
                channel_thread_id=conversation.get("id"),
                content=text,
                metadata={
                    "service_url": payload.get("serviceUrl", ""),
                    "conversation_id": conversation.get("id", ""),
                    "from_name": from_data.get("name", ""),
                    "activity_id": payload.get("id", ""),
                },
            )
            await self._dispatch_message(msg)
        except Exception:
            logger.exception("Error procesando webhook de MS Teams")
