"""Sistema pub/sub para eventos de sesión y transcript.

Portado de OpenClaw: transcript-events.ts.
Extiende el bus de eventos original con soporte para:
- Eventos de transcript (mensajes agregados/modificados)
- Listeners tipados para actualizaciones de transcript
- Emisión normalizada con validación de campos
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set

from shared.types import SessionTranscriptUpdate

logger = logging.getLogger(__name__)

# ── Tipos de callback ───────────────────────────────────────
EventCallback = Callable[[str, Dict[str, Any]], Coroutine[Any, Any, None]]
TranscriptListener = Callable[[SessionTranscriptUpdate], Coroutine[Any, Any, None]]
SyncTranscriptListener = Callable[[SessionTranscriptUpdate], None]


class SessionEventBus:
    """Pub/sub para eventos de sesión.

    Eventos estándar:
        session.created, session.message, session.closed,
        session.compacted, session.error

    Eventos de transcript (portados de OpenClaw):
        transcript.update — actualización del transcript de una sesión
    """

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[EventCallback]] = {}
        self._transcript_listeners: List[TranscriptListener] = []
        self._sync_transcript_listeners: List[SyncTranscriptListener] = []

    # ── Pub/sub genérico ────────────────────────────────────

    def subscribe(self, event_type: str, callback: EventCallback) -> None:
        """Suscribe un callback a un tipo de evento."""
        self._subscribers.setdefault(event_type, []).append(callback)

    def unsubscribe(self, event_type: str, callback: EventCallback) -> None:
        """Desuscribe un callback."""
        if event_type in self._subscribers:
            try:
                self._subscribers[event_type].remove(callback)
            except ValueError:
                pass

    async def emit(self, event_type: str, data: Dict[str, Any]) -> int:
        """Emite un evento a todos los suscriptores.

        Returns:
            Número de callbacks ejecutados.
        """
        callbacks = self._subscribers.get(event_type, [])
        count = 0
        for cb in callbacks:
            try:
                await cb(event_type, data)
                count += 1
            except Exception:
                logger.exception("Error en event callback para %s", event_type)
        return count

    def subscriber_count(self, event_type: str) -> int:
        return len(self._subscribers.get(event_type, []))

    def clear(self) -> None:
        """Limpia todos los suscriptores (genéricos y transcript)."""
        self._subscribers.clear()
        self._transcript_listeners.clear()
        self._sync_transcript_listeners.clear()

    # ── Transcript events (portado de OpenClaw) ─────────────

    def on_transcript_update(
        self, listener: TranscriptListener
    ) -> Callable[[], None]:
        """Registra un listener async para actualizaciones de transcript.

        Portado de OpenClaw: ``onSessionTranscriptUpdate``.

        Returns:
            Función para desuscribir el listener.
        """
        self._transcript_listeners.append(listener)

        def _unsub() -> None:
            try:
                self._transcript_listeners.remove(listener)
            except ValueError:
                pass

        return _unsub

    def on_transcript_update_sync(
        self, listener: SyncTranscriptListener
    ) -> Callable[[], None]:
        """Registra un listener síncrono para actualizaciones de transcript.

        Útil para bridges y logging donde no se necesita async.

        Returns:
            Función para desuscribir el listener.
        """
        self._sync_transcript_listeners.append(listener)

        def _unsub() -> None:
            try:
                self._sync_transcript_listeners.remove(listener)
            except ValueError:
                pass

        return _unsub

    async def emit_transcript_update(
        self,
        update: SessionTranscriptUpdate,
    ) -> None:
        """Emite una actualización de transcript normalizada.

        Portado de OpenClaw: ``emitSessionTranscriptUpdate``.
        Normaliza los campos y notifica a todos los listeners registrados.
        """
        normalized = _normalize_transcript_update(update)
        if normalized is None:
            return

        # Listeners síncronos primero (logging, bridges)
        for listener in self._sync_transcript_listeners:
            try:
                listener(normalized)
            except Exception:
                logger.exception("Error en sync transcript listener")

        # Listeners async
        for listener in self._transcript_listeners:
            try:
                await listener(normalized)
            except Exception:
                logger.exception("Error en async transcript listener")

        # También emitir como evento genérico para compatibilidad
        await self.emit("transcript.update", normalized.model_dump())

    def emit_transcript_update_sync(
        self,
        update: SessionTranscriptUpdate,
    ) -> None:
        """Emite una actualización de transcript de forma síncrona.

        Solo notifica a los listeners síncronos. Útil desde contextos
        donde no hay event loop disponible.
        """
        normalized = _normalize_transcript_update(update)
        if normalized is None:
            return

        for listener in self._sync_transcript_listeners:
            try:
                listener(normalized)
            except Exception:
                logger.exception("Error en sync transcript listener")

    @property
    def transcript_listener_count(self) -> int:
        """Cantidad total de transcript listeners (sync + async)."""
        return len(self._transcript_listeners) + len(self._sync_transcript_listeners)


# ── Utilidades internas ─────────────────────────────────────

def _normalize_transcript_update(
    update: SessionTranscriptUpdate,
) -> Optional[SessionTranscriptUpdate]:
    """Normaliza y valida una actualización de transcript.

    Portado de OpenClaw: lógica de normalización en
    ``emitSessionTranscriptUpdate``.

    Returns:
        Update normalizado, o None si el session_file está vacío.
    """
    session_file = update.session_file.strip()
    if not session_file:
        return None

    session_key: Optional[str] = None
    if update.session_key is not None:
        trimmed = update.session_key.strip()
        if trimmed:
            session_key = trimmed

    message_id: Optional[str] = None
    if update.message_id is not None:
        trimmed = update.message_id.strip()
        if trimmed:
            message_id = trimmed

    return SessionTranscriptUpdate(
        session_file=session_file,
        session_key=session_key,
        message=update.message,
        message_id=message_id,
    )
