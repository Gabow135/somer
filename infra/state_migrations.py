"""Sistema de migraciones de estado/config — SOMER.

Portado de OpenClaw: state-migrations.ts.

Permite aplicar migraciones incrementales al estado persistido
(config, sesiones, etc.) cuando se actualiza la versión del sistema.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Tipos ───────────────────────────────────────────────────

MigrationFn = Callable[[Dict[str, Any]], Dict[str, Any]]


@dataclass
class Migration:
    """Define una migración de estado."""

    version: int
    description: str
    migrate: MigrationFn


@dataclass
class MigrationResult:
    """Resultado de aplicar migraciones."""

    applied: List[int] = field(default_factory=list)
    skipped: List[int] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    from_version: int = 0
    to_version: int = 0


STATE_VERSION_KEY = "__state_version"
STATE_MIGRATED_AT_KEY = "__state_migrated_at"


class StateMigrationManager:
    """Gestor de migraciones de estado.

    Aplica migraciones incrementales al estado persistido,
    rastreando la versión actual para evitar re-aplicaciones.
    """

    def __init__(self) -> None:
        self._migrations: List[Migration] = []

    def register(
        self,
        version: int,
        description: str,
        migrate_fn: MigrationFn,
    ) -> None:
        """Registra una nueva migración.

        Args:
            version: Número de versión (debe ser incremental).
            description: Descripción de la migración.
            migrate_fn: Función que transforma el estado.
        """
        if any(m.version == version for m in self._migrations):
            raise ValueError(f"Migración con versión {version} ya registrada")

        self._migrations.append(
            Migration(version=version, description=description, migrate=migrate_fn)
        )
        self._migrations.sort(key=lambda m: m.version)

    @property
    def latest_version(self) -> int:
        """Retorna la versión más reciente registrada."""
        if not self._migrations:
            return 0
        return self._migrations[-1].version

    @property
    def migration_count(self) -> int:
        """Número total de migraciones registradas."""
        return len(self._migrations)

    def get_state_version(self, state: Dict[str, Any]) -> int:
        """Obtiene la versión actual del estado."""
        return int(state.get(STATE_VERSION_KEY, 0))

    def needs_migration(self, state: Dict[str, Any]) -> bool:
        """Verifica si el estado necesita migraciones."""
        current = self.get_state_version(state)
        return current < self.latest_version

    def apply(self, state: Dict[str, Any]) -> MigrationResult:
        """Aplica todas las migraciones pendientes al estado.

        Modifica el estado in-place y retorna el resultado.

        Args:
            state: Diccionario de estado a migrar.

        Returns:
            Resultado de las migraciones aplicadas.
        """
        current_version = self.get_state_version(state)
        result = MigrationResult(from_version=current_version)

        pending = [m for m in self._migrations if m.version > current_version]

        if not pending:
            result.to_version = current_version
            return result

        for migration in pending:
            try:
                logger.info(
                    "Aplicando migración v%d: %s",
                    migration.version,
                    migration.description,
                )
                migrated = migration.migrate(state)
                # La función puede retornar el estado modificado o None (in-place)
                if migrated is not None and migrated is not state:
                    state.clear()
                    state.update(migrated)
                state[STATE_VERSION_KEY] = migration.version
                state[STATE_MIGRATED_AT_KEY] = time.time()
                result.applied.append(migration.version)
                logger.info("Migración v%d aplicada exitosamente", migration.version)
            except Exception as exc:
                error_msg = f"Error en migración v{migration.version}: {exc}"
                logger.error(error_msg)
                result.errors.append(error_msg)
                break

        result.to_version = self.get_state_version(state)
        return result

    def apply_to_file(self, file_path: Path) -> MigrationResult:
        """Aplica migraciones a un archivo JSON de estado.

        Lee el archivo, aplica migraciones y guarda el resultado.

        Args:
            file_path: Ruta al archivo JSON.

        Returns:
            Resultado de las migraciones.
        """
        if not file_path.exists():
            logger.debug("Archivo de estado no encontrado: %s", file_path)
            return MigrationResult()

        try:
            state = json.loads(file_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Error leyendo archivo de estado %s: %s", file_path, exc)
            return MigrationResult(errors=[f"Error leyendo archivo: {exc}"])

        if not isinstance(state, dict):
            return MigrationResult(errors=["Estado no es un diccionario"])

        result = self.apply(state)

        if result.applied:
            try:
                # Backup antes de escribir
                backup_path = file_path.with_suffix(
                    f".v{result.from_version}.bak"
                )
                if not backup_path.exists():
                    import shutil
                    shutil.copy2(file_path, backup_path)

                file_path.write_text(
                    json.dumps(state, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                logger.info(
                    "Estado migrado de v%d a v%d en %s",
                    result.from_version,
                    result.to_version,
                    file_path,
                )
            except OSError as exc:
                result.errors.append(f"Error escribiendo archivo: {exc}")

        return result


# ── Singleton global ────────────────────────────────────────

_global_manager: Optional[StateMigrationManager] = None


def get_migration_manager() -> StateMigrationManager:
    """Obtiene el gestor de migraciones global."""
    global _global_manager
    if _global_manager is None:
        _global_manager = StateMigrationManager()
    return _global_manager


def reset_migration_manager() -> None:
    """Reinicia el gestor global (para tests)."""
    global _global_manager
    _global_manager = None
