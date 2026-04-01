"""Tests para la rotación de perfiles de autenticación."""

from __future__ import annotations

import pytest

from agents.auth_profiles import AuthProfileManager


class TestAuthProfileRotation:
    def test_set_rotation_order(self) -> None:
        mgr = AuthProfileManager()
        mgr.get_or_create("p1")
        mgr.get_or_create("p2")
        mgr.get_or_create("p3")
        mgr.set_rotation_order(["p1", "p2", "p3"])

        # next_available rota round-robin
        assert mgr.next_available() == "p1"
        assert mgr.next_available() == "p2"
        assert mgr.next_available() == "p3"
        assert mgr.next_available() == "p1"

    def test_rotation_skips_unavailable(self) -> None:
        mgr = AuthProfileManager()
        mgr.get_or_create("p1", cooldown_secs=1.0)
        mgr.get_or_create("p2", cooldown_secs=1.0)
        mgr.set_rotation_order(["p1", "p2"])

        mgr.record_failure("p1")  # p1 en cooldown
        result = mgr.next_available()
        assert result == "p2"

    def test_rotation_all_unavailable(self) -> None:
        mgr = AuthProfileManager()
        mgr.get_or_create("p1", cooldown_secs=1.0)
        mgr.get_or_create("p2", cooldown_secs=1.0)
        mgr.set_rotation_order(["p1", "p2"])

        mgr.record_failure("p1")
        mgr.record_failure("p2")
        assert mgr.next_available() is None

    def test_ordered_available(self) -> None:
        mgr = AuthProfileManager()
        mgr.get_or_create("p1", cooldown_secs=1.0)
        mgr.get_or_create("p2")
        mgr.get_or_create("p3", cooldown_secs=1.0)
        mgr.set_rotation_order(["p1", "p2", "p3"])

        mgr.record_failure("p1")
        ordered = mgr.ordered_available()
        # p2 disponible, p1 y p3 en cooldown (p1 primero porque falló)
        assert ordered[0] == "p2"

    def test_soonest_expiry(self) -> None:
        mgr = AuthProfileManager()
        mgr.get_or_create("p1", cooldown_secs=100.0)
        mgr.get_or_create("p2", cooldown_secs=10.0)

        mgr.record_failure("p1")
        mgr.record_failure("p2")

        soonest = mgr.soonest_expiry()
        assert soonest is not None

    def test_soonest_expiry_all_available(self) -> None:
        mgr = AuthProfileManager()
        mgr.get_or_create("p1")
        mgr.get_or_create("p2")
        assert mgr.soonest_expiry() is None


class TestSessionOverrides:
    def test_set_and_get(self) -> None:
        mgr = AuthProfileManager()
        mgr.get_or_create("p1")
        mgr.set_session_override("session1", "p1")
        assert mgr.get_session_override("session1") == "p1"

    def test_clear(self) -> None:
        mgr = AuthProfileManager()
        mgr.set_session_override("session1", "p1")
        mgr.clear_session_override("session1")
        assert mgr.get_session_override("session1") is None

    def test_resolve_with_override(self) -> None:
        mgr = AuthProfileManager()
        mgr.get_or_create("p1")
        mgr.get_or_create("p2")
        mgr.set_session_override("session1", "p1")
        assert mgr.resolve_for_session("session1") == "p1"

    def test_resolve_without_override(self) -> None:
        mgr = AuthProfileManager()
        mgr.get_or_create("p1")
        result = mgr.resolve_for_session("session_no_override")
        assert result is not None  # Falls back to rotation

    def test_resolve_override_unavailable(self) -> None:
        mgr = AuthProfileManager()
        mgr.get_or_create("p1", cooldown_secs=1.0)
        mgr.get_or_create("p2")
        mgr.set_session_override("s1", "p1")
        mgr.record_failure("p1")  # p1 en cooldown

        # Override está en cooldown, debe rotar a p2
        result = mgr.resolve_for_session("s1")
        assert result == "p2"
