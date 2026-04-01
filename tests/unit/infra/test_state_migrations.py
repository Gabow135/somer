"""Tests para infra/state_migrations.py — Migraciones de estado."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Dict

import pytest

from infra.state_migrations import (
    STATE_VERSION_KEY,
    StateMigrationManager,
    get_migration_manager,
    reset_migration_manager,
)


class TestStateMigrationManager:
    """Tests del gestor de migraciones."""

    def setup_method(self) -> None:
        self.mgr = StateMigrationManager()

    def test_empty_manager(self) -> None:
        """Manager sin migraciones."""
        assert self.mgr.latest_version == 0
        assert self.mgr.migration_count == 0

    def test_register_migration(self) -> None:
        """Registrar migraciones."""
        self.mgr.register(1, "Primera migración", lambda s: s)
        self.mgr.register(2, "Segunda migración", lambda s: s)

        assert self.mgr.latest_version == 2
        assert self.mgr.migration_count == 2

    def test_duplicate_version_raises(self) -> None:
        """Versión duplicada lanza error."""
        self.mgr.register(1, "v1", lambda s: s)
        with pytest.raises(ValueError, match="ya registrada"):
            self.mgr.register(1, "v1 dup", lambda s: s)

    def test_needs_migration(self) -> None:
        """Detecta si el estado necesita migraciones."""
        self.mgr.register(1, "v1", lambda s: s)
        self.mgr.register(2, "v2", lambda s: s)

        assert self.mgr.needs_migration({}) is True
        assert self.mgr.needs_migration({STATE_VERSION_KEY: 1}) is True
        assert self.mgr.needs_migration({STATE_VERSION_KEY: 2}) is False

    def test_apply_migrations(self) -> None:
        """Aplica migraciones pendientes."""
        def v1(state: Dict[str, Any]) -> Dict[str, Any]:
            state["migrated_v1"] = True
            return state

        def v2(state: Dict[str, Any]) -> Dict[str, Any]:
            state["migrated_v2"] = True
            return state

        self.mgr.register(1, "v1", v1)
        self.mgr.register(2, "v2", v2)

        state: Dict[str, Any] = {"original": True}
        result = self.mgr.apply(state)

        assert result.from_version == 0
        assert result.to_version == 2
        assert result.applied == [1, 2]
        assert result.errors == []
        assert state["migrated_v1"] is True
        assert state["migrated_v2"] is True
        assert state["original"] is True

    def test_partial_migration(self) -> None:
        """Solo aplica migraciones pendientes."""
        self.mgr.register(1, "v1", lambda s: s)
        self.mgr.register(2, "v2", lambda s: s)

        state = {STATE_VERSION_KEY: 1}
        result = self.mgr.apply(state)

        assert result.applied == [2]
        assert result.from_version == 1

    def test_no_pending_migrations(self) -> None:
        """Sin migraciones pendientes."""
        self.mgr.register(1, "v1", lambda s: s)

        state = {STATE_VERSION_KEY: 1}
        result = self.mgr.apply(state)

        assert result.applied == []
        assert result.from_version == 1
        assert result.to_version == 1

    def test_migration_error_stops(self) -> None:
        """Error en migración detiene el proceso."""
        self.mgr.register(1, "v1", lambda s: s)
        self.mgr.register(2, "v2 fail", lambda s: (_ for _ in ()).throw(ValueError("boom")))
        self.mgr.register(3, "v3", lambda s: s)

        state: Dict[str, Any] = {}
        result = self.mgr.apply(state)

        assert 1 in result.applied
        assert len(result.errors) == 1
        assert "boom" in result.errors[0]
        assert state[STATE_VERSION_KEY] == 1  # Solo v1 aplicada

    def test_apply_to_file(self) -> None:
        """Aplica migraciones a un archivo JSON."""
        self.mgr.register(1, "v1", lambda s: {**s, "upgraded": True})

        with tempfile.NamedTemporaryFile(
            suffix=".json", mode="w", delete=False
        ) as f:
            json.dump({"data": "original"}, f)
            path = Path(f.name)

        try:
            result = self.mgr.apply_to_file(path)
            assert result.applied == [1]

            # Verificar que el archivo fue actualizado
            saved = json.loads(path.read_text())
            assert saved["upgraded"] is True
            assert saved[STATE_VERSION_KEY] == 1

            # Verificar backup
            backup = path.with_suffix(".v0.bak")
            assert backup.exists()
        finally:
            path.unlink(missing_ok=True)
            path.with_suffix(".v0.bak").unlink(missing_ok=True)

    def test_apply_to_missing_file(self) -> None:
        """Archivo inexistente retorna resultado vacío."""
        result = self.mgr.apply_to_file(Path("/tmp/nonexistent_somer_test.json"))
        assert result.applied == []


class TestGlobalManager:
    """Tests del singleton global."""

    def setup_method(self) -> None:
        reset_migration_manager()

    def teardown_method(self) -> None:
        reset_migration_manager()

    def test_singleton(self) -> None:
        """get_migration_manager retorna el mismo objeto."""
        mgr1 = get_migration_manager()
        mgr2 = get_migration_manager()
        assert mgr1 is mgr2

    def test_reset(self) -> None:
        """reset_migration_manager crea nueva instancia."""
        mgr1 = get_migration_manager()
        reset_migration_manager()
        mgr2 = get_migration_manager()
        assert mgr1 is not mgr2
