"""Tests para persistencia de variables en ~/.somer/.env."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict
from unittest.mock import patch

import pytest


@pytest.fixture
def tmp_somer_home(tmp_path: Path) -> Path:
    """Crea un directorio temporal como SOMER_HOME."""
    home = tmp_path / ".somer"
    home.mkdir()
    return home


class TestSaveEnvVar:
    """Tests para save_env_var."""

    def test_creates_file_if_not_exists(self, tmp_somer_home: Path) -> None:
        from infra.env import save_env_var

        env_file = tmp_somer_home / ".env"
        with patch("infra.env.get_env_file_path", return_value=env_file):
            save_env_var("TEST_KEY", "test_value")

        assert env_file.exists()
        content = env_file.read_text()
        assert 'TEST_KEY="test_value"' in content

    def test_updates_existing_key(self, tmp_somer_home: Path) -> None:
        from infra.env import save_env_var

        env_file = tmp_somer_home / ".env"
        env_file.write_text('TEST_KEY="old_value"\n')

        with patch("infra.env.get_env_file_path", return_value=env_file):
            save_env_var("TEST_KEY", "new_value")

        content = env_file.read_text()
        assert 'TEST_KEY="new_value"' in content
        assert "old_value" not in content

    def test_preserves_other_keys(self, tmp_somer_home: Path) -> None:
        from infra.env import save_env_var

        env_file = tmp_somer_home / ".env"
        env_file.write_text('FIRST_KEY="first"\nSECOND_KEY="second"\n')

        with patch("infra.env.get_env_file_path", return_value=env_file):
            save_env_var("FIRST_KEY", "updated")

        content = env_file.read_text()
        assert 'FIRST_KEY="updated"' in content
        assert 'SECOND_KEY="second"' in content

    def test_sets_os_environ(self, tmp_somer_home: Path) -> None:
        from infra.env import save_env_var

        env_file = tmp_somer_home / ".env"
        env_key = "_SOMER_TEST_SAVE_ENV_" + str(id(self))

        try:
            with patch("infra.env.get_env_file_path", return_value=env_file):
                save_env_var(env_key, "myvalue")
            assert os.environ.get(env_key) == "myvalue"
        finally:
            os.environ.pop(env_key, None)

    def test_appends_new_key(self, tmp_somer_home: Path) -> None:
        from infra.env import save_env_var

        env_file = tmp_somer_home / ".env"
        env_file.write_text('EXISTING="value"\n')

        with patch("infra.env.get_env_file_path", return_value=env_file):
            save_env_var("NEW_KEY", "new_value")

        content = env_file.read_text()
        assert 'EXISTING="value"' in content
        assert 'NEW_KEY="new_value"' in content

    def test_preserves_comments(self, tmp_somer_home: Path) -> None:
        from infra.env import save_env_var

        env_file = tmp_somer_home / ".env"
        env_file.write_text('# SOMER config\nKEY="val"\n')

        with patch("infra.env.get_env_file_path", return_value=env_file):
            save_env_var("KEY", "newval")

        content = env_file.read_text()
        assert "# SOMER config" in content
        assert 'KEY="newval"' in content


class TestLoadSomerEnv:
    """Tests para load_somer_env."""

    def test_loads_vars_into_environ(self, tmp_somer_home: Path) -> None:
        from infra.env import load_somer_env

        env_file = tmp_somer_home / ".env"
        env_key = "_SOMER_TEST_LOAD_" + str(id(self))
        env_file.write_text(f'{env_key}="loaded_value"\n')

        try:
            os.environ.pop(env_key, None)
            with patch("infra.env.get_env_file_path", return_value=env_file):
                loaded = load_somer_env()
            assert loaded[env_key] == "loaded_value"
            assert os.environ.get(env_key) == "loaded_value"
        finally:
            os.environ.pop(env_key, None)

    def test_does_not_overwrite_existing(self, tmp_somer_home: Path) -> None:
        from infra.env import load_somer_env

        env_file = tmp_somer_home / ".env"
        env_key = "_SOMER_TEST_NOOVERWRITE_" + str(id(self))
        env_file.write_text(f'{env_key}="file_value"\n')

        try:
            os.environ[env_key] = "env_value"
            with patch("infra.env.get_env_file_path", return_value=env_file):
                loaded = load_somer_env()
            # Debe mantener el valor del entorno
            assert os.environ[env_key] == "env_value"
            assert loaded[env_key] == "env_value"
        finally:
            os.environ.pop(env_key, None)

    def test_returns_empty_if_no_file(self, tmp_somer_home: Path) -> None:
        from infra.env import load_somer_env

        env_file = tmp_somer_home / ".env.nonexistent"
        with patch("infra.env.get_env_file_path", return_value=env_file):
            loaded = load_somer_env()
        assert loaded == {}

    def test_skips_comments_and_blanks(self, tmp_somer_home: Path) -> None:
        from infra.env import load_somer_env

        env_file = tmp_somer_home / ".env"
        env_key = "_SOMER_TEST_SKIP_" + str(id(self))
        env_file.write_text(f"# comment\n\n{env_key}=\"val\"\nnoinvalid\n")

        try:
            os.environ.pop(env_key, None)
            with patch("infra.env.get_env_file_path", return_value=env_file):
                loaded = load_somer_env()
            assert env_key in loaded
        finally:
            os.environ.pop(env_key, None)


class TestRoundTrip:
    """Tests del ciclo completo: save → load."""

    def test_save_then_load(self, tmp_somer_home: Path) -> None:
        """Guarda múltiples vars y verifica que se cargan correctamente."""
        from infra.env import load_somer_env, save_env_var

        env_file = tmp_somer_home / ".env"
        prefix = "_SOMER_RT_" + str(id(self)) + "_"
        keys = [prefix + k for k in ["DEEPSEEK", "TELEGRAM", "ANTHROPIC"]]
        values = ["sk-deep-123", "bot:token456", "sk-ant-789"]

        try:
            with patch("infra.env.get_env_file_path", return_value=env_file):
                for k, v in zip(keys, values):
                    save_env_var(k, v)

            # Limpiar entorno para simular reinicio
            for k in keys:
                os.environ.pop(k, None)

            with patch("infra.env.get_env_file_path", return_value=env_file):
                loaded = load_somer_env()

            for k, v in zip(keys, values):
                assert loaded[k] == v, f"{k}: expected '{v}', got '{loaded.get(k)}'"
                assert os.environ.get(k) == v
        finally:
            for k in keys:
                os.environ.pop(k, None)

    def test_save_overwrites_correctly(self, tmp_somer_home: Path) -> None:
        """Guarda una var, la actualiza, y verifica que load lee el valor nuevo."""
        from infra.env import load_somer_env, save_env_var

        env_file = tmp_somer_home / ".env"
        key = "_SOMER_OW_" + str(id(self))

        try:
            with patch("infra.env.get_env_file_path", return_value=env_file):
                save_env_var(key, "first")
                save_env_var(key, "second")

            os.environ.pop(key, None)

            with patch("infra.env.get_env_file_path", return_value=env_file):
                loaded = load_somer_env()

            assert loaded[key] == "second"
        finally:
            os.environ.pop(key, None)
