"""Plugin loader — descubrimiento, validación y carga de plugins.

Portado desde OpenClaw loader.ts. Descubre plugins desde el filesystem,
paquetes pip y directorios configurados, los valida y los carga.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from plugins.contracts import CONTRACT_MAP, validate_contract
from plugins.lifecycle import PluginLifecycleManager
from plugins.manifest import PluginManifest, PluginManifestError, load_manifest
from plugins.registry import PluginRegistry, PluginRegistryError
from plugins.sdk import PluginSDK
from plugins.types import (
    PluginCapability,
    PluginDiagnostic,
    PluginFormat,
    PluginKind,
    PluginOrigin,
    PluginRecord,
    PluginState,
)
from shared.errors import SomerError

logger = logging.getLogger(__name__)

# ── Constantes ───────────────────────────────────────────────

DEFAULT_PLUGIN_DIRS: List[str] = [
    "~/.somer/plugins",
    "~/.somer/extensions",
]

PLUGIN_ENTRY_CANDIDATES = [
    "main.py",
    "__init__.py",
    "plugin.py",
    "index.py",
]

MANIFEST_FILENAMES = [
    "manifest.json",
    "somer.plugin.json",
    "plugin.json",
]

PACKAGE_METADATA_KEY = "somer"


# ── Errores ──────────────────────────────────────────────────

class PluginLoadError(SomerError):
    """Error al cargar un plugin."""


class PluginDiscoveryError(SomerError):
    """Error durante el descubrimiento de plugins."""


class PluginValidationError(SomerError):
    """Error en la validación de un plugin."""


# ── Candidato de plugin ──────────────────────────────────────

class PluginCandidate:
    """Candidato descubierto durante el escaneo de directorios."""

    def __init__(
        self,
        id_hint: str,
        source: str,
        root_dir: str,
        origin: PluginOrigin,
        format: PluginFormat = PluginFormat.SOMER,
        manifest: Optional[PluginManifest] = None,
        package_name: Optional[str] = None,
        package_version: Optional[str] = None,
    ) -> None:
        self.id_hint = id_hint
        self.source = source
        self.root_dir = root_dir
        self.origin = origin
        self.format = format
        self.manifest = manifest
        self.package_name = package_name
        self.package_version = package_version


# ── Discovery ────────────────────────────────────────────────

def discover_plugins(
    search_dirs: Optional[List[str]] = None,
    extra_paths: Optional[List[str]] = None,
    include_bundled: bool = True,
) -> Tuple[List[PluginCandidate], List[PluginDiagnostic]]:
    """Descubre plugins en los directorios de búsqueda.

    Escanea directorios de plugins buscando:
    1. Directorios con manifest.json
    2. Directorios con package.json/pyproject.toml
    3. Archivos Python individuales

    Args:
        search_dirs: Directorios donde buscar plugins.
        extra_paths: Rutas adicionales a incluir.
        include_bundled: Incluir plugins bundled.

    Returns:
        Tupla de (candidatos, diagnósticos).
    """
    candidates: List[PluginCandidate] = []
    diagnostics: List[PluginDiagnostic] = []

    dirs = list(search_dirs or DEFAULT_PLUGIN_DIRS)
    if extra_paths:
        dirs.extend(extra_paths)

    for raw_dir in dirs:
        dir_path = Path(raw_dir).expanduser()
        if not dir_path.exists():
            continue
        if not dir_path.is_dir():
            diagnostics.append(PluginDiagnostic(
                level="warn",
                message=f"Ruta de plugins no es un directorio: {dir_path}",
            ))
            continue

        origin = _resolve_origin(dir_path)

        try:
            for child in sorted(dir_path.iterdir()):
                if child.name.startswith(".") or child.name.startswith("__"):
                    continue

                if child.is_dir():
                    candidate = _discover_directory(child, origin)
                    if candidate is not None:
                        candidates.append(candidate)
                elif child.is_file() and child.suffix == ".py":
                    candidate = _discover_single_file(child, origin)
                    if candidate is not None:
                        candidates.append(candidate)
        except PermissionError:
            diagnostics.append(PluginDiagnostic(
                level="error",
                message=f"Sin permiso para leer directorio: {dir_path}",
            ))

    # Deduplicar por id_hint
    seen: Dict[str, PluginCandidate] = {}
    for candidate in candidates:
        existing = seen.get(candidate.id_hint)
        if existing is None:
            seen[candidate.id_hint] = candidate
        else:
            diagnostics.append(PluginDiagnostic(
                level="warn",
                message=(
                    f"Plugin duplicado '{candidate.id_hint}': "
                    f"{candidate.source} ignorado (ya descubierto en "
                    f"{existing.source})"
                ),
            ))

    return list(seen.values()), diagnostics


def _resolve_origin(dir_path: Path) -> PluginOrigin:
    """Determina el origen de un plugin según su ubicación."""
    home = Path.home()
    somer_global = home / ".somer" / "plugins"
    somer_ext = home / ".somer" / "extensions"

    path_str = str(dir_path)
    if path_str.startswith(str(somer_global)) or path_str.startswith(str(somer_ext)):
        return PluginOrigin.GLOBAL
    return PluginOrigin.LOCAL


def _discover_directory(
    dir_path: Path,
    origin: PluginOrigin,
) -> Optional[PluginCandidate]:
    """Descubre un plugin en un directorio."""
    # Buscar manifiesto
    manifest: Optional[PluginManifest] = None
    for manifest_name in MANIFEST_FILENAMES:
        manifest_path = dir_path / manifest_name
        if manifest_path.exists():
            try:
                manifest = load_manifest(str(manifest_path))
            except PluginManifestError:
                pass
            break

    # Buscar entry point
    entry_source: Optional[str] = None
    if manifest and manifest.entry_point:
        entry_path = dir_path / manifest.entry_point
        if entry_path.exists():
            entry_source = str(entry_path)

    if entry_source is None:
        for candidate_name in PLUGIN_ENTRY_CANDIDATES:
            candidate_path = dir_path / candidate_name
            if candidate_path.exists():
                entry_source = str(candidate_path)
                break

    if entry_source is None:
        return None

    id_hint = manifest.name if manifest else dir_path.name
    fmt = PluginFormat.SOMER if manifest else PluginFormat.DIRECTORY

    # Detectar pyproject.toml para paquetes Python
    pyproject = dir_path / "pyproject.toml"
    package_name: Optional[str] = None
    package_version: Optional[str] = None
    if pyproject.exists():
        fmt = PluginFormat.PYTHON_PACKAGE
        try:
            # Lectura simple de pyproject.toml sin dependencia de tomli
            text = pyproject.read_text(encoding="utf-8")
            for line in text.split("\n"):
                line = line.strip()
                if line.startswith("name") and "=" in line:
                    package_name = line.split("=", 1)[1].strip().strip('"\'')
                elif line.startswith("version") and "=" in line:
                    package_version = line.split("=", 1)[1].strip().strip('"\'')
        except Exception:
            pass

    return PluginCandidate(
        id_hint=id_hint,
        source=entry_source,
        root_dir=str(dir_path),
        origin=origin,
        format=fmt,
        manifest=manifest,
        package_name=package_name,
        package_version=package_version,
    )


def _discover_single_file(
    file_path: Path,
    origin: PluginOrigin,
) -> Optional[PluginCandidate]:
    """Descubre un plugin de archivo único."""
    if file_path.name.startswith("_"):
        return None

    return PluginCandidate(
        id_hint=file_path.stem,
        source=str(file_path),
        root_dir=str(file_path.parent),
        origin=origin,
        format=PluginFormat.SINGLE_FILE,
    )


# ── Validación ───────────────────────────────────────────────

def validate_plugin(
    candidate: PluginCandidate,
) -> List[PluginDiagnostic]:
    """Valida un candidato de plugin antes de cargarlo.

    Verifica:
    1. Que el entry point existe
    2. Que el manifiesto es válido (si existe)
    3. Que las dependencias están satisfechas

    Args:
        candidate: Candidato a validar.

    Returns:
        Lista de diagnósticos (errores y warnings).
    """
    diagnostics: List[PluginDiagnostic] = []

    # Verificar entry point
    source_path = Path(candidate.source)
    if not source_path.exists():
        diagnostics.append(PluginDiagnostic(
            level="error",
            plugin_id=candidate.id_hint,
            source=candidate.source,
            message=f"Entry point no encontrado: {candidate.source}",
        ))
        return diagnostics

    # Verificar dependencias del manifiesto
    if candidate.manifest and candidate.manifest.dependencies:
        for dep in candidate.manifest.dependencies:
            dep_name = dep.split(">=")[0].split("==")[0].split("<")[0].strip()
            try:
                importlib.import_module(dep_name)
            except ImportError:
                diagnostics.append(PluginDiagnostic(
                    level="error",
                    plugin_id=candidate.id_hint,
                    source=candidate.source,
                    message=f"Dependencia no satisfecha: {dep}",
                ))

    return diagnostics


# ── Carga de módulo ──────────────────────────────────────────

def _load_module(
    plugin_id: str,
    source: str,
) -> Any:
    """Carga un módulo Python desde una ruta.

    Args:
        plugin_id: ID del plugin (para nombre del módulo).
        source: Ruta al archivo Python.

    Returns:
        Módulo cargado.

    Raises:
        PluginLoadError: Si no se puede cargar el módulo.
    """
    module_name = f"somer_plugin_{plugin_id.replace('-', '_').replace('.', '_')}"
    source_path = Path(source)

    spec = importlib.util.spec_from_file_location(module_name, str(source_path))
    if spec is None or spec.loader is None:
        raise PluginLoadError(
            f"No se pudo crear spec para {source}"
        )

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module

    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop(module_name, None)
        raise PluginLoadError(
            f"Error al ejecutar {source}: {exc}"
        ) from exc

    return module


def _resolve_plugin_definition(module: Any) -> Dict[str, Any]:
    """Extrae la definición del plugin de un módulo cargado.

    Busca en orden:
    1. Atributo 'plugin' (dict con definición)
    2. Atributo 'PLUGIN' (dict)
    3. Función 'register' o 'setup'

    Args:
        module: Módulo cargado.

    Returns:
        Dict con la definición del plugin.
    """
    # Buscar definición explícita
    for attr_name in ("plugin", "PLUGIN", "definition", "DEFINITION"):
        defn = getattr(module, attr_name, None)
        if isinstance(defn, dict):
            return defn

    # Construir definición desde atributos
    result: Dict[str, Any] = {}
    for attr in ("id", "name", "version", "description", "kind"):
        value = getattr(module, attr, None)
        if value is not None:
            result[attr] = value

    # Detectar funciones de registro
    register = getattr(module, "register", None)
    if register is not None and callable(register):
        result["register"] = register
    setup = getattr(module, "setup", None)
    if setup is not None and callable(setup):
        result["setup"] = setup

    return result


# ── Plugin Loader Principal ──────────────────────────────────

class PluginLoader:
    """Cargador de plugins — descubre, valida y carga plugins.

    Uso::

        loader = PluginLoader(registry=registry, lifecycle=lifecycle)
        results = await loader.load_all()
        loaded = await loader.load_from_directory("/path/to/plugins")
    """

    def __init__(
        self,
        registry: Optional[PluginRegistry] = None,
        lifecycle: Optional[PluginLifecycleManager] = None,
        search_dirs: Optional[List[str]] = None,
    ) -> None:
        self._registry = registry or PluginRegistry()
        self._lifecycle = lifecycle or PluginLifecycleManager()
        self._search_dirs = search_dirs
        self._loaded_modules: Dict[str, Any] = {}

    @property
    def registry(self) -> PluginRegistry:
        """Registry asociado a este loader."""
        return self._registry

    @property
    def lifecycle(self) -> PluginLifecycleManager:
        """Lifecycle manager asociado a este loader."""
        return self._lifecycle

    async def load_all(
        self,
        extra_paths: Optional[List[str]] = None,
    ) -> List[PluginRecord]:
        """Descubre y carga todos los plugins disponibles.

        Args:
            extra_paths: Rutas adicionales donde buscar plugins.

        Returns:
            Lista de records de plugins cargados.
        """
        candidates, diagnostics = discover_plugins(
            search_dirs=self._search_dirs,
            extra_paths=extra_paths,
        )

        for diag in diagnostics:
            logger.warning("%s", diag.message)

        loaded: List[PluginRecord] = []
        for candidate in candidates:
            try:
                record = await self.load_candidate(candidate)
                loaded.append(record)
            except (PluginLoadError, PluginRegistryError) as exc:
                logger.error(
                    "Error al cargar plugin '%s': %s",
                    candidate.id_hint, exc,
                )

        return loaded

    async def load_candidate(
        self,
        candidate: PluginCandidate,
    ) -> PluginRecord:
        """Carga un candidato de plugin.

        Args:
            candidate: Candidato descubierto.

        Returns:
            PluginRecord del plugin cargado.

        Raises:
            PluginLoadError: Si la carga falla.
            PluginValidationError: Si la validación falla.
        """
        plugin_id = candidate.id_hint

        # Validar
        diagnostics = validate_plugin(candidate)
        errors = [d for d in diagnostics if d.level == "error"]
        if errors:
            error_msg = "; ".join(d.message for d in errors)
            raise PluginValidationError(
                f"Validación fallida para '{plugin_id}': {error_msg}"
            )

        # Registrar en lifecycle
        self._lifecycle.register_plugin(
            plugin_id, PluginState.DISCOVERED
        )

        # Transicionar a VALIDATING
        await self._lifecycle.transition(plugin_id, PluginState.VALIDATING)

        # Crear record
        manifest = candidate.manifest
        record = PluginRecord(
            id=plugin_id,
            name=manifest.name if manifest else plugin_id,
            version=manifest.version if manifest else candidate.package_version,
            description=manifest.description if manifest else "",
            format=candidate.format,
            kind=PluginKind(manifest.tags[0]) if manifest and manifest.tags else None,
            source=candidate.source,
            root_dir=candidate.root_dir,
            origin=candidate.origin,
            enabled=True,
            state=PluginState.VALIDATING,
            has_config_schema=bool(
                manifest and manifest.config_schema
            ),
        )

        # Transicionar a INIT
        await self._lifecycle.transition(plugin_id, PluginState.INIT)
        record.state = PluginState.INIT

        # Cargar módulo
        try:
            module = _load_module(plugin_id, candidate.source)
            self._loaded_modules[plugin_id] = module
        except PluginLoadError as exc:
            await self._lifecycle.transition(
                plugin_id, PluginState.ERROR, error=str(exc)
            )
            record.state = PluginState.ERROR
            record.error = str(exc)
            self._registry.register_plugin(record)
            raise

        # Crear SDK y ejecutar setup/register
        sdk = PluginSDK(plugin_name=plugin_id)
        definition = _resolve_plugin_definition(module)

        register_fn = definition.get("register")
        setup_fn = definition.get("setup") or getattr(module, "setup", None)

        try:
            if register_fn is not None and callable(register_fn):
                import asyncio
                if asyncio.iscoroutinefunction(register_fn):
                    await register_fn(sdk)
                else:
                    register_fn(sdk)

            if setup_fn is not None and callable(setup_fn):
                import asyncio
                if asyncio.iscoroutinefunction(setup_fn):
                    await setup_fn(sdk)
                else:
                    setup_fn(sdk)
        except Exception as exc:
            await self._lifecycle.transition(
                plugin_id, PluginState.ERROR, error=str(exc)
            )
            record.state = PluginState.ERROR
            record.error = str(exc)
            self._registry.register_plugin(record)
            raise PluginLoadError(
                f"Error en setup/register de '{plugin_id}': {exc}"
            ) from exc

        # Registrar capacidades en el registry
        self._registry.register_plugin(record)

        for skill in sdk.registered_skills:
            record.tool_names.append(skill.name)

        for tool_name, handler in sdk.registered_tools.items():
            try:
                # Separar nombre calificado
                parts = tool_name.split(".", 1)
                name = parts[1] if len(parts) > 1 else parts[0]
                self._registry.register_tool(plugin_id, name, handler)
            except PluginRegistryError:
                pass

        for event, callbacks in sdk.registered_hooks.items():
            for callback in callbacks:
                self._registry.register_hook(plugin_id, event, callback)

        # Transicionar a READY
        await self._lifecycle.transition(plugin_id, PluginState.READY)
        record.state = PluginState.READY

        logger.info(
            "Plugin '%s' v%s cargado (%d skills, %d tools, %d hooks)",
            record.name,
            record.version or "?",
            len(sdk.registered_skills),
            len(sdk.registered_tools),
            sum(len(v) for v in sdk.registered_hooks.values()),
        )

        return record

    async def load_from_manifest(
        self,
        manifest_path: str,
        config: Optional[Dict[str, Any]] = None,
    ) -> PluginRecord:
        """Carga un plugin desde su manifiesto.

        Args:
            manifest_path: Ruta al archivo manifest.json.
            config: Configuración a pasar al plugin.

        Returns:
            PluginRecord del plugin cargado.
        """
        manifest = load_manifest(manifest_path)
        candidate = PluginCandidate(
            id_hint=manifest.name,
            source=str(Path(manifest.source_path or ".") / manifest.entry_point),
            root_dir=str(manifest.source_path or Path(manifest_path).parent),
            origin=PluginOrigin.LOCAL,
            format=PluginFormat.SOMER,
            manifest=manifest,
        )
        return await self.load_candidate(candidate)

    async def unload(self, plugin_id: str) -> bool:
        """Descarga un plugin.

        Args:
            plugin_id: ID del plugin a descargar.

        Returns:
            True si se descargó exitosamente.
        """
        state = self._lifecycle.get_state(plugin_id)
        if state is None:
            logger.warning("Plugin '%s' no está registrado", plugin_id)
            return False

        # Llamar teardown si existe
        module = self._loaded_modules.get(plugin_id)
        if module is not None:
            teardown_fn = getattr(module, "teardown", None)
            if teardown_fn is not None and callable(teardown_fn):
                try:
                    import asyncio
                    if asyncio.iscoroutinefunction(teardown_fn):
                        await teardown_fn()
                    else:
                        teardown_fn()
                except Exception:
                    logger.exception(
                        "Error en teardown() de '%s'", plugin_id
                    )

        # Detener si está running
        if state == PluginState.RUNNING:
            await self._lifecycle.transition(
                plugin_id, PluginState.STOPPING
            )
            await self._lifecycle.transition(
                plugin_id, PluginState.STOPPED
            )

        # Limpiar módulo
        module_name = f"somer_plugin_{plugin_id.replace('-', '_').replace('.', '_')}"
        sys.modules.pop(module_name, None)
        self._loaded_modules.pop(plugin_id, None)

        # Desregistrar
        self._registry.unregister_plugin(plugin_id)
        self._lifecycle.unregister_plugin(plugin_id)

        logger.info("Plugin '%s' descargado", plugin_id)
        return True

    def get_loaded_module(self, plugin_id: str) -> Optional[Any]:
        """Obtiene el módulo cargado de un plugin.

        Args:
            plugin_id: ID del plugin.

        Returns:
            Módulo Python o None.
        """
        return self._loaded_modules.get(plugin_id)
