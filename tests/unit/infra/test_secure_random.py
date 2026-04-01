"""Tests para infra/secure_random.py — Generación segura de valores."""

from __future__ import annotations

import pytest

from infra.secure_random import (
    generate_api_key,
    hash_token,
    secure_compare,
    secure_id,
    secure_password,
    secure_token,
    secure_token_urlsafe,
    secure_uuid,
)


class TestSecureToken:
    """Tests de generación de tokens."""

    def test_default_length(self) -> None:
        """Token por defecto tiene 64 caracteres hex."""
        token = secure_token()
        assert len(token) == 64
        assert all(c in "0123456789abcdef" for c in token)

    def test_custom_length(self) -> None:
        """Token con longitud personalizada."""
        token = secure_token(16)
        assert len(token) == 32

    def test_unique(self) -> None:
        """Dos tokens son diferentes."""
        t1 = secure_token()
        t2 = secure_token()
        assert t1 != t2

    def test_urlsafe(self) -> None:
        """Token URL-safe."""
        token = secure_token_urlsafe()
        assert isinstance(token, str)
        assert len(token) > 0


class TestSecureId:
    """Tests de generación de IDs."""

    def test_basic(self) -> None:
        sid = secure_id()
        assert len(sid) == 16

    def test_with_prefix(self) -> None:
        sid = secure_id(prefix="sess_")
        assert sid.startswith("sess_")

    def test_custom_length(self) -> None:
        sid = secure_id(length=8)
        assert len(sid) == 8


class TestSecurePassword:
    """Tests de generación de contraseñas."""

    def test_default_length(self) -> None:
        pwd = secure_password()
        assert len(pwd) == 24

    def test_has_variety(self) -> None:
        """Contiene letras, números y símbolos."""
        pwd = secure_password(length=24, include_symbols=True)
        has_lower = any(c.islower() for c in pwd)
        has_upper = any(c.isupper() for c in pwd)
        has_digit = any(c.isdigit() for c in pwd)
        assert has_lower
        assert has_upper
        assert has_digit

    def test_no_symbols(self) -> None:
        pwd = secure_password(length=20, include_symbols=False)
        assert all(c.isalnum() for c in pwd)

    def test_unique(self) -> None:
        p1 = secure_password()
        p2 = secure_password()
        assert p1 != p2


class TestSecureUuid:
    """Tests de UUID."""

    def test_format(self) -> None:
        uid = secure_uuid()
        assert len(uid) == 36
        assert uid.count("-") == 4

    def test_unique(self) -> None:
        u1 = secure_uuid()
        u2 = secure_uuid()
        assert u1 != u2


class TestSecureCompare:
    """Tests de comparación en tiempo constante."""

    def test_equal(self) -> None:
        assert secure_compare("abc", "abc") is True

    def test_not_equal(self) -> None:
        assert secure_compare("abc", "def") is False

    def test_empty(self) -> None:
        assert secure_compare("", "") is True


class TestHashToken:
    """Tests de hash de token."""

    def test_deterministic(self) -> None:
        h1 = hash_token("my-token")
        h2 = hash_token("my-token")
        assert h1 == h2

    def test_different_tokens(self) -> None:
        h1 = hash_token("token-a")
        h2 = hash_token("token-b")
        assert h1 != h2

    def test_with_salt(self) -> None:
        h1 = hash_token("token", salt="salt1")
        h2 = hash_token("token", salt="salt2")
        assert h1 != h2


class TestGenerateApiKey:
    """Tests de generación de API key."""

    def test_default_prefix(self) -> None:
        key = generate_api_key()
        assert key.startswith("sk_")

    def test_custom_prefix(self) -> None:
        key = generate_api_key(prefix="pk")
        assert key.startswith("pk_")

    def test_unique(self) -> None:
        k1 = generate_api_key()
        k2 = generate_api_key()
        assert k1 != k2
