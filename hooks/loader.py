"""Sistema de hooks — carga, descubrimiento, instalacion y validacion.

Portado de OpenClaw (install.ts + workspace.ts) adaptado a las
convenciones de SOMER 2.0: asyncio, Pydantic v2, Python 3.9+.
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import logging
import os
import platform
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Literal, Optional, Set

from shared.constants import DEFAULT_HOME
from shared.errors import HookError, HookInstallError, HookNotFoundError, HookValidationError

logger = logging.getLogger(__name__)

# ── Tipos ───────────────────────────────────────────────────────

HookCallback = Callable[..., Coroutine[Any, Any, None]]

# Eventos de lifecycle soportados
LIFECYCLE_EVENTS = (
    "on_startup",
    "on_shutdown",
    "on_session_create",
    "on_session_close",
    "on_message_in",
    "on_message_out",
    "on_error",
    "on_compact",
    "on_provider_switch",
    "on_tool_call",
    "on_tool_result",
    "on_memory_store",
    "on_memory_recall",
)

# Regex para frontmatter YAML entre ---
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.+?)\n---\s*\n", re.DOTALL)

HookSource = Literal[
    "somer-bundled",
    "somer-managed",
    "somer-workspace",
    "somer-plugin",
    "somer-config",
]


# ── Modelos de datos ────────────────────────────────────────────

@dataclass
class HookMeta:
    """Metadata de un hook (parseado de HOOK.md frontmatter)."""

    name: str
    description: str = ""
    version: str = "1.0.0"
    events: List[str] = field(default_factory=list)
    enabled: bool = True
    always: bool = False
    hook_key: Optional[str] = None
    os: Optional[List[str]] = None
    requires_env: List[str] = field(default_factory=list)
    requires_bins: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)


@dataclass
class HookEntry:
    """Entrada completa de un hook descubierto."""

    name: str
    description: str = ""
    source: HookSource = "somer-workspace"
    plugin_id: Optional[str] = None
    file_path: str = ""       # Ruta al HOOK.md
    base_dir: str = ""        # Directorio que contiene el hook
    handler_path: str = ""    # Ruta al modulo handler (handler.py)
    meta: Optional[HookMeta] = None
    enabled: bool = True


@dataclass
class HookSnapshot:
    """Snapshot del estado actual de hooks."""

    hooks: List[Dict[str, Any]] = field(default_factory=list)
    resolved_hooks: List[HookEntry] = field(default_factory=list)
    version: Optional[int] = None


@dataclass
class InstallResult:
    """Resultado de una instalacion de hook."""

    ok: bool
    hook_id: str = ""
    hooks: List[str] = field(default_factory=list)
    target_dir: str = ""
    version: Optional[str] = None
    error: Optional[str] = None


# ── Utilidades de frontmatter ───────────────────────────────────

def parse_hook_frontmatter(content: str) -> Dict[str, Any]:
    """Parsea frontmatter YAML de un archivo HOOK.md.

    Args:
        content: Contenido completo del archivo HOOK.md.

    Returns:
        Dict con las claves del frontmatter.
    """
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return {}

    raw = match.group(1)
    result: Dict[str, Any] = {}
    current_key: Optional[str] = None
    current_list: Optional[List[str]] = None

    for line in raw.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Elemento de lista
        if stripped.startswith("- "):
            if current_key is not None and current_list is not None:
                current_list.append(stripped[2:].strip().strip("'\""))
            continue

        # Key: value
        if ":" in stripped:
            # Guardar lista pendiente
            if current_key is not None and current_list is not None:
                result[current_key] = current_list

            parts = stripped.split(":", 1)
            key = parts[0].strip()
            value = parts[1].strip() if len(parts) > 1 else ""

            if not value:
                current_key = key
                current_list = []
            else:
                current_key = None
                current_list = None
                value = value.strip("'\"")
                if value.lower() == "true":
                    result[key] = True
                elif value.lower() == "false":
                    result[key] = False
                else:
                    try:
                        result[key] = int(value)
                    except ValueError:
                        result[key] = value

    if current_key is not None and current_list is not None:
        result[current_key] = current_list

    return result


def _resolve_hook_meta(frontmatter: Dict[str, Any], name_hint: str) -> HookMeta:
    """Construye HookMeta a partir del frontmatter parseado.

    Args:
        frontmatter: Dict con las claves del frontmatter.
        name_hint: Nombre por defecto si el frontmatter no lo tiene.

    Returns:
        HookMeta con los campos resueltos.
    """
    name = str(frontmatter.get("name", name_hint))
    events_raw = frontmatter.get("events", [])
    events = events_raw if isinstance(events_raw, list) else [str(events_raw)]

    requires_env = frontmatter.get("requires_env", [])
    if isinstance(requires_env, str):
        requires_env = [requires_env]

    requires_bins = frontmatter.get("requires_bins", [])
    if isinstance(requires_bins, str):
        requires_bins = [requires_bins]

    os_list = frontmatter.get("os", None)
    if isinstance(os_list, str):
        os_list = [os_list]

    tags = frontmatter.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]

    return HookMeta(
        name=name,
        description=str(frontmatter.get("description", "")),
        version=str(frontmatter.get("version", "1.0.0")),
        events=[str(e) for e in events],
        enabled=bool(frontmatter.get("enabled", True)),
        always=bool(frontmatter.get("always", False)),
        hook_key=frontmatter.get("hook_key") or frontmatter.get("hookKey"),
        os=os_list,
        requires_env=[str(e) for e in requires_env],
        requires_bins=[str(b) for b in requires_bins],
        tags=[str(t) for t in tags],
    )


# ── Validacion ──────────────────────────────────────────────────

def validate_hook_id(hook_id: str) -> Optional[str]:
    """Valida un identificador de hook.

    Returns:
        Mensaje de error si es invalido, None si es valido.
    """
    if not hook_id:
        return "nombre de hook invalido: vacio"
    if hook_id in (".", ".."):
        return "nombre de hook invalido: segmento de ruta reservado"
    if "/" in hook_id or "\\" in hook_id:
        return "nombre de hook invalido: separadores de ruta no permitidos"
    if hook_id.startswith("."):
        return "nombre de hook invalido: no puede empezar con punto"
    return None


def validate_hook_dir(hook_dir: Path) -> None:
    """Valida que un directorio contenga un hook valido.

    Args:
        hook_dir: Ruta al directorio del hook.

    Raises:
        HookValidationError: Si el directorio no es un hook valido.
    """
    hook_md = hook_dir / "HOOK.md"
    if not hook_md.exists():
        raise HookValidationError(f"HOOK.md no encontrado en {hook_dir}")

    # Buscar archivo handler
    handler_candidates = ["handler.py", "hook.py", "index.py", "__init__.py"]
    has_handler = any((hook_dir / c).exists() for c in handler_candidates)

    if not has_handler:
        raise HookValidationError(
            f"Archivo handler no encontrado en {hook_dir}. "
            f"Se esperaba alguno de: {', '.join(handler_candidates)}"
        )


def _is_path_inside(parent: Path, child: Path) -> bool:
    """Verifica que child este dentro de parent (sin symlink escape).

    Args:
        parent: Directorio padre.
        child: Ruta a verificar.

    Returns:
        True si child esta dentro de parent.
    """
    try:
        resolved_parent = parent.resolve()
        resolved_child = child.resolve()
        return str(resolved_child).startswith(str(resolved_parent))
    except (OSError, ValueError):
        return False


# ── Eligibilidad ────────────────────────────────────────────────

def check_hook_eligibility(
    meta: HookMeta,
    hook_config: Optional[Dict[str, Any]] = None,
) -> bool:
    """Evalua si un hook es elegible para ejecucion en el entorno actual.

    Verifica plataforma (OS), binarios requeridos, variables de entorno
    y estado de habilitacion.

    Args:
        meta: Metadata del hook.
        hook_config: Config especifica del hook (de la config global).

    Returns:
        True si el hook es elegible.
    """
    # Verificar enabled
    if not meta.enabled:
        return False

    # Verificar plataforma
    if meta.os:
        current_os = platform.system().lower()
        os_aliases: Dict[str, Set[str]] = {
            "linux": {"linux"},
            "darwin": {"darwin", "macos", "mac"},
            "windows": {"windows", "win", "win32"},
        }
        current_aliases = os_aliases.get(current_os, {current_os})
        supported = {s.lower() for s in meta.os}
        if not current_aliases & supported:
            return False

    # Verificar binarios requeridos
    for bin_name in meta.requires_bins:
        if shutil.which(bin_name) is None:
            logger.debug(
                "Hook requiere binario no disponible: %s", bin_name
            )
            return False

    # Verificar variables de entorno
    for env_name in meta.requires_env:
        env_value = os.environ.get(env_name)
        if not env_value:
            # Revisar si esta en la config del hook
            if hook_config and hook_config.get("env", {}).get(env_name):
                continue
            logger.debug(
                "Hook requiere variable de entorno no definida: %s", env_name
            )
            return False

    # Config override: deshabilitado explicitamente
    if hook_config and hook_config.get("enabled") is False:
        return False

    return True


# ── Carga desde directorio (discovery) ──────────────────────────

def _load_hook_from_dir(
    hook_dir: Path,
    source: HookSource,
    plugin_id: Optional[str] = None,
    name_hint: Optional[str] = None,
) -> Optional[HookEntry]:
    """Carga un hook desde un directorio con HOOK.md.

    Args:
        hook_dir: Directorio del hook.
        source: Origen del hook.
        plugin_id: ID del plugin si viene de un plugin.
        name_hint: Nombre por defecto si HOOK.md no tiene nombre.

    Returns:
        HookEntry o None si no se puede cargar.
    """
    hook_md = hook_dir / "HOOK.md"
    if not hook_md.exists():
        return None

    try:
        content = hook_md.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("No se pudo leer %s: %s", hook_md, exc)
        return None

    try:
        frontmatter = parse_hook_frontmatter(content)
        hint = name_hint or hook_dir.name
        meta = _resolve_hook_meta(frontmatter, hint)

        # Buscar handler
        handler_candidates = ["handler.py", "hook.py", "index.py", "__init__.py"]
        handler_path = ""
        for candidate in handler_candidates:
            candidate_path = hook_dir / candidate
            if candidate_path.exists() and _is_path_inside(hook_dir, candidate_path):
                handler_path = str(candidate_path.resolve())
                break

        if not handler_path:
            logger.warning(
                "Hook '%s' tiene HOOK.md pero no handler en %s", meta.name, hook_dir
            )
            return None

        # Resolver base_dir con realpath
        try:
            base_dir = str(hook_dir.resolve())
        except OSError:
            base_dir = str(hook_dir)

        return HookEntry(
            name=meta.name,
            description=meta.description,
            source=source,
            plugin_id=plugin_id,
            file_path=str(hook_md),
            base_dir=base_dir,
            handler_path=handler_path,
            meta=meta,
            enabled=meta.enabled,
        )

    except Exception as exc:
        logger.warning("Error cargando hook de %s: %s", hook_dir, exc)
        return None


def _load_hooks_from_dir(
    directory: Path,
    source: HookSource,
    plugin_id: Optional[str] = None,
) -> List[HookEntry]:
    """Escanea un directorio buscando hooks (subdirectorios con HOOK.md).

    Soporta tanto hooks individuales como paquetes de hooks
    (con somer.hooks en package.json o somer_hooks.json).

    Args:
        directory: Directorio a escanear.
        source: Origen de los hooks.
        plugin_id: ID del plugin si viene de un plugin.

    Returns:
        Lista de HookEntry encontrados.
    """
    if not directory.exists() or not directory.is_dir():
        return []

    hooks: List[HookEntry] = []

    try:
        entries = sorted(directory.iterdir())
    except OSError:
        return []

    for entry in entries:
        if not entry.is_dir():
            continue

        # Verificar si es un paquete de hooks (somer_hooks.json)
        pack_manifest = entry / "somer_hooks.json"
        if pack_manifest.exists():
            pack_hooks = _load_hook_pack(entry, pack_manifest, source, plugin_id)
            hooks.extend(pack_hooks)
            continue

        # Hook individual
        hook = _load_hook_from_dir(entry, source, plugin_id, name_hint=entry.name)
        if hook:
            hooks.append(hook)

    return hooks


def _load_hook_pack(
    pack_dir: Path,
    manifest_path: Path,
    source: HookSource,
    plugin_id: Optional[str] = None,
) -> List[HookEntry]:
    """Carga un paquete de hooks desde somer_hooks.json.

    El manifiesto debe tener formato:
    {"name": "pack-name", "hooks": ["subdir1", "subdir2"]}

    Args:
        pack_dir: Directorio del paquete.
        manifest_path: Ruta al somer_hooks.json.
        source: Origen del hook.
        plugin_id: ID del plugin.

    Returns:
        Lista de HookEntry del paquete.
    """
    import json

    try:
        raw = manifest_path.read_text(encoding="utf-8")
        manifest = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Manifiesto de hooks invalido en %s: %s", manifest_path, exc)
        return []

    hook_paths = manifest.get("hooks", [])
    if not isinstance(hook_paths, list):
        logger.warning("Campo 'hooks' invalido en %s", manifest_path)
        return []

    hooks: List[HookEntry] = []
    for hook_path_str in hook_paths:
        if not isinstance(hook_path_str, str) or not hook_path_str.strip():
            continue

        hook_dir = (pack_dir / hook_path_str.strip()).resolve()

        # Verificar que no escape del directorio del paquete
        if not _is_path_inside(pack_dir, hook_dir):
            logger.warning(
                "Hook path escapa del directorio del paquete: %s en %s",
                hook_path_str, pack_dir,
            )
            continue

        hook = _load_hook_from_dir(
            hook_dir, source, plugin_id, name_hint=hook_dir.name
        )
        if hook:
            hooks.append(hook)

    return hooks


# ── Carga desde config (modulo:funcion) ─────────────────────────

def _load_callback_from_spec(spec: str) -> Optional[HookCallback]:
    """Carga un callback desde un spec 'modulo.path:funcion'.

    Args:
        spec: Especificacion en formato 'modulo.path:funcion'.

    Returns:
        Funcion callback o None si falla.
    """
    try:
        module_path, func_name = spec.rsplit(":", 1)
        module = importlib.import_module(module_path)
        func = getattr(module, func_name)
        if not callable(func):
            logger.error("'%s' no es callable en %s", func_name, module_path)
            return None
        return func  # type: ignore[return-value]
    except (ValueError, ImportError, AttributeError) as exc:
        logger.error("Error cargando hook spec '%s': %s", spec, exc)
        return None


def _load_callback_from_file(handler_path: str) -> Optional[HookCallback]:
    """Carga el callback principal de un archivo handler de hook.

    Busca funciones con nombre 'hook', 'handler', 'run' o 'main' (en ese
    orden) que sean async callables.

    Args:
        handler_path: Ruta absoluta al archivo handler.

    Returns:
        Funcion callback o None si no se encuentra.
    """
    path = Path(handler_path)
    if not path.exists():
        logger.warning("Handler no encontrado: %s", handler_path)
        return None

    module_name = f"somer_hook_{path.stem}_{id(path)}"

    try:
        spec = importlib.util.spec_from_file_location(module_name, str(path))
        if spec is None or spec.loader is None:
            return None

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    except Exception as exc:
        logger.error("Error importando handler %s: %s", handler_path, exc)
        return None

    # Buscar funcion handler por convencion
    handler_names = ("hook", "handler", "run", "main")
    for name in handler_names:
        func = getattr(module, name, None)
        if func is not None and callable(func):
            return func  # type: ignore[return-value]

    logger.warning(
        "No se encontro funcion handler en %s (buscados: %s)",
        handler_path, ", ".join(handler_names),
    )
    return None


# ── Instalacion/Desinstalacion ──────────────────────────────────

def resolve_hooks_dir(custom_dir: Optional[str] = None) -> Path:
    """Resuelve el directorio base de hooks instalados.

    Args:
        custom_dir: Directorio personalizado. Si None, usa ~/.somer/hooks.

    Returns:
        Path al directorio de hooks.
    """
    if custom_dir:
        return Path(custom_dir).expanduser().resolve()
    return DEFAULT_HOME / "hooks"


def resolve_hook_install_dir(
    hook_id: str,
    hooks_dir: Optional[str] = None,
) -> Path:
    """Resuelve el directorio de instalacion para un hook especifico.

    Args:
        hook_id: Identificador del hook.
        hooks_dir: Directorio base de hooks.

    Returns:
        Path al directorio destino.

    Raises:
        HookValidationError: Si el hook_id es invalido.
    """
    base = resolve_hooks_dir(hooks_dir)
    error = validate_hook_id(hook_id)
    if error:
        raise HookValidationError(error)

    target = (base / hook_id).resolve()

    # Verificar path traversal
    if not _is_path_inside(base, target):
        raise HookValidationError(
            "nombre de hook invalido: path traversal detectado"
        )

    return target


async def install_hook_from_dir(
    source_dir: str,
    hooks_dir: Optional[str] = None,
    mode: Literal["install", "update"] = "install",
    dry_run: bool = False,
    expected_hook_id: Optional[str] = None,
) -> InstallResult:
    """Instala un hook desde un directorio local.

    Copia el directorio al directorio de hooks gestionados (~/.somer/hooks/).

    Args:
        source_dir: Directorio fuente con HOOK.md y handler.
        hooks_dir: Directorio base de hooks (override).
        mode: 'install' para nuevo, 'update' para sobreescribir.
        dry_run: Si True, no ejecuta cambios reales.
        expected_hook_id: Si se provee, verifica que el hook tenga este ID.

    Returns:
        InstallResult con el resultado de la operacion.
    """
    source = Path(source_dir).resolve()

    if not source.is_dir():
        return InstallResult(ok=False, error=f"Directorio no encontrado: {source}")

    # Verificar si es un hook pack
    pack_manifest = source / "somer_hooks.json"
    if pack_manifest.exists():
        return await _install_hook_pack(
            source, hooks_dir, mode, dry_run, expected_hook_id
        )

    # Hook individual
    try:
        validate_hook_dir(source)
    except HookValidationError as exc:
        return InstallResult(ok=False, error=str(exc))

    # Leer nombre del hook desde HOOK.md
    hook_md = source / "HOOK.md"
    content = hook_md.read_text(encoding="utf-8")
    frontmatter = parse_hook_frontmatter(content)
    hook_name = str(frontmatter.get("name", source.name))

    error = validate_hook_id(hook_name)
    if error:
        return InstallResult(ok=False, error=error)

    if expected_hook_id and expected_hook_id != hook_name:
        return InstallResult(
            ok=False,
            error=f"ID de hook no coincide: esperado {expected_hook_id}, obtenido {hook_name}",
        )

    # Resolver directorio destino
    try:
        target = resolve_hook_install_dir(hook_name, hooks_dir)
    except HookValidationError as exc:
        return InstallResult(ok=False, error=str(exc))

    # Verificar disponibilidad
    if target.exists():
        if mode == "install":
            return InstallResult(
                ok=False,
                error=f"Hook ya existe: {target} (eliminar primero o usar mode='update')",
            )
        # mode == "update": eliminar existente
        if not dry_run:
            shutil.rmtree(target)

    if dry_run:
        return InstallResult(
            ok=True,
            hook_id=hook_name,
            hooks=[hook_name],
            target_dir=str(target),
            version=frontmatter.get("version"),
        )

    # Copiar
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.get_event_loop().run_in_executor(
            None, shutil.copytree, str(source), str(target)
        )
    except OSError as exc:
        return InstallResult(
            ok=False, error=f"Error copiando hook: {exc}"
        )

    logger.info("Hook '%s' instalado en %s", hook_name, target)
    return InstallResult(
        ok=True,
        hook_id=hook_name,
        hooks=[hook_name],
        target_dir=str(target),
        version=frontmatter.get("version"),
    )


async def _install_hook_pack(
    source_dir: Path,
    hooks_dir: Optional[str],
    mode: Literal["install", "update"],
    dry_run: bool,
    expected_hook_id: Optional[str],
) -> InstallResult:
    """Instala un paquete de hooks desde un directorio con somer_hooks.json.

    Args:
        source_dir: Directorio del paquete.
        hooks_dir: Directorio base de hooks.
        mode: 'install' o 'update'.
        dry_run: Si True, no ejecuta cambios.
        expected_hook_id: ID esperado del paquete.

    Returns:
        InstallResult con el resultado de la operacion.
    """
    import json

    manifest_path = source_dir / "somer_hooks.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return InstallResult(ok=False, error=f"Manifiesto invalido: {exc}")

    pack_name = manifest.get("name", source_dir.name)
    hook_entries = manifest.get("hooks", [])

    if not isinstance(hook_entries, list) or not hook_entries:
        return InstallResult(ok=False, error="somer_hooks.json: campo 'hooks' vacio")

    error = validate_hook_id(pack_name)
    if error:
        return InstallResult(ok=False, error=error)

    if expected_hook_id and expected_hook_id != pack_name:
        return InstallResult(
            ok=False,
            error=f"ID de paquete no coincide: esperado {expected_hook_id}, obtenido {pack_name}",
        )

    # Validar todos los hooks del paquete
    resolved_hooks: List[str] = []
    for entry_path in hook_entries:
        if not isinstance(entry_path, str):
            continue
        hook_dir = (source_dir / entry_path).resolve()
        if not _is_path_inside(source_dir, hook_dir):
            return InstallResult(
                ok=False,
                error=f"Hook escapa del directorio del paquete: {entry_path}",
            )
        try:
            validate_hook_dir(hook_dir)
        except HookValidationError as exc:
            return InstallResult(ok=False, error=str(exc))

        # Leer nombre del hook
        hook_md = hook_dir / "HOOK.md"
        content = hook_md.read_text(encoding="utf-8")
        fm = parse_hook_frontmatter(content)
        hook_name = str(fm.get("name", hook_dir.name))
        resolved_hooks.append(hook_name)

    # Resolver directorio destino
    try:
        target = resolve_hook_install_dir(pack_name, hooks_dir)
    except HookValidationError as exc:
        return InstallResult(ok=False, error=str(exc))

    if target.exists():
        if mode == "install":
            return InstallResult(
                ok=False,
                error=f"Paquete de hooks ya existe: {target} (eliminar primero)",
            )
        if not dry_run:
            shutil.rmtree(target)

    if dry_run:
        return InstallResult(
            ok=True,
            hook_id=pack_name,
            hooks=resolved_hooks,
            target_dir=str(target),
            version=manifest.get("version"),
        )

    # Copiar paquete completo
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.get_event_loop().run_in_executor(
            None, shutil.copytree, str(source_dir), str(target)
        )
    except OSError as exc:
        return InstallResult(
            ok=False, error=f"Error copiando paquete de hooks: {exc}"
        )

    logger.info(
        "Paquete de hooks '%s' instalado en %s (%d hooks)",
        pack_name, target, len(resolved_hooks),
    )
    return InstallResult(
        ok=True,
        hook_id=pack_name,
        hooks=resolved_hooks,
        target_dir=str(target),
        version=manifest.get("version"),
    )


async def install_hook_from_path(
    path: str,
    hooks_dir: Optional[str] = None,
    mode: Literal["install", "update"] = "install",
    dry_run: bool = False,
    expected_hook_id: Optional[str] = None,
) -> InstallResult:
    """Instala un hook desde una ruta (directorio o archivo).

    Si la ruta es un directorio, instala directamente.
    Si es un archivo .tar.gz/.zip, extrae e instala.

    Args:
        path: Ruta al hook (directorio o archivo).
        hooks_dir: Directorio base de hooks.
        mode: 'install' o 'update'.
        dry_run: Si True, no ejecuta cambios.
        expected_hook_id: ID esperado del hook.

    Returns:
        InstallResult.
    """
    resolved = Path(path).expanduser().resolve()

    if not resolved.exists():
        return InstallResult(ok=False, error=f"Ruta no encontrada: {resolved}")

    if resolved.is_dir():
        return await install_hook_from_dir(
            str(resolved), hooks_dir, mode, dry_run, expected_hook_id
        )

    # Intentar como archivo comprimido
    archive_exts = {".tar.gz", ".tgz", ".zip"}
    suffixes = "".join(resolved.suffixes).lower()
    is_archive = any(suffixes.endswith(ext) for ext in archive_exts)

    if not is_archive:
        return InstallResult(
            ok=False, error=f"Tipo de archivo no soportado: {resolved.name}"
        )

    return await install_hook_from_archive(
        str(resolved), hooks_dir, mode, dry_run, expected_hook_id
    )


async def install_hook_from_archive(
    archive_path: str,
    hooks_dir: Optional[str] = None,
    mode: Literal["install", "update"] = "install",
    dry_run: bool = False,
    expected_hook_id: Optional[str] = None,
) -> InstallResult:
    """Instala un hook desde un archivo comprimido (.tar.gz, .zip).

    Extrae a un directorio temporal, valida e instala.

    Args:
        archive_path: Ruta al archivo.
        hooks_dir: Directorio base de hooks.
        mode: 'install' o 'update'.
        dry_run: Si True, no ejecuta cambios.
        expected_hook_id: ID esperado del hook.

    Returns:
        InstallResult.
    """
    resolved = Path(archive_path).resolve()
    if not resolved.exists():
        return InstallResult(ok=False, error=f"Archivo no encontrado: {resolved}")

    temp_dir = None
    try:
        temp_dir = Path(tempfile.mkdtemp(prefix="somer-hook-"))

        # Extraer
        try:
            await asyncio.get_event_loop().run_in_executor(
                None, shutil.unpack_archive, str(resolved), str(temp_dir)
            )
        except (shutil.ReadError, OSError) as exc:
            return InstallResult(ok=False, error=f"Error extrayendo archivo: {exc}")

        # Buscar la raiz del hook (puede estar en un subdirectorio)
        root = _find_hook_root(temp_dir)
        if root is None:
            return InstallResult(
                ok=False,
                error="No se encontro HOOK.md ni somer_hooks.json en el archivo",
            )

        return await install_hook_from_dir(
            str(root), hooks_dir, mode, dry_run, expected_hook_id
        )

    finally:
        if temp_dir and temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def _find_hook_root(directory: Path) -> Optional[Path]:
    """Busca la raiz de un hook en un directorio extraido.

    Busca HOOK.md o somer_hooks.json, maximo 2 niveles de profundidad.

    Args:
        directory: Directorio a buscar.

    Returns:
        Path a la raiz del hook o None.
    """
    # Nivel 0
    if (directory / "HOOK.md").exists() or (directory / "somer_hooks.json").exists():
        return directory

    # Nivel 1
    try:
        for child in directory.iterdir():
            if child.is_dir():
                if (child / "HOOK.md").exists() or (child / "somer_hooks.json").exists():
                    return child
    except OSError:
        pass

    return None


async def uninstall_hook(
    hook_id: str,
    hooks_dir: Optional[str] = None,
) -> InstallResult:
    """Desinstala un hook del directorio de hooks gestionados.

    Args:
        hook_id: Identificador del hook a desinstalar.
        hooks_dir: Directorio base de hooks.

    Returns:
        InstallResult.
    """
    error = validate_hook_id(hook_id)
    if error:
        return InstallResult(ok=False, error=error)

    try:
        target = resolve_hook_install_dir(hook_id, hooks_dir)
    except HookValidationError as exc:
        return InstallResult(ok=False, error=str(exc))

    if not target.exists():
        return InstallResult(
            ok=False,
            error=f"Hook no instalado: {hook_id} (no existe {target})",
        )

    try:
        await asyncio.get_event_loop().run_in_executor(
            None, shutil.rmtree, str(target)
        )
    except OSError as exc:
        return InstallResult(
            ok=False, error=f"Error eliminando hook: {exc}"
        )

    logger.info("Hook '%s' desinstalado de %s", hook_id, target)
    return InstallResult(ok=True, hook_id=hook_id, hooks=[hook_id], target_dir=str(target))


def list_installed_hooks(hooks_dir: Optional[str] = None) -> List[HookEntry]:
    """Lista los hooks instalados en el directorio gestionado.

    Args:
        hooks_dir: Directorio base de hooks.

    Returns:
        Lista de HookEntry instalados.
    """
    base = resolve_hooks_dir(hooks_dir)
    return _load_hooks_from_dir(base, source="somer-managed")


# ── Manager principal ───────────────────────────────────────────

class HookManager:
    """Gestiona hooks de lifecycle: registro, descubrimiento, ejecucion.

    Combina la funcionalidad de carga por configuracion (module:function),
    descubrimiento desde directorios de workspace/managed/bundled,
    e instalacion/desinstalacion dinamica.
    """

    def __init__(self) -> None:
        self._hooks: Dict[str, List[HookCallback]] = {}
        self._entries: Dict[str, HookEntry] = {}
        self._hook_configs: Dict[str, Dict[str, Any]] = {}

    # ── Registro directo ────────────────────────────────────────

    def register(self, event: str, callback: HookCallback) -> None:
        """Registra un callback para un evento de lifecycle.

        Args:
            event: Nombre del evento (ej: 'on_startup').
            callback: Funcion async a ejecutar.
        """
        self._hooks.setdefault(event, []).append(callback)
        logger.debug("Hook registrado: %s", event)

    def unregister(self, event: str, callback: HookCallback) -> None:
        """Des-registra un callback de un evento.

        Args:
            event: Nombre del evento.
            callback: Funcion a remover.
        """
        if event in self._hooks:
            try:
                self._hooks[event].remove(callback)
            except ValueError:
                pass

    def unregister_all(self, event: Optional[str] = None) -> int:
        """Des-registra todos los callbacks de un evento o de todos los eventos.

        Args:
            event: Evento especifico, o None para limpiar todo.

        Returns:
            Numero de callbacks removidos.
        """
        if event:
            count = len(self._hooks.get(event, []))
            self._hooks.pop(event, None)
            return count

        total = sum(len(cbs) for cbs in self._hooks.values())
        self._hooks.clear()
        return total

    # ── Ejecucion ───────────────────────────────────────────────

    async def trigger(self, event: str, **kwargs: Any) -> int:
        """Ejecuta todos los hooks registrados para un evento.

        Cada hook se ejecuta en orden de registro. Los errores se capturan
        individualmente para no interrumpir la cadena.

        Args:
            event: Nombre del evento.
            **kwargs: Argumentos pasados a cada callback.

        Returns:
            Numero de hooks ejecutados exitosamente.
        """
        callbacks = self._hooks.get(event, [])
        executed = 0
        for cb in callbacks:
            try:
                await cb(**kwargs)
                executed += 1
            except Exception:
                logger.exception("Error en hook %s (%s)", event, getattr(cb, "__name__", "?"))
        return executed

    async def trigger_concurrent(self, event: str, **kwargs: Any) -> int:
        """Ejecuta todos los hooks para un evento concurrentemente.

        Util para hooks que no dependen entre si y pueden ejecutar en paralelo.

        Args:
            event: Nombre del evento.
            **kwargs: Argumentos pasados a cada callback.

        Returns:
            Numero de hooks ejecutados exitosamente.
        """
        callbacks = self._hooks.get(event, [])
        if not callbacks:
            return 0

        results = await asyncio.gather(
            *(cb(**kwargs) for cb in callbacks),
            return_exceptions=True,
        )

        executed = 0
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                cb_name = getattr(callbacks[i], "__name__", "?")
                logger.exception(
                    "Error en hook concurrente %s (%s): %s",
                    event, cb_name, result,
                )
            else:
                executed += 1

        return executed

    # ── Carga desde configuracion ───────────────────────────────

    def load_from_config(self, hooks_config: Dict[str, List[str]]) -> int:
        """Carga hooks desde configuracion de SOMER.

        Formato config: {"on_startup": ["module.path:function_name", ...]}

        Args:
            hooks_config: Dict de evento -> lista de specs.

        Returns:
            Numero de hooks cargados exitosamente.
        """
        loaded = 0
        for event, entries in hooks_config.items():
            for entry in entries:
                callback = _load_callback_from_spec(entry)
                if callback:
                    self.register(event, callback)
                    # Crear entry basica para tracking
                    self._entries[entry] = HookEntry(
                        name=entry,
                        source="somer-config",
                        enabled=True,
                    )
                    loaded += 1
                else:
                    logger.error("Error cargando hook: %s", entry)
        return loaded

    # ── Descubrimiento desde workspace ──────────────────────────

    def load_from_workspace(
        self,
        workspace_dir: str,
        managed_hooks_dir: Optional[str] = None,
        bundled_hooks_dir: Optional[str] = None,
        extra_dirs: Optional[List[str]] = None,
        plugin_dirs: Optional[List[Dict[str, str]]] = None,
        hook_configs: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> int:
        """Carga hooks desde workspace, directorios gestionados y bundled.

        Precedencia (mayor gana): workspace > managed > plugin > bundled > extra

        Args:
            workspace_dir: Directorio raiz del workspace.
            managed_hooks_dir: Dir de hooks instalados (~/.somer/hooks).
            bundled_hooks_dir: Dir de hooks incluidos con SOMER.
            extra_dirs: Directorios adicionales a escanear.
            plugin_dirs: Lista de {"dir": path, "plugin_id": id}.
            hook_configs: Config especifica por hook (para eligibilidad).

        Returns:
            Numero de hooks cargados.
        """
        self._hook_configs = hook_configs or {}

        workspace = Path(workspace_dir)
        managed_dir = Path(managed_hooks_dir) if managed_hooks_dir else DEFAULT_HOME / "hooks"
        workspace_hooks_dir = workspace / "hooks"

        # Cargar de cada fuente
        extra_entries: List[HookEntry] = []
        if extra_dirs:
            for d in extra_dirs:
                d_str = d.strip() if isinstance(d, str) else ""
                if d_str:
                    resolved = Path(d_str).expanduser().resolve()
                    extra_entries.extend(
                        _load_hooks_from_dir(resolved, source="somer-workspace")
                    )

        bundled_entries: List[HookEntry] = []
        if bundled_hooks_dir:
            bundled_entries = _load_hooks_from_dir(
                Path(bundled_hooks_dir), source="somer-bundled"
            )

        plugin_entries: List[HookEntry] = []
        if plugin_dirs:
            for pd in plugin_dirs:
                plugin_dir = pd.get("dir", "")
                plugin_id = pd.get("plugin_id")
                if plugin_dir:
                    plugin_entries.extend(
                        _load_hooks_from_dir(
                            Path(plugin_dir), source="somer-plugin", plugin_id=plugin_id
                        )
                    )

        managed_entries = _load_hooks_from_dir(managed_dir, source="somer-managed")
        workspace_entries = _load_hooks_from_dir(workspace_hooks_dir, source="somer-workspace")

        # Merge con precedencia
        merged: Dict[str, HookEntry] = {}
        for entry in extra_entries:
            merged[entry.name] = entry
        for entry in bundled_entries:
            merged[entry.name] = entry
        for entry in plugin_entries:
            merged[entry.name] = entry
        for entry in managed_entries:
            merged[entry.name] = entry
        for entry in workspace_entries:
            merged[entry.name] = entry

        # Filtrar por elegibilidad y registrar
        loaded = 0
        for name, entry in merged.items():
            if not self._should_include_hook(entry):
                logger.debug("Hook '%s' excluido por elegibilidad", name)
                continue

            callback = _load_callback_from_file(entry.handler_path)
            if callback is None:
                logger.warning("No se pudo cargar handler de hook '%s'", name)
                continue

            # Registrar para cada evento declarado
            events = entry.meta.events if entry.meta else []
            if not events:
                # Sin eventos especificos -> registrar como hook generico
                events = ["on_message_in"]

            for event in events:
                self.register(event, callback)

            self._entries[name] = entry
            loaded += 1
            logger.debug(
                "Hook '%s' cargado desde %s (eventos: %s)",
                name, entry.source, events,
            )

        return loaded

    def _should_include_hook(self, entry: HookEntry) -> bool:
        """Evalua si un hook debe incluirse basado en elegibilidad.

        Args:
            entry: HookEntry a evaluar.

        Returns:
            True si debe incluirse.
        """
        if entry.meta is None:
            return entry.enabled

        hook_key = entry.meta.hook_key or entry.name
        hook_config = self._hook_configs.get(hook_key)

        # Hooks de plugin no se deshabilitan por config (solo por meta)
        if entry.source != "somer-plugin" and hook_config:
            if hook_config.get("enabled") is False:
                return False

        return check_hook_eligibility(entry.meta, hook_config)

    # ── Snapshot ────────────────────────────────────────────────

    def build_snapshot(self, version: Optional[int] = None) -> HookSnapshot:
        """Construye un snapshot del estado actual de hooks.

        Args:
            version: Numero de version del snapshot.

        Returns:
            HookSnapshot con los hooks activos.
        """
        hooks_list: List[Dict[str, Any]] = []
        entries_list: List[HookEntry] = []

        for name, entry in self._entries.items():
            events = entry.meta.events if entry.meta else []
            hooks_list.append({"name": name, "events": events})
            entries_list.append(entry)

        return HookSnapshot(
            hooks=hooks_list,
            resolved_hooks=entries_list,
            version=version,
        )

    # ── Instalacion dinamica ────────────────────────────────────

    async def install_hook(
        self,
        path: str,
        hooks_dir: Optional[str] = None,
        mode: Literal["install", "update"] = "install",
        dry_run: bool = False,
    ) -> InstallResult:
        """Instala un hook y lo registra en el manager.

        Args:
            path: Ruta al hook (directorio o archivo).
            hooks_dir: Directorio base de hooks.
            mode: 'install' o 'update'.
            dry_run: Si True, no ejecuta cambios.

        Returns:
            InstallResult.
        """
        result = await install_hook_from_path(path, hooks_dir, mode, dry_run)

        if result.ok and not dry_run:
            # Cargar los hooks recien instalados
            target = Path(result.target_dir)
            new_entries = _load_hooks_from_dir(target.parent, source="somer-managed")

            for entry in new_entries:
                if entry.name in result.hooks:
                    callback = _load_callback_from_file(entry.handler_path)
                    if callback:
                        events = entry.meta.events if entry.meta else ["on_message_in"]
                        for event in events:
                            self.register(event, callback)
                        self._entries[entry.name] = entry
                        logger.info("Hook '%s' instalado y registrado", entry.name)

        return result

    async def uninstall_hook(
        self,
        hook_id: str,
        hooks_dir: Optional[str] = None,
    ) -> InstallResult:
        """Desinstala un hook y lo des-registra del manager.

        Args:
            hook_id: Identificador del hook.
            hooks_dir: Directorio base de hooks.

        Returns:
            InstallResult.
        """
        result = await uninstall_hook(hook_id, hooks_dir)

        if result.ok:
            # Limpiar registros del hook
            if hook_id in self._entries:
                del self._entries[hook_id]
            logger.info("Hook '%s' desinstalado y des-registrado", hook_id)

        return result

    # ── Introspección ───────────────────────────────────────────

    def list_events(self) -> List[str]:
        """Retorna la lista de eventos con hooks registrados."""
        return list(self._hooks.keys())

    def hook_count(self, event: str) -> int:
        """Retorna el numero de hooks registrados para un evento."""
        return len(self._hooks.get(event, []))

    def total_hook_count(self) -> int:
        """Retorna el total de callbacks registrados."""
        return sum(len(cbs) for cbs in self._hooks.values())

    def list_entries(self) -> List[HookEntry]:
        """Retorna todas las entradas de hooks registrados."""
        return list(self._entries.values())

    def get_entry(self, name: str) -> Optional[HookEntry]:
        """Retorna la entrada de un hook por nombre.

        Args:
            name: Nombre del hook.

        Returns:
            HookEntry o None.
        """
        return self._entries.get(name)

    def has_hook(self, name: str) -> bool:
        """Verifica si un hook esta registrado.

        Args:
            name: Nombre del hook.

        Returns:
            True si existe.
        """
        return name in self._entries
