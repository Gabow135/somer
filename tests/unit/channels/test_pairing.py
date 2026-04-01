"""Tests para channels/pairing.py — sistema de pairing y allowlist."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from channels.pairing import (
    _ALPHABET,
    _CODE_LENGTH,
    _generate_code,
    add_to_allowlist,
    approve_pairing,
    create_pairing_request,
    is_sender_allowed,
    list_pending,
    load_allowlist,
    reject_pairing,
    remove_from_allowlist,
    save_allowlist,
)


@pytest.fixture()
def oauth_dir(tmp_path: Path) -> Path:
    """Crea un directorio oauth temporal y lo parchea."""
    d = tmp_path / "oauth"
    d.mkdir()
    return d


@pytest.fixture(autouse=True)
def _patch_oauth(oauth_dir: Path) -> Any:
    """Parchea _oauth_dir para usar directorio temporal."""
    with patch("channels.pairing._oauth_dir", return_value=oauth_dir):
        yield


class TestCodeGeneration:
    def test_code_length(self) -> None:
        code = _generate_code([])
        assert len(code) == _CODE_LENGTH

    def test_code_characters(self) -> None:
        code = _generate_code([])
        for ch in code:
            assert ch in _ALPHABET

    def test_code_unique(self) -> None:
        codes = [_generate_code([]) for _ in range(50)]
        assert len(set(codes)) == 50

    def test_avoids_existing(self) -> None:
        existing = ["ABCDEFGH"]
        code = _generate_code(existing)
        assert code != "ABCDEFGH"


class TestAllowlist:
    def test_empty_by_default(self) -> None:
        assert load_allowlist("telegram") == []

    def test_add_and_load(self) -> None:
        add_to_allowlist("telegram", "123")
        assert "123" in load_allowlist("telegram")

    def test_add_duplicate(self) -> None:
        add_to_allowlist("telegram", "123")
        added = add_to_allowlist("telegram", "123")
        assert not added
        assert load_allowlist("telegram").count("123") == 1

    def test_remove(self) -> None:
        add_to_allowlist("telegram", "123")
        removed = remove_from_allowlist("telegram", "123")
        assert removed
        assert "123" not in load_allowlist("telegram")

    def test_remove_nonexistent(self) -> None:
        removed = remove_from_allowlist("telegram", "999")
        assert not removed

    def test_save_and_load(self) -> None:
        save_allowlist("telegram", ["100", "200", "300"])
        assert load_allowlist("telegram") == ["100", "200", "300"]

    def test_separate_channels(self) -> None:
        add_to_allowlist("telegram", "111")
        add_to_allowlist("discord", "222")
        assert load_allowlist("telegram") == ["111"]
        assert load_allowlist("discord") == ["222"]


class TestPairingRequests:
    def test_create_returns_code(self) -> None:
        code = create_pairing_request("telegram", "123")
        assert len(code) == _CODE_LENGTH

    def test_same_sender_same_code(self) -> None:
        code1 = create_pairing_request("telegram", "123")
        code2 = create_pairing_request("telegram", "123")
        assert code1 == code2

    def test_different_senders_different_codes(self) -> None:
        code1 = create_pairing_request("telegram", "123")
        code2 = create_pairing_request("telegram", "456")
        assert code1 != code2

    def test_list_pending(self) -> None:
        create_pairing_request("telegram", "123", {"username": "alice"})
        pending = list_pending("telegram")
        assert len(pending) == 1
        assert pending[0]["sender_id"] == "123"
        assert pending[0]["metadata"]["username"] == "alice"

    def test_approve(self) -> None:
        code = create_pairing_request("telegram", "123")
        result = approve_pairing("telegram", code)
        assert result is not None
        assert result["sender_id"] == "123"
        # Debe estar en allowlist
        assert "123" in load_allowlist("telegram")
        # No debe haber pendientes
        assert len(list_pending("telegram")) == 0

    def test_approve_case_insensitive(self) -> None:
        code = create_pairing_request("telegram", "123")
        result = approve_pairing("telegram", code.lower())
        assert result is not None

    def test_approve_nonexistent(self) -> None:
        result = approve_pairing("telegram", "ZZZZZZZZ")
        assert result is None

    def test_reject(self) -> None:
        code = create_pairing_request("telegram", "123")
        result = reject_pairing("telegram", code)
        assert result is not None
        assert len(list_pending("telegram")) == 0
        # NO debe estar en allowlist
        assert "123" not in load_allowlist("telegram")

    def test_max_pending_prunes_oldest(self) -> None:
        create_pairing_request("telegram", "100")
        create_pairing_request("telegram", "200")
        create_pairing_request("telegram", "300")
        # El 4to debería eliminar el más antiguo
        create_pairing_request("telegram", "400")
        pending = list_pending("telegram")
        sender_ids = [r["sender_id"] for r in pending]
        assert "100" not in sender_ids
        assert "400" in sender_ids

    def test_expired_requests_pruned(self) -> None:
        code = create_pairing_request("telegram", "123")
        # Simular expiración modificando created_at
        from channels.pairing import _pairing_path, _read_json, _write_json
        requests = _read_json(_pairing_path("telegram"))
        requests[0]["created_at"] = time.time() - 7200  # 2h atrás
        _write_json(_pairing_path("telegram"), requests)

        pending = list_pending("telegram")
        assert len(pending) == 0

        # Approve de código expirado debe fallar
        result = approve_pairing("telegram", code)
        assert result is None


class TestIsSenderAllowed:
    def test_open_policy(self) -> None:
        assert is_sender_allowed("telegram", "123", "open") is True

    def test_none_policy(self) -> None:
        assert is_sender_allowed("telegram", "123", None) is True

    def test_disabled_policy(self) -> None:
        assert is_sender_allowed("telegram", "123", "disabled") is False

    def test_allowlist_with_config(self) -> None:
        assert is_sender_allowed("telegram", "123", "allowlist", ["123", "456"]) is True
        assert is_sender_allowed("telegram", "789", "allowlist", ["123", "456"]) is False

    def test_allowlist_with_wildcard(self) -> None:
        assert is_sender_allowed("telegram", "anyone", "allowlist", ["*"]) is True

    def test_pairing_with_approved(self) -> None:
        add_to_allowlist("telegram", "123")
        assert is_sender_allowed("telegram", "123", "pairing") is True

    def test_pairing_without_approved(self) -> None:
        assert is_sender_allowed("telegram", "999", "pairing") is False

    def test_combined_config_and_store(self) -> None:
        # Config allowlist + pairing store combinados
        add_to_allowlist("telegram", "200")
        assert is_sender_allowed("telegram", "100", "pairing", ["100"]) is True
        assert is_sender_allowed("telegram", "200", "pairing") is True
        assert is_sender_allowed("telegram", "300", "pairing") is False
