"""Contexto de usuario para tool handlers — multi-usuario nativo.

Usa contextvars.ContextVar para inyectar el user_id activo en el
contexto de ejecución de cada request, de forma segura para asyncio.
"""

from __future__ import annotations

import os
from contextvars import ContextVar

# ContextVar para el user_id del usuario actual.
# Valor por defecto: "default" para compatibilidad con instalaciones existentes.
_current_user_id: ContextVar[str] = ContextVar("current_user_id", default="default")


def set_current_user_id(user_id: str) -> None:
    """Establece el user_id activo para el contexto de ejecución actual."""
    _current_user_id.set(user_id or "default")


def get_current_user_id() -> str:
    """Obtiene el user_id activo. Retorna 'default' si no se ha establecido."""
    return _current_user_id.get()


def get_google_token_path(service: str = "tasks") -> str:
    """Retorna la ruta del token de Google para el usuario actual."""
    uid = get_current_user_id()
    base = os.path.expanduser("~/.somer")
    if uid == "default":
        return os.path.join(base, f"google_{service}_token.json")
    return os.path.join(base, f"google_{service}_token_{uid}.json")
