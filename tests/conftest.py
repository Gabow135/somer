"""Fixtures compartidos para tests de SOMER 2.0."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

import pytest

# Bloquear .env en tests
os.environ.setdefault("SOMER_HOME", str(Path("/tmp/somer-test")))


@pytest.fixture
def tmp_somer_home(tmp_path: Path) -> Path:
    """Crea un directorio SOMER temporal para tests."""
    home = tmp_path / ".somer"
    home.mkdir()
    for subdir in ("sessions", "credentials", "memory", "logs"):
        (home / subdir).mkdir()
    return home


@pytest.fixture
def sample_config_data() -> Dict[str, Any]:
    """Config de ejemplo para tests."""
    return {
        "version": "2.0",
        "default_model": "claude-sonnet-4-5-20250929",
        "providers": {
            "anthropic": {
                "enabled": True,
                "auth": {"api_key_env": "ANTHROPIC_API_KEY"},
                "models": [
                    {
                        "id": "claude-sonnet-4-5-20250929",
                        "provider": "anthropic",
                        "api": "anthropic-messages",
                        "max_input_tokens": 200000,
                        "max_output_tokens": 8192,
                    }
                ],
            }
        },
        "channels": {
            "entries": {
                "telegram": {
                    "enabled": True,
                    "plugin": "somer.channels.telegram",
                    "config": {"token_env": "TELEGRAM_BOT_TOKEN"},
                }
            }
        },
    }


@pytest.fixture
def sample_config_file(
    tmp_somer_home: Path, sample_config_data: Dict[str, Any]
) -> Path:
    """Crea un archivo de config de ejemplo."""
    config_path = tmp_somer_home / "config.json"
    config_path.write_text(json.dumps(sample_config_data, indent=2))
    return config_path
