"""Tests unitarios para el módulo de credenciales SRI multi-usuario."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


# ── Helpers de cifrado ────────────────────────────────────────


class TestEncryptDecrypt:
    """Tests para las funciones de cifrado/descifrado Fernet."""

    def test_roundtrip_fernet(self, tmp_path):
        """Cifrar y descifrar con Fernet produce el texto original."""
        key_file = tmp_path / "sri.key"
        somer_dir = tmp_path

        with patch.dict(os.environ, {}, clear=False):
            # Eliminar SRI_ENCRYPTION_KEY del env para usar archivo
            env = {k: v for k, v in os.environ.items() if k != "SRI_ENCRYPTION_KEY"}
            with patch.dict(os.environ, env, clear=True):
                # Parchear _SOMER_DIR y _KEY_PATH en el módulo
                with patch("agents.tools.sri_credentials._SOMER_DIR", somer_dir):
                    with patch("agents.tools.sri_credentials._KEY_PATH", key_file):
                        from agents.tools.sri_credentials import encrypt_password, decrypt_password
                        # Reload para que use los paths mockeados
                        password = "MiPassword$ecreta123"
                        encrypted = encrypt_password(password)
                        assert encrypted != password
                        assert len(encrypted) > 0
                        decrypted = decrypt_password(encrypted)
                        assert decrypted == password

    def test_fernet_not_reveals_password(self):
        """El texto cifrado no contiene el password en claro."""
        from agents.tools.sri_credentials import encrypt_password
        password = "secreto_sri"
        encrypted = encrypt_password(password)
        assert password not in encrypted

    def test_decrypt_base64_fallback(self):
        """Descifrado de base64 legacy funciona correctamente."""
        import base64
        from agents.tools.sri_credentials import decrypt_password
        password = "test_pass"
        encoded = "b64:" + base64.b64encode(password.encode()).decode()
        result = decrypt_password(encoded)
        assert result == password

    def test_different_passwords_different_ciphertext(self):
        """Dos passwords distintos producen ciphertexts distintos."""
        from agents.tools.sri_credentials import encrypt_password
        enc1 = encrypt_password("pass1")
        enc2 = encrypt_password("pass2")
        assert enc1 != enc2

    def test_same_password_different_ciphertext_fernet(self):
        """Fernet produce ciphertext diferente cada vez (nonce aleatorio)."""
        from agents.tools.sri_credentials import encrypt_password
        enc1 = encrypt_password("mismopassword")
        enc2 = encrypt_password("mismopassword")
        # Fernet usa nonce aleatorio: deben ser diferentes
        assert enc1 != enc2


# ── Tests de base de datos ────────────────────────────────────


class TestSRICredentialsDB:
    """Tests para las operaciones CRUD en SQLite."""

    @pytest.fixture(autouse=True)
    def use_temp_db(self, tmp_path):
        """Redirige la BD y key al directorio temporal."""
        db_file = tmp_path / "sri_credentials.db"
        key_file = tmp_path / "sri.key"
        with patch("agents.tools.sri_credentials._DB_PATH", db_file):
            with patch("agents.tools.sri_credentials._KEY_PATH", key_file):
                with patch("agents.tools.sri_credentials._SOMER_DIR", tmp_path):
                    yield

    def test_save_valid_ruc(self):
        """Guarda un RUC válido y retorna success."""
        from agents.tools.sri_credentials import save_credentials
        result = save_credentials("1804758934001", "pass123", alias="TestEmpresa")
        assert result["success"] is True
        assert result["ruc"] == "1804758934001"
        assert result["alias"] == "TestEmpresa"
        assert result["action"] in ("created", "updated")

    def test_save_invalid_ruc_short(self):
        """Rechaza RUC con menos de 13 dígitos."""
        from agents.tools.sri_credentials import save_credentials
        result = save_credentials("12345", "pass")
        assert result["success"] is False
        assert "RUC" in result["error"] or "ruc" in result["error"].lower()

    def test_save_invalid_ruc_letters(self):
        """Rechaza RUC con letras."""
        from agents.tools.sri_credentials import save_credentials
        result = save_credentials("18047ABCDE001", "pass")
        assert result["success"] is False

    def test_save_empty_password(self):
        """Rechaza password vacío."""
        from agents.tools.sri_credentials import save_credentials
        result = save_credentials("1804758934001", "")
        assert result["success"] is False

    def test_get_credentials_roundtrip(self):
        """Guardar y recuperar credenciales preserva los datos."""
        from agents.tools.sri_credentials import save_credentials, get_credentials
        save_credentials("1804758934001", "secretpass", alias="Empresa Test")
        creds = get_credentials("1804758934001")
        assert creds is not None
        assert creds["ruc"] == "1804758934001"
        assert creds["password"] == "secretpass"
        assert creds["alias"] == "Empresa Test"

    def test_get_credentials_not_found(self):
        """Retorna None para RUC no registrado."""
        from agents.tools.sri_credentials import get_credentials
        result = get_credentials("9999999999999")
        assert result is None

    def test_update_existing_ruc(self):
        """Actualizar un RUC existente cambia el password."""
        from agents.tools.sri_credentials import save_credentials, get_credentials
        save_credentials("1804758934001", "oldpass")
        result = save_credentials("1804758934001", "newpass", alias="Nuevo Alias")
        assert result["action"] == "updated"
        creds = get_credentials("1804758934001")
        assert creds["password"] == "newpass"
        assert creds["alias"] == "Nuevo Alias"

    def test_list_all_credentials(self):
        """list_all_credentials retorna todos los registros sin passwords."""
        from agents.tools.sri_credentials import save_credentials, list_all_credentials
        save_credentials("1804758934001", "pass1", alias="Empresa A")
        save_credentials("1804758934002", "pass2", alias="Empresa B")
        records = list_all_credentials()
        assert len(records) == 2
        rucs = {r["ruc"] for r in records}
        assert "1804758934001" in rucs
        assert "1804758934002" in rucs
        # No debe exponer passwords
        for r in records:
            assert "password" not in r

    def test_list_all_empty(self):
        """list_all_credentials retorna lista vacía si no hay registros."""
        from agents.tools.sri_credentials import list_all_credentials
        records = list_all_credentials()
        assert records == []

    def test_delete_credentials(self):
        """Eliminar credenciales las borra de la BD."""
        from agents.tools.sri_credentials import save_credentials, get_credentials, delete_credentials
        save_credentials("1804758934001", "pass")
        deleted = delete_credentials("1804758934001")
        assert deleted is True
        assert get_credentials("1804758934001") is None

    def test_delete_nonexistent(self):
        """Eliminar un RUC inexistente retorna False."""
        from agents.tools.sri_credentials import delete_credentials
        result = delete_credentials("9999999999999")
        assert result is False

    def test_owner_user_id_stored(self):
        """El owner_user_id se guarda correctamente."""
        from agents.tools.sri_credentials import save_credentials, get_credentials
        save_credentials("1804758934001", "pass", owner_user_id="telegram_123")
        creds = get_credentials("1804758934001")
        assert creds["owner_user_id"] == "telegram_123"


# ── Tests de registro de tools ────────────────────────────────


class TestSRIToolsRegistered:
    """Verifica que las nuevas tools SRI quedan registradas."""

    def test_sri_tools_registered(self):
        """Las tres nuevas tools SRI están en el registry."""
        from agents.tools.registry import ToolRegistry
        from agents.tools.personal_tools import register_personal_tools

        registry = ToolRegistry()
        register_personal_tools(registry)

        assert "sri_save_credentials" in registry.tool_names
        assert "sri_check_user" in registry.tool_names
        assert "sri_check_all_users" in registry.tool_names
        # Legacy tool debe seguir presente
        assert "sri_check_obligations" in registry.tool_names

    def test_sri_save_credentials_schema(self):
        """sri_save_credentials tiene los parámetros correctos."""
        from agents.tools.registry import ToolRegistry
        from agents.tools.personal_tools import register_personal_tools

        registry = ToolRegistry()
        register_personal_tools(registry)

        tool = registry.get("sri_save_credentials")
        assert tool is not None
        params = tool.parameters
        assert "ruc" in params["properties"]
        assert "password" in params["properties"]
        assert "ruc" in params.get("required", [])
        assert "password" in params.get("required", [])

    def test_sri_check_user_schema(self):
        """sri_check_user requiere el parámetro ruc_or_name (acepta RUC o nombre)."""
        from agents.tools.registry import ToolRegistry
        from agents.tools.personal_tools import register_personal_tools

        registry = ToolRegistry()
        register_personal_tools(registry)

        tool = registry.get("sri_check_user")
        assert tool is not None
        # El parámetro ahora es ruc_or_name (acepta RUC exacto o nombre parcial)
        assert "ruc_or_name" in tool.parameters.get("required", [])
        assert "ruc_or_name" in tool.parameters.get("properties", {})
