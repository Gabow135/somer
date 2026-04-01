"""Skill registry — registro, búsqueda, dependencias y estadísticas de skills.

Portado desde la arquitectura de plugins de SOMER, adaptado al sistema
de skills basado en SKILL.md.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from shared.errors import SkillError, SkillNotFoundError
from shared.types import SkillMeta

logger = logging.getLogger(__name__)


# ── Tipos auxiliares ─────────────────────────────────────────


@dataclass
class SkillDiagnostic:
    """Diagnóstico emitido durante registro o resolución de skills."""

    level: str  # "info" | "warn" | "error"
    skill_name: str
    message: str
    timestamp: float = field(default_factory=time.time)

    def __str__(self) -> str:
        return f"[{self.level.upper()}] {self.skill_name}: {self.message}"


@dataclass
class SkillUsageStats:
    """Estadísticas de uso de un skill."""

    invocations: int = 0
    last_invoked: float = 0.0
    errors: int = 0
    total_duration_ms: float = 0.0

    @property
    def avg_duration_ms(self) -> float:
        """Duración promedio por invocación en milisegundos."""
        if self.invocations == 0:
            return 0.0
        return self.total_duration_ms / self.invocations


# ── Filtros ──────────────────────────────────────────────────


@dataclass
class SkillFilter:
    """Filtro compuesto para búsqueda de skills."""

    tag: Optional[str] = None
    category: Optional[str] = None
    enabled: Optional[bool] = None
    name_contains: Optional[str] = None
    has_trigger: Optional[str] = None
    min_invocations: Optional[int] = None

    def matches(self, skill: SkillMeta, stats: SkillUsageStats) -> bool:
        """Evalúa si un skill cumple todos los criterios del filtro."""
        if self.tag is not None:
            if self.tag.lower() not in [t.lower() for t in skill.tags]:
                return False
        if self.category is not None:
            if skill.category.lower() != self.category.lower():
                return False
        if self.enabled is not None:
            if skill.enabled != self.enabled:
                return False
        if self.name_contains is not None:
            if self.name_contains.lower() not in skill.name.lower():
                return False
        if self.has_trigger is not None:
            trigger_lower = self.has_trigger.lower()
            if not any(trigger_lower in t.lower() for t in skill.triggers):
                return False
        if self.min_invocations is not None:
            if stats.invocations < self.min_invocations:
                return False
        return True


# ── Registry ─────────────────────────────────────────────────


class SkillRegistry:
    """Registro central de skills con búsqueda, dependencias y estadísticas.

    Funcionalidades portadas desde SOMER PluginRegistry:
    - Registro con metadata completa y detección de conflictos (triggers duplicados).
    - Resolución de dependencias entre skills.
    - Enable/disable/toggle individual y por categoría.
    - Búsqueda por nombre, tag, categoría y filtros compuestos.
    - Tracking de uso y estadísticas.
    - Operaciones bulk.
    - Sistema de diagnósticos (warnings y errores de registro).
    """

    def __init__(self) -> None:
        self._skills: Dict[str, SkillMeta] = {}
        self._trigger_index: Dict[str, str] = {}  # trigger → skill name
        self._usage: Dict[str, SkillUsageStats] = {}
        self._diagnostics: List[SkillDiagnostic] = []
        self._on_change_callbacks: List[Callable[[str, str], None]] = []

    # ── Diagnósticos ─────────────────────────────────────────

    def _push_diagnostic(
        self, level: str, skill_name: str, message: str
    ) -> None:
        """Registra un diagnóstico interno."""
        diag = SkillDiagnostic(level=level, skill_name=skill_name, message=message)
        self._diagnostics.append(diag)
        log_fn = getattr(logger, level, logger.warning)
        log_fn("Skill %s: %s", skill_name, message)

    @property
    def diagnostics(self) -> List[SkillDiagnostic]:
        """Retorna todos los diagnósticos acumulados."""
        return list(self._diagnostics)

    def clear_diagnostics(self) -> None:
        """Limpia los diagnósticos acumulados."""
        self._diagnostics.clear()

    # ── Callbacks de cambio ──────────────────────────────────

    def on_change(self, callback: Callable[[str, str], None]) -> None:
        """Registra un callback que se invoca al cambiar estado de un skill.

        El callback recibe (skill_name, action) donde action es una de:
        "registered", "unregistered", "enabled", "disabled", "toggled".
        """
        self._on_change_callbacks.append(callback)

    def _notify_change(self, skill_name: str, action: str) -> None:
        """Notifica a todos los callbacks registrados."""
        for cb in self._on_change_callbacks:
            try:
                cb(skill_name, action)
            except Exception:
                logger.exception(
                    "Error en callback de cambio para skill %s", skill_name
                )

    # ── Registro / des-registro ──────────────────────────────

    def register(self, skill: SkillMeta) -> List[SkillDiagnostic]:
        """Registra un skill con detección de conflictos de triggers.

        Si el skill ya existe con el mismo nombre, se sobrescribe.
        Si un trigger ya está ocupado por otro skill, se emite un
        diagnóstico de error y se omite ese trigger (el skill se
        registra igual con los triggers no conflictivos).

        Args:
            skill: Metadata del skill a registrar.

        Returns:
            Lista de diagnósticos generados durante el registro.
        """
        registration_diags: List[SkillDiagnostic] = []

        # Si ya existe, limpiar triggers anteriores
        if skill.name in self._skills:
            self._remove_triggers(skill.name)

        self._skills[skill.name] = skill

        # Inicializar stats si es skill nuevo
        if skill.name not in self._usage:
            self._usage[skill.name] = SkillUsageStats()

        # Registrar triggers con detección de conflictos
        registered_triggers = 0
        for trigger in skill.triggers:
            trigger_lower = trigger.lower()
            existing_owner = self._trigger_index.get(trigger_lower)
            if existing_owner and existing_owner != skill.name:
                diag = SkillDiagnostic(
                    level="error",
                    skill_name=skill.name,
                    message=(
                        f"Conflicto de trigger: '{trigger}' ya registrado "
                        f"por skill '{existing_owner}'"
                    ),
                )
                self._diagnostics.append(diag)
                registration_diags.append(diag)
                logger.error(
                    "Skill %s: conflicto de trigger '%s' con '%s'",
                    skill.name,
                    trigger,
                    existing_owner,
                )
            else:
                self._trigger_index[trigger_lower] = skill.name
                registered_triggers += 1

        logger.debug(
            "Skill registrado: %s (%d/%d triggers, categoría=%s)",
            skill.name,
            registered_triggers,
            len(skill.triggers),
            skill.category,
        )
        self._notify_change(skill.name, "registered")
        return registration_diags

    def register_many(self, skills: List[SkillMeta]) -> List[SkillDiagnostic]:
        """Registra múltiples skills de una vez.

        Args:
            skills: Lista de skills a registrar.

        Returns:
            Lista acumulada de diagnósticos de todos los registros.
        """
        all_diags: List[SkillDiagnostic] = []
        for skill in skills:
            diags = self.register(skill)
            all_diags.extend(diags)
        return all_diags

    def unregister(self, name: str) -> bool:
        """Elimina un skill del registro.

        Args:
            name: Nombre del skill a eliminar.

        Returns:
            True si el skill existía y fue eliminado, False si no existía.
        """
        skill = self._skills.pop(name, None)
        if skill is None:
            return False
        self._remove_triggers(name)
        self._usage.pop(name, None)
        self._notify_change(name, "unregistered")
        return True

    def _remove_triggers(self, skill_name: str) -> None:
        """Elimina todos los triggers asociados a un skill del índice."""
        to_remove = [
            trigger
            for trigger, owner in self._trigger_index.items()
            if owner == skill_name
        ]
        for trigger in to_remove:
            del self._trigger_index[trigger]

    # ── Lookup ───────────────────────────────────────────────

    def get(self, name: str) -> Optional[SkillMeta]:
        """Obtiene un skill por nombre exacto."""
        return self._skills.get(name)

    def get_or_raise(self, name: str) -> SkillMeta:
        """Obtiene un skill por nombre, lanza excepción si no existe.

        Raises:
            SkillNotFoundError: Si el skill no está registrado.
        """
        skill = self._skills.get(name)
        if skill is None:
            raise SkillNotFoundError(f"Skill no encontrado: '{name}'")
        return skill

    def match_trigger(self, text: str) -> Optional[SkillMeta]:
        """Busca un skill habilitado que matchee con el texto dado.

        Recorre el índice de triggers y retorna el primer skill habilitado
        cuyo trigger aparezca como substring en el texto.

        Args:
            text: Texto del usuario.

        Returns:
            SkillMeta si hay match, None si no.
        """
        text_lower = text.lower()
        for trigger, skill_name in self._trigger_index.items():
            if trigger in text_lower:
                skill = self._skills.get(skill_name)
                if skill and skill.enabled:
                    return skill
        return None

    def match_all_triggers(self, text: str) -> List[SkillMeta]:
        """Retorna todos los skills habilitados que matcheen con el texto.

        A diferencia de match_trigger(), retorna todos los matches, no solo
        el primero. Útil para resolución de ambigüedades.

        Args:
            text: Texto del usuario.

        Returns:
            Lista de SkillMeta que matchean (puede estar vacía).
        """
        text_lower = text.lower()
        seen: Set[str] = set()
        results: List[SkillMeta] = []
        for trigger, skill_name in self._trigger_index.items():
            if trigger in text_lower and skill_name not in seen:
                skill = self._skills.get(skill_name)
                if skill and skill.enabled:
                    results.append(skill)
                    seen.add(skill_name)
        return results

    # ── Búsqueda por tag / categoría ─────────────────────────

    def search_by_tag(self, tag: str) -> List[SkillMeta]:
        """Busca skills por tag (case-insensitive)."""
        tag_lower = tag.lower()
        return [
            s
            for s in self._skills.values()
            if tag_lower in [t.lower() for t in s.tags]
        ]

    def search_by_category(self, category: str) -> List[SkillMeta]:
        """Busca skills por categoría (case-insensitive)."""
        cat_lower = category.lower()
        return [
            s
            for s in self._skills.values()
            if s.category.lower() == cat_lower
        ]

    def search(self, skill_filter: SkillFilter) -> List[SkillMeta]:
        """Búsqueda avanzada con filtro compuesto.

        Args:
            skill_filter: Criterios de filtrado.

        Returns:
            Lista de skills que cumplen todos los criterios.
        """
        return [
            s
            for s in self._skills.values()
            if skill_filter.matches(s, self._usage.get(s.name, SkillUsageStats()))
        ]

    def list_categories(self) -> List[str]:
        """Retorna todas las categorías únicas registradas."""
        return sorted({s.category for s in self._skills.values()})

    def list_tags(self) -> List[str]:
        """Retorna todos los tags únicos registrados."""
        tags: Set[str] = set()
        for s in self._skills.values():
            tags.update(s.tags)
        return sorted(tags)

    # ── Listado ──────────────────────────────────────────────

    def list_skills(self) -> List[SkillMeta]:
        """Retorna todos los skills registrados."""
        return list(self._skills.values())

    def list_enabled(self) -> List[SkillMeta]:
        """Retorna solo los skills habilitados."""
        return [s for s in self._skills.values() if s.enabled]

    def list_disabled(self) -> List[SkillMeta]:
        """Retorna solo los skills deshabilitados."""
        return [s for s in self._skills.values() if not s.enabled]

    # ── Enable / Disable / Toggle ────────────────────────────

    def enable(self, name: str) -> bool:
        """Habilita un skill.

        Args:
            name: Nombre del skill.

        Returns:
            True si el skill fue encontrado y habilitado, False si no existe.
        """
        skill = self._skills.get(name)
        if skill is None:
            return False
        if not skill.enabled:
            skill.enabled = True
            self._notify_change(name, "enabled")
            logger.info("Skill habilitado: %s", name)
        return True

    def disable(self, name: str) -> bool:
        """Deshabilita un skill.

        Args:
            name: Nombre del skill.

        Returns:
            True si el skill fue encontrado y deshabilitado, False si no existe.
        """
        skill = self._skills.get(name)
        if skill is None:
            return False
        if skill.enabled:
            skill.enabled = False
            self._notify_change(name, "disabled")
            logger.info("Skill deshabilitado: %s", name)
        return True

    def toggle(self, name: str) -> Optional[bool]:
        """Alterna el estado habilitado/deshabilitado de un skill.

        Args:
            name: Nombre del skill.

        Returns:
            Nuevo estado (True=habilitado, False=deshabilitado), o None si
            el skill no existe.
        """
        skill = self._skills.get(name)
        if skill is None:
            return None
        skill.enabled = not skill.enabled
        self._notify_change(name, "toggled")
        logger.info(
            "Skill %s: %s",
            name,
            "habilitado" if skill.enabled else "deshabilitado",
        )
        return skill.enabled

    # ── Operaciones bulk ─────────────────────────────────────

    def enable_all(self) -> int:
        """Habilita todos los skills. Retorna la cantidad de skills afectados."""
        count = 0
        for skill in self._skills.values():
            if not skill.enabled:
                skill.enabled = True
                self._notify_change(skill.name, "enabled")
                count += 1
        if count:
            logger.info("Habilitados %d skills", count)
        return count

    def disable_all(self) -> int:
        """Deshabilita todos los skills. Retorna la cantidad de skills afectados."""
        count = 0
        for skill in self._skills.values():
            if skill.enabled:
                skill.enabled = False
                self._notify_change(skill.name, "disabled")
                count += 1
        if count:
            logger.info("Deshabilitados %d skills", count)
        return count

    def enable_category(self, category: str) -> int:
        """Habilita todos los skills de una categoría.

        Args:
            category: Categoría a habilitar.

        Returns:
            Cantidad de skills afectados.
        """
        cat_lower = category.lower()
        count = 0
        for skill in self._skills.values():
            if skill.category.lower() == cat_lower and not skill.enabled:
                skill.enabled = True
                self._notify_change(skill.name, "enabled")
                count += 1
        if count:
            logger.info("Habilitados %d skills de categoría '%s'", count, category)
        return count

    def disable_category(self, category: str) -> int:
        """Deshabilita todos los skills de una categoría.

        Args:
            category: Categoría a deshabilitar.

        Returns:
            Cantidad de skills afectados.
        """
        cat_lower = category.lower()
        count = 0
        for skill in self._skills.values():
            if skill.category.lower() == cat_lower and skill.enabled:
                skill.enabled = False
                self._notify_change(skill.name, "disabled")
                count += 1
        if count:
            logger.info("Deshabilitados %d skills de categoría '%s'", count, category)
        return count

    def enable_by_tag(self, tag: str) -> int:
        """Habilita todos los skills que tengan un tag específico.

        Args:
            tag: Tag a buscar.

        Returns:
            Cantidad de skills afectados.
        """
        tag_lower = tag.lower()
        count = 0
        for skill in self._skills.values():
            if tag_lower in [t.lower() for t in skill.tags] and not skill.enabled:
                skill.enabled = True
                self._notify_change(skill.name, "enabled")
                count += 1
        return count

    def disable_by_tag(self, tag: str) -> int:
        """Deshabilita todos los skills que tengan un tag específico.

        Args:
            tag: Tag a buscar.

        Returns:
            Cantidad de skills afectados.
        """
        tag_lower = tag.lower()
        count = 0
        for skill in self._skills.values():
            if tag_lower in [t.lower() for t in skill.tags] and skill.enabled:
                skill.enabled = False
                self._notify_change(skill.name, "disabled")
                count += 1
        return count

    # ── Dependencias ─────────────────────────────────────────

    def resolve_dependencies(self, name: str) -> List[str]:
        """Resuelve el árbol de dependencias de un skill (orden topológico).

        Retorna la lista de nombres de skills necesarios para ejecutar el
        skill dado, en orden de ejecución (dependencias primero).

        Args:
            name: Nombre del skill raíz.

        Returns:
            Lista ordenada de nombres de skills (incluye el skill raíz al final).

        Raises:
            SkillNotFoundError: Si el skill o alguna dependencia no existe.
            SkillError: Si se detecta una dependencia circular.
        """
        resolved: List[str] = []
        visited: Set[str] = set()
        in_stack: Set[str] = set()

        self._resolve_deps_recursive(name, resolved, visited, in_stack)
        return resolved

    def _resolve_deps_recursive(
        self,
        name: str,
        resolved: List[str],
        visited: Set[str],
        in_stack: Set[str],
    ) -> None:
        """Resolución recursiva de dependencias con detección de ciclos."""
        if name in in_stack:
            raise SkillError(
                f"Dependencia circular detectada: '{name}' aparece en su "
                f"propia cadena de dependencias"
            )
        if name in visited:
            return

        skill = self._skills.get(name)
        if skill is None:
            raise SkillNotFoundError(
                f"Dependencia no encontrada: '{name}' no está registrado"
            )

        in_stack.add(name)
        for dep_name in skill.dependencies:
            self._resolve_deps_recursive(dep_name, resolved, visited, in_stack)
        in_stack.discard(name)

        visited.add(name)
        resolved.append(name)

    def check_dependencies(self, name: str) -> Tuple[bool, List[str]]:
        """Verifica si todas las dependencias de un skill están satisfechas.

        Args:
            name: Nombre del skill a verificar.

        Returns:
            Tupla (satisfechas, faltantes) donde satisfechas es True si todas
            las dependencias están registradas y habilitadas.
        """
        skill = self._skills.get(name)
        if skill is None:
            return False, [name]

        missing: List[str] = []
        for dep_name in skill.dependencies:
            dep = self._skills.get(dep_name)
            if dep is None:
                missing.append(dep_name)
            elif not dep.enabled:
                missing.append(f"{dep_name} (deshabilitado)")
        return len(missing) == 0, missing

    # ── Detección de conflictos ──────────────────────────────

    def detect_conflicts(self) -> List[SkillDiagnostic]:
        """Detecta conflictos en el registro actual.

        Busca:
        - Triggers duplicados (dos skills reclamando el mismo trigger).
        - Dependencias faltantes.
        - Dependencias circulares.

        Returns:
            Lista de diagnósticos encontrados.
        """
        conflicts: List[SkillDiagnostic] = []

        # Verificar triggers: construir mapa reverso
        trigger_owners: Dict[str, List[str]] = {}
        for skill in self._skills.values():
            for trigger in skill.triggers:
                trigger_lower = trigger.lower()
                trigger_owners.setdefault(trigger_lower, []).append(skill.name)
        for trigger, owners in trigger_owners.items():
            if len(owners) > 1:
                conflicts.append(
                    SkillDiagnostic(
                        level="error",
                        skill_name=", ".join(owners),
                        message=f"Trigger compartido: '{trigger}' reclamado por {owners}",
                    )
                )

        # Verificar dependencias
        for skill in self._skills.values():
            for dep_name in skill.dependencies:
                if dep_name not in self._skills:
                    conflicts.append(
                        SkillDiagnostic(
                            level="warn",
                            skill_name=skill.name,
                            message=f"Dependencia faltante: '{dep_name}'",
                        )
                    )

            # Verificar ciclos
            try:
                self.resolve_dependencies(skill.name)
            except SkillError as exc:
                conflicts.append(
                    SkillDiagnostic(
                        level="error",
                        skill_name=skill.name,
                        message=str(exc),
                    )
                )

        return conflicts

    # ── Estadísticas de uso ──────────────────────────────────

    def record_invocation(
        self, name: str, duration_ms: float = 0.0, error: bool = False
    ) -> None:
        """Registra una invocación de un skill.

        Args:
            name: Nombre del skill invocado.
            duration_ms: Duración de la invocación en milisegundos.
            error: True si la invocación terminó en error.
        """
        stats = self._usage.get(name)
        if stats is None:
            stats = SkillUsageStats()
            self._usage[name] = stats
        stats.invocations += 1
        stats.last_invoked = time.time()
        stats.total_duration_ms += duration_ms
        if error:
            stats.errors += 1

    def get_usage_stats(self, name: str) -> Optional[SkillUsageStats]:
        """Obtiene las estadísticas de uso de un skill."""
        return self._usage.get(name)

    def get_all_usage_stats(self) -> Dict[str, SkillUsageStats]:
        """Retorna las estadísticas de uso de todos los skills."""
        return dict(self._usage)

    def get_most_used(self, limit: int = 10) -> List[Tuple[str, SkillUsageStats]]:
        """Retorna los skills más usados, ordenados por invocaciones.

        Args:
            limit: Máximo de resultados.

        Returns:
            Lista de tuplas (nombre, stats) ordenada descendentemente.
        """
        ranked = sorted(
            self._usage.items(),
            key=lambda item: item[1].invocations,
            reverse=True,
        )
        return ranked[:limit]

    def reset_usage_stats(self, name: Optional[str] = None) -> None:
        """Resetea estadísticas de uso.

        Args:
            name: Si se proporciona, resetea solo ese skill. Si es None,
                  resetea todos.
        """
        if name is not None:
            if name in self._usage:
                self._usage[name] = SkillUsageStats()
        else:
            for key in self._usage:
                self._usage[key] = SkillUsageStats()

    # ── Resumen ──────────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        """Retorna un resumen completo del estado del registro.

        Incluye conteos por categoría, estado, triggers, y diagnósticos.
        """
        by_category: Dict[str, int] = {}
        for skill in self._skills.values():
            by_category[skill.category] = by_category.get(skill.category, 0) + 1

        total_invocations = sum(s.invocations for s in self._usage.values())
        total_errors = sum(s.errors for s in self._usage.values())

        return {
            "total_skills": len(self._skills),
            "enabled": sum(1 for s in self._skills.values() if s.enabled),
            "disabled": sum(1 for s in self._skills.values() if not s.enabled),
            "total_triggers": len(self._trigger_index),
            "categories": by_category,
            "total_invocations": total_invocations,
            "total_errors": total_errors,
            "diagnostics_count": len(self._diagnostics),
        }

    # ── Propiedades ──────────────────────────────────────────

    @property
    def skill_count(self) -> int:
        """Cantidad total de skills registrados."""
        return len(self._skills)

    @property
    def trigger_count(self) -> int:
        """Cantidad total de triggers indexados."""
        return len(self._trigger_index)

    def __contains__(self, name: str) -> bool:
        """Permite usar 'name in registry'."""
        return name in self._skills

    def __len__(self) -> int:
        return len(self._skills)

    def __repr__(self) -> str:
        enabled = sum(1 for s in self._skills.values() if s.enabled)
        return (
            f"<SkillRegistry skills={len(self._skills)} "
            f"enabled={enabled} triggers={len(self._trigger_index)}>"
        )
