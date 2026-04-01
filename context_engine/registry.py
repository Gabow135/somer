"""Registry para Context Engine plugins.

Portado de OpenClaw registry.ts — adaptado a convenciones SOMER 2.0.

El registry mantiene un mapa global de fábricas de ContextEngine,
soporta registros con dueño (owner), prioridad, habilitación/deshabilitación
y resolución desde la configuración.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import IntEnum
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    Sequence,
    Type,
    Union,
)

from context_engine.base import ContextEngine
from shared.errors import SomerError

logger = logging.getLogger(__name__)

# ── Tipos ────────────────────────────────────────────────────

# Una fábrica puede ser: una clase de ContextEngine, un callable que
# retorna una instancia, o un callable async que retorna una instancia.
ContextEngineFactory = Union[
    Type[ContextEngine],
    Callable[..., ContextEngine],
    Callable[..., Awaitable[ContextEngine]],
]

# Propietarios reservados
CORE_OWNER = "core"
PUBLIC_SDK_OWNER = "public-sdk"
DEFAULT_ENGINE_ID = "default"


# ── Excepciones ──────────────────────────────────────────────

class ContextEngineRegistryError(SomerError):
    """Error en el registry de context engines."""


class EngineNotRegisteredError(ContextEngineRegistryError):
    """Engine no registrado en el registry."""


class EngineOwnerConflictError(ContextEngineRegistryError):
    """Conflicto de propietario al registrar un engine."""


class EngineAlreadyRegisteredError(ContextEngineRegistryError):
    """Engine ya registrado (sin permiso de refresh)."""


# ── Enums ────────────────────────────────────────────────────

class EnginePhase(IntEnum):
    """Fases del ciclo de vida del context engine, ordenadas por ejecución."""
    BOOTSTRAP = 10
    INGEST = 20
    ASSEMBLE = 30
    COMPACT = 40
    AFTER_TURN = 50


class RegistrationStatus(IntEnum):
    """Estado de un registro de engine."""
    ENABLED = 1
    DISABLED = 0


# ── Modelos ──────────────────────────────────────────────────

@dataclass
class EngineRegistration:
    """Registro individual de un context engine en el registry.

    Attributes:
        engine_id: Identificador único del engine.
        factory: Fábrica para crear instancias del engine.
        owner: Propietario del registro (ej. 'core', 'public-sdk', plugin id).
        priority: Prioridad de resolución (menor = mayor prioridad).
        status: Si el engine está habilitado o deshabilitado.
        phases: Fases del ciclo de vida que este engine maneja.
        metadata: Datos arbitrarios del registro.
    """
    engine_id: str
    factory: ContextEngineFactory
    owner: str = PUBLIC_SDK_OWNER
    priority: int = 100
    status: RegistrationStatus = RegistrationStatus.ENABLED
    phases: List[EnginePhase] = field(default_factory=lambda: list(EnginePhase))
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def enabled(self) -> bool:
        """Indica si el engine está habilitado."""
        return self.status == RegistrationStatus.ENABLED


@dataclass
class RegistrationResult:
    """Resultado de un intento de registro.

    Attributes:
        ok: Si el registro fue exitoso.
        existing_owner: Propietario existente en caso de conflicto.
        message: Mensaje descriptivo del resultado.
    """
    ok: bool
    existing_owner: Optional[str] = None
    message: str = ""


# ── Registry ─────────────────────────────────────────────────

class ContextEngineRegistry:
    """Registro global de implementaciones de ContextEngine.

    Mantiene un mapa de fábricas registradas con soporte para:
    - Registro con propietario y prioridad
    - Habilitación/deshabilitación dinámica
    - Resolución por id o desde configuración
    - Listado y filtrado por fase, owner o estado
    - Creación asíncrona de instancias via factory

    Portado de OpenClaw registry.ts, adaptado a Python/asyncio.
    """

    def __init__(self) -> None:
        self._engines: Dict[str, EngineRegistration] = {}
        self._instances: Dict[str, ContextEngine] = {}
        self._register_defaults()

    # ── API pública: registro ────────────────────────────────

    def register(
        self,
        engine_id: str,
        factory: ContextEngineFactory,
        *,
        owner: str = PUBLIC_SDK_OWNER,
        priority: int = 100,
        phases: Optional[List[EnginePhase]] = None,
        allow_refresh: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> RegistrationResult:
        """Registra una implementación de ContextEngine.

        Args:
            engine_id: Identificador único del engine.
            factory: Fábrica (clase, callable o async callable).
            owner: Propietario del registro.
            priority: Prioridad de resolución (menor = mayor prioridad).
            phases: Fases que maneja. Default: todas.
            allow_refresh: Permitir re-registro si el mismo owner ya lo registró.
            metadata: Datos arbitrarios asociados al registro.

        Returns:
            RegistrationResult indicando éxito o conflicto.
        """
        normalized_owner = self._validate_owner(owner)

        # Proteger el engine default: solo el owner core puede registrarlo
        if engine_id == DEFAULT_ENGINE_ID and normalized_owner != CORE_OWNER:
            return RegistrationResult(
                ok=False,
                existing_owner=CORE_OWNER,
                message=f"El engine '{DEFAULT_ENGINE_ID}' es reservado para el owner '{CORE_OWNER}'.",
            )

        existing = self._engines.get(engine_id)

        if existing is not None:
            # Conflicto de owner diferente
            if existing.owner != normalized_owner:
                return RegistrationResult(
                    ok=False,
                    existing_owner=existing.owner,
                    message=(
                        f"Engine '{engine_id}' ya registrado por '{existing.owner}'. "
                        f"No se puede registrar desde '{normalized_owner}'."
                    ),
                )
            # Mismo owner, pero no se permite refresh
            if not allow_refresh:
                return RegistrationResult(
                    ok=False,
                    existing_owner=existing.owner,
                    message=(
                        f"Engine '{engine_id}' ya registrado por '{normalized_owner}'. "
                        f"Usa allow_refresh=True para actualizar."
                    ),
                )

        registration = EngineRegistration(
            engine_id=engine_id,
            factory=factory,
            owner=normalized_owner,
            priority=priority,
            phases=phases if phases is not None else list(EnginePhase),
            metadata=metadata or {},
        )

        self._engines[engine_id] = registration
        # Invalidar instancia cacheada si existía
        self._instances.pop(engine_id, None)

        logger.debug(
            "Context engine '%s' registrado (owner=%s, priority=%d)",
            engine_id, normalized_owner, priority,
        )
        return RegistrationResult(ok=True, message=f"Engine '{engine_id}' registrado exitosamente.")

    def register_public(
        self,
        engine_id: str,
        factory: ContextEngineFactory,
        *,
        priority: int = 100,
        phases: Optional[List[EnginePhase]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> RegistrationResult:
        """Punto de entrada público para registros de terceros.

        No puede reclamar ids reservados al core ni hacer refresh
        de registros existentes.
        """
        return self.register(
            engine_id,
            factory,
            owner=PUBLIC_SDK_OWNER,
            priority=priority,
            phases=phases,
            allow_refresh=False,
            metadata=metadata,
        )

    def unregister(self, engine_id: str) -> bool:
        """Elimina un engine del registry.

        Returns:
            True si se eliminó, False si no existía.
        """
        if engine_id == DEFAULT_ENGINE_ID:
            logger.warning("No se puede eliminar el engine default.")
            return False

        removed = self._engines.pop(engine_id, None)
        self._instances.pop(engine_id, None)

        if removed is not None:
            logger.debug("Context engine '%s' eliminado del registry.", engine_id)
            return True
        return False

    # ── API pública: habilitación / deshabilitación ──────────

    def enable(self, engine_id: str) -> bool:
        """Habilita un engine previamente deshabilitado.

        Returns:
            True si se habilitó, False si no se encontró.
        """
        reg = self._engines.get(engine_id)
        if reg is None:
            return False
        reg.status = RegistrationStatus.ENABLED
        logger.debug("Context engine '%s' habilitado.", engine_id)
        return True

    def disable(self, engine_id: str) -> bool:
        """Deshabilita un engine sin eliminarlo del registry.

        Returns:
            True si se deshabilitó, False si no se encontró.
        """
        if engine_id == DEFAULT_ENGINE_ID:
            logger.warning("No se puede deshabilitar el engine default.")
            return False

        reg = self._engines.get(engine_id)
        if reg is None:
            return False
        reg.status = RegistrationStatus.DISABLED
        self._instances.pop(engine_id, None)
        logger.debug("Context engine '%s' deshabilitado.", engine_id)
        return True

    # ── API pública: consulta ────────────────────────────────

    def get(self, engine_id: str = DEFAULT_ENGINE_ID) -> Optional[EngineRegistration]:
        """Obtiene el registro de un engine por id.

        Returns:
            EngineRegistration o None si no existe.
        """
        return self._engines.get(engine_id)

    def get_factory(self, engine_id: str) -> Optional[ContextEngineFactory]:
        """Obtiene la fábrica de un engine por id.

        Returns:
            La fábrica o None si no existe el engine.
        """
        reg = self._engines.get(engine_id)
        return reg.factory if reg is not None else None

    def has(self, engine_id: str) -> bool:
        """Verifica si un engine está registrado."""
        return engine_id in self._engines

    def list_engines(self) -> List[str]:
        """Lista los ids de todos los engines registrados."""
        return list(self._engines.keys())

    def list_enabled(self) -> List[str]:
        """Lista los ids de los engines habilitados."""
        return [
            eid for eid, reg in self._engines.items()
            if reg.enabled
        ]

    def list_by_owner(self, owner: str) -> List[str]:
        """Lista los ids de engines registrados por un owner específico."""
        normalized = owner.strip()
        return [
            eid for eid, reg in self._engines.items()
            if reg.owner == normalized
        ]

    def list_by_phase(self, phase: EnginePhase) -> List[str]:
        """Lista los ids de engines que manejan una fase específica.

        Retorna ordenados por prioridad (menor = primero).
        """
        matching = [
            (reg.priority, eid)
            for eid, reg in self._engines.items()
            if phase in reg.phases and reg.enabled
        ]
        matching.sort(key=lambda x: x[0])
        return [eid for _, eid in matching]

    def list_registrations(
        self,
        *,
        enabled_only: bool = False,
        owner: Optional[str] = None,
        phase: Optional[EnginePhase] = None,
    ) -> List[EngineRegistration]:
        """Lista registros completos con filtros opcionales.

        Args:
            enabled_only: Solo retornar engines habilitados.
            owner: Filtrar por propietario.
            phase: Filtrar por fase soportada.

        Returns:
            Lista de EngineRegistration ordenada por prioridad.
        """
        results: List[EngineRegistration] = []
        normalized_owner = owner.strip() if owner else None

        for reg in self._engines.values():
            if enabled_only and not reg.enabled:
                continue
            if normalized_owner is not None and reg.owner != normalized_owner:
                continue
            if phase is not None and phase not in reg.phases:
                continue
            results.append(reg)

        results.sort(key=lambda r: r.priority)
        return results

    # ── API pública: creación de instancias ──────────────────

    async def create(self, engine_id: str, **kwargs: Any) -> ContextEngine:
        """Crea una instancia de ContextEngine a partir de su fábrica.

        Soporta fábricas síncronas y asíncronas. Los kwargs se pasan
        a la fábrica si acepta parámetros.

        Args:
            engine_id: Id del engine registrado.
            **kwargs: Argumentos a pasar a la fábrica.

        Returns:
            Instancia de ContextEngine.

        Raises:
            EngineNotRegisteredError: Si el engine no está registrado.
            ContextEngineRegistryError: Si el engine está deshabilitado.
        """
        reg = self._engines.get(engine_id)
        if reg is None:
            available = ", ".join(self.list_engines()) or "(ninguno)"
            raise EngineNotRegisteredError(
                f"Context engine '{engine_id}' no está registrado. "
                f"Engines disponibles: {available}"
            )

        if not reg.enabled:
            raise ContextEngineRegistryError(
                f"Context engine '{engine_id}' está deshabilitado."
            )

        instance = await self._invoke_factory(reg.factory, **kwargs)
        self._instances[engine_id] = instance
        return instance

    async def get_or_create(self, engine_id: str = DEFAULT_ENGINE_ID, **kwargs: Any) -> ContextEngine:
        """Obtiene una instancia cacheada o crea una nueva.

        Args:
            engine_id: Id del engine registrado.
            **kwargs: Argumentos a pasar a la fábrica (solo si se crea nueva).

        Returns:
            Instancia de ContextEngine (puede ser cacheada).
        """
        cached = self._instances.get(engine_id)
        if cached is not None:
            return cached
        return await self.create(engine_id, **kwargs)

    # ── Resolución desde configuración ───────────────────────

    async def resolve(self, config: Optional[Any] = None) -> ContextEngine:
        """Resuelve qué ContextEngine usar basándose en la configuración.

        Orden de resolución:
          1. config.context_engine.engine (si existe en la config)
          2. DEFAULT_ENGINE_ID ('default')

        Lanza error si el engine resuelto no está registrado.

        Args:
            config: Objeto de configuración de SOMER (SomerConfig o similar).

        Returns:
            Instancia de ContextEngine lista para usar.

        Raises:
            EngineNotRegisteredError: Si el engine resuelto no está registrado.
        """
        engine_id = DEFAULT_ENGINE_ID
        kwargs: Dict[str, Any] = {}

        if config is not None:
            # Soportar SomerConfig.context_engine.engine o atributo directo
            ctx_config = getattr(config, "context_engine", None)
            if ctx_config is not None:
                # Id del engine desde config
                configured_id = getattr(ctx_config, "engine", None)
                if isinstance(configured_id, str) and configured_id.strip():
                    engine_id = configured_id.strip()

                # Pasar parámetros de configuración relevantes como kwargs
                max_tokens = getattr(ctx_config, "max_context_tokens", None)
                if max_tokens is not None:
                    kwargs["max_context_tokens"] = max_tokens

                compact_ratio = getattr(ctx_config, "compact_threshold_ratio", None)
                if compact_ratio is not None:
                    kwargs["compact_ratio"] = compact_ratio

        logger.info("Resolviendo context engine: '%s'", engine_id)
        return await self.get_or_create(engine_id, **kwargs)

    # ── Utilidades de prioridad ──────────────────────────────

    def get_priority_order(self) -> List[str]:
        """Retorna los ids de engines habilitados ordenados por prioridad.

        Útil para pipelines donde múltiples engines cooperan.
        """
        enabled = [
            (reg.priority, eid)
            for eid, reg in self._engines.items()
            if reg.enabled
        ]
        enabled.sort(key=lambda x: x[0])
        return [eid for _, eid in enabled]

    def set_priority(self, engine_id: str, priority: int) -> bool:
        """Actualiza la prioridad de un engine registrado.

        Returns:
            True si se actualizó, False si no se encontró.
        """
        reg = self._engines.get(engine_id)
        if reg is None:
            return False
        reg.priority = priority
        return True

    # ── Ciclo de vida ────────────────────────────────────────

    def clear(self) -> None:
        """Limpia todo el registry y re-registra los defaults.

        Útil para testing o reinicialización completa.
        """
        self._engines.clear()
        self._instances.clear()
        self._register_defaults()

    def clear_instances(self) -> None:
        """Limpia solo las instancias cacheadas, sin tocar los registros."""
        self._instances.clear()

    @property
    def count(self) -> int:
        """Número total de engines registrados."""
        return len(self._engines)

    @property
    def enabled_count(self) -> int:
        """Número de engines habilitados."""
        return sum(1 for reg in self._engines.values() if reg.enabled)

    # ── Internos ─────────────────────────────────────────────

    def _register_defaults(self) -> None:
        """Registra los engines core que vienen con SOMER."""
        # Importación diferida para evitar circular
        from context_engine.default import DefaultContextEngine

        self._engines[DEFAULT_ENGINE_ID] = EngineRegistration(
            engine_id=DEFAULT_ENGINE_ID,
            factory=DefaultContextEngine,
            owner=CORE_OWNER,
            priority=0,
        )

    @staticmethod
    def _validate_owner(owner: str) -> str:
        """Valida y normaliza el string de owner.

        Raises:
            ValueError: Si el owner está vacío.
        """
        normalized = owner.strip()
        if not normalized:
            raise ValueError(
                f"El owner debe ser un string no vacío, se recibió: {owner!r}"
            )
        return normalized

    @staticmethod
    async def _invoke_factory(factory: ContextEngineFactory, **kwargs: Any) -> ContextEngine:
        """Invoca una fábrica de ContextEngine (síncrona o asíncrona).

        Args:
            factory: La fábrica a invocar.
            **kwargs: Argumentos a pasar a la fábrica.

        Returns:
            Instancia de ContextEngine.
        """
        try:
            result = factory(**kwargs)
        except TypeError:
            # Si la fábrica no acepta kwargs, intentar sin ellos
            result = factory()

        if asyncio.iscoroutine(result) or asyncio.isfuture(result):
            return await result
        return result  # type: ignore[return-value]

    def __repr__(self) -> str:
        engines = ", ".join(
            f"{eid}({'on' if reg.enabled else 'off'})"
            for eid, reg in self._engines.items()
        )
        return f"<ContextEngineRegistry [{engines}]>"


# ── Singleton global ─────────────────────────────────────────

_global_registry: Optional[ContextEngineRegistry] = None


def get_registry() -> ContextEngineRegistry:
    """Obtiene la instancia global del registry (singleton).

    Crea la instancia en la primera llamada. Usar esta función
    en vez de instanciar ContextEngineRegistry directamente
    cuando se necesite un registry compartido entre módulos.
    """
    global _global_registry
    if _global_registry is None:
        _global_registry = ContextEngineRegistry()
    return _global_registry


def reset_global_registry() -> None:
    """Resetea el singleton global. Solo para testing."""
    global _global_registry
    _global_registry = None
