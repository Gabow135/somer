"""Pairing store — autenticación de usuarios por código de emparejamiento.

Inspirado en OpenClaw: pairing-store.ts.
Genera códigos temporales de 8 caracteres que el usuario recibe en /start
y el administrador aprueba vía CLI. Al aprobar, el sender_id se agrega
al allowlist persistente del canal.

Almacenamiento:
  ~/.somer/oauth/<channel>-pairing.json      — solicitudes pendientes
  ~/.somer/oauth/<channel>-allowFrom.json    — IDs aprobados
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Alfabeto base36 sin caracteres ambiguos (0/O, 1/I)
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 8
_PAIRING_TTL_SECS = 3600  # 1 hora
_MAX_PENDING = 3  # máximo de solicitudes pendientes por canal


def _oauth_dir() -> Path:
    """Retorna el directorio de oauth, creándolo si no existe."""
    from shared.constants import DEFAULT_HOME
    d = DEFAULT_HOME / "oauth"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _pairing_path(channel: str) -> Path:
    return _oauth_dir() / f"{channel}-pairing.json"


def _allowfrom_path(channel: str) -> Path:
    return _oauth_dir() / f"{channel}-allowFrom.json"


# ── Generación de código ──────────────────────────────────────


def _generate_code(existing: List[str], max_attempts: int = 500) -> str:
    """Genera un código único de 8 caracteres base36."""
    import os
    import struct

    alpha_len = len(_ALPHABET)
    for _ in range(max_attempts):
        # Generar bytes aleatorios criptográficamente seguros
        rand_bytes = os.urandom(_CODE_LENGTH * 2)
        code = ""
        for i in range(_CODE_LENGTH):
            val = struct.unpack("H", rand_bytes[i * 2:(i + 1) * 2])[0]
            code += _ALPHABET[val % alpha_len]
        if code not in existing:
            return code
    raise RuntimeError("No se pudo generar un código único tras %d intentos" % max_attempts)


# ── Lectura/escritura atómica de JSON ─────────────────────────


def _read_json(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        logger.warning("Error leyendo %s, retornando vacío", path)
        return []


def _write_json(path: Path, data: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


# ── Allowlist ─────────────────────────────────────────────────


def load_allowlist(channel: str) -> List[str]:
    """Carga la lista de IDs permitidos para un canal."""
    path = _allowfrom_path(channel)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [str(x) for x in data] if isinstance(data, list) else []
    except Exception:
        return []


def save_allowlist(channel: str, ids: List[str]) -> None:
    """Guarda la lista de IDs permitidos."""
    path = _allowfrom_path(channel)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json_simple(path, ids)


def add_to_allowlist(channel: str, sender_id: str) -> bool:
    """Agrega un sender_id al allowlist. Retorna True si es nuevo."""
    ids = load_allowlist(channel)
    if sender_id in ids:
        return False
    ids.append(sender_id)
    save_allowlist(channel, ids)
    return True


def remove_from_allowlist(channel: str, sender_id: str) -> bool:
    """Remueve un sender_id del allowlist. Retorna True si existía."""
    ids = load_allowlist(channel)
    if sender_id not in ids:
        return False
    ids.remove(sender_id)
    save_allowlist(channel, ids)
    return True


def _write_json_simple(path: Path, data: Any) -> None:
    """Escritura atómica de cualquier dato JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


# ── Pairing requests ─────────────────────────────────────────


def _prune_expired(requests: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Elimina solicitudes expiradas (TTL 1h)."""
    now = time.time()
    return [r for r in requests if now - r.get("created_at", 0) < _PAIRING_TTL_SECS]


def list_pending(channel: str) -> List[Dict[str, Any]]:
    """Lista solicitudes de pairing pendientes para un canal."""
    requests = _read_json(_pairing_path(channel))
    requests = _prune_expired(requests)
    _write_json(_pairing_path(channel), requests)
    return requests


def create_pairing_request(
    channel: str,
    sender_id: str,
    metadata: Optional[Dict[str, str]] = None,
) -> str:
    """Crea una solicitud de pairing y retorna el código generado.

    Si el usuario ya tiene un código pendiente no expirado, retorna ese mismo.
    Limita a MAX_PENDING solicitudes por canal (elimina las más antiguas).
    """
    requests = _read_json(_pairing_path(channel))
    requests = _prune_expired(requests)

    # Si ya tiene un código pendiente, retornarlo
    for req in requests:
        if req.get("sender_id") == sender_id:
            return req["code"]

    # Generar código único
    existing_codes = [r["code"] for r in requests]
    code = _generate_code(existing_codes)

    # Limitar pending (eliminar los más antiguos si excede)
    while len(requests) >= _MAX_PENDING:
        requests.pop(0)

    requests.append({
        "code": code,
        "sender_id": sender_id,
        "created_at": time.time(),
        "metadata": metadata or {},
    })

    _write_json(_pairing_path(channel), requests)
    logger.info("Pairing code generado para %s/%s: %s", channel, sender_id, code)
    return code


def approve_pairing(channel: str, code: str) -> Optional[Dict[str, Any]]:
    """Aprueba un código de pairing.

    Retorna la solicitud aprobada (con sender_id) o None si no se encontró.
    Al aprobar, el sender_id se agrega automáticamente al allowlist.
    """
    code = code.upper().strip()
    requests = _read_json(_pairing_path(channel))
    requests = _prune_expired(requests)

    found = None
    remaining = []
    for req in requests:
        if req["code"] == code and found is None:
            found = req
        else:
            remaining.append(req)

    if not found:
        return None

    # Guardar pending sin la solicitud aprobada
    _write_json(_pairing_path(channel), remaining)

    # Agregar al allowlist
    sender_id = found["sender_id"]
    add_to_allowlist(channel, sender_id)
    logger.info(
        "Pairing aprobado para %s: sender=%s code=%s",
        channel, sender_id, code,
    )
    return found


def reject_pairing(channel: str, code: str) -> Optional[Dict[str, Any]]:
    """Rechaza/elimina un código de pairing pendiente."""
    code = code.upper().strip()
    requests = _read_json(_pairing_path(channel))

    found = None
    remaining = []
    for req in requests:
        if req["code"] == code and found is None:
            found = req
        else:
            remaining.append(req)

    if found:
        _write_json(_pairing_path(channel), remaining)
        logger.info("Pairing rechazado para %s: code=%s", channel, code)

    return found


def is_sender_allowed(
    channel: str,
    sender_id: str,
    dm_policy: Optional[str],
    config_allow_from: Optional[List[str]] = None,
) -> bool:
    """Verifica si un sender está autorizado según la política del canal.

    Args:
        channel: ID del canal (ej: "telegram")
        sender_id: ID del remitente
        dm_policy: Política DM ("pairing", "allowlist", "open", "disabled", None)
        config_allow_from: Lista de IDs permitidos desde config

    Returns:
        True si el sender está autorizado.
    """
    if dm_policy is None or dm_policy == "open":
        return True

    if dm_policy == "disabled":
        return False

    # Para "pairing" y "allowlist": verificar allowlist combinada
    # 1. Config allow_from
    if config_allow_from:
        normalized = [str(x).strip() for x in config_allow_from]
        if sender_id in normalized or "*" in normalized:
            return True

    # 2. Pairing store allowlist
    pairing_allowlist = load_allowlist(channel)
    if sender_id in pairing_allowlist:
        return True

    return False
