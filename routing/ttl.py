"""TTL management — gestion de tiempo de vida para rutas y bindings.

Maneja la expiracion automatica de rutas de sesion y limpieza
periodica de entradas caducadas.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)


class TTLEntry:
    """Entrada con tiempo de vida."""

    __slots__ = ("key", "created_at", "last_activity", "ttl_secs", "metadata")

    def __init__(
        self,
        key: str,
        ttl_secs: float,
        metadata: Optional[Dict[str, object]] = None,
    ) -> None:
        self.key = key
        self.created_at = time.monotonic()
        self.last_activity = self.created_at
        self.ttl_secs = ttl_secs
        self.metadata = metadata or {}

    def touch(self) -> None:
        """Actualiza el timestamp de ultima actividad."""
        self.last_activity = time.monotonic()

    @property
    def is_expired(self) -> bool:
        """Verifica si la entrada ha expirado."""
        return (time.monotonic() - self.last_activity) >= self.ttl_secs

    @property
    def age_secs(self) -> float:
        """Edad en segundos desde la ultima actividad."""
        return time.monotonic() - self.last_activity

    @property
    def remaining_secs(self) -> float:
        """Segundos restantes antes de expirar."""
        remaining = self.ttl_secs - self.age_secs
        return max(0.0, remaining)


class TTLStore:
    """Almacen de entradas con TTL automatico.

    Provee registro, consulta y limpieza de entradas con tiempo de vida.
    Soporta callbacks de expiracion y limpieza periodica en background.

    Uso::

        store = TTLStore(default_ttl=3600.0)
        store.register("session:abc", ttl_secs=1800.0)
        store.touch("session:abc")

        if store.is_expired("session:abc"):
            store.remove("session:abc")

        # Limpieza manual
        expired = store.cleanup()
    """

    def __init__(
        self,
        default_ttl: float = 3600.0,
        on_expire: Optional[Callable[[str, TTLEntry], None]] = None,
        max_entries: int = 10000,
    ) -> None:
        self._entries: Dict[str, TTLEntry] = {}
        self._default_ttl = default_ttl
        self._on_expire = on_expire
        self._max_entries = max_entries
        self._cleanup_task: Optional[asyncio.Task[None]] = None

    def register(
        self,
        key: str,
        ttl_secs: Optional[float] = None,
        metadata: Optional[Dict[str, object]] = None,
    ) -> TTLEntry:
        """Registra una nueva entrada con TTL.

        Si ya existe, actualiza su TTL y metadata.
        """
        ttl = ttl_secs if ttl_secs is not None else self._default_ttl
        existing = self._entries.get(key)
        if existing is not None:
            existing.ttl_secs = ttl
            existing.touch()
            if metadata:
                existing.metadata.update(metadata)
            return existing

        entry = TTLEntry(key, ttl, metadata)
        self._entries[key] = entry

        # Eviccion si se excede el maximo
        if len(self._entries) > self._max_entries:
            self._evict_oldest()

        return entry

    def touch(self, key: str) -> bool:
        """Actualiza la actividad de una entrada.

        Returns:
            True si la entrada existe y no ha expirado.
        """
        entry = self._entries.get(key)
        if entry is None:
            return False
        if entry.is_expired:
            self._expire_entry(key, entry)
            return False
        entry.touch()
        return True

    def get(self, key: str) -> Optional[TTLEntry]:
        """Obtiene una entrada si existe y no ha expirado."""
        entry = self._entries.get(key)
        if entry is None:
            return None
        if entry.is_expired:
            self._expire_entry(key, entry)
            return None
        return entry

    def is_expired(self, key: str) -> bool:
        """Verifica si una entrada ha expirado (o no existe)."""
        entry = self._entries.get(key)
        if entry is None:
            return True
        return entry.is_expired

    def remove(self, key: str) -> bool:
        """Elimina una entrada. Retorna True si existia."""
        return self._entries.pop(key, None) is not None

    def cleanup(self) -> int:
        """Elimina todas las entradas expiradas.

        Returns:
            Cantidad de entradas eliminadas.
        """
        expired_keys = [
            key for key, entry in self._entries.items()
            if entry.is_expired
        ]
        for key in expired_keys:
            entry = self._entries.pop(key, None)
            if entry and self._on_expire:
                try:
                    self._on_expire(key, entry)
                except Exception:
                    logger.exception(
                        "Error en callback de expiracion para %s", key
                    )
        if expired_keys:
            logger.debug(
                "TTL cleanup: %d entradas expiradas eliminadas",
                len(expired_keys),
            )
        return len(expired_keys)

    def list_active(self) -> list:
        """Lista todas las entradas activas (no expiradas)."""
        return [
            entry for entry in self._entries.values()
            if not entry.is_expired
        ]

    @property
    def entry_count(self) -> int:
        """Cantidad total de entradas (incluye posibles expiradas)."""
        return len(self._entries)

    @property
    def active_count(self) -> int:
        """Cantidad de entradas activas."""
        return sum(
            1 for entry in self._entries.values()
            if not entry.is_expired
        )

    # ── Background cleanup ──────────────────────────────────

    async def start_cleanup_loop(
        self,
        interval_secs: float = 60.0,
    ) -> None:
        """Inicia un loop de limpieza periodica en background.

        Args:
            interval_secs: Intervalo entre limpiezas.
        """
        if self._cleanup_task is not None:
            return

        async def _loop() -> None:
            while True:
                await asyncio.sleep(interval_secs)
                try:
                    self.cleanup()
                except Exception:
                    logger.exception("Error en cleanup loop de TTL")

        self._cleanup_task = asyncio.create_task(_loop())
        logger.debug(
            "TTL cleanup loop iniciado (intervalo=%.0fs)", interval_secs
        )

    async def stop_cleanup_loop(self) -> None:
        """Detiene el loop de limpieza periodica."""
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
            logger.debug("TTL cleanup loop detenido")

    # ── Internos ────────────────────────────────────────────

    def _expire_entry(self, key: str, entry: TTLEntry) -> None:
        """Procesa la expiracion de una entrada."""
        self._entries.pop(key, None)
        if self._on_expire:
            try:
                self._on_expire(key, entry)
            except Exception:
                logger.exception(
                    "Error en callback de expiracion para %s", key
                )

    def _evict_oldest(self) -> None:
        """Expulsa la entrada mas antigua para mantener el limite."""
        if not self._entries:
            return
        # Primero intentar eliminar expiradas
        cleaned = self.cleanup()
        if cleaned > 0:
            return
        # Si no hay expiradas, eliminar la de menor actividad
        oldest_key = min(
            self._entries,
            key=lambda k: self._entries[k].last_activity,
        )
        entry = self._entries.pop(oldest_key, None)
        if entry:
            logger.debug(
                "TTL eviccion: eliminada entrada '%s' (edad=%.0fs)",
                oldest_key,
                entry.age_secs,
            )
