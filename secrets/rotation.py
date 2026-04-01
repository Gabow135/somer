"""Rotación de credenciales — soporte para actualizar y rotar secretos.

Portado de OpenClaw: configure.ts, apply.ts (secciones de rotación).
Permite rotar credenciales de forma segura, manteniendo backup del
valor anterior y actualizando la configuración atómicamente.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from secrets.refs import SecretRef, SecretSource
from secrets.store import CredentialStore
from secrets.validation import (
    ValidationReport,
    ValidationResult,
    ValidationSeverity,
    validate_api_key_format,
)
from shared.errors import SecretError, SecretNotFoundError

logger = logging.getLogger(__name__)


@dataclass
class RotationResult:
    """Resultado de una operación de rotación de credencial."""
    service: str
    key: str
    success: bool
    message: str
    previous_backup_path: Optional[str] = None


@dataclass
class RotationPlan:
    """Plan de rotación de credenciales.

    Portado de OpenClaw: configure-plan.ts (concepto de plan de cambios).
    """
    rotations: List[Dict[str, Any]] = field(default_factory=list)
    generated_at: str = ""
    generated_by: str = "somer secrets rotate"

    def add_rotation(
        self,
        service: str,
        key: str,
        new_ref: SecretRef,
        reason: str = "",
    ) -> None:
        """Agrega una rotación al plan.

        Args:
            service: Nombre del servicio.
            key: Nombre de la credencial.
            new_ref: Nueva referencia al secreto.
            reason: Razón de la rotación.
        """
        self.rotations.append({
            "service": service,
            "key": key,
            "new_ref": {
                "source": new_ref.source.value,
                "key": new_ref.key,
                "provider": new_ref.provider,
            },
            "reason": reason,
        })

    @property
    def has_changes(self) -> bool:
        """True si el plan tiene rotaciones pendientes."""
        return len(self.rotations) > 0


class CredentialRotator:
    """Gestor de rotación de credenciales.

    Portado de OpenClaw: apply.ts (funcionalidad de aplicar cambios
    a la configuración de secretos).

    Permite rotar credenciales manteniendo un historial de backups
    y verificando que los nuevos valores sean válidos antes de aplicar.
    """

    def __init__(
        self,
        store: CredentialStore,
        backup_dir: Optional[Path] = None,
    ):
        """Inicializa el rotador.

        Args:
            store: CredentialStore donde se gestionan las credenciales.
            backup_dir: Directorio para backups (default: store._dir / ".backups").
        """
        self._store = store
        self._backup_dir = backup_dir or (store._dir / ".backups")
        self._backup_dir.mkdir(parents=True, exist_ok=True)

    def rotate(
        self,
        service: str,
        key: str,
        new_value: str,
        validate: bool = True,
    ) -> RotationResult:
        """Rota una credencial para un servicio.

        1. Valida el nuevo valor (opcional).
        2. Hace backup del valor actual.
        3. Actualiza el valor en el store.

        Args:
            service: Nombre del servicio (ej: "anthropic").
            key: Nombre de la credencial (ej: "api_key").
            new_value: Nuevo valor de la credencial.
            validate: Si se debe validar el formato del nuevo valor.

        Returns:
            RotationResult con el resultado de la operación.
        """
        # 1. Validar formato si es API key
        if validate and key in ("api_key", "apiKey"):
            result = validate_api_key_format(service, new_value)
            if result.severity == ValidationSeverity.ERROR:
                return RotationResult(
                    service=service,
                    key=key,
                    success=False,
                    message=f"Validación falló: {result.message}",
                )

        # 2. Backup del valor actual
        backup_path = None
        if self._store.has(service):
            backup_path = self._backup_credentials(service)

        # 3. Actualizar
        try:
            current = {}
            if self._store.has(service):
                try:
                    current = self._store.retrieve(service)
                except Exception:
                    current = {}

            current[key] = new_value
            self._store.store(service, current)

            logger.info(
                "Credencial rotada: %s.%s (backup: %s)",
                service, key, backup_path or "sin backup previo",
            )
            return RotationResult(
                service=service,
                key=key,
                success=True,
                message=f"Credencial {service}.{key} rotada exitosamente.",
                previous_backup_path=backup_path,
            )
        except Exception as exc:
            # Intentar restaurar backup
            if backup_path:
                self._restore_backup(service, backup_path)
            return RotationResult(
                service=service,
                key=key,
                success=False,
                message=f"Error rotando credencial: {exc}",
            )

    def rotate_from_ref(
        self,
        service: str,
        key: str,
        ref: SecretRef,
        validate: bool = True,
    ) -> RotationResult:
        """Rota una credencial usando un SecretRef como fuente del nuevo valor.

        Args:
            service: Nombre del servicio.
            key: Nombre de la credencial.
            ref: SecretRef con el nuevo valor.
            validate: Si se debe validar el formato.

        Returns:
            RotationResult con el resultado.
        """
        try:
            new_value = ref.resolve()
        except Exception as exc:
            return RotationResult(
                service=service,
                key=key,
                success=False,
                message=f"No se pudo resolver la referencia: {exc}",
            )
        return self.rotate(service, key, new_value, validate=validate)

    def execute_plan(
        self,
        plan: RotationPlan,
        validate: bool = True,
    ) -> List[RotationResult]:
        """Ejecuta un plan de rotación completo.

        Portado de OpenClaw: apply.ts (aplicar un SecretsApplyPlan).

        Args:
            plan: Plan de rotación a ejecutar.
            validate: Si se deben validar los nuevos valores.

        Returns:
            Lista de RotationResults.
        """
        results: List[RotationResult] = []
        for rotation in plan.rotations:
            service = rotation["service"]
            key = rotation["key"]
            ref_data = rotation["new_ref"]

            try:
                ref = SecretRef(
                    source=SecretSource(ref_data["source"]),
                    key=ref_data["key"],
                    provider=ref_data.get("provider", "default"),
                )
                result = self.rotate_from_ref(
                    service=service,
                    key=key,
                    ref=ref,
                    validate=validate,
                )
                results.append(result)
            except Exception as exc:
                results.append(RotationResult(
                    service=service,
                    key=key,
                    success=False,
                    message=f"Error ejecutando rotación: {exc}",
                ))
        return results

    def list_backups(self, service: Optional[str] = None) -> List[Dict[str, Any]]:
        """Lista los backups disponibles.

        Args:
            service: Filtrar por servicio (None = todos).

        Returns:
            Lista de dicts con info de cada backup.
        """
        backups: List[Dict[str, Any]] = []
        for path in sorted(self._backup_dir.iterdir()):
            if not path.name.endswith(".json"):
                continue
            parts = path.stem.split("_", 1)
            backup_service = parts[0]
            if service and backup_service != service:
                continue
            try:
                stat = path.stat()
                backups.append({
                    "path": str(path),
                    "service": backup_service,
                    "timestamp": parts[1] if len(parts) > 1 else "",
                    "size": stat.st_size,
                    "created": stat.st_mtime,
                })
            except Exception:
                continue
        return backups

    def restore_from_backup(self, backup_path: str) -> bool:
        """Restaura credenciales desde un backup.

        Args:
            backup_path: Ruta al archivo de backup.

        Returns:
            True si se restauró correctamente.
        """
        path = Path(backup_path)
        if not path.exists():
            logger.error("Backup no encontrado: %s", backup_path)
            return False

        try:
            data = json.loads(path.read_bytes())
            service = path.stem.split("_", 1)[0]
            self._store.store(service, data)
            logger.info("Credenciales restauradas desde backup: %s", backup_path)
            return True
        except Exception as exc:
            logger.error("Error restaurando backup %s: %s", backup_path, exc)
            return False

    def _backup_credentials(self, service: str) -> Optional[str]:
        """Crea backup de las credenciales de un servicio.

        Returns:
            Ruta al archivo de backup, o None si no había credenciales.
        """
        try:
            creds = self._store.retrieve(service)
            timestamp = str(int(time.time()))
            backup_file = self._backup_dir / f"{service}_{timestamp}.json"
            backup_file.write_text(
                json.dumps(creds, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            backup_file.chmod(0o600)
            logger.debug("Backup creado: %s", backup_file)
            return str(backup_file)
        except SecretNotFoundError:
            return None
        except Exception as exc:
            logger.warning("No se pudo crear backup para %s: %s", service, exc)
            return None

    def _restore_backup(self, service: str, backup_path: str) -> None:
        """Restaura credenciales desde un backup específico."""
        try:
            data = json.loads(Path(backup_path).read_bytes())
            self._store.store(service, data)
            logger.info("Credenciales restauradas para %s desde backup", service)
        except Exception as exc:
            logger.error(
                "ERROR CRÍTICO: No se pudo restaurar backup para %s: %s",
                service, exc,
            )
