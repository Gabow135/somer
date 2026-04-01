"""Catálogos enriquecidos de modelos por provider.

Cada catálogo exporta una lista de ModelDefinition con costos reales,
flags de compatibilidad y metadatos enriquecidos.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List

if TYPE_CHECKING:
    from shared.types import ModelDefinition

# Lazy imports para evitar carga circular
_cache: Dict[str, List[ModelDefinition]] = {}


def get_catalog(provider_id: str) -> List[ModelDefinition]:
    """Obtiene el catálogo de modelos para un provider (lazy import).

    Args:
        provider_id: ID del provider (e.g. 'anthropic', 'openai').

    Returns:
        Lista de ModelDefinition enriquecidos, o lista vacía si
        el provider no tiene catálogo.
    """
    if provider_id in _cache:
        return _cache[provider_id]

    catalog: List[ModelDefinition] = []

    try:
        if provider_id == "anthropic":
            from providers.catalogs.anthropic import ANTHROPIC_CATALOG
            catalog = ANTHROPIC_CATALOG
        elif provider_id == "openai":
            from providers.catalogs.openai import OPENAI_CATALOG
            catalog = OPENAI_CATALOG
        elif provider_id == "deepseek":
            from providers.catalogs.deepseek import DEEPSEEK_CATALOG
            catalog = DEEPSEEK_CATALOG
        elif provider_id == "google":
            from providers.catalogs.google import GOOGLE_CATALOG
            catalog = GOOGLE_CATALOG
        elif provider_id == "xai":
            from providers.catalogs.xai import XAI_CATALOG
            catalog = XAI_CATALOG
        elif provider_id == "mistral":
            from providers.catalogs.mistral import MISTRAL_CATALOG
            catalog = MISTRAL_CATALOG
        elif provider_id == "groq":
            from providers.catalogs.groq import GROQ_CATALOG
            catalog = GROQ_CATALOG
        elif provider_id == "together":
            from providers.catalogs.together import TOGETHER_CATALOG
            catalog = TOGETHER_CATALOG
        elif provider_id == "perplexity":
            from providers.catalogs.perplexity import PERPLEXITY_CATALOG
            catalog = PERPLEXITY_CATALOG
        elif provider_id == "openrouter":
            from providers.catalogs.openrouter import OPENROUTER_CATALOG
            catalog = OPENROUTER_CATALOG
        elif provider_id == "nvidia":
            from providers.catalogs.nvidia import NVIDIA_CATALOG
            catalog = NVIDIA_CATALOG
        elif provider_id == "bedrock":
            from providers.catalogs.bedrock import BEDROCK_CATALOG
            catalog = BEDROCK_CATALOG
        elif provider_id == "minimax":
            from providers.catalogs.minimax import MINIMAX_CATALOG
            catalog = MINIMAX_CATALOG
        elif provider_id == "moonshot":
            from providers.catalogs.moonshot import MOONSHOT_CATALOG
            catalog = MOONSHOT_CATALOG
        elif provider_id == "qianfan":
            from providers.catalogs.qianfan import QIANFAN_CATALOG
            catalog = QIANFAN_CATALOG
        elif provider_id == "huggingface":
            from providers.catalogs.huggingface import HUGGINGFACE_CATALOG
            catalog = HUGGINGFACE_CATALOG
        elif provider_id == "volcengine":
            from providers.catalogs.volcengine import VOLCENGINE_CATALOG
            catalog = VOLCENGINE_CATALOG
        elif provider_id == "venice":
            from providers.catalogs.venice import VENICE_CATALOG
            catalog = VENICE_CATALOG
    except ImportError:
        pass

    _cache[provider_id] = catalog
    return catalog
