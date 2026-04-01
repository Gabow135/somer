"""Resolución de secretos en runtime — motor principal.

Portado de OpenClaw: runtime.ts, runtime-shared.ts, resolve.ts.
Gestiona la resolución de SecretRefs en el contexto de la configuración
activa, creando y aplicando snapshots de secretos resueltos.
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

from config.schema import SomerConfig
from secrets.refs import (
    SecretExpectedValue,
    SecretRef,
    SecretResolveCache,
    is_expected_resolved_value,
    resolve_refs_batch,
)
from shared.errors import SecretRefResolutionError

logger = logging.getLogger(__name__)


# ── Tipos de warning ────────────────────────────────────────

class SecretResolverWarningCode:
    """Códigos de warning durante la resolución de secretos.

    Portado de OpenClaw: runtime-shared.ts SecretResolverWarningCode.
    """
    REF_OVERRIDES_PLAINTEXT = "SECRETS_REF_OVERRIDES_PLAINTEXT"
    REF_IGNORED_INACTIVE = "SECRETS_REF_IGNORED_INACTIVE_SURFACE"


@dataclass
class SecretResolverWarning:
    """Warning emitido durante la resolución de secretos.

    Portado de OpenClaw: runtime-shared.ts SecretResolverWarning.
    """
    code: str
    path: str
    message: str


# ── Asignaciones ────────────────────────────────────────────

@dataclass
class SecretAssignment:
    """Asignación pendiente de un secreto a un campo de configuración.

    Portado de OpenClaw: runtime-shared.ts SecretAssignment.
    """
    ref: SecretRef
    path: str
    expected: SecretExpectedValue
    apply: Callable[[Any], None]


# ── Contexto de resolución ──────────────────────────────────

@dataclass
class ResolverContext:
    """Contexto acumulativo para la resolución de secretos.

    Portado de OpenClaw: runtime-shared.ts ResolverContext.

    Acumula asignaciones, warnings y mantiene caché de resolución
    durante todo el proceso de recolección y aplicación.
    """
    source_config: SomerConfig
    env: Dict[str, str] = field(default_factory=dict)
    cache: SecretResolveCache = field(default_factory=SecretResolveCache)
    warnings: List[SecretResolverWarning] = field(default_factory=list)
    warning_keys: Set[str] = field(default_factory=set)
    assignments: List[SecretAssignment] = field(default_factory=list)


def create_resolver_context(
    source_config: SomerConfig,
    env: Optional[Dict[str, str]] = None,
) -> ResolverContext:
    """Crea un nuevo contexto de resolución.

    Portado de OpenClaw: runtime-shared.ts createResolverContext().

    Args:
        source_config: Configuración original sin modificar.
        env: Variables de entorno (default: os.environ).

    Returns:
        ResolverContext configurado.
    """
    import os
    return ResolverContext(
        source_config=source_config,
        env=env if env is not None else dict(os.environ),
    )


# ── Helpers de contexto ─────────────────────────────────────

def push_warning(context: ResolverContext, warning: SecretResolverWarning) -> None:
    """Agrega un warning al contexto, deduplicando por clave.

    Portado de OpenClaw: runtime-shared.ts pushWarning().
    """
    key = f"{warning.code}:{warning.path}:{warning.message}"
    if key in context.warning_keys:
        return
    context.warning_keys.add(key)
    context.warnings.append(warning)


def push_inactive_surface_warning(
    context: ResolverContext,
    path: str,
    details: Optional[str] = None,
) -> None:
    """Agrega un warning de superficie inactiva.

    Portado de OpenClaw: runtime-shared.ts pushInactiveSurfaceWarning().
    """
    msg = (
        f"{path}: {details}"
        if details and details.strip()
        else f"{path}: secret ref configurado en superficie inactiva; "
             f"se omite resolución hasta que se active."
    )
    push_warning(context, SecretResolverWarning(
        code=SecretResolverWarningCode.REF_IGNORED_INACTIVE,
        path=path,
        message=msg,
    ))


def push_assignment(context: ResolverContext, assignment: SecretAssignment) -> None:
    """Agrega una asignación pendiente al contexto.

    Portado de OpenClaw: runtime-shared.ts pushAssignment().
    """
    context.assignments.append(assignment)


def collect_secret_input_assignment(
    *,
    value: Any,
    path: str,
    expected: SecretExpectedValue,
    context: ResolverContext,
    active: Optional[bool] = None,
    inactive_reason: Optional[str] = None,
    apply: Callable[[Any], None],
) -> None:
    """Recolecta una asignación de secreto si el valor es un SecretRef.

    Portado de OpenClaw: runtime-shared.ts collectSecretInputAssignment().

    Detecta si el valor es una referencia a secreto (string con formato
    SecretRef) y lo registra como asignación pendiente.

    Args:
        value: Valor del campo (puede ser SecretRef string, literal, etc.).
        path: Ruta del campo en la configuración.
        expected: Tipo esperado del valor resuelto.
        context: Contexto de resolución.
        active: Si la superficie está activa (None = siempre activa).
        inactive_reason: Razón si está inactiva.
        apply: Función para aplicar el valor resuelto.
    """
    ref = _coerce_secret_ref(value)
    if ref is None:
        return
    if active is False:
        push_inactive_surface_warning(
            context=context,
            path=path,
            details=inactive_reason,
        )
        return
    push_assignment(context, SecretAssignment(
        ref=ref,
        path=path,
        expected=expected,
        apply=apply,
    ))


def _coerce_secret_ref(value: Any) -> Optional[SecretRef]:
    """Intenta convertir un valor a SecretRef.

    Portado de OpenClaw: config/types.secrets.ts coerceSecretRef().
    """
    if isinstance(value, SecretRef):
        return value
    if isinstance(value, str):
        return SecretRef.parse_ref_string(value)
    if isinstance(value, dict):
        try:
            return SecretRef(**value)
        except Exception:
            return None
    return None


# ── Aplicación de asignaciones resueltas ────────────────────

async def apply_resolved_assignments(
    assignments: List[SecretAssignment],
    resolved: Dict[str, str],
) -> None:
    """Aplica los valores resueltos a las asignaciones pendientes.

    Portado de OpenClaw: runtime-shared.ts applyResolvedAssignments().

    Args:
        assignments: Lista de asignaciones pendientes.
        resolved: Dict de ref_key → valor resuelto.

    Raises:
        SecretRefResolutionError: Si alguna referencia no tiene valor.
    """
    for assignment in assignments:
        key = assignment.ref.ref_key()
        if key not in resolved:
            raise SecretRefResolutionError(
                f"Referencia '{key}' no se resolvió a ningún valor."
            )
        value = resolved[key]
        if not is_expected_resolved_value(value, assignment.expected):
            if assignment.expected == SecretExpectedValue.STRING:
                raise SecretRefResolutionError(
                    f"{assignment.path} se resolvió a un valor no-string o vacío."
                )
            else:
                raise SecretRefResolutionError(
                    f"{assignment.path} se resolvió a un tipo de valor no soportado."
                )
        assignment.apply(value)


# ── Snapshot de secretos ────────────────────────────────────

@dataclass
class SecretsRuntimeSnapshot:
    """Snapshot de una configuración con secretos resueltos.

    Portado de OpenClaw: runtime.ts PreparedSecretsRuntimeSnapshot.
    """
    source_config: SomerConfig
    config: SomerConfig
    warnings: List[SecretResolverWarning] = field(default_factory=list)


# Estado global del snapshot activo
_active_snapshot: Optional[SecretsRuntimeSnapshot] = None


async def prepare_secrets_snapshot(
    config: SomerConfig,
    env: Optional[Dict[str, str]] = None,
) -> SecretsRuntimeSnapshot:
    """Prepara un snapshot de secretos resueltos.

    Portado de OpenClaw: runtime.ts prepareSecretsRuntimeSnapshot().

    1. Clona la configuración.
    2. Recolecta todas las asignaciones de secretos.
    3. Resuelve las referencias en lote.
    4. Aplica los valores resueltos.

    Args:
        config: Configuración de SOMER.
        env: Variables de entorno (default: os.environ).

    Returns:
        SecretsRuntimeSnapshot con la config resuelta.
    """
    from secrets.collectors import collect_all_assignments

    source_config = config.model_copy(deep=True)
    resolved_config = config.model_copy(deep=True)

    context = create_resolver_context(source_config, env)
    collect_all_assignments(config=resolved_config, context=context)

    if context.assignments:
        refs = [a.ref for a in context.assignments]
        resolved = await resolve_refs_batch(refs, cache=context.cache)
        await apply_resolved_assignments(context.assignments, resolved)

    return SecretsRuntimeSnapshot(
        source_config=source_config,
        config=resolved_config,
        warnings=context.warnings,
    )


def activate_snapshot(snapshot: SecretsRuntimeSnapshot) -> None:
    """Activa un snapshot de secretos como el snapshot global.

    Portado de OpenClaw: runtime.ts activateSecretsRuntimeSnapshot().
    """
    global _active_snapshot
    _active_snapshot = snapshot
    logger.info(
        "Snapshot de secretos activado (%d warnings)",
        len(snapshot.warnings),
    )


def get_active_snapshot() -> Optional[SecretsRuntimeSnapshot]:
    """Obtiene el snapshot activo de secretos.

    Portado de OpenClaw: runtime.ts getActiveSecretsRuntimeSnapshot().
    """
    return _active_snapshot


def clear_snapshot() -> None:
    """Limpia el snapshot activo de secretos.

    Portado de OpenClaw: runtime.ts clearSecretsRuntimeSnapshot().
    """
    global _active_snapshot
    _active_snapshot = None
    logger.info("Snapshot de secretos limpiado")
