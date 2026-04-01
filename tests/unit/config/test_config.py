"""Tests para el sistema de configuración."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from config.loader import load_config, merge_config, save_config
from config.runtime_overrides import apply_env_overrides
from config.schema import SomerConfig
from shared.errors import ConfigValidationError


class TestSomerConfig:
    """Tests del schema de configuración."""

    def test_default_config(self) -> None:
        config = SomerConfig()
        assert config.version == "2.0"
        assert config.default_model == "claude-sonnet-4-5-20250929"
        assert config.gateway.host == "127.0.0.1"
        assert config.gateway.port == 18789

    def test_config_with_providers(self) -> None:
        config = SomerConfig(
            providers={
                "anthropic": {
                    "enabled": True,
                    "auth": {"api_key_env": "ANTHROPIC_API_KEY"},
                }
            }
        )
        assert "anthropic" in config.providers
        assert config.providers["anthropic"].enabled is True

    def test_config_with_channels(self) -> None:
        config = SomerConfig(
            channels={
                "entries": {
                    "telegram": {
                        "enabled": True,
                        "plugin": "somer.channels.telegram",
                    }
                }
            }
        )
        assert "telegram" in config.channels.entries
        assert config.channels.entries["telegram"].enabled is True


class TestConfigLoader:
    """Tests de carga/guardado de configuración."""

    def test_load_default_when_missing(self, tmp_path: Path) -> None:
        config = load_config(tmp_path / "nonexistent.json")
        assert isinstance(config, SomerConfig)
        assert config.version == "2.0"

    def test_load_from_file(
        self, sample_config_file: Path, sample_config_data: Dict[str, Any]
    ) -> None:
        config = load_config(sample_config_file)
        assert config.default_model == sample_config_data["default_model"]
        assert "anthropic" in config.providers

    def test_load_invalid_json(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{invalid json")
        with pytest.raises(ConfigValidationError):
            load_config(bad_file)

    def test_save_and_reload(self, tmp_path: Path) -> None:
        config = SomerConfig(default_model="test-model")
        saved_path = save_config(config, tmp_path / "saved.json")
        reloaded = load_config(saved_path)
        assert reloaded.default_model == "test-model"

    def test_merge_config(self) -> None:
        base = SomerConfig(default_model="base-model")
        merged = merge_config(base, {"default_model": "new-model"})
        assert merged.default_model == "new-model"
        # Base no se modificó
        assert base.default_model == "base-model"

    def test_merge_nested(self) -> None:
        base = SomerConfig()
        merged = merge_config(base, {"gateway": {"port": 9999}})
        assert merged.gateway.port == 9999
        assert merged.gateway.host == "127.0.0.1"  # No tocado


class TestRuntimeOverrides:
    """Tests de overrides por env vars."""

    def test_override_default_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SOMER_DEFAULT_MODEL", "my-model")
        config = apply_env_overrides(SomerConfig())
        assert config.default_model == "my-model"

    def test_override_gateway_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SOMER_GATEWAY_PORT", "9999")
        config = apply_env_overrides(SomerConfig())
        assert config.gateway.port == 9999

    def test_auto_enable_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        config = apply_env_overrides(SomerConfig())
        assert "anthropic" in config.providers
        assert config.providers["anthropic"].enabled is True

    def test_no_overrides_no_change(self) -> None:
        original = SomerConfig()
        result = apply_env_overrides(original)
        assert result.default_model == original.default_model
