"""Generación segura de valores aleatorios — SOMER.

Portado de OpenClaw: secure-random.ts.

Utilidades para generar tokens, IDs y secretos criptográficamente
seguros usando primitivas de os.urandom y hmac.

Compatible con Python 3.9 (macOS built-in incluido).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import random as _stdlib_random
import string
import uuid


def _secure_random_bytes(nbytes: int) -> bytes:
    """Genera bytes aleatorios criptográficamente seguros."""
    return os.urandom(nbytes)


def _secure_choice(sequence: str) -> str:
    """Selecciona un carácter aleatorio de forma segura."""
    idx = int.from_bytes(_secure_random_bytes(4), "big") % len(sequence)
    return sequence[idx]


def _secure_randbelow(n: int) -> int:
    """Genera un entero aleatorio en [0, n) de forma segura."""
    if n <= 0:
        return 0
    return int.from_bytes(_secure_random_bytes(4), "big") % n


def secure_token(nbytes: int = 32) -> str:
    """Genera un token hexadecimal criptográficamente seguro.

    Args:
        nbytes: Número de bytes aleatorios (default 32 = 64 chars hex).

    Returns:
        Token hexadecimal.
    """
    return _secure_random_bytes(nbytes).hex()


def secure_token_urlsafe(nbytes: int = 32) -> str:
    """Genera un token URL-safe criptográficamente seguro.

    Args:
        nbytes: Número de bytes aleatorios.

    Returns:
        Token URL-safe (base64).
    """
    raw = _secure_random_bytes(nbytes)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def secure_id(prefix: str = "", length: int = 16) -> str:
    """Genera un ID único con prefijo opcional.

    Args:
        prefix: Prefijo para el ID (ej: "sess_", "run_").
        length: Longitud de la parte aleatoria (hex chars).

    Returns:
        ID único con formato: "{prefix}{random_hex}".
    """
    nbytes = max(1, (length + 1) // 2)
    random_part = _secure_random_bytes(nbytes).hex()[:length]
    return f"{prefix}{random_part}"


def secure_password(length: int = 24, include_symbols: bool = True) -> str:
    """Genera una contraseña segura.

    Args:
        length: Longitud de la contraseña.
        include_symbols: Si incluir símbolos especiales.

    Returns:
        Contraseña generada.
    """
    alphabet = string.ascii_letters + string.digits
    if include_symbols:
        alphabet += "!@#$%&*-_=+"

    # Garantizar al menos uno de cada tipo
    password_chars = [
        _secure_choice(string.ascii_lowercase),
        _secure_choice(string.ascii_uppercase),
        _secure_choice(string.digits),
    ]
    if include_symbols:
        password_chars.append(_secure_choice("!@#$%&*-_=+"))

    remaining = length - len(password_chars)
    for _ in range(max(0, remaining)):
        password_chars.append(_secure_choice(alphabet))

    # Fisher-Yates shuffle con random seguro
    order = list(range(len(password_chars)))
    for i in range(len(order) - 1, 0, -1):
        j = _secure_randbelow(i + 1)
        order[i], order[j] = order[j], order[i]

    return "".join(password_chars[idx] for idx in order)


def secure_uuid() -> str:
    """Genera un UUID v4 seguro.

    Returns:
        UUID v4 como string.
    """
    return str(uuid.uuid4())


def secure_compare(a: str, b: str) -> bool:
    """Comparación de strings en tiempo constante.

    Previene ataques de timing al comparar tokens o secretos.

    Args:
        a: Primer string.
        b: Segundo string.

    Returns:
        True si son iguales.
    """
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def hash_token(token: str, salt: str = "") -> str:
    """Genera un hash SHA-256 de un token.

    Útil para almacenar tokens en logs sin exponer el valor real.

    Args:
        token: Token a hashear.
        salt: Salt opcional.

    Returns:
        Hash hexadecimal.
    """
    data = f"{salt}{token}".encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def generate_api_key(prefix: str = "sk") -> str:
    """Genera una API key con formato estándar.

    Formato: "{prefix}_{random_urlsafe}".

    Args:
        prefix: Prefijo de la key (ej: "sk", "pk").

    Returns:
        API key generada.
    """
    random_part = secure_token_urlsafe(32)
    return f"{prefix}_{random_part}"
