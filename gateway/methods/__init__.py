"""Métodos RPC built-in del Gateway."""

from __future__ import annotations

from typing import Any, Dict

from shared.constants import VERSION


async def ping(params: Dict[str, Any]) -> Dict[str, Any]:
    """Health check."""
    return {"pong": True, "version": VERSION}


async def get_version(params: Dict[str, Any]) -> Dict[str, Any]:
    """Retorna la versión de SOMER."""
    return {"version": VERSION}


# Registro de métodos built-in
BUILTIN_METHODS = {
    "ping": ping,
    "version": get_version,
}
