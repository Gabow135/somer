"""Plugin de canal Telegram — polling real con python-telegram-bot v21+."""

from __future__ import annotations

import asyncio
import logging
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


class TelegramPlugin(ChannelPlugin):
    """Plugin para Telegram usando python-telegram-bot v21+.

    Arranca polling real para recibir mensajes.
    Soporta dm_policy: pairing | allowlist | open | disabled.
    """

    def __init__(self) -> None:
        super().__init__(
            plugin_id="telegram",
            meta=ChannelMeta(
                id="telegram",
                name="Telegram",
                version="2.0.0",
                description="Telegram Bot channel plugin",
            ),
            capabilities=ChannelCapabilities(
                supports_threads=True,
                supports_reactions=True,
                supports_media=True,
                supports_editing=True,
                supports_deletion=True,
                max_message_length=4096,
            ),
        )
        self._app: Any = None
        self._token: Optional[str] = None
        self._polling_task: Optional[asyncio.Task] = None  # type: ignore[type-arg]
        self._dm_policy: Optional[str] = None
        self._allow_from: Optional[List[str]] = None

    async def setup(self, config: Dict[str, Any]) -> None:
        """Configura el token del bot y las políticas de acceso."""
        import os
        token_env = config.get("token_env", "TELEGRAM_BOT_TOKEN")
        self._token = config.get("token") or os.environ.get(token_env)
        if not self._token:
            raise ChannelSetupError(
                f"Token de Telegram no encontrado. Configura {token_env}"
            )
        # Políticas de acceso (inyectadas por gateway bootstrap)
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
            "Telegram plugin configurado (token: %s..., dm_policy: %s)",
            self._token[:8], policy_label,
        )

    def _is_dm(self, chat_type: str) -> bool:
        """Retorna True si el chat es un DM (mensaje privado)."""
        return chat_type == "private"

    def _check_dm_access(self, sender_id: str, chat_type: str) -> str:
        """Verifica acceso DM según dm_policy.

        Returns:
            "allow" — dejar pasar
            "pairing" — emitir código de pairing
            "deny" — rechazar silenciosamente
        """
        # Grupos/supergrupos no aplican dm_policy
        if not self._is_dm(chat_type):
            return "allow"

        policy = self._dm_policy
        if policy is None or policy == "open":
            return "allow"
        if policy == "disabled":
            return "deny"

        # Para "pairing" y "allowlist": verificar allowlist combinada
        from channels.pairing import is_sender_allowed
        if is_sender_allowed("telegram", sender_id, policy, self._allow_from):
            return "allow"

        # Si es pairing, emitir código; si es allowlist puro, denegar
        if policy == "pairing":
            return "pairing"
        return "deny"

    async def start(self) -> None:
        """Inicia el bot con polling real."""
        if not self._token:
            raise ChannelSetupError("Ejecuta setup() primero")

        try:
            from telegram import Update
            from telegram.ext import (
                ApplicationBuilder,
                CommandHandler,
                ContextTypes,
                MessageHandler,
                filters,
            )
        except ImportError:
            raise ChannelError(
                "python-telegram-bot no instalado. Ejecuta: pip install python-telegram-bot"
            )

        # Crear la aplicación
        self._app = ApplicationBuilder().token(self._token).build()

        # Handler de mensajes de texto
        async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            if not update.message or not update.message.text:
                return
            if not update.message.from_user:
                return

            sender_id = str(update.message.from_user.id)
            chat_type = update.message.chat.type if update.message.chat else "private"

            # Enforcement de dm_policy
            access = self._check_dm_access(sender_id, chat_type)
            if access == "deny":
                logger.debug("DM denegado para %s (policy=%s)", sender_id, self._dm_policy)
                return
            if access == "pairing":
                await self._send_pairing_challenge(update, sender_id)
                return

            msg = IncomingMessage(
                channel=ChannelType.TELEGRAM,
                channel_user_id=sender_id,
                channel_thread_id=(
                    str(update.message.message_thread_id)
                    if update.message.message_thread_id
                    else None
                ),
                content=update.message.text,
                metadata={
                    "chat_id": str(update.message.chat_id),
                    "message_id": update.message.message_id,
                    "username": update.message.from_user.username or "",
                    "first_name": update.message.from_user.first_name or "",
                    "chat_type": chat_type,
                },
            )
            await self._dispatch_message(msg)

        # Handler de /start
        async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            if not update.message or not update.message.from_user:
                return

            sender_id = str(update.message.from_user.id)
            chat_type = update.message.chat.type if update.message.chat else "private"

            # Si dm_policy es pairing y el usuario no está en allowlist → generar código
            access = self._check_dm_access(sender_id, chat_type)

            if access == "deny":
                if update.message:
                    await update.message.reply_text(
                        "Lo siento, no tienes acceso a este bot."
                    )
                return

            if access == "pairing":
                await self._send_pairing_challenge(update, sender_id)
                return

            # Usuario autorizado — saludo normal
            if update.message:
                await update.message.reply_text(
                    "Hola! Soy SOMER, tu asistente. Escríbeme lo que necesites."
                )

        # Handler de mensajes de voz y audio
        async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            if not update.message or not update.message.from_user:
                return

            sender_id = str(update.message.from_user.id)
            chat_type = update.message.chat.type if update.message.chat else "private"

            # Enforcement de dm_policy
            access = self._check_dm_access(sender_id, chat_type)
            if access == "deny":
                return
            if access == "pairing":
                await self._send_pairing_challenge(update, sender_id)
                return

            voice = update.message.voice
            audio = update.message.audio
            media_obj = voice or audio
            if not media_obj:
                return

            chat_id = str(update.message.chat_id)

            # Indicar que estamos procesando (typing + texto)
            try:
                await context.bot.send_chat_action(chat_id=int(chat_id), action="typing")
                await update.message.reply_text("Transcribiendo audio...")
            except Exception:
                pass

            # Descargar archivo de audio
            tmp_path: Optional[Path] = None
            try:
                tg_file = await media_obj.get_file()
                suffix = ".ogg" if voice else (
                    f".{audio.file_name.rsplit('.', 1)[-1]}"
                    if audio and audio.file_name and "." in audio.file_name
                    else ".ogg"
                )
                tmp_fd, tmp_str = tempfile.mkstemp(suffix=suffix, prefix="somer_voice_")
                tmp_path = Path(tmp_str)
                import os as _os
                _os.close(tmp_fd)
                await tg_file.download_to_drive(str(tmp_path))
            except Exception as exc:
                logger.error("Error descargando audio de Telegram: %s", exc)
                try:
                    await update.message.reply_text(
                        "No pude descargar el audio. Intenta de nuevo."
                    )
                except Exception:
                    pass
                return

            # Transcribir
            transcript = ""
            try:
                from media.pipeline import MediaPipeline
                pipeline = MediaPipeline()
                media_file = pipeline.process(str(tmp_path))
                transcript = await pipeline.transcribe(media_file)
            except Exception as exc:
                logger.error("Error transcribiendo audio: %s", exc, exc_info=True)
                transcript = ""

            # Limpiar archivo temporal
            if tmp_path and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass

            if not transcript or transcript.startswith("[Transcripción no disponible"):
                try:
                    await update.message.reply_text(
                        "No pude transcribir el audio. Asegúrate de que "
                        "OPENAI_API_KEY esté configurada o whisper instalado."
                    )
                except Exception:
                    pass
                return

            # Despachar como mensaje de texto con metadata de audio
            caption = update.message.caption or ""
            content = transcript
            if caption:
                content = f"{caption}\n\n[Audio transcrito]: {transcript}"

            msg = IncomingMessage(
                channel=ChannelType.TELEGRAM,
                channel_user_id=sender_id,
                channel_thread_id=(
                    str(update.message.message_thread_id)
                    if update.message.message_thread_id
                    else None
                ),
                content=content,
                metadata={
                    "chat_id": chat_id,
                    "message_id": update.message.message_id,
                    "username": update.message.from_user.username or "",
                    "first_name": update.message.from_user.first_name or "",
                    "chat_type": chat_type,
                    "is_voice": True,
                    "original_transcript": transcript,
                    "duration_secs": getattr(media_obj, "duration", None),
                },
            )
            await self._dispatch_message(msg)

        self._app.add_handler(CommandHandler("start", handle_start))
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
        self._app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))

        # Inicializar y arrancar polling (con retry para DNS temporales)
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                await self._app.initialize()
                break
            except Exception as exc:
                if attempt == max_retries:
                    raise ChannelError(
                        f"No se pudo conectar a Telegram después de {max_retries} intentos: {exc}"
                    ) from exc
                logger.warning(
                    "Telegram intento %d/%d falló: %s. Reintentando en %ds...",
                    attempt, max_retries, exc, attempt * 2,
                )
                await asyncio.sleep(attempt * 2)

        await self._app.start()

        if self._app.updater:
            await self._app.updater.start_polling(
                drop_pending_updates=True,
                allowed_updates=Update.ALL_TYPES,
            )

        self._running = True

        # Obtener info del bot para confirmar
        bot_info = await self._app.bot.get_me()
        logger.info(
            "Telegram bot iniciado: @%s (%s)",
            bot_info.username, bot_info.first_name,
        )
        from rich.console import Console
        Console().print(
            f"  [green]Telegram bot activo: @{bot_info.username}[/green]"
        )

    async def _send_pairing_challenge(self, update: Any, sender_id: str) -> None:
        """Genera y envía un código de pairing al usuario."""
        from channels.pairing import create_pairing_request

        username = ""
        first_name = ""
        if update.message and update.message.from_user:
            username = update.message.from_user.username or ""
            first_name = update.message.from_user.first_name or ""

        code = create_pairing_request(
            channel="telegram",
            sender_id=sender_id,
            metadata={
                "username": username,
                "first_name": first_name,
            },
        )

        msg = (
            f"Para usar este bot, necesitas autorización.\n\n"
            f"Tu código de emparejamiento es:\n\n"
            f"    `{code}`\n\n"
            f"Comparte este código con el administrador del bot.\n"
            f"El administrador debe ejecutar:\n\n"
            f"    `somer pairing approve telegram {code}`\n\n"
            f"Una vez aprobado, podrás usar el bot normalmente."
        )

        if update.message:
            try:
                await update.message.reply_text(msg, parse_mode="Markdown")
            except Exception:
                await update.message.reply_text(msg)

    async def stop(self) -> None:
        """Detiene el polling y cierra el bot."""
        self._running = False
        if self._app:
            try:
                if self._app.updater and self._app.updater.running:
                    await self._app.updater.stop()
                if self._app.running:
                    await self._app.stop()
                await self._app.shutdown()
            except Exception as exc:
                logger.warning("Error deteniendo Telegram: %s", exc)
        self._app = None
        logger.info("Telegram plugin detenido")

    async def send_typing(self, target: str) -> None:
        """Envía indicador de 'escribiendo...' al chat de Telegram."""
        if not self._app or not self._app.bot:
            return
        try:
            await self._app.bot.send_chat_action(
                chat_id=int(target), action="typing"
            )
        except Exception as exc:
            logger.debug("Error enviando typing a %s: %s", target, exc)

    async def send_message(
        self,
        target: str,
        content: str,
        media: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> None:
        """Envía mensaje a un chat_id de Telegram.

        Args:
            target: chat_id destino.
            content: Texto del mensaje.
            media: Adjuntos opcionales.
            **kwargs: Parámetros extra. Soporta ``reply_to_message_id``
                para responder a un mensaje específico.
        """
        if not self._app or not self._app.bot:
            raise ChannelError("Telegram no está iniciado")

        reply_to = kwargs.get("reply_to_message_id")

        # Dividir mensajes largos (límite 4096 chars)
        chunks = self._split_message(content, 4096)

        for i, chunk in enumerate(chunks):
            # Solo reply_to en el primer chunk
            reply_id = reply_to if i == 0 else None
            try:
                await self._app.bot.send_message(
                    chat_id=int(target),
                    text=chunk,
                    parse_mode="Markdown",
                    reply_to_message_id=reply_id,
                )
            except Exception:
                # Fallback sin Markdown si falla el parseo
                try:
                    await self._app.bot.send_message(
                        chat_id=int(target),
                        text=chunk,
                        reply_to_message_id=reply_id,
                    )
                except Exception as exc:
                    raise ChannelError(f"Error enviando mensaje: {exc}") from exc

    async def send_file(
        self,
        target: str,
        file_path: str,
        filename: Optional[str] = None,
        caption: Optional[str] = None,
    ) -> bool:
        """Envía un archivo como documento a un chat de Telegram."""
        if not self._app or not self._app.bot:
            return False
        try:
            with open(file_path, "rb") as f:
                await self._app.bot.send_document(
                    chat_id=int(target),
                    document=f,
                    filename=filename or Path(file_path).name,
                    caption=caption,
                )
            return True
        except Exception as exc:
            logger.error("Error enviando archivo Telegram a %s: %s", target, exc)
            return False

    @staticmethod
    def _split_message(text: str, max_len: int) -> List[str]:
        """Divide un mensaje largo en chunks."""
        if len(text) <= max_len:
            return [text]

        chunks = []
        while text:
            if len(text) <= max_len:
                chunks.append(text)
                break
            # Buscar punto de corte en newline o espacio
            cut = text.rfind("\n", 0, max_len)
            if cut == -1:
                cut = text.rfind(" ", 0, max_len)
            if cut == -1:
                cut = max_len
            chunks.append(text[:cut])
            text = text[cut:].lstrip()
        return chunks
