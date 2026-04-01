"""Tests para catálogos enriquecidos de modelos."""

from __future__ import annotations

import pytest

from providers.catalogs import get_catalog
from shared.types import ModelCostConfig, ModelCompatConfig


class TestGetCatalog:
    """Tests de la función get_catalog."""

    def test_known_provider(self) -> None:
        catalog = get_catalog("anthropic")
        assert len(catalog) >= 3

    def test_unknown_provider(self) -> None:
        catalog = get_catalog("nonexistent-provider")
        assert catalog == []

    def test_caching(self) -> None:
        c1 = get_catalog("openai")
        c2 = get_catalog("openai")
        assert c1 is c2


class TestCatalogCompleteness:
    """Tests de que todos los catálogos tienen datos enriquecidos."""

    PROVIDERS_WITH_CATALOGS = [
        "anthropic", "openai", "deepseek", "google", "xai", "mistral",
        "groq", "together", "perplexity", "openrouter", "nvidia",
        "bedrock", "minimax", "moonshot", "qianfan", "huggingface",
        "volcengine", "venice",
    ]

    def test_all_providers_have_catalogs(self) -> None:
        for pid in self.PROVIDERS_WITH_CATALOGS:
            catalog = get_catalog(pid)
            assert len(catalog) >= 1, f"{pid} tiene catálogo vacío"

    def test_all_models_have_cost(self) -> None:
        for pid in self.PROVIDERS_WITH_CATALOGS:
            for model in get_catalog(pid):
                assert isinstance(model.cost, ModelCostConfig), (
                    f"{pid}/{model.id} no tiene ModelCostConfig"
                )

    def test_all_models_have_compat(self) -> None:
        for pid in self.PROVIDERS_WITH_CATALOGS:
            for model in get_catalog(pid):
                assert isinstance(model.compat, ModelCompatConfig), (
                    f"{pid}/{model.id} no tiene ModelCompatConfig"
                )

    def test_no_duplicate_ids_within_provider(self) -> None:
        for pid in self.PROVIDERS_WITH_CATALOGS:
            catalog = get_catalog(pid)
            ids = [m.id for m in catalog]
            assert len(ids) == len(set(ids)), (
                f"{pid} tiene IDs duplicados: {ids}"
            )

    def test_all_models_have_provider_set(self) -> None:
        for pid in self.PROVIDERS_WITH_CATALOGS:
            for model in get_catalog(pid):
                assert model.provider == pid, (
                    f"{pid}/{model.id}: provider={model.provider}"
                )


class TestAnthropicCatalog:
    """Tests específicos del catálogo Anthropic."""

    def test_models_count(self) -> None:
        catalog = get_catalog("anthropic")
        assert len(catalog) == 3

    def test_opus_has_vision_and_reasoning(self) -> None:
        catalog = get_catalog("anthropic")
        opus = next(m for m in catalog if "opus" in m.id)
        assert opus.supports_vision is True
        assert opus.reasoning is True
        assert opus.cost.input > 0
        assert opus.cost.cache_read > 0
        assert opus.compat.thinking_format == "anthropic"

    def test_haiku_cost_lower_than_opus(self) -> None:
        catalog = get_catalog("anthropic")
        opus = next(m for m in catalog if "opus" in m.id)
        haiku = next(m for m in catalog if "haiku" in m.id)
        assert haiku.cost.input < opus.cost.input


class TestOpenAICatalog:
    """Tests específicos del catálogo OpenAI."""

    def test_models_count(self) -> None:
        catalog = get_catalog("openai")
        assert len(catalog) >= 3

    def test_gpt4o_has_developer_role(self) -> None:
        catalog = get_catalog("openai")
        gpt4o = next(m for m in catalog if m.id == "gpt-4o")
        assert gpt4o.compat.supports_developer_role is True

    def test_o3_mini_is_reasoning(self) -> None:
        catalog = get_catalog("openai")
        o3 = next(m for m in catalog if m.id == "o3-mini")
        assert o3.reasoning is True
        assert o3.compat.max_tokens_field == "max_completion_tokens"


class TestProviderCatalogConsistency:
    """Tests de consistencia entre provider y catálogo."""

    def test_anthropic_provider_uses_catalog(self) -> None:
        from providers.anthropic import ANTHROPIC_MODELS
        from providers.catalogs.anthropic import ANTHROPIC_CATALOG
        assert ANTHROPIC_MODELS is ANTHROPIC_CATALOG

    def test_openai_provider_uses_catalog(self) -> None:
        from providers.openai import OPENAI_MODELS
        from providers.catalogs.openai import OPENAI_CATALOG
        assert OPENAI_MODELS is OPENAI_CATALOG

    def test_deepseek_provider_uses_catalog(self) -> None:
        from providers.deepseek import DEEPSEEK_MODELS
        from providers.catalogs.deepseek import DEEPSEEK_CATALOG
        assert DEEPSEEK_MODELS is DEEPSEEK_CATALOG

    def test_xai_provider_uses_catalog(self) -> None:
        from providers.xai import XAI_MODELS
        from providers.catalogs.xai import XAI_CATALOG
        assert XAI_MODELS is XAI_CATALOG

    def test_mistral_provider_uses_catalog(self) -> None:
        from providers.mistral import MISTRAL_MODELS
        from providers.catalogs.mistral import MISTRAL_CATALOG
        assert MISTRAL_MODELS is MISTRAL_CATALOG
