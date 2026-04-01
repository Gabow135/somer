"""Tests para el sistema de aliases de modelo."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from config.schema import AgentDefaultsConfig, ModelAliasEntry
from providers.aliases import (
    bootstrap_model_aliases,
    build_alias_lines,
    load_aliases_from_config,
)
from providers.base import BaseProvider
from providers.registry import ProviderRegistry
from shared.types import ModelDefinition


class DummyProvider(BaseProvider):
    """Provider de testing para aliases."""

    def __init__(
        self,
        provider_id: str = "dummy",
        models: Optional[List[ModelDefinition]] = None,
    ):
        super().__init__(
            provider_id=provider_id,
            api="openai-completions",
            api_key="test-key",
            models=models or [
                ModelDefinition(
                    id="dummy-model",
                    name="Dummy Model",
                    api="openai-completions",
                    provider=provider_id,
                )
            ],
        )

    async def complete(self, messages: List[Dict[str, Any]], model: str, **kw: Any) -> Dict[str, Any]:
        return {"content": "ok", "model": model, "usage": {}, "stop_reason": "end_turn"}


class TestLoadAliasesFromConfig:
    """Tests de load_aliases_from_config."""

    def _make_registry(self) -> ProviderRegistry:
        registry = ProviderRegistry()
        registry.register(DummyProvider("anthropic", [
            ModelDefinition(id="claude-sonnet-4-5", name="Sonnet", api="anthropic-messages", provider="anthropic"),
        ]))
        registry.register(DummyProvider("openai", [
            ModelDefinition(id="gpt-4o", name="GPT-4o", api="openai-completions", provider="openai"),
        ]))
        return registry

    def test_load_string_entries(self) -> None:
        registry = self._make_registry()
        defaults = AgentDefaultsConfig(models={
            "smart": "anthropic/claude-sonnet-4-5",
            "fast": "openai/gpt-4o",
        })
        count = load_aliases_from_config(defaults, registry)
        assert count == 2

        resolved = registry.resolve_model("smart")
        assert resolved is not None
        assert resolved.model.id == "claude-sonnet-4-5"

    def test_load_dict_entries(self) -> None:
        registry = self._make_registry()
        defaults = AgentDefaultsConfig(models={
            "smart": {"alias": "anthropic/claude-sonnet-4-5"},
        })
        count = load_aliases_from_config(defaults, registry)
        assert count == 1

    def test_empty_config(self) -> None:
        registry = self._make_registry()
        defaults = AgentDefaultsConfig()
        count = load_aliases_from_config(defaults, registry)
        assert count == 0

    def test_invalid_entry_skipped(self) -> None:
        registry = self._make_registry()
        defaults = AgentDefaultsConfig(models={
            "broken": {"alias": None},
            "also_broken": {},
        })
        count = load_aliases_from_config(defaults, registry)
        assert count == 0

    def test_case_insensitive_resolve(self) -> None:
        registry = self._make_registry()
        defaults = AgentDefaultsConfig(models={
            "Smart": "anthropic/claude-sonnet-4-5",
        })
        load_aliases_from_config(defaults, registry)
        # El alias se registra case-insensitive
        resolved = registry.resolve_model("smart")
        assert resolved is not None

    def test_model_without_provider_slash(self) -> None:
        registry = self._make_registry()
        defaults = AgentDefaultsConfig(models={
            "sonnet": "claude-sonnet-4-5",
        })
        count = load_aliases_from_config(defaults, registry)
        assert count == 1
        resolved = registry.resolve_model("sonnet")
        assert resolved is not None


class TestBuildAliasLines:
    """Tests de build_alias_lines."""

    def test_with_aliases(self) -> None:
        defaults = AgentDefaultsConfig(models={
            "fast": "openai/gpt-4o-mini",
            "smart": {"alias": "anthropic/claude-opus-4-6"},
        })
        lines = build_alias_lines(defaults)
        assert len(lines) == 2
        assert any("fast" in line and "gpt-4o-mini" in line for line in lines)

    def test_empty(self) -> None:
        defaults = AgentDefaultsConfig()
        lines = build_alias_lines(defaults)
        assert lines == []


class TestBootstrapModelAliases:
    """Tests de bootstrap_model_aliases."""

    def test_bootstrap(self) -> None:
        registry = ProviderRegistry()
        registry.register(DummyProvider("anthropic", [
            ModelDefinition(id="claude-sonnet-4-5", name="Sonnet", api="anthropic-messages", provider="anthropic"),
        ]))
        defaults = AgentDefaultsConfig(models={
            "smart": "anthropic/claude-sonnet-4-5",
        })
        count = bootstrap_model_aliases(defaults, registry)
        assert count == 1


class TestModelAliasEntry:
    """Tests del tipo ModelAliasEntry."""

    def test_defaults(self) -> None:
        entry = ModelAliasEntry()
        assert entry.alias is None

    def test_with_alias(self) -> None:
        entry = ModelAliasEntry(alias="anthropic/claude-sonnet-4-5")
        assert entry.alias == "anthropic/claude-sonnet-4-5"
