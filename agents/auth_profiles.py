"""Gestión de perfiles de autenticación con rotación para modelos.

Portado de OpenClaw: auth-profiles.ts, auth-profiles/order.ts,
auth-profiles/usage.ts, auth-profiles/session-override.ts,
api-key-rotation.ts.

Implementa:
- Perfiles de auth con cooldown y backoff exponencial
- Rotación entre perfiles cuando uno falla (rate limit, billing)
- Ordenamiento por disponibilidad y prioridad
- Session-level overrides de perfil
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from providers.base import AuthProfile

logger = logging.getLogger(__name__)


class AuthProfileManager:
    """Gestiona perfiles de auth con cooldown y rotación para múltiples providers.

    Portado de OpenClaw: auth-profiles.ts, api-key-rotation.ts.
    """

    def __init__(self) -> None:
        self._profiles: Dict[str, AuthProfile] = {}
        self._rotation_order: List[str] = []
        self._last_used_index: int = 0
        self._session_overrides: Dict[str, str] = {}  # session_key → provider_id

    def get_or_create(
        self, provider_id: str, cooldown_secs: float = 60.0
    ) -> AuthProfile:
        """Obtiene o crea un perfil de autenticación."""
        if provider_id not in self._profiles:
            self._profiles[provider_id] = AuthProfile(provider_id, cooldown_secs)
            if provider_id not in self._rotation_order:
                self._rotation_order.append(provider_id)
        return self._profiles[provider_id]

    def is_available(self, provider_id: str) -> bool:
        """Verifica si un provider está disponible."""
        profile = self._profiles.get(provider_id)
        return profile.is_available if profile else True

    def record_success(self, provider_id: str) -> None:
        """Registra un uso exitoso."""
        profile = self._profiles.get(provider_id)
        if profile:
            profile.record_success()

    def record_failure(
        self, provider_id: str, is_billing: bool = False
    ) -> float:
        """Registra un fallo y aplica cooldown."""
        profile = self.get_or_create(provider_id)
        return profile.record_failure(is_billing=is_billing)

    def available_providers(self) -> List[str]:
        """Lista providers disponibles."""
        return [pid for pid, p in self._profiles.items() if p.is_available]

    def reset_all(self) -> None:
        """Resetea todos los perfiles."""
        for profile in self._profiles.values():
            profile.reset()
        self._last_used_index = 0

    def status(self) -> Dict[str, Dict[str, Any]]:
        """Estado de todos los perfiles."""
        return {
            pid: {
                "available": p.is_available,
                "failures": p.failure_count,
            }
            for pid, p in self._profiles.items()
        }

    # ── Rotación (portado de OpenClaw: api-key-rotation.ts) ───

    def set_rotation_order(self, order: List[str]) -> None:
        """Establece el orden de rotación de providers.

        Portado de OpenClaw: auth-profiles/order.ts → resolveAuthProfileOrder.
        """
        self._rotation_order = list(order)
        self._last_used_index = 0

    def next_available(self) -> Optional[str]:
        """Obtiene el siguiente provider disponible en la rotación.

        Portado de OpenClaw: api-key-rotation.ts → rotation logic.
        Implementa round-robin entre providers disponibles.

        Returns:
            Provider ID o None si ninguno disponible.
        """
        if not self._rotation_order:
            available = self.available_providers()
            return available[0] if available else None

        n = len(self._rotation_order)
        for offset in range(n):
            idx = (self._last_used_index + offset) % n
            pid = self._rotation_order[idx]
            if self.is_available(pid):
                self._last_used_index = (idx + 1) % n
                return pid

        return None

    def ordered_available(self) -> List[str]:
        """Lista providers disponibles en orden de rotación.

        Portado de OpenClaw: auth-profiles/order.ts → orderProfilesByMode.
        Retorna providers disponibles primero (en orden de rotación),
        seguidos de los que están en cooldown (ordenados por expiración).
        """
        available: List[str] = []
        in_cooldown: List[Tuple[float, str]] = []

        order = self._rotation_order or list(self._profiles.keys())
        for pid in order:
            profile = self._profiles.get(pid)
            if profile is None:
                continue
            if profile.is_available:
                available.append(pid)
            else:
                until = profile._cooldown_until
                in_cooldown.append((until, pid))

        in_cooldown.sort(key=lambda x: x[0])
        return available + [pid for _, pid in in_cooldown]

    def soonest_expiry(self) -> Optional[float]:
        """Retorna el timestamp de expiración del cooldown más cercano.

        Portado de OpenClaw: usage.ts → getSoonestCooldownExpiry.
        """
        soonest: Optional[float] = None
        for profile in self._profiles.values():
            if not profile.is_available:
                until = profile._cooldown_until
                if until > 0 and (soonest is None or until < soonest):
                    soonest = until
        return soonest

    # ── Session overrides ─────────────────────────────────────

    def set_session_override(
        self, session_key: str, provider_id: str
    ) -> None:
        """Establece un override de perfil para una sesión.

        Portado de OpenClaw: auth-profiles/session-override.ts.
        """
        self._session_overrides[session_key] = provider_id
        logger.debug(
            "Session override: %s → %s", session_key, provider_id
        )

    def clear_session_override(self, session_key: str) -> None:
        """Limpia el override de perfil para una sesión."""
        self._session_overrides.pop(session_key, None)

    def get_session_override(self, session_key: str) -> Optional[str]:
        """Obtiene el override de perfil para una sesión."""
        return self._session_overrides.get(session_key)

    def resolve_for_session(self, session_key: str) -> Optional[str]:
        """Resuelve el provider a usar para una sesión.

        Prioridad: session override > rotación normal.
        """
        override = self.get_session_override(session_key)
        if override and self.is_available(override):
            return override
        return self.next_available()
