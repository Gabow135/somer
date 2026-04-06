"""Plugin de canal WhatsApp Business Cloud API para SOMER 2.0.

Integra WhatsApp mediante la Meta Graph API v19.0 (Cloud API).
Recibe mensajes a través de un servidor de webhook (aiohttp) y envía
mensajes usando el cliente HTTP de channels/whatsapp/client.py.

Flujo de mensajes entrantes:
  Meta → POST /webhook/whatsapp → WhatsAppWebhookServer
       → _procesar_payload() → _dispatch_message()
       → callbacks registrados (gateway bootstrap)

Flujo de mensajes salientes:
  AgentRunner → plugin.send_message() → WhatsAppClient.send_text_message()
               → Graph API → dispositivo del usuario

Variables de entorno requeridas:
  WHATSAPP_TOKEN               Token de acceso de la Meta App
  WHATSAPP_PHONE_NUMBER_ID     ID del número de teléfono de negocio
  WHATSAPP_BUSINESS_ACCOUNT_ID ID de la cuenta de negocio (opcional)
  WHATSAPP_VERIFY_TOKEN        Token secreto para verificación de webhook
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
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
    """Plugin para WhatsApp Business Cloud API (Meta Graph API v19.0).

    Soporta:
      - Mensajes de texto entrantes y salientes
      - Mensajes con media (imágenes, documentos, audio, video)
      - Mensajes de template para notificaciones proactivas
      - Reacciones
      - Marcar como leído automáticamente (configurable)
      - Servidor de webhook integrado (aiohttp, puerto configurable)
      - Soporte para múltiples tipos de mensajes entrantes:
          text, image, audio, video, document, sticker, location,
          contacts, interactive, template, reaction
    """

    def __init__(self) -> None:
        super().__init__(
            plugin_id="whatsapp",
            meta=ChannelMeta(
                id="whatsapp",
                name="WhatsApp",
                version="2.0.0",
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
        # Cliente HTTP hacia la Graph API
        self._client: Any = None  # WhatsAppClient

        # Servidor de webhook
        self._webhook_server: Any = None  # WhatsAppWebhookServer
        self._webhook_task: Optional[asyncio.Task] = None  # type: ignore[type-arg]

        # Configuración leída en setup()
        self._token: Optional[str] = None
        self._phone_number_id: Optional[str] = None
        self._verify_token: Optional[str] = None
        self._webhook_port: int = 8099
        self._webhook_host: str = "0.0.0.0"
        self._webhook_path: str = "/webhook/whatsapp"
        self._auto_read: bool = True
        self._default_language: str = "es"
        self._dm_policy: Optional[str] = None
        self._allow_from: Optional[List[str]] = None

    # ── Ciclo de vida ─────────────────────────────────────────

    async def setup(self, config: Dict[str, Any]) -> None:
        """Configura el plugin con credenciales y opciones desde el config.

        Lee credenciales de variables de entorno.
        Las claves de entorno configurables (token_env, phone_number_id_env, etc.)
        permiten usar nombres de env vars personalizados.

        Args:
            config: Sección config del canal en ~/.somer/config.json
        """
        # ── Credenciales ──────────────────────────────────────
        token_env = config.get("token_env", "WHATSAPP_TOKEN")
        self._token = config.get("token") or os.environ.get(token_env)
        if not self._token:
            raise ChannelSetupError(
                f"Token de WhatsApp no encontrado. "
                f"Configura la variable de entorno {token_env}"
            )

        phone_env = config.get("phone_number_id_env", "WHATSAPP_PHONE_NUMBER_ID")
        self._phone_number_id = config.get("phone_number_id") or os.environ.get(phone_env)
        if not self._phone_number_id:
            raise ChannelSetupError(
                f"Phone Number ID de WhatsApp no encontrado. "
                f"Configura la variable de entorno {phone_env}"
            )

        verify_env = config.get("verify_token_env", "WHATSAPP_VERIFY_TOKEN")
        self._verify_token = config.get("verify_token") or os.environ.get(verify_env)
        if not self._verify_token:
            raise ChannelSetupError(
                f"Verify token de WhatsApp no encontrado. "
                f"Configura la variable de entorno {verify_env}"
            )

        # ── Opciones del webhook ──────────────────────────────
        self._webhook_port = int(config.get("webhook_port", 8099))
        self._webhook_host = config.get("webhook_host", "0.0.0.0")
        self._webhook_path = config.get("webhook_path", "/webhook/whatsapp")

        # ── Opciones de comportamiento ────────────────────────
        self._auto_read = bool(config.get("auto_read", True))
        self._default_language = config.get("default_language", "es")

        # ── Políticas de acceso DM ────────────────────────────
        self._dm_policy = config.get("dm_policy")
        raw_allow = config.get("allow_from")
        if isinstance(raw_allow, str):
            self._allow_from = [raw_allow]
        elif isinstance(raw_allow, list):
            self._allow_from = [str(x) for x in raw_allow]
        else:
            self._allow_from = None

        policy_label = self._dm_policy or "open (default)"
        logger.info(
            "WhatsApp dm_policy: %s", policy_label,
        )

        logger.info(
            "WhatsApp plugin configurado (phone_id: %s..., webhook: %s:%d%s)",
            self._phone_number_id[:6] if self._phone_number_id else "?",
            self._webhook_host,
            self._webhook_port,
            self._webhook_path,
        )

    async def start(self) -> None:
        """Inicia el cliente HTTP y el servidor de webhook."""
        if not self._token:
            raise ChannelSetupError("Ejecuta setup() antes de start()")

        # Inicializar cliente HTTP hacia la Graph API
        from channels.whatsapp.client import WhatsAppClient

        self._client = WhatsAppClient(
            token=self._token,
            phone_number_id=self._phone_number_id,
        )
        await self._client.start()

        # Inicializar servidor de webhook
        from channels.whatsapp.webhook import WhatsAppWebhookServer

        self._webhook_server = WhatsAppWebhookServer(
            on_message=self._procesar_payload,
            port=self._webhook_port,
            host=self._webhook_host,
            webhook_path=self._webhook_path,
            verify_token=self._verify_token,
        )
        await self._webhook_server.start()

        self._running = True
        logger.info(
            "WhatsApp plugin iniciado — webhook en %s:%d%s",
            self._webhook_host, self._webhook_port, self._webhook_path,
        )

        try:
            from rich.console import Console
            Console().print(
                f"  [green]WhatsApp webhook activo: "
                f"http://{self._webhook_host}:{self._webhook_port}"
                f"{self._webhook_path}[/green]"
            )
        except Exception:
            pass

    async def stop(self) -> None:
        """Detiene el servidor de webhook y el cliente HTTP."""
        self._running = False

        if self._webhook_server:
            try:
                await self._webhook_server.stop()
            except Exception as exc:
                logger.warning("Error deteniendo webhook de WhatsApp: %s", exc)
            self._webhook_server = None

        if self._client:
            try:
                await self._client.stop()
            except Exception as exc:
                logger.warning("Error cerrando cliente WhatsApp: %s", exc)
            self._client = None

        logger.info("WhatsApp plugin detenido")

    # ── Mensajería saliente ───────────────────────────────────

    async def send_message(
        self,
        target: str,
        content: str,
        media: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> None:
        """Envía un mensaje de texto a un número de WhatsApp.

        Si kwargs contiene 'template_name', se envía como template message.
        Si no, se envía como mensaje de texto plano.

        Los mensajes largos (> 65536 chars) se dividen automáticamente.

        Args:
            target:  Número de WhatsApp destino (ej: "521234567890").
            content: Texto del mensaje.
            media:   Adjuntos opcionales (no implementado en v2.0).
            **kwargs:
              template_name (str): Nombre del template de Meta.
              language (str):      Idioma del template (default: self._default_language).
              components (list):   Componentes del template.
              reply_to_message_id: Ignorado (WhatsApp no soporta reply nativo via API).
        """
        if not self._client:
            raise ChannelError("WhatsApp plugin no está iniciado")

        try:
            template_name = kwargs.get("template_name")

            if template_name:
                # Enviar como template (para notificaciones proactivas)
                await self._client.send_template_message(
                    to=target,
                    template_name=template_name,
                    language=kwargs.get("language", self._default_language),
                    components=kwargs.get("components"),
                )
            else:
                # Dividir mensajes largos
                chunks = self.split_message(content, 65536)
                for chunk in chunks:
                    await self._client.send_text_message(to=target, text=chunk)

        except Exception as exc:
            raise ChannelError(
                f"Error enviando mensaje WhatsApp a {target}: {exc}"
            ) from exc

    async def send_notification(
        self,
        to: str,
        template_name: str,
        language: str = "es",
        components: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Envía un template message de notificación proactiva.

        Los templates son necesarios para iniciar conversaciones o enviar
        mensajes fuera de la ventana de 24 horas de atención al cliente.

        El template debe estar previamente aprobado en Meta Business Manager.

        Args:
            to:            Número destino (ej: "521234567890").
            template_name: Nombre del template aprobado.
            language:      Código de idioma (default "es").
            components:    Variables y componentes del template, por ejemplo:
                           [{"type": "body", "parameters": [
                               {"type": "text", "text": "Juan"}
                           ]}]
        """
        if not self._client:
            raise ChannelError("WhatsApp plugin no está iniciado")
        try:
            await self._client.send_template_message(
                to=to,
                template_name=template_name,
                language=language,
                components=components or [],
            )
            logger.info("Notificación template '%s' enviada a %s", template_name, to)
        except Exception as exc:
            raise ChannelError(
                f"Error enviando notificación template '{template_name}' a {to}: {exc}"
            ) from exc

    async def send_reaction(
        self,
        target: str,
        message_id: str,
        emoji: str,
    ) -> None:
        """Envía una reacción emoji a un mensaje de WhatsApp.

        Args:
            target:     Número de WhatsApp destino.
            message_id: ID del mensaje (wamid.xxx).
            emoji:      Emoji a enviar (ej: "👍").
        """
        if not self._client:
            raise ChannelError("WhatsApp plugin no está iniciado")
        try:
            await self._client.send_reaction(
                to=target,
                message_id=message_id,
                emoji=emoji,
            )
        except Exception as exc:
            logger.warning("Error enviando reacción a %s/%s: %s", target, message_id, exc)

    async def send_file(
        self,
        target: str,
        file_path: str,
        filename: Optional[str] = None,
        caption: Optional[str] = None,
    ) -> bool:
        """Envía un archivo local como documento por WhatsApp Cloud API.

        Proceso:
          1. Detectar MIME type del archivo.
          2. Subir el archivo a los servidores de Meta (obtener media_id).
          3. Enviar mensaje de tipo 'document' con el media_id.

        Args:
            target:    Número de WhatsApp destino.
            file_path: Ruta al archivo local.
            filename:  Nombre del archivo para el destinatario.
            caption:   Texto de descripción del documento.

        Returns:
            True si se envió exitosamente.
        """
        if not self._client:
            return False
        try:
            import mimetypes
            from pathlib import Path

            mime = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
            fname = filename or Path(file_path).name

            # 1. Subir media a servidores de Meta
            media_id = await self._client.upload_media(file_path, mime)

            # 2. Enviar mensaje de documento
            payload: Dict[str, Any] = {
                "messaging_product": "whatsapp",
                "to": target,
                "type": "document",
                "document": {
                    "id": media_id,
                    "filename": fname,
                    "caption": caption or "",
                },
            }
            await self._client._post_message(payload)
            return True

        except Exception as exc:
            logger.error(
                "Error enviando archivo WhatsApp a %s: %s", target, exc
            )
            return False

    # ── DM policy (mismo sistema que Telegram) ─────────────

    def _check_dm_access(self, sender_id: str) -> str:
        """Verifica acceso según dm_policy.

        Returns:
            "allow"   — dejar pasar
            "pairing" — emitir código de pairing
            "deny"    — rechazar silenciosamente
        """
        policy = self._dm_policy
        if policy is None or policy == "open":
            return "allow"
        if policy == "disabled":
            return "deny"

        # Para "pairing" y "allowlist": verificar allowlist combinada
        from channels.pairing import is_sender_allowed
        if is_sender_allowed("whatsapp", sender_id, policy, self._allow_from):
            return "allow"

        # Si es pairing, emitir código; si es allowlist puro, denegar
        if policy == "pairing":
            return "pairing"
        return "deny"

    async def _send_pairing_challenge(self, sender_number: str) -> None:
        """Genera y envía un código de pairing al usuario por WhatsApp."""
        from channels.pairing import create_pairing_request

        code = create_pairing_request("whatsapp", sender_number)
        msg = (
            f"Para usar este bot, necesitas un código de emparejamiento.\n\n"
            f"Tu código: *{code}*\n\n"
            f"Comparte este código con el administrador para que apruebe tu acceso.\n"
            f"El administrador debe ejecutar:\n\n"
            f"    somer pairing approve whatsapp {code}\n\n"
            f"Una vez aprobado, podrás usar el bot normalmente."
        )
        if self._client:
            try:
                await self._client.send_text_message(to=sender_number, text=msg)
            except Exception as exc:
                logger.warning("Error enviando pairing challenge a %s: %s", sender_number, exc)

    async def send_typing(self, target: str) -> None:
        """WhatsApp no soporta typing indicators nativamente."""
        pass

    # ── Mensajería entrante (procesamiento de webhook) ────────

    async def _procesar_payload(self, payload: Dict[str, Any]) -> None:
        """Procesa el payload completo de Meta y despacha mensajes al agente.

        Parsea todos los mensajes del payload, marca como leídos si
        auto_read está activo, y crea IncomingMessage para cada uno.

        Args:
            payload: Payload JSON completo recibido del webhook de Meta.
        """
        from channels.whatsapp.webhook import parse_whatsapp_messages

        mensajes = parse_whatsapp_messages(payload)

        for m in mensajes:
            # Marcar como leído inmediatamente si está habilitado
            if self._auto_read and self._client and m.get("message_id"):
                try:
                    await self._client.mark_as_read(m["message_id"])
                except Exception as exc:
                    logger.debug("No se pudo marcar como leído: %s", exc)

            # ── Enforcement de dm_policy ──────────────────────
            sender_number = m["from_number"]
            access = self._check_dm_access(sender_number)
            if access == "deny":
                logger.info("WhatsApp: número no autorizado ignorado: %s", sender_number)
                continue
            if access == "pairing":
                await self._send_pairing_challenge(sender_number)
                continue

            # ── Transcripción de audio/voz ────────────────────
            if m["type"] == "audio":
                await self._handle_audio_message(m)
                continue

            # Construir el IncomingMessage normalizado
            incoming = IncomingMessage(
                channel=ChannelType.WHATSAPP,
                channel_user_id=m["from_number"],
                channel_thread_id=None,  # WhatsApp no tiene hilos
                content=m["content"],
                metadata={
                    "message_id": m["message_id"],
                    "timestamp": m["timestamp"],
                    "type": m["type"],
                    "contact_name": m["contact_name"],
                    "phone_number_id": m["phone_number_id"],
                    # chat_id = número del remitente (para responder con send_message)
                    "chat_id": m["from_number"],
                    # Guardar el mensaje raw para acceso a campos extra (media_id, etc.)
                    "raw": m["raw"],
                },
            )
            await self._dispatch_message(incoming)

    # ── Transcripción de audio ───────────────────────────────

    async def _handle_audio_message(self, m: Dict[str, Any]) -> None:
        """Descarga y transcribe un mensaje de audio/voz usando MediaPipeline.

        Sigue el mismo flujo que el plugin de Telegram:
          1. Envía indicador "Transcribiendo audio..."
          2. Descarga el audio desde la Graph API
          3. Guarda en archivo temporal
          4. Transcribe con MediaPipeline (OpenAI Whisper API o whisper CLI local)
          5. Despacha IncomingMessage con la transcripción como contenido

        Args:
            m: Dict normalizado del mensaje (de parse_whatsapp_messages).
        """
        sender_number = m["from_number"]
        raw = m["raw"]
        media_id = raw.get("audio", {}).get("id", "")
        mime_type = raw.get("audio", {}).get("mime_type", "audio/ogg")

        if not media_id:
            logger.warning("Audio sin media_id de %s", sender_number)
            return

        # Notificar al usuario que estamos transcribiendo
        if self._client:
            try:
                await self._client.send_text_message(
                    to=sender_number, text="Transcribiendo audio..."
                )
            except Exception:
                pass

        # Descargar el audio
        tmp_path: Optional[Path] = None
        try:
            if not self._client:
                logger.error("Cliente WhatsApp no disponible para descargar audio")
                return

            audio_bytes = await self._client.download_media(media_id)

            # Determinar extensión según MIME type
            ext = ".ogg"
            if "mp4" in mime_type or "m4a" in mime_type:
                ext = ".m4a"
            elif "mpeg" in mime_type or "mp3" in mime_type:
                ext = ".mp3"
            elif "wav" in mime_type:
                ext = ".wav"
            elif "opus" in mime_type:
                ext = ".opus"

            tmp_fd, tmp_str = tempfile.mkstemp(suffix=ext, prefix="somer_wa_voice_")
            tmp_path = Path(tmp_str)
            os.close(tmp_fd)
            tmp_path.write_bytes(audio_bytes)

        except Exception as exc:
            logger.error("Error descargando audio de WhatsApp: %s", exc)
            if self._client:
                try:
                    await self._client.send_text_message(
                        to=sender_number,
                        text="No pude descargar el audio. Intenta de nuevo.",
                    )
                except Exception:
                    pass
            return

        # Transcribir usando MediaPipeline (mismo que Telegram)
        transcript = ""
        try:
            from media.pipeline import MediaPipeline

            pipeline = MediaPipeline()
            media_file = pipeline.process(str(tmp_path))
            transcript = await pipeline.transcribe(media_file)
        except Exception as exc:
            logger.error("Error transcribiendo audio de WhatsApp: %s", exc, exc_info=True)
            transcript = ""

        # Limpiar archivo temporal
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass

        # Verificar resultado de la transcripción
        if not transcript or transcript.startswith("[Transcripci\u00f3n no disponible"):
            if self._client:
                try:
                    await self._client.send_text_message(
                        to=sender_number,
                        text=(
                            "No pude transcribir el audio. Aseg\u00farate de que "
                            "OPENAI_API_KEY est\u00e9 configurada o whisper instalado."
                        ),
                    )
                except Exception:
                    pass
            return

        # Despachar como mensaje de texto con metadata de audio
        duration_secs = raw.get("audio", {}).get("duration", None)

        incoming = IncomingMessage(
            channel=ChannelType.WHATSAPP,
            channel_user_id=sender_number,
            channel_thread_id=None,
            content=transcript,
            metadata={
                "message_id": m["message_id"],
                "timestamp": m["timestamp"],
                "type": m["type"],
                "contact_name": m["contact_name"],
                "phone_number_id": m["phone_number_id"],
                "chat_id": sender_number,
                "raw": raw,
                "is_voice": True,
                "original_transcript": transcript,
                "duration_secs": duration_secs,
            },
        )
        await self._dispatch_message(incoming)

    # ── Media ─────────────────────────────────────────────────

    async def download_media(
        self,
        media_id: str,
        destination: Optional[str] = None,
    ) -> Optional[str]:
        """Descarga un media recibido por WhatsApp y lo guarda en disco.

        Args:
            media_id:    ID del media recibido en el webhook.
            destination: Ruta donde guardar. Si es None, usa un archivo temporal.

        Returns:
            Ruta al archivo descargado o None si hubo error.
        """
        if not self._client:
            return None
        try:
            import tempfile

            contenido = await self._client.download_media(media_id)

            if destination:
                ruta = destination
            else:
                _, ruta = tempfile.mkstemp(prefix="somer_wa_media_")

            with open(ruta, "wb") as f:
                f.write(contenido)

            logger.debug("Media %s descargado en %s", media_id, ruta)
            return ruta
        except Exception as exc:
            logger.error("Error descargando media %s: %s", media_id, exc)
            return None

    # ── Health check ──────────────────────────────────────────

    async def health_check(self) -> bool:
        """Verifica que el plugin está corriendo y el cliente está activo."""
        return self._running and self._client is not None
