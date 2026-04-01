"""Tests para infra/env.py — Normalización de entorno."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from infra.env import (
    is_truthy_env,
    mask_secret,
)


class TestIsTruthyEnv:
    """Tests de detección de valores truthy."""

    def test_truthy_values(self) -> None:
        assert is_truthy_env("1") is True
        assert is_truthy_env("true") is True
        assert is_truthy_env("yes") is True
        assert is_truthy_env("on") is True
        assert is_truthy_env("TRUE") is True
        assert is_truthy_env("  true  ") is True

    def test_falsy_values(self) -> None:
        assert is_truthy_env("0") is False
        assert is_truthy_env("false") is False
        assert is_truthy_env("no") is False
        assert is_truthy_env("off") is False
        assert is_truthy_env("") is False
        assert is_truthy_env(None) is False


class TestMaskSecret:
    """Tests de enmascaramiento de secretos."""

    def test_normal(self) -> None:
        result = mask_secret("sk-abcdef1234567890")
        assert "sk-" in result
        assert result.endswith("7890")
        assert "*" in result

    def test_short(self) -> None:
        result = mask_secret("abc")
        assert result == "***"

    def test_empty(self) -> None:
        assert mask_secret("") == ""

    def test_custom_visible(self) -> None:
        result = mask_secret("very-long-secret-key", visible_chars=6)
        assert result.endswith("et-key")
