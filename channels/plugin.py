"""Contrato base de plugin de canal — portado de OpenClaw adapters.

Define la clase abstracta ``ChannelPlugin`` con todas las interfaces necesarias
para un canal completo: ciclo de vida, envío/recepción de mensajes,
normalización, manejo de archivos/medios, rate limiting, indicadores de
escritura y gestión del estado de conexión.
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple

from shared.types import (
    ChannelCapabilities,
    ChannelMeta,
    ChannelType,
    IncomingMessage,
    OutgoingMessage,
)

logger = logging.getLogger(__name__)

# ── Tipos auxiliares ──────────────────────────────────────────

MessageCallback = Callable[[IncomingMessage], Coroutine[Any, Any, None]]


class ConnectionState(str, Enum):
    """Estado de conexión de un plugin de canal."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    DISCONNECTING = "disconnecting"
    ERROR = "error"


class DeliveryMode(str, Enum):
    """Modo de entrega de mensajes salientes (inspirado en OpenClaw outbound)."""

    DIRECT = "direct"
    GATEWAY = "gateway"
    HYBRID = "hybrid"


class MediaType(str, Enum):
    """Tipo de archivo/media soportado por un canal."""

    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"
    STICKER = "sticker"
    VOICE = "voice"
    GIF = "gif"


class MediaAttachment:
    """Representación normalizada de un adjunto de media."""

    __slots__ = (
        "media_type", "url", "local_path", "mime_type",
        "filename", "size_bytes", "caption", "metadata",
    )

    def __init__(
        self,
        media_type: MediaType,
        url: Optional[str] = None,
        local_path: Optional[str] = None,
        mime_type: Optional[str] = None,
        filename: Optional[str] = None,
        size_bytes: Optional[int] = None,
        caption: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.media_type = media_type
        self.url = url
        self.local_path = local_path
        self.mime_type = mime_type
        self.filename = filename
        self.size_bytes = size_bytes
        self.caption = caption
        self.metadata = metadata or {}


class ChannelHealthStatus:
    """Snapshot del estado de salud de un plugin."""

    __slots__ = (
        "connected", "running", "last_connected_at", "last_error",
        "last_message_at", "reconnect_attempts", "latency_ms",
        "connection_state",
    )

    def __init__(
        self,
        connected: bool = False,
        running: bool = False,
        last_connected_at: Optional[float] = None,
        last_error: Optional[str] = None,
        last_message_at: Optional[float] = None,
        reconnect_attempts: int = 0,
        latency_ms: Optional[float] = None,
        connection_state: ConnectionState = ConnectionState.DISCONNECTED,
    ) -> None:
        self.connected = connected
        self.running = running
        self.last_connected_at = last_connected_at
        self.last_error = last_error
        self.last_message_at = last_message_at
        self.reconnect_attempts = reconnect_attempts
        self.latency_ms = latency_ms
        self.connection_state = connection_state


class RateLimitInfo:
    """Información de rate-limiting del canal."""

    __slots__ = (
        "max_per_second", "max_per_minute", "remaining", "reset_at",
    )

    def __init__(
        self,
        max_per_second: Optional[float] = None,
        max_per_minute: Optional[float] = None,
        remaining: Optional[int] = None,
        reset_at: Optional[float] = None,
    ) -> None:
        self.max_per_second = max_per_second
        self.max_per_minute = max_per_minute
        self.remaining = remaining
        self.reset_at = reset_at


# ── Plugin base ───────────────────────────────────────────────


class ChannelPlugin(ABC):
    """Clase base abstracta para plugins de canal.

    Portada de la arquitectura de adapters de OpenClaw: cada canal
    (Telegram, Slack, Discord, etc.) implementa esta interfaz completa.

    Superficies del plugin (inspiradas en OpenClaw ChannelPlugin):
      - Ciclo de vida: setup / start / stop / restart
      - Mensajería entrante: on_message / _dispatch_message
      - Mensajería saliente: send_message / send_media / send_typing
      - Normalización: normalize_incoming / normalize_outgoing
      - Estado de conexión: connection_state / health_check
      - Rate limiting: get_rate_limit / check_rate_limit
      - Medios: download_media / upload_media
    """

    def __init__(
        self,
        plugin_id: str,
        meta: ChannelMeta,
        capabilities: ChannelCapabilities,
        *,
        channel_type: Optional[ChannelType] = None,
        delivery_mode: DeliveryMode = DeliveryMode.DIRECT,
        text_chunk_limit: int = 4096,
        aliases: Optional[List[str]] = None,
    ) -> None:
        self.id = plugin_id
        self.meta = meta
        self.capabilities = capabilities
        self.channel_type: Optional[ChannelType] = channel_type
        self.delivery_mode = delivery_mode
        self.text_chunk_limit = text_chunk_limit
        self.aliases: List[str] = aliases or []

        # Estado interno
        self._callbacks: List[MessageCallback] = []
        self._running: bool = False
        self._connection_state: ConnectionState = ConnectionState.DISCONNECTED
        self._last_connected_at: Optional[float] = None
        self._last_error: Optional[str] = None
        self._last_message_at: Optional[float] = None
        self._reconnect_attempts: int = 0
        self._config: Dict[str, Any] = {}
        self._started_at: Optional[float] = None
        self._stopped_at: Optional[float] = None

        # Rate limiting interno
        self._rate_limit: Optional[RateLimitInfo] = None
        self._send_count_window: List[float] = []

    # ── Ciclo de vida ─────────────────────────────────────────

    @abstractmethod
    async def setup(self, config: Dict[str, Any]) -> None:
        """Configura el plugin con credenciales y opciones.

        Args:
            config: Diccionario con credenciales, tokens, opciones del canal.
        """
        ...

    @abstractmethod
    async def start(self) -> None:
        """Inicia el plugin — empieza a escuchar mensajes entrantes."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Detiene el plugin limpiamente."""
        ...

    async def restart(self) -> None:
        """Reinicia el plugin (stop + start).

        Útil para reconexión o recarga de configuración.
        """
        self._connection_state = ConnectionState.RECONNECTING
        self._reconnect_attempts += 1
        logger.info("Reiniciando canal %s (intento %d)", self.id, self._reconnect_attempts)
        try:
            await self.stop()
            await self.start()
            self._reconnect_attempts = 0
        except Exception as exc:
            self._last_error = str(exc)
            self._connection_state = ConnectionState.ERROR
            logger.exception("Error reiniciando canal %s", self.id)
            raise

    # ── Mensajería saliente ───────────────────────────────────

    @abstractmethod
    async def send_message(
        self,
        target: str,
        content: str,
        media: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> None:
        """Envía un mensaje de texto a un target (chat_id, channel, etc.).

        Args:
            target: Identificador del destinatario en el canal.
            content: Contenido del mensaje.
            media: Lista opcional de adjuntos (legacy dict format).
            **kwargs: Parámetros específicos del canal (ej. reply_to_message_id).
        """
        ...

    async def send_media(
        self,
        target: str,
        attachment: MediaAttachment,
        caption: Optional[str] = None,
    ) -> None:
        """Envía un adjunto de media normalizado.

        Implementación por defecto: convierte a dict y llama a send_message.
        Los plugins concretos deberían sobrescribir esto.

        Args:
            target: Identificador del destinatario en el canal.
            attachment: Adjunto de media normalizado.
            caption: Texto de caption asociado al media.
        """
        media_dict: Dict[str, Any] = {
            "type": attachment.media_type.value,
            "url": attachment.url,
            "local_path": attachment.local_path,
            "mime_type": attachment.mime_type,
            "filename": attachment.filename,
        }
        media_dict.update(attachment.metadata)
        await self.send_message(
            target, caption or attachment.caption or "", media=[media_dict]
        )

    async def send_file(
        self,
        target: str,
        file_path: str,
        filename: Optional[str] = None,
        caption: Optional[str] = None,
    ) -> bool:
        """Envía un archivo local al target.

        Implementación por defecto: retorna False (no soportado).
        Los plugins concretos deben sobrescribir este método.

        Args:
            target: Identificador del destinatario.
            file_path: Ruta al archivo local.
            filename: Nombre del archivo para el destinatario.
            caption: Texto de caption asociado al archivo.

        Returns:
            True si se envió exitosamente.
        """
        return False

    async def send_typing(self, target: str) -> None:
        """Envía indicador de 'escribiendo...' al canal.

        Implementación por defecto: no-op. Los plugins que lo soporten
        deben sobrescribir este método.

        Args:
            target: Identificador del destinatario.
        """
        pass

    async def edit_message(
        self,
        target: str,
        message_id: str,
        new_content: str,
    ) -> None:
        """Edita un mensaje existente.

        Solo disponible si ``capabilities.supports_editing == True``.
        Implementación por defecto: no-op. Los plugins que lo soporten
        deben sobrescribir.

        Args:
            target: Identificador del chat/canal.
            message_id: ID del mensaje a editar.
            new_content: Nuevo contenido del mensaje.
        """
        pass

    async def delete_message(self, target: str, message_id: str) -> None:
        """Elimina un mensaje.

        Solo disponible si ``capabilities.supports_deletion == True``.
        Implementación por defecto: no-op.

        Args:
            target: Identificador del chat/canal.
            message_id: ID del mensaje a eliminar.
        """
        pass

    async def send_reaction(
        self,
        target: str,
        message_id: str,
        emoji: str,
    ) -> None:
        """Envía una reacción a un mensaje.

        Solo disponible si ``capabilities.supports_reactions == True``.
        Implementación por defecto: no-op.

        Args:
            target: Identificador del chat/canal.
            message_id: ID del mensaje objetivo.
            emoji: Emoji de la reacción.
        """
        pass

    # ── Mensajería entrante ───────────────────────────────────

    def on_message(self, callback: MessageCallback) -> None:
        """Registra un callback para mensajes entrantes.

        Args:
            callback: Función async que recibe un IncomingMessage.
        """
        self._callbacks.append(callback)

    def remove_callback(self, callback: MessageCallback) -> bool:
        """Elimina un callback previamente registrado.

        Returns:
            True si el callback fue encontrado y eliminado.
        """
        try:
            self._callbacks.remove(callback)
            return True
        except ValueError:
            return False

    async def _dispatch_message(self, message: IncomingMessage) -> None:
        """Despacha un mensaje entrante a todos los callbacks registrados.

        Los errores en callbacks individuales se loguean sin interrumpir
        el procesamiento de los demás.
        """
        self._last_message_at = time.time()
        for cb in self._callbacks:
            try:
                await cb(message)
            except Exception:
                logger.exception(
                    "Error en callback de canal %s", self.id
                )

    # ── Normalización ─────────────────────────────────────────

    def normalize_incoming(self, raw: Dict[str, Any]) -> Optional[IncomingMessage]:
        """Normaliza un mensaje crudo del canal a IncomingMessage.

        Implementación por defecto: retorna None (sin normalización).
        Los plugins concretos deben sobrescribir para convertir eventos
        nativos del canal.

        Args:
            raw: Diccionario con el evento/mensaje crudo del canal.

        Returns:
            IncomingMessage normalizado o None si el evento no es procesable.
        """
        return None

    def normalize_outgoing(self, message: OutgoingMessage) -> Dict[str, Any]:
        """Normaliza un OutgoingMessage al formato nativo del canal.

        Implementación por defecto: retorna dict mínimo.

        Args:
            message: Mensaje saliente normalizado de SOMER.

        Returns:
            Diccionario con el formato esperado por la API del canal.
        """
        return {
            "content": message.content,
            "media": message.media,
            "metadata": message.metadata,
        }

    # ── Manejo de media ───────────────────────────────────────

    async def download_media(
        self,
        media_id: str,
        destination: Optional[str] = None,
    ) -> Optional[str]:
        """Descarga un adjunto de media del canal.

        Args:
            media_id: Identificador del media en el canal.
            destination: Ruta de destino para guardar. Si es None, retorna
                         la ruta a un archivo temporal.

        Returns:
            Ruta al archivo descargado o None si no es soportado.
        """
        return None

    async def upload_media(
        self,
        target: str,
        file_path: str,
        media_type: Optional[MediaType] = None,
    ) -> Optional[str]:
        """Sube un archivo como media al canal.

        Args:
            target: Identificador del destinatario.
            file_path: Ruta al archivo local.
            media_type: Tipo de media, si es conocido.

        Returns:
            Identificador del media subido o None si no es soportado.
        """
        return None

    # ── Estado de conexión ────────────────────────────────────

    @property
    def is_running(self) -> bool:
        """True si el plugin está ejecutándose."""
        return self._running

    @property
    def connection_state(self) -> ConnectionState:
        """Estado actual de la conexión del canal."""
        return self._connection_state

    def _set_connection_state(self, state: ConnectionState) -> None:
        """Actualiza el estado de conexión (para uso interno del plugin)."""
        old = self._connection_state
        self._connection_state = state
        if state == ConnectionState.CONNECTED:
            self._last_connected_at = time.time()
            self._reconnect_attempts = 0
        logger.debug(
            "Canal %s: conexión %s → %s", self.id, old.value, state.value
        )

    def health_status(self) -> ChannelHealthStatus:
        """Retorna snapshot del estado de salud del plugin.

        Returns:
            ChannelHealthStatus con métricas de salud actuales.
        """
        return ChannelHealthStatus(
            connected=self._connection_state == ConnectionState.CONNECTED,
            running=self._running,
            last_connected_at=self._last_connected_at,
            last_error=self._last_error,
            last_message_at=self._last_message_at,
            reconnect_attempts=self._reconnect_attempts,
            connection_state=self._connection_state,
        )

    async def health_check(self) -> bool:
        """Verifica que el plugin está saludable.

        Implementación por defecto: retorna si está corriendo y conectado.
        Los plugins pueden sobrescribir con checks más elaborados (ping, etc.)

        Returns:
            True si el plugin está saludable.
        """
        return self._running and self._connection_state == ConnectionState.CONNECTED

    # ── Rate limiting ─────────────────────────────────────────

    def get_rate_limit(self) -> Optional[RateLimitInfo]:
        """Retorna la información de rate limiting actual.

        Returns:
            RateLimitInfo o None si el canal no tiene rate limits.
        """
        return self._rate_limit

    def _set_rate_limit(self, info: RateLimitInfo) -> None:
        """Establece los parámetros de rate limiting."""
        self._rate_limit = info

    def check_rate_limit(self) -> bool:
        """Verifica si se puede enviar un mensaje sin exceder el rate limit.

        Returns:
            True si está dentro del límite o no hay rate limit configurado.
        """
        if not self._rate_limit:
            return True

        now = time.time()

        # Limpiar ventana (últimos 60s)
        self._send_count_window = [
            t for t in self._send_count_window if now - t < 60.0
        ]

        if self._rate_limit.max_per_minute is not None:
            if len(self._send_count_window) >= self._rate_limit.max_per_minute:
                return False

        if self._rate_limit.max_per_second is not None:
            recent = sum(1 for t in self._send_count_window if now - t < 1.0)
            if recent >= self._rate_limit.max_per_second:
                return False

        return True

    def _record_send(self) -> None:
        """Registra un envío para el control de rate limiting."""
        self._send_count_window.append(time.time())

    # ── Utilidades ────────────────────────────────────────────

    def split_message(self, text: str, max_len: Optional[int] = None) -> List[str]:
        """Divide un mensaje largo en chunks respetando el límite del canal.

        Busca puntos de corte naturales (newline, espacio) antes de
        cortar en posiciones arbitrarias.

        Args:
            text: Texto a dividir.
            max_len: Límite máximo (por defecto: text_chunk_limit del plugin).

        Returns:
            Lista de fragmentos de texto.
        """
        limit = max_len or self.text_chunk_limit
        if len(text) <= limit:
            return [text]

        chunks: List[str] = []
        remaining = text
        while remaining:
            if len(remaining) <= limit:
                chunks.append(remaining)
                break
            # Buscar punto de corte natural
            cut = remaining.rfind("\n", 0, limit)
            if cut == -1:
                cut = remaining.rfind(" ", 0, limit)
            if cut == -1:
                cut = limit
            chunks.append(remaining[:cut])
            remaining = remaining[cut:].lstrip()
        return chunks

    def __repr__(self) -> str:
        state = "running" if self._running else "stopped"
        return f"<{self.__class__.__name__} id={self.id!r} state={state}>"
