"""Sistema de aliases de modelo desde configuración.

Portado de OpenClaw: model-aliases.ts.
Permite mapear nombres cortos (e.g. 'fast', 'smart') a modelos reales
desde la sección ``agents.defaults.models`` de la configuración.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from config.schema import AgentDefaultsConfig
    from providers.registry import ProviderRegistry

logger = logging.getLogger(__name__)


def load_aliases_from_config(
    defaults: AgentDefaultsConfig,
    registry: ProviderRegistry,
) -> int:
    """Carga aliases de modelo desde la configuración de agentes.

    Parsea ``defaults.models`` y registra cada alias en el registry.
    Cada entrada puede ser:
    - ``{"alias": "provider/model"}`` → ModelAliasEntry
    - ``{"alias": "model-id"}`` → se resuelve con default_provider

    Args:
        defaults: Configuración de defaults de agentes.
        registry: Registry de providers donde registrar aliases.

    Returns:
        Número de aliases registrados.
    """
    count = 0
    models_dict: Dict[str, Any] = defaults.models or {}

    for alias_name, entry in models_dict.items():
        target: Optional[str] = None

        if isinstance(entry, str):
            target = entry
        elif isinstance(entry, dict):
            target = entry.get("alias")
        elif hasattr(entry, "alias"):
            target = entry.alias

        if not target:
            continue

        # Separar provider/model si tiene slash
        if "/" in target:
            parts = target.split("/", 1)
            provider_id = parts[0].strip()
            model_id = parts[1].strip()
        else:
            # Sin slash, intentar resolverlo contra el registry
            model_id = target.strip()
            provider_id = _guess_provider(model_id, registry)

        if provider_id and model_id:
            registry.register_alias(alias_name, provider_id, model_id)
            count += 1
            logger.debug(
                "Alias cargado: %s → %s/%s", alias_name, provider_id, model_id
            )

    return count


def _guess_provider(model_id: str, registry: ProviderRegistry) -> str:
    """Intenta adivinar el provider de un model_id buscando en el registry."""
    provider = registry.get_provider_for_model(model_id)
    if provider:
        return provider.provider_id
    return "anthropic"


def build_alias_lines(defaults: AgentDefaultsConfig) -> List[str]:
    """Genera líneas de display de aliases configurados.

    Args:
        defaults: Configuración de defaults de agentes.

    Returns:
        Lista de strings formateados para mostrar.
    """
    models_dict: Dict[str, Any] = defaults.models or {}
    lines: List[str] = []

    for alias_name, entry in models_dict.items():
        target: Optional[str] = None
        if isinstance(entry, str):
            target = entry
        elif isinstance(entry, dict):
            target = entry.get("alias")
        elif hasattr(entry, "alias"):
            target = entry.alias

        if target:
            lines.append(f"  {alias_name} → {target}")

    return lines


def bootstrap_model_aliases(
    defaults: AgentDefaultsConfig,
    registry: ProviderRegistry,
) -> int:
    """Bootstrap de aliases de modelo.

    Punto de entrada principal para inicializar aliases desde la config.

    Args:
        defaults: Configuración de defaults de agentes.
        registry: Registry de providers.

    Returns:
        Número de aliases registrados.
    """
    count = load_aliases_from_config(defaults, registry)
    if count > 0:
        logger.info("Aliases de modelo cargados: %d", count)
    return count
