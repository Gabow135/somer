"""Plugin de canal Nostr."""

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


class NostrPlugin(ChannelPlugin):
    """Plugin para Nostr usando nostr-sdk o implementacion custom con websockets."""

    def __init__(self) -> None:
        super().__init__(
            plugin_id="nostr",
            meta=ChannelMeta(
                id="nostr",
                name="Nostr",
                version="1.0.0",
                description="Nostr decentralized protocol channel plugin",
            ),
            capabilities=ChannelCapabilities(
                supports_threads=False,
                supports_reactions=True,
                supports_media=False,
                supports_editing=False,
                supports_deletion=False,
                max_message_length=65536,
            ),
        )
        self._client: Any = None
        self._private_key: Optional[str] = None
        self._relays: List[str] = []
        self._ws_connections: List[Any] = []

    async def setup(self, config: Dict[str, Any]) -> None:
        import os

        pk_env = config.get("private_key_env", "NOSTR_PRIVATE_KEY")
        self._private_key = config.get("private_key") or os.environ.get(pk_env)
        if not self._private_key:
            raise ChannelSetupError(
                f"Clave privada de Nostr no encontrada. Configura {pk_env}"
            )
        relays_env = config.get("relays_env", "NOSTR_RELAYS")
        raw_relays = config.get("relays") or os.environ.get(
            relays_env, "wss://relay.damus.io,wss://nos.lol"
        )
        if isinstance(raw_relays, str):
            self._relays = [r.strip() for r in raw_relays.split(",") if r.strip()]
        else:
            self._relays = list(raw_relays)

    async def start(self) -> None:
        if not self._private_key:
            raise ChannelSetupError("Ejecuta setup() primero")
        try:
            import websockets

            for relay_url in self._relays:
                try:
                    ws = await websockets.connect(relay_url)
                    self._ws_connections.append(ws)
                    logger.info("Conectado a relay Nostr: %s", relay_url)
                except Exception:
                    logger.warning("No se pudo conectar a relay: %s", relay_url)

            if not self._ws_connections:
                raise ChannelError(
                    "No se pudo conectar a ningun relay de Nostr"
                )
            self._running = True
            logger.info(
                "Nostr plugin iniciado con %d relays", len(self._ws_connections)
            )
        except ImportError:
            raise ChannelError(
                "websockets no instalado. Ejecuta: pip install websockets"
            )

    async def stop(self) -> None:
        for ws in self._ws_connections:
            try:
                await ws.close()
            except Exception:
                pass
        self._ws_connections.clear()
        self._running = False
        logger.info("Nostr plugin detenido")

    async def send_message(
        self,
        target: str,
        content: str,
        media: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> None:
        if not self._ws_connections:
            raise ChannelError("Nostr no esta iniciado")
        try:
            import hashlib
            import json
            import time

            # Crear evento NIP-01 kind 1 (short text note)
            # o kind 4 (encrypted DM) si target es pubkey
            created_at = int(time.time())
            event = {
                "pubkey": self._get_public_key(),
                "created_at": created_at,
                "kind": 1,
                "tags": [],
                "content": content,
            }
            if target:
                # Si target es una pubkey, crear como DM (kind 4)
                event["kind"] = 4
                event["tags"] = [["p", target]]

            # Serializar para ID (NIP-01)
            serialized = json.dumps(
                [
                    0,
                    event["pubkey"],
                    event["created_at"],
                    event["kind"],
                    event["tags"],
                    event["content"],
                ],
                separators=(",", ":"),
                ensure_ascii=False,
            )
            event["id"] = hashlib.sha256(serialized.encode()).hexdigest()
            event["sig"] = self._sign_event(event["id"])

            msg = json.dumps(["EVENT", event])
            for ws in self._ws_connections:
                try:
                    await ws.send(msg)
                except Exception:
                    logger.warning("Error enviando a relay Nostr")
        except Exception as exc:
            raise ChannelError(f"Error enviando mensaje Nostr: {exc}") from exc

    def _get_public_key(self) -> str:
        """Deriva la clave publica desde la clave privada."""
        # Placeholder: en produccion usar secp256k1
        import hashlib

        return hashlib.sha256(
            (self._private_key or "").encode()
        ).hexdigest()

    def _sign_event(self, event_id: str) -> str:
        """Firma un evento Nostr con la clave privada (Schnorr/secp256k1)."""
        # Placeholder: en produccion usar firma Schnorr real
        import hashlib

        return hashlib.sha256(
            f"{self._private_key}{event_id}".encode()
        ).hexdigest()

    async def _listen_loop(self) -> None:
        """Loop de escucha de eventos desde relays Nostr."""
        import json

        for ws in self._ws_connections:
            while self._running:
                try:
                    raw = await ws.recv()
                    data = json.loads(raw)
                    if isinstance(data, list) and len(data) >= 3:
                        if data[0] == "EVENT":
                            event = data[2]
                            msg = IncomingMessage(
                                channel=ChannelType.NOSTR,
                                channel_user_id=event.get("pubkey", ""),
                                channel_thread_id=None,
                                content=event.get("content", ""),
                                metadata={
                                    "event_id": event.get("id", ""),
                                    "kind": str(event.get("kind", "")),
                                    "created_at": str(
                                        event.get("created_at", "")
                                    ),
                                },
                            )
                            await self._dispatch_message(msg)
                except Exception:
                    logger.exception("Error en listen loop de Nostr")
                    break
