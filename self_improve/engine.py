"""Motor de auto-mejora de SOMER.

Coordina las operaciones de auto-mejora:
- Escanear y aprender patrones de skills
- Aplicar parches a archivos del proyecto
- Validar cambios (syntax check, tests)
- Solicitar restart para aplicar cambios
- Reportar estado y mejoras realizadas
"""

from __future__ import annotations

import ast
import json
import logging
import os
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from self_improve.learner import PatternLearner
from self_improve.paths import get_project_root, get_somer_home

logger = logging.getLogger(__name__)

IMPROVEMENT_LOG = "improvements.jsonl"


@dataclass
class ImprovementRecord:
    """Registro de una mejora aplicada."""
    timestamp: float
    action: str  # learn_patterns, patch_file, add_pattern, restart
    target: str  # archivo o módulo afectado
    description: str
    success: bool
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PatchResult:
    """Resultado de aplicar un parche."""
    file_path: str
    success: bool
    backup_path: str = ""
    error: str = ""
    lines_changed: int = 0


@dataclass
class ValidationResult:
    """Resultado de validar un archivo modificado."""
    file_path: str
    valid: bool
    errors: List[str] = field(default_factory=list)


class SelfImproveEngine:
    """Motor principal de auto-mejora.

    Capacidades:
    - Aprender patrones nuevos de credenciales
    - Aplicar parches seguros a archivos Python
    - Validar cambios antes de aplicar
    - Solicitar restart del servicio
    - Registrar historial de mejoras

    Uso:
        engine = SelfImproveEngine()
        result = engine.learn_from_skills()
        engine.request_restart("Nuevos patrones de credenciales")
    """

    def __init__(self) -> None:
        self._home = get_somer_home()
        self._project_root = get_project_root()
        self._learner = PatternLearner()
        self._log_path = self._home / IMPROVEMENT_LOG

    # ── Aprendizaje ───────────────────────────────────────────

    def learn_from_skills(self) -> Dict[str, Any]:
        """Escanea skills y aprende patrones nuevos.

        Returns:
            Dict con resultados: new_patterns, total, skills_scanned
        """
        new_count = self._learner.scan_and_learn()
        stats = self._learner.stats

        self._log_improvement(ImprovementRecord(
            timestamp=time.time(),
            action="learn_patterns",
            target="skills/",
            description=f"Escaneados {stats['skills_scanned']} skills, {new_count} patrones nuevos",
            success=True,
            details=stats,
        ))

        return {
            "new_patterns": new_count,
            "total_patterns": stats["total_patterns"],
            "skills_scanned": stats["skills_scanned"],
        }

    def get_learned_patterns(self) -> List[Dict[str, Any]]:
        """Retorna patrones aprendidos como lista de dicts."""
        return [asdict(p) for p in self._learner.get_patterns()]

    # ── Parches seguros ───────────────────────────────────────

    def patch_file(
        self,
        relative_path: str,
        old_content: str,
        new_content: str,
        *,
        dry_run: bool = False,
    ) -> PatchResult:
        """Aplica un parche a un archivo del proyecto con backup.

        Args:
            relative_path: Path relativo desde project root.
            old_content: Texto exacto a reemplazar.
            new_content: Texto de reemplazo.
            dry_run: Si True, solo valida sin aplicar.

        Returns:
            PatchResult con el resultado.
        """
        if not self._project_root:
            return PatchResult(
                file_path=relative_path,
                success=False,
                error="No se encontró el project root",
            )

        file_path = self._project_root / relative_path
        if not file_path.exists():
            return PatchResult(
                file_path=relative_path,
                success=False,
                error=f"Archivo no encontrado: {file_path}",
            )

        # Leer contenido actual
        current = file_path.read_text(encoding="utf-8")
        if old_content not in current:
            return PatchResult(
                file_path=relative_path,
                success=False,
                error="old_content no encontrado en el archivo",
            )

        # Aplicar parche
        patched = current.replace(old_content, new_content, 1)

        # Validar si es Python
        if file_path.suffix == ".py":
            validation = self.validate_python(patched, str(file_path))
            if not validation.valid:
                return PatchResult(
                    file_path=relative_path,
                    success=False,
                    error=f"Validación falló: {'; '.join(validation.errors)}",
                )

        if dry_run:
            return PatchResult(
                file_path=relative_path,
                success=True,
                lines_changed=abs(
                    len(new_content.splitlines()) - len(old_content.splitlines())
                ),
            )

        # Crear backup
        backup_path = file_path.with_suffix(file_path.suffix + ".bak")
        backup_path.write_text(current, encoding="utf-8")

        # Escribir parche
        file_path.write_text(patched, encoding="utf-8")

        lines_changed = abs(
            len(new_content.splitlines()) - len(old_content.splitlines())
        )

        self._log_improvement(ImprovementRecord(
            timestamp=time.time(),
            action="patch_file",
            target=relative_path,
            description=f"Parche aplicado: {lines_changed} líneas cambiadas",
            success=True,
            details={"backup": str(backup_path)},
        ))

        return PatchResult(
            file_path=relative_path,
            success=True,
            backup_path=str(backup_path),
            lines_changed=lines_changed,
        )

    def revert_patch(self, relative_path: str) -> bool:
        """Revierte un parche restaurando el backup.

        Returns:
            True si se restauró exitosamente.
        """
        if not self._project_root:
            return False

        file_path = self._project_root / relative_path
        backup_path = file_path.with_suffix(file_path.suffix + ".bak")

        if not backup_path.exists():
            logger.warning("No hay backup para %s", relative_path)
            return False

        backup_content = backup_path.read_text(encoding="utf-8")
        file_path.write_text(backup_content, encoding="utf-8")
        backup_path.unlink()

        self._log_improvement(ImprovementRecord(
            timestamp=time.time(),
            action="revert_patch",
            target=relative_path,
            description="Parche revertido desde backup",
            success=True,
        ))

        return True

    # ── Validación ────────────────────────────────────────────

    def validate_python(self, source: str, filename: str = "<patch>") -> ValidationResult:
        """Valida que código Python es sintácticamente correcto.

        Args:
            source: Código fuente Python.
            filename: Nombre de archivo para mensajes de error.

        Returns:
            ValidationResult.
        """
        errors: List[str] = []
        try:
            ast.parse(source, filename=filename)
        except SyntaxError as exc:
            errors.append(f"SyntaxError línea {exc.lineno}: {exc.msg}")

        return ValidationResult(
            file_path=filename,
            valid=len(errors) == 0,
            errors=errors,
        )

    def run_tests(self, test_path: str = "tests/unit/") -> Tuple[bool, str]:
        """Ejecuta tests para validar que los cambios no rompen nada.

        Args:
            test_path: Path relativo a los tests.

        Returns:
            Tupla (passed, output).
        """
        if not self._project_root:
            return False, "No se encontró project root"

        full_path = self._project_root / test_path
        if not full_path.exists():
            return False, f"Path de tests no encontrado: {full_path}"

        try:
            result = subprocess.run(
                ["python3", "-m", "pytest", str(full_path), "-v", "--tb=short", "-q"],
                capture_output=True,
                text=True,
                timeout=120,
                env={**os.environ, "PYTHONPATH": str(self._project_root)},
                cwd=str(self._project_root),
            )
            passed = result.returncode == 0
            output = result.stdout + result.stderr
            # Limitar output
            if len(output) > 3000:
                output = output[-3000:]
            return passed, output
        except subprocess.TimeoutExpired:
            return False, "Tests excedieron timeout de 120s"
        except Exception as exc:
            return False, f"Error ejecutando tests: {exc}"

    # ── Restart ───────────────────────────────────────────────

    def request_restart(self, reason: str = "Auto-mejora aplicada") -> bool:
        """Solicita reinicio del servicio para aplicar cambios.

        Usa el RestartSentinel existente de SOMER.

        Returns:
            True si la solicitud se registró.
        """
        try:
            from infra.restart_sentinel import RestartSentinel
            sentinel = RestartSentinel()
            sentinel.request_restart(
                reason=reason,
                requested_by="self_improve",
            )

            self._log_improvement(ImprovementRecord(
                timestamp=time.time(),
                action="restart",
                target="service",
                description=f"Restart solicitado: {reason}",
                success=True,
            ))

            return True
        except Exception as exc:
            logger.error("Error solicitando restart: %s", exc)
            return False

    def force_restart(self) -> bool:
        """Reinicia el proceso actual con os.execv (hard restart).

        PELIGROSO: Solo usar cuando el sentinel no es suficiente.

        Returns:
            True si se inició el restart (no debería retornar).
        """
        import sys

        self._log_improvement(ImprovementRecord(
            timestamp=time.time(),
            action="force_restart",
            target="process",
            description="Hard restart via os.execv",
            success=True,
        ))

        try:
            os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception as exc:
            logger.error("Error en force_restart: %s", exc)
            return False
        return True  # No debería llegar aquí

    # ── Estado e historial ────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """Retorna estado completo del engine."""
        from infra.restart_sentinel import RestartSentinel
        sentinel = RestartSentinel()

        return {
            "project_root": str(self._project_root) if self._project_root else None,
            "somer_home": str(self._home),
            "learner": self._learner.stats,
            "restart_pending": sentinel.is_pending(),
            "improvements_logged": self._count_improvements(),
        }

    def get_improvement_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Retorna historial de mejoras recientes.

        Args:
            limit: Máximo de registros a retornar.

        Returns:
            Lista de registros de mejora (más recientes primero).
        """
        if not self._log_path.exists():
            return []

        records = []
        for line in self._log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        return list(reversed(records[-limit:]))

    # ── Helpers internos ──────────────────────────────────────

    def _log_improvement(self, record: ImprovementRecord) -> None:
        """Registra una mejora en el log JSONL."""
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")

    def _count_improvements(self) -> int:
        """Cuenta registros de mejora."""
        if not self._log_path.exists():
            return 0
        try:
            return sum(
                1 for line in self._log_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
        except OSError:
            return 0
