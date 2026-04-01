"""Sistema de plugins de SOMER 2.0.

Portado desde OpenClaw. Provee un sistema completo de plugins que incluye:

- **types**: Sistema completo de tipos (capacidades, permisos, estados de lifecycle)
- **manifest**: Definición y carga de manifiestos de plugins
- **contracts**: Interfaces/protocolos que los plugins deben implementar
- **registry**: Registro centralizado, consulta y resolución de dependencias
- **loader**: Descubrimiento, validación y carga desde filesystem/paquetes
- **installer**: Instalación/desinstalación desde git, pip, local
- **lifecycle**: Gestión de estados (discovered → init → ready → running → stopped → error)
- **runtime**: Ejecución, IPC y límites de recursos
- **sdk**: Interfaz que reciben los plugins para registrar capacidades
"""

from __future__ import annotations

from plugins.contracts import (
    ChannelPluginContract,
    ContextEnginePluginContract,
    HookPluginContract,
    PluginContract,
    ProviderPluginContract,
    ServicePluginContract,
    SkillPluginContract,
    ToolPluginContract,
    validate_contract,
)
from plugins.lifecycle import (
    PluginLifecycleError,
    PluginLifecycleManager,
    is_valid_transition,
)
from plugins.manifest import (
    PluginManifest,
    PluginManifestError,
    load_manifest,
    resolve_manifest_path,
    validate_manifest,
)
from plugins.registry import (
    PluginRegistry,
    PluginRegistryError,
)
from plugins.runtime import (
    LoadedPlugin,
    PluginRuntime,
    PluginRuntimeError,
)
from plugins.sdk import PluginSDK
from plugins.types import (
    PLUGIN_HOOK_NAMES,
    HookCallback,
    PluginCapability,
    PluginConfigSchema,
    PluginConfigUiHint,
    PluginConfigValidation,
    PluginDiagnostic,
    PluginFormat,
    PluginHookRegistration,
    PluginKind,
    PluginOrigin,
    PluginPermission,
    PluginRecord,
    PluginState,
    ResourceLimits,
    ToolHandler,
    is_plugin_hook_name,
)

__all__ = [
    # Types
    "PluginState",
    "PluginOrigin",
    "PluginFormat",
    "PluginKind",
    "PluginCapability",
    "PluginPermission",
    "PluginRecord",
    "PluginDiagnostic",
    "PluginConfigSchema",
    "PluginConfigUiHint",
    "PluginConfigValidation",
    "PluginHookRegistration",
    "ResourceLimits",
    "ToolHandler",
    "HookCallback",
    "PLUGIN_HOOK_NAMES",
    "is_plugin_hook_name",
    # Manifest
    "PluginManifest",
    "PluginManifestError",
    "load_manifest",
    "resolve_manifest_path",
    "validate_manifest",
    # Contracts
    "PluginContract",
    "ChannelPluginContract",
    "ProviderPluginContract",
    "SkillPluginContract",
    "HookPluginContract",
    "ContextEnginePluginContract",
    "ServicePluginContract",
    "ToolPluginContract",
    "validate_contract",
    # Registry
    "PluginRegistry",
    "PluginRegistryError",
    # Lifecycle
    "PluginLifecycleManager",
    "PluginLifecycleError",
    "is_valid_transition",
    # Runtime
    "PluginRuntime",
    "PluginRuntimeError",
    "LoadedPlugin",
    # SDK
    "PluginSDK",
]
