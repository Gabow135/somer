"""Plugin manifest — definición y carga de manifiestos de plugins.

Portado desde OpenClaw manifest.ts. Define la estructura del manifiesto
que describe un plugin: metadata, entry points, capacidades, permisos,
canales, providers, skills y esquema de configuración.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from shared.errors import SomerError

logger = logging.getLogger(__name__)

# ── Constantes ───────────────────────────────────────────────

MANIFEST_FILENAMES = [
    "manifest.json",
    "somer.plugin.json",
    "plugin.json",
]


# ── Errores ──────────────────────────────────────────────────

class PluginManifestError(SomerError):
    """Error al cargar o validar un manifiesto de plugin."""


# ── Dataclass ────────────────────────────────────────────────

@dataclass
class PluginManifest:
    """Manifiesto de un plugin — describe su metadata y entry point.

    Formato del archivo JSON::

        {
            "name": "my-plugin",
            "version": "1.0.0",
            "description": "Plugin de ejemplo",
            "author": "SOMER Team",
            "entry_point": "main.py",
            "kind": "general",
            "capabilities": ["tool", "hook"],
            "permissions": ["read_config", "network"],
            "channels": ["telegram"],
            "providers": ["openai"],
            "skills": ["search"],
            "skills_dir": "skills",
            "config_schema": {"api_key": {"type": "string", "required": true}},
            "enabled_by_default": true,
            "min_somer_version": "2.0.0"
        }
    """

    name: str
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    entry_point: str = "main.py"
    setup_entry: Optional[str] = None  # Entry point alternativo para setup-only
    skills_dir: Optional[str] = None
    config_schema: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    source_path: Optional[Path] = None  # Directorio donde vive el plugin

    # ── Nuevos campos portados de OpenClaw ────────────────────
    kind: Optional[str] = None  # Tipo funcional: provider, channel, etc.
    capabilities: List[str] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)
    channels: List[str] = field(default_factory=list)
    providers: List[str] = field(default_factory=list)
    skills: List[str] = field(default_factory=list)
    enabled_by_default: bool = True
    min_somer_version: Optional[str] = None
    ui_hints: Dict[str, Any] = field(default_factory=dict)
    env_vars: List[str] = field(default_factory=list)  # Variables de entorno asociadas


# ── Funciones de carga ───────────────────────────────────────

def load_manifest(path: str) -> PluginManifest:
    """Carga un PluginManifest desde un archivo JSON.

    Args:
        path: Ruta al archivo manifest.json.

    Returns:
        PluginManifest con los datos cargados.

    Raises:
        PluginManifestError: Si el archivo no existe, no es JSON válido,
            o le faltan campos requeridos.
    """
    file_path = Path(path)
    if not file_path.exists():
        raise PluginManifestError(f"Manifiesto no encontrado: {path}")

    try:
        raw = file_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PluginManifestError(f"JSON inválido en {path}: {exc}")

    if not isinstance(data, dict):
        raise PluginManifestError(f"El manifiesto debe ser un objeto JSON: {path}")

    name = data.get("name")
    if not name:
        raise PluginManifestError(f"Campo 'name' requerido en manifiesto: {path}")

    manifest = PluginManifest(
        name=name,
        version=data.get("version", "1.0.0"),
        description=data.get("description", ""),
        author=data.get("author", ""),
        entry_point=data.get("entry_point", "main.py"),
        setup_entry=data.get("setup_entry"),
        skills_dir=data.get("skills_dir"),
        config_schema=data.get("config_schema", {}),
        tags=_normalize_string_list(data.get("tags")),
        dependencies=_normalize_string_list(data.get("dependencies")),
        source_path=file_path.parent,
        kind=data.get("kind"),
        capabilities=_normalize_string_list(data.get("capabilities")),
        permissions=_normalize_string_list(data.get("permissions")),
        channels=_normalize_string_list(data.get("channels")),
        providers=_normalize_string_list(data.get("providers")),
        skills=_normalize_string_list(data.get("skills")),
        enabled_by_default=data.get("enabled_by_default", True),
        min_somer_version=data.get("min_somer_version"),
        ui_hints=data.get("ui_hints", {}),
        env_vars=_normalize_string_list(data.get("env_vars")),
    )
    logger.info("Manifiesto cargado: %s v%s", manifest.name, manifest.version)
    return manifest


def resolve_manifest_path(root_dir: str) -> Optional[str]:
    """Busca el archivo de manifiesto en un directorio.

    Busca los nombres de archivo conocidos para manifiestos
    en el directorio dado.

    Args:
        root_dir: Directorio raíz donde buscar.

    Returns:
        Ruta al manifiesto encontrado o None.
    """
    root = Path(root_dir)
    for filename in MANIFEST_FILENAMES:
        candidate = root / filename
        if candidate.exists():
            return str(candidate)
    return None


def validate_manifest(manifest: PluginManifest) -> List[str]:
    """Valida un manifiesto de plugin.

    Verifica que todos los campos requeridos estén presentes
    y que los valores sean válidos.

    Args:
        manifest: Manifiesto a validar.

    Returns:
        Lista de errores de validación (vacía si es válido).
    """
    errors: List[str] = []

    if not manifest.name or not manifest.name.strip():
        errors.append("Campo 'name' es requerido y no puede estar vacío")

    if not manifest.entry_point or not manifest.entry_point.strip():
        errors.append("Campo 'entry_point' es requerido")

    # Validar source_path si existe
    if manifest.source_path:
        entry = manifest.source_path / manifest.entry_point
        if not entry.exists():
            errors.append(
                f"Entry point no encontrado: {entry}"
            )

    # Validar kind
    valid_kinds = {
        "provider", "channel", "skill", "hook",
        "context_engine", "memory", "tool", "general",
    }
    if manifest.kind and manifest.kind not in valid_kinds:
        errors.append(f"Kind inválido: '{manifest.kind}' (válidos: {valid_kinds})")

    # Validar permisos
    valid_permissions = {
        "read_config", "write_config", "read_secrets", "network",
        "filesystem", "subprocess", "register_hooks", "register_tools",
        "register_providers", "register_channels", "register_skills",
        "register_gateway_methods",
    }
    for perm in manifest.permissions:
        if perm not in valid_permissions:
            errors.append(f"Permiso inválido: '{perm}'")

    return errors


# ── Helpers ──────────────────────────────────────────────────

def _normalize_string_list(value: Any) -> List[str]:
    """Normaliza un valor a lista de strings no vacíos."""
    if not isinstance(value, list):
        return []
    return [
        str(entry).strip()
        for entry in value
        if isinstance(entry, str) and entry.strip()
    ]
