"""Gestión de credenciales SRI Ecuador — multi-usuario.

Almacena RUC/password cifrados con Fernet en SQLite (~/.somer/sri_credentials.db).
La clave de cifrado se lee de SRI_ENCRYPTION_KEY o se genera y guarda en ~/.somer/sri.key.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import stat
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_SOMER_DIR = Path.home() / ".somer"
_DB_PATH = _SOMER_DIR / "sri_credentials.db"
_KEY_PATH = _SOMER_DIR / "sri.key"


# ── Cifrado Fernet ────────────────────────────────────────────


def _get_fernet():
    """Retorna instancia Fernet con la key del entorno o archivo."""
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        return None

    # 1. Variable de entorno
    raw_key = os.environ.get("SRI_ENCRYPTION_KEY", "").strip()
    if raw_key:
        try:
            return Fernet(raw_key.encode() if isinstance(raw_key, str) else raw_key)
        except Exception as exc:
            logger.warning("SRI_ENCRYPTION_KEY inválida: %s — usando archivo de key", exc)

    # 2. Archivo ~/.somer/sri.key
    _SOMER_DIR.mkdir(parents=True, exist_ok=True)
    if _KEY_PATH.exists():
        key = _KEY_PATH.read_bytes().strip()
    else:
        key = Fernet.generate_key()
        _KEY_PATH.write_bytes(key)
        # Permisos 600
        _KEY_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)
        logger.info("Nueva Fernet key generada en %s", _KEY_PATH)

    return Fernet(key)


def encrypt_password(password: str) -> str:
    """Cifra un password. Retorna base64-url string.

    Si Fernet no está disponible usa base64 simple (inseguro, solo fallback).
    """
    fernet = _get_fernet()
    if fernet:
        return fernet.encrypt(password.encode()).decode()
    # Fallback base64 — INSEGURO, solo para compatibilidad mínima
    # TODO: instalar `cryptography` para cifrado real
    import base64
    return "b64:" + base64.b64encode(password.encode()).decode()


def decrypt_password(encrypted: str) -> str:
    """Descifra un password cifrado con encrypt_password."""
    if encrypted.startswith("b64:"):
        import base64
        return base64.b64decode(encrypted[4:]).decode()

    fernet = _get_fernet()
    if not fernet:
        raise RuntimeError("No se puede descifrar: cryptography no disponible")
    return fernet.decrypt(encrypted.encode()).decode()


# ── Base de datos ─────────────────────────────────────────────


def _get_db() -> sqlite3.Connection:
    """Abre la conexión SQLite y asegura que la tabla exista."""
    _SOMER_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sri_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ruc TEXT NOT NULL,
            password TEXT NOT NULL,
            alias TEXT,
            name TEXT,
            owner_user_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(ruc)
        )
    """)
    conn.commit()
    # Migration automática: agregar columna name si no existe (compatibilidad con BD existente)
    try:
        conn.execute("ALTER TABLE sri_users ADD COLUMN name TEXT")
        conn.commit()
    except Exception:
        pass  # Ya existe la columna, ignorar silenciosamente
    # Migration automática: agregar columna whatsapp_number si no existe
    try:
        conn.execute("ALTER TABLE sri_users ADD COLUMN whatsapp_number TEXT DEFAULT NULL")
        conn.commit()
    except Exception:
        pass  # Ya existe la columna, ignorar silenciosamente
    return conn


# ── Operaciones CRUD ──────────────────────────────────────────


def save_credentials(
    ruc: str,
    password: str,
    alias: Optional[str] = None,
    owner_user_id: Optional[str] = None,
    name: Optional[str] = None,
    whatsapp_number: Optional[str] = None,
) -> dict:
    """Guarda (INSERT OR REPLACE) credenciales SRI.

    Args:
        ruc: RUC del contribuyente (13 dígitos).
        password: Password del portal SRI.
        alias: Nombre amigable interno (ej: 'Empresa ABC').
        owner_user_id: ID del usuario propietario.
        name: Razón social o nombre completo del contribuyente (opcional).
        whatsapp_number: Número WhatsApp en formato internacional sin + (ej: '593987654321').

    Returns:
        dict con {success, ruc, alias, name, whatsapp_number, message}
    """
    if not ruc or len(ruc) != 13 or not ruc.isdigit():
        return {"success": False, "error": f"RUC inválido: debe tener 13 dígitos numéricos (recibido: '{ruc}')"}

    if not password:
        return {"success": False, "error": "Password no puede estar vacío"}

    # Normalizar número WhatsApp: quitar +, espacios y guiones
    if whatsapp_number:
        whatsapp_number = whatsapp_number.strip().lstrip("+").replace(" ", "").replace("-", "")

    encrypted = encrypt_password(password)
    conn = _get_db()
    try:
        existing = conn.execute("SELECT id FROM sri_users WHERE ruc = ?", (ruc,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE sri_users SET password = ?, alias = ?, name = ?, owner_user_id = ?, "
                "whatsapp_number = ?, updated_at = CURRENT_TIMESTAMP WHERE ruc = ?",
                (encrypted, alias, name, owner_user_id, whatsapp_number, ruc),
            )
            action = "updated"
        else:
            conn.execute(
                "INSERT INTO sri_users (ruc, password, alias, name, owner_user_id, whatsapp_number) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (ruc, encrypted, alias, name, owner_user_id, whatsapp_number),
            )
            action = "created"
        conn.commit()
        display = name or alias or ""
        return {
            "success": True,
            "ruc": ruc,
            "alias": alias or "",
            "name": name or "",
            "whatsapp_number": whatsapp_number or "",
            "action": action,
            "message": f"Credenciales SRI {action} para RUC {ruc}" + (f" ({display})" if display else ""),
        }
    finally:
        conn.close()


def get_credentials(ruc_or_name: str, user_id: Optional[str] = None) -> Optional[dict]:
    """Obtiene credenciales descifradas para un RUC o nombre/razón social.

    Args:
        ruc_or_name: RUC exacto (13 dígitos) o nombre/razón social parcial.
        user_id: Si se proporciona, filtra por owner_user_id (opcional).

    Returns:
        dict con {ruc, password, alias, name, owner_user_id} o None si no existe.
        Si la búsqueda por nombre devuelve múltiples resultados, retorna el primero.
    """
    conn = _get_db()
    try:
        # Intentar primero por RUC exacto
        if ruc_or_name and ruc_or_name.isdigit() and len(ruc_or_name) == 13:
            if user_id:
                row = conn.execute(
                    "SELECT * FROM sri_users WHERE ruc = ? AND owner_user_id = ?", (ruc_or_name, user_id)
                ).fetchone()
            else:
                row = conn.execute("SELECT * FROM sri_users WHERE ruc = ?", (ruc_or_name,)).fetchone()
        else:
            # Buscar por nombre parcial (case-insensitive)
            pattern = f"%{ruc_or_name}%"
            if user_id:
                row = conn.execute(
                    "SELECT * FROM sri_users WHERE (LOWER(name) LIKE LOWER(?) OR LOWER(alias) LIKE LOWER(?)) "
                    "AND owner_user_id = ? ORDER BY updated_at DESC LIMIT 1",
                    (pattern, pattern, user_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM sri_users WHERE LOWER(name) LIKE LOWER(?) OR LOWER(alias) LIKE LOWER(?) "
                    "ORDER BY updated_at DESC LIMIT 1",
                    (pattern, pattern),
                ).fetchone()
        if not row:
            return None
        row_keys = row.keys()
        return {
            "ruc": row["ruc"],
            "password": decrypt_password(row["password"]),
            "alias": row["alias"],
            "name": row["name"] if "name" in row_keys else None,
            "owner_user_id": row["owner_user_id"],
            "whatsapp_number": row["whatsapp_number"] if "whatsapp_number" in row_keys else None,
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }
    finally:
        conn.close()


def get_credentials_by_name(name: str, user_id: Optional[str] = None) -> list[dict]:
    """Busca credenciales SRI por nombre/razón social parcial (case-insensitive).

    Args:
        name: Texto a buscar en el campo name o alias (búsqueda LIKE %name%).
        user_id: Si se proporciona, filtra por owner_user_id (opcional).

    Returns:
        Lista de dicts {ruc, alias, name, owner_user_id, whatsapp_number} sin passwords descifrados.
    """
    conn = _get_db()
    try:
        pattern = f"%{name}%"
        if user_id:
            rows = conn.execute(
                "SELECT ruc, alias, name, owner_user_id, whatsapp_number, created_at, updated_at FROM sri_users "
                "WHERE (LOWER(name) LIKE LOWER(?) OR LOWER(alias) LIKE LOWER(?)) AND owner_user_id = ? "
                "ORDER BY ruc",
                (pattern, pattern, user_id),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT ruc, alias, name, owner_user_id, whatsapp_number, created_at, updated_at FROM sri_users "
                "WHERE LOWER(name) LIKE LOWER(?) OR LOWER(alias) LIKE LOWER(?) "
                "ORDER BY ruc",
                (pattern, pattern),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_all_credentials(user_id: Optional[str] = None) -> list[dict]:
    """Retorna todos los registros SRI (sin passwords descifrados).

    Args:
        user_id: Si se proporciona, filtra por owner_user_id (opcional).

    Returns:
        Lista de dicts {ruc, alias, name, owner_user_id, whatsapp_number, created_at, updated_at}
    """
    conn = _get_db()
    try:
        if user_id:
            rows = conn.execute(
                "SELECT ruc, alias, name, owner_user_id, whatsapp_number, created_at, updated_at FROM sri_users "
                "WHERE owner_user_id = ? ORDER BY ruc",
                (user_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT ruc, alias, name, owner_user_id, whatsapp_number, created_at, updated_at FROM sri_users ORDER BY ruc"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def delete_credentials(ruc: str) -> bool:
    """Elimina credenciales para un RUC. Retorna True si se eliminó algo."""
    conn = _get_db()
    try:
        cursor = conn.execute("DELETE FROM sri_users WHERE ruc = ?", (ruc,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def set_whatsapp_number(ruc: str, whatsapp_number: str) -> dict:
    """Actualiza el número de WhatsApp para un RUC específico.

    Args:
        ruc: RUC del contribuyente (13 dígitos).
        whatsapp_number: Número WhatsApp en formato internacional.
            Se normaliza automáticamente (quita +, espacios, guiones).
            Ejemplo: '+593 99 546-6833' → '593995466833'.

    Returns:
        dict con {success, ruc, whatsapp_number, message} o {success, error}.
    """
    if not ruc or len(ruc) != 13 or not ruc.isdigit():
        return {"success": False, "error": f"RUC inválido: debe tener 13 dígitos numéricos (recibido: '{ruc}')"}

    if not whatsapp_number:
        return {"success": False, "error": "whatsapp_number no puede estar vacío"}

    # Normalizar: quitar +, espacios y guiones
    numero_normalizado = whatsapp_number.strip().lstrip("+").replace(" ", "").replace("-", "")

    conn = _get_db()
    try:
        existing = conn.execute("SELECT id FROM sri_users WHERE ruc = ?", (ruc,)).fetchone()
        if not existing:
            return {"success": False, "error": f"RUC {ruc} no encontrado en la base de datos"}

        conn.execute(
            "UPDATE sri_users SET whatsapp_number = ?, updated_at = CURRENT_TIMESTAMP WHERE ruc = ?",
            (numero_normalizado, ruc),
        )
        conn.commit()
        return {
            "success": True,
            "ruc": ruc,
            "whatsapp_number": numero_normalizado,
            "message": f"Número WhatsApp actualizado para RUC {ruc}: {numero_normalizado}",
        }
    finally:
        conn.close()
