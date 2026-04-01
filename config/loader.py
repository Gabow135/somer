"""Carga y persistencia de configuración SOMER 2.0.

Portado de OpenClaw: io.ts.
Incluye: carga multi-archivo, escritura atómica, migración de config,
hash de config, $include resolution, y merge profundo.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from config.schema import SomerConfig
from shared.constants import DEFAULT_CONFIG_PATH, DEFAULT_HOME, VERSION
from shared.errors import ConfigNotFoundError, ConfigValidationError

logger = logging.getLogger(__name__)

# json5 es opcional; fallback a json estándar
try:
    import json5  # type: ignore[import-untyped]
    _loads = json5.loads
except ImportError:
    _loads = json.loads


# ════════════════════════════════════════════════════════════════
# Helpers internos
# ════════════════════════════════════════════════════════════════

def _ensure_home() -> Path:
    """Crea el directorio home de SOMER si no existe."""
    DEFAULT_HOME.mkdir(parents=True, exist_ok=True)
    return DEFAULT_HOME


def _hash_content(content: str) -> str:
    """Genera SHA-256 del contenido de config."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> None:
    """Merge profundo in-place de override sobre base."""
    for key, value in override.items():
        if (
            key in base
            and isinstance(base[key], dict)
            and isinstance(value, dict)
        ):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def _resolve_env_vars_in_string(value: str) -> str:
    """Resuelve referencias ``${VAR}`` dentro de un string.

    Portado de OpenClaw: env-substitution.ts.
    """
    def _replace(match: re.Match[str]) -> str:
        var_name = match.group(1)
        env_value = os.environ.get(var_name)
        if env_value is None:
            logger.warning(
                "Variable de entorno %s referenciada en config no está definida",
                var_name,
            )
            return match.group(0)  # Dejar sin modificar
        return env_value

    return re.sub(r"\$\{([A-Z][A-Z0-9_]*)\}", _replace, value)


def _resolve_env_vars(data: Any) -> Any:
    """Resuelve recursivamente referencias ``${VAR}`` en la config.

    Portado de OpenClaw: env-substitution.ts ``resolveConfigEnvVars``.
    """
    if isinstance(data, str):
        return _resolve_env_vars_in_string(data)
    if isinstance(data, dict):
        return {k: _resolve_env_vars(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_resolve_env_vars(item) for item in data]
    return data


# ════════════════════════════════════════════════════════════════
# $include resolution
# ════════════════════════════════════════════════════════════════

_MAX_INCLUDE_DEPTH = 10


def _resolve_includes(
    data: Dict[str, Any],
    config_dir: Path,
    depth: int = 0,
    seen: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Resuelve directivas ``$include`` en la configuración.

    Portado de OpenClaw: includes.ts ``resolveConfigIncludes``.
    Permite dividir la configuración en múltiples archivos.

    Ejemplo en config.json:
        { "$include": "providers.json", "gateway": { ... } }
    o múltiples:
        { "$include": ["providers.json", "channels.json"] }

    Args:
        data: Config dict con posibles $include.
        config_dir: Directorio base para resolver paths relativos.
        depth: Profundidad de recursión actual.
        seen: Rutas ya visitadas (detección de ciclos).

    Returns:
        Config dict con $include resueltos.
    """
    if seen is None:
        seen = []

    if depth > _MAX_INCLUDE_DEPTH:
        raise ConfigValidationError(
            f"$include anidado excede el máximo de {_MAX_INCLUDE_DEPTH} niveles"
        )

    include_value = data.pop("$include", None)
    if include_value is None:
        return data

    includes: List[str] = (
        include_value if isinstance(include_value, list) else [include_value]
    )

    merged: Dict[str, Any] = {}
    for include_path_str in includes:
        if not isinstance(include_path_str, str) or not include_path_str.strip():
            continue

        include_path = config_dir / include_path_str
        resolved = str(include_path.resolve())

        if resolved in seen:
            raise ConfigValidationError(
                f"$include circular detectado: {resolved}"
            )

        if not include_path.exists():
            logger.warning(
                "$include referencia archivo inexistente: %s", include_path
            )
            continue

        try:
            raw = include_path.read_text(encoding="utf-8")
            included_data = _loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ConfigValidationError(
                f"Error parseando $include {include_path}: {exc}"
            ) from exc

        if not isinstance(included_data, dict):
            raise ConfigValidationError(
                f"$include {include_path} debe ser un objeto JSON, "
                f"recibido: {type(included_data).__name__}"
            )

        included_data = _resolve_includes(
            included_data,
            include_path.parent,
            depth + 1,
            seen + [resolved],
        )
        _deep_merge(merged, included_data)

    # El contenido del archivo principal tiene prioridad sobre los includes
    _deep_merge(merged, data)
    return merged


# ════════════════════════════════════════════════════════════════
# Migración de config
# ════════════════════════════════════════════════════════════════

def _migrate_config(data: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Migra configuraciones de versiones anteriores.

    Portado de OpenClaw: legacy-migrate.ts, legacy.migrations.*.ts.

    Args:
        data: Config dict a migrar.

    Returns:
        Tupla de (config migrada, lista de warnings).
    """
    warnings: List[str] = []
    version = data.get("version", "1.0")

    # v1.x → v2.0: migrar skills_dirs a skills.dirs
    if "skills_dirs" in data:
        skills = data.setdefault("skills", {})
        if "dirs" not in skills:
            skills["dirs"] = data.pop("skills_dirs")
            warnings.append(
                "Migrado: skills_dirs → skills.dirs"
            )
        else:
            data.pop("skills_dirs")

    # v1.x → v2.0: migrar hooks dict a hooks.internal.handlers
    if isinstance(data.get("hooks"), dict):
        hooks_data = data["hooks"]
        # Solo migrar si parece ser el formato viejo (dict de event → [handlers])
        if hooks_data and all(
            isinstance(v, list) and all(isinstance(i, str) for i in v)
            for v in hooks_data.values()
        ):
            handlers = []
            for event, modules in hooks_data.items():
                for mod in modules:
                    handlers.append({"event": event, "module": mod})
            data["hooks"] = {
                "enabled": True,
                "internal": {"handlers": handlers},
            }
            warnings.append(
                "Migrado: hooks (dict) → hooks.internal.handlers"
            )

    # v1.x → v2.0: migrar dm_scope top-level a sessions.dm_scope
    if "dm_scope" in data:
        sessions = data.setdefault("sessions", {})
        if "dm_scope" not in sessions:
            sessions["dm_scope"] = data.pop("dm_scope")
            warnings.append("Migrado: dm_scope → sessions.dm_scope")
        else:
            data.pop("dm_scope")

    # v1.x → v2.0: migrar identity_links top-level a sessions.identity_links
    if "identity_links" in data:
        sessions = data.setdefault("sessions", {})
        if "identity_links" not in sessions:
            sessions["identity_links"] = data.pop("identity_links")
            warnings.append(
                "Migrado: identity_links → sessions.identity_links"
            )
        else:
            data.pop("identity_links")

    # v1.x → v2.0: migrar channels (dict plano) a channels.entries
    if isinstance(data.get("channels"), dict):
        channels_data = data["channels"]
        # Detectar formato viejo: si las claves son nombres de canales
        # y los valores tienen "enabled"/"plugin"
        if channels_data and "entries" not in channels_data and "defaults" not in channels_data:
            first_value = next(iter(channels_data.values()), None)
            if isinstance(first_value, dict) and (
                "enabled" in first_value or "plugin" in first_value
            ):
                data["channels"] = {"entries": channels_data}
                warnings.append(
                    "Migrado: channels (dict plano) → channels.entries"
                )

    # Actualizar versión
    if version != "2.0":
        data["version"] = "2.0"
        if warnings:
            warnings.insert(0, f"Config migrada de v{version} a v2.0")

    return data, warnings


# ════════════════════════════════════════════════════════════════
# Config Validation
# ════════════════════════════════════════════════════════════════

class ConfigValidationIssue:
    """Problema encontrado durante validación de configuración.

    Portado de OpenClaw: types.openclaw.ts ``ConfigValidationIssue``.
    """

    def __init__(
        self,
        path: str,
        message: str,
        allowed_values: Optional[List[str]] = None,
    ):
        self.path = path
        self.message = message
        self.allowed_values = allowed_values or []

    def __repr__(self) -> str:
        return f"ConfigValidationIssue(path={self.path!r}, message={self.message!r})"


def validate_config(
    data: Dict[str, Any],
) -> Tuple[SomerConfig, List[ConfigValidationIssue], List[ConfigValidationIssue]]:
    """Valida la configuración con mensajes detallados.

    Portado de OpenClaw: validation.ts ``validateConfigObjectWithPlugins``.

    Args:
        data: Config dict a validar.

    Returns:
        Tupla de (SomerConfig, errores, advertencias).
    """
    errors: List[ConfigValidationIssue] = []
    warnings: List[ConfigValidationIssue] = []

    # Verificar campos desconocidos en top-level
    known_fields = set(SomerConfig.model_fields.keys())
    for key in data:
        if key not in known_fields and key != "$include":
            warnings.append(
                ConfigValidationIssue(
                    path=key,
                    message=f"Campo desconocido en configuración raíz: '{key}'",
                )
            )

    # Validar providers tienen modelos si están habilitados
    for provider_id, provider_data in data.get("providers", {}).items():
        if isinstance(provider_data, dict):
            if provider_data.get("enabled", True):
                auth = provider_data.get("auth", {})
                if not any([
                    auth.get("api_key_env"),
                    auth.get("api_key_file"),
                    auth.get("api_key"),
                    os.environ.get(f"{provider_id.upper()}_API_KEY"),
                ]):
                    warnings.append(
                        ConfigValidationIssue(
                            path=f"providers.{provider_id}.auth",
                            message=f"Provider '{provider_id}' habilitado sin "
                            f"API key configurada",
                        )
                    )

    # Validar que el modelo por defecto exista en algún provider
    default_model = data.get("default_model")
    if default_model and data.get("providers"):
        model_found = False
        for provider_data in data["providers"].values():
            if isinstance(provider_data, dict):
                for model in provider_data.get("models", []):
                    if isinstance(model, dict) and model.get("id") == default_model:
                        model_found = True
                        break
            if model_found:
                break
        if not model_found:
            warnings.append(
                ConfigValidationIssue(
                    path="default_model",
                    message=f"Modelo por defecto '{default_model}' no encontrado "
                    f"en ningún provider configurado",
                )
            )

    # Intentar parsear con Pydantic
    try:
        config = SomerConfig.model_validate(data)
    except Exception as exc:
        errors.append(
            ConfigValidationIssue(
                path="(root)",
                message=f"Error de validación: {exc}",
            )
        )
        # Intentar con defaults para poder continuar
        config = SomerConfig()

    return config, errors, warnings


# ════════════════════════════════════════════════════════════════
# Config File Snapshot
# ════════════════════════════════════════════════════════════════

class ConfigFileSnapshot:
    """Snapshot de un archivo de configuración.

    Portado de OpenClaw: types.openclaw.ts ``ConfigFileSnapshot``.
    """

    def __init__(
        self,
        path: Path,
        exists: bool,
        raw: Optional[str],
        parsed: Any,
        config: SomerConfig,
        valid: bool,
        content_hash: Optional[str],
        issues: Optional[List[ConfigValidationIssue]] = None,
        warnings: Optional[List[ConfigValidationIssue]] = None,
        migration_warnings: Optional[List[str]] = None,
    ):
        self.path = path
        self.exists = exists
        self.raw = raw
        self.parsed = parsed
        self.config = config
        self.valid = valid
        self.content_hash = content_hash
        self.issues = issues or []
        self.warnings = warnings or []
        self.migration_warnings = migration_warnings or []


# ════════════════════════════════════════════════════════════════
# Carga principal
# ════════════════════════════════════════════════════════════════

def resolve_config_path(path: Optional[Path] = None) -> Path:
    """Resuelve la ruta del archivo de configuración.

    Busca en orden: path dado, SOMER_CONFIG env, candidatos por defecto.
    Portado de OpenClaw: paths.ts ``resolveConfigPath``.
    """
    if path is not None:
        return path

    env_path = os.environ.get("SOMER_CONFIG")
    if env_path:
        return Path(env_path)

    # Candidatos por defecto
    candidates = [
        DEFAULT_CONFIG_PATH,
        DEFAULT_HOME / "config.json5",
        Path("somer.json"),
        Path("somer.json5"),
        Path(".somer.json"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    return DEFAULT_CONFIG_PATH


def load_config(path: Optional[Path] = None) -> SomerConfig:
    """Carga configuración desde archivo JSON/JSON5.

    Portado de OpenClaw: io.ts ``readConfigFile``.
    Soporta: JSON5, $include, ${ENV} substitution, migración automática.

    Args:
        path: Ruta al archivo. Si None, resuelve automáticamente.

    Returns:
        SomerConfig validado.

    Raises:
        ConfigNotFoundError: Si el archivo no existe y no se puede crear.
        ConfigValidationError: Si el contenido no es válido.
    """
    config_path = resolve_config_path(path)

    if not config_path.exists():
        logger.info("Config no encontrada en %s, usando defaults", config_path)
        return SomerConfig()

    try:
        raw = config_path.read_text(encoding="utf-8")
        data = _loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ConfigValidationError(
            f"Error parseando config en {config_path}: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise ConfigValidationError(
            f"Config en {config_path} debe ser un objeto JSON, "
            f"recibido: {type(data).__name__}"
        )

    # Resolver $include
    try:
        data = _resolve_includes(data, config_path.parent)
    except ConfigValidationError:
        raise
    except Exception as exc:
        raise ConfigValidationError(
            f"Error resolviendo $include en {config_path}: {exc}"
        ) from exc

    # Resolver ${ENV} vars
    data = _resolve_env_vars(data)

    # Migrar config antigua
    data, migration_warnings = _migrate_config(data)
    for warning in migration_warnings:
        logger.warning("Migración de config: %s", warning)

    try:
        return SomerConfig.model_validate(data)
    except Exception as exc:
        raise ConfigValidationError(
            f"Config inválida en {config_path}: {exc}"
        ) from exc


def load_config_snapshot(
    path: Optional[Path] = None,
) -> ConfigFileSnapshot:
    """Carga configuración como snapshot con metadatos.

    Portado de OpenClaw: io.ts ``readConfigFileSnapshot``.

    Args:
        path: Ruta al archivo.

    Returns:
        ConfigFileSnapshot con toda la información de la carga.
    """
    config_path = resolve_config_path(path)

    if not config_path.exists():
        return ConfigFileSnapshot(
            path=config_path,
            exists=False,
            raw=None,
            parsed=None,
            config=SomerConfig(),
            valid=True,
            content_hash=None,
        )

    try:
        raw = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        return ConfigFileSnapshot(
            path=config_path,
            exists=True,
            raw=None,
            parsed=None,
            config=SomerConfig(),
            valid=False,
            content_hash=None,
            issues=[
                ConfigValidationIssue(
                    path="(file)", message=f"No se pudo leer: {exc}"
                )
            ],
        )

    content_hash = _hash_content(raw)

    try:
        parsed = _loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        return ConfigFileSnapshot(
            path=config_path,
            exists=True,
            raw=raw,
            parsed=None,
            config=SomerConfig(),
            valid=False,
            content_hash=content_hash,
            issues=[
                ConfigValidationIssue(
                    path="(parse)", message=f"JSON inválido: {exc}"
                )
            ],
        )

    if not isinstance(parsed, dict):
        return ConfigFileSnapshot(
            path=config_path,
            exists=True,
            raw=raw,
            parsed=parsed,
            config=SomerConfig(),
            valid=False,
            content_hash=content_hash,
            issues=[
                ConfigValidationIssue(
                    path="(root)",
                    message="Config debe ser un objeto JSON",
                )
            ],
        )

    # Resolver includes y env vars
    data = dict(parsed)
    try:
        data = _resolve_includes(data, config_path.parent)
    except ConfigValidationError as exc:
        return ConfigFileSnapshot(
            path=config_path,
            exists=True,
            raw=raw,
            parsed=parsed,
            config=SomerConfig(),
            valid=False,
            content_hash=content_hash,
            issues=[
                ConfigValidationIssue(
                    path="$include", message=str(exc)
                )
            ],
        )

    data = _resolve_env_vars(data)
    data, migration_warnings = _migrate_config(data)
    config, errors, warnings = validate_config(data)

    return ConfigFileSnapshot(
        path=config_path,
        exists=True,
        raw=raw,
        parsed=parsed,
        config=config,
        valid=len(errors) == 0,
        content_hash=content_hash,
        issues=errors,
        warnings=warnings,
        migration_warnings=migration_warnings,
    )


# ════════════════════════════════════════════════════════════════
# Escritura atómica
# ════════════════════════════════════════════════════════════════

def save_config(
    config: SomerConfig,
    path: Optional[Path] = None,
    *,
    exclude_defaults: bool = False,
    stamp_meta: bool = True,
) -> Path:
    """Guarda configuración a archivo JSON con escritura atómica.

    Portado de OpenClaw: io.ts ``writeConfigFile``.
    Usa write-to-temp + rename para evitar corrupción.

    Args:
        config: Configuración a guardar.
        path: Ruta destino. Si None, usa ~/.somer/config.json.
        exclude_defaults: Si True, omite valores iguales al default.
        stamp_meta: Si True, actualiza meta.last_touched_version/at.

    Returns:
        Path al archivo guardado.
    """
    config_path = path or DEFAULT_CONFIG_PATH
    _ensure_home()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Actualizar meta si se solicita
    if stamp_meta:
        from config.schema import ConfigMeta
        config = config.model_copy(
            update={
                "meta": ConfigMeta(
                    last_touched_version=VERSION,
                    last_touched_at=datetime.now(timezone.utc).isoformat(),
                )
            }
        )

    data = config.model_dump(exclude_defaults=exclude_defaults)
    content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"

    # Escritura atómica: temp file + rename
    try:
        fd, tmp_path = tempfile.mkstemp(
            dir=str(config_path.parent),
            prefix=".somer-config-",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, str(config_path))
        except BaseException:
            # Limpiar temp file en caso de error
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except OSError:
        # Fallback: escritura directa si atómica falla
        logger.warning(
            "Escritura atómica falló, usando escritura directa en %s",
            config_path,
        )
        config_path.write_text(content, encoding="utf-8")

    logger.info("Config guardada en %s", config_path)
    return config_path


# ════════════════════════════════════════════════════════════════
# Merge de config
# ════════════════════════════════════════════════════════════════

def merge_config(base: SomerConfig, overrides: Dict[str, Any]) -> SomerConfig:
    """Merge parcial de overrides sobre una config base.

    Portado de OpenClaw: merge-patch.ts ``applyMergePatch``.

    Args:
        base: Configuración base.
        overrides: Dict parcial con overrides.

    Returns:
        Nueva SomerConfig con los overrides aplicados.
    """
    base_data = base.model_dump()
    _deep_merge(base_data, overrides)
    return SomerConfig.model_validate(base_data)


# ════════════════════════════════════════════════════════════════
# File Watcher
# ════════════════════════════════════════════════════════════════

class ConfigFileWatcher:
    """Watcher de cambios en archivo de configuración.

    Portado de OpenClaw: io.ts ``watchConfigFile``.
    Usa polling de stat (mtime + size) para detectar cambios.
    """

    def __init__(
        self,
        path: Optional[Path] = None,
        debounce_ms: int = 300,
        on_change: Optional[Callable[[SomerConfig], None]] = None,
    ):
        self._path = resolve_config_path(path)
        self._debounce_ms = debounce_ms
        self._on_change = on_change
        self._last_mtime: float = 0.0
        self._last_size: int = 0
        self._last_hash: Optional[str] = None
        self._running = False

    def check(self) -> Optional[SomerConfig]:
        """Verifica cambios y recarga si es necesario.

        Returns:
            Nueva SomerConfig si hubo cambios, None si no.
        """
        if not self._path.exists():
            return None

        try:
            stat = self._path.stat()
        except OSError:
            return None

        if stat.st_mtime == self._last_mtime and stat.st_size == self._last_size:
            return None

        self._last_mtime = stat.st_mtime
        self._last_size = stat.st_size

        try:
            raw = self._path.read_text(encoding="utf-8")
        except OSError:
            return None

        content_hash = _hash_content(raw)
        if content_hash == self._last_hash:
            return None

        self._last_hash = content_hash

        try:
            config = load_config(self._path)
        except (ConfigValidationError, ConfigNotFoundError):
            logger.warning(
                "Config cambió pero no es válida, ignorando recarga"
            )
            return None

        if self._on_change:
            self._on_change(config)

        logger.info("Config recargada desde %s", self._path)
        return config

    @property
    def path(self) -> Path:
        return self._path

    @property
    def last_hash(self) -> Optional[str]:
        return self._last_hash
