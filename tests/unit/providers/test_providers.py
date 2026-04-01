"""Tests para el sistema de providers LLM."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, patch

import pytest

from providers.base import AuthProfile, BaseProvider
from providers.registry import ProviderRegistry
from shared.types import ModelDefinition


class DummyProvider(BaseProvider):
    """Provider de testing."""

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

    async def complete(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        *,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: Optional[List[Dict[str, Any]]] = None,
        stream: bool = False,
    ) -> Dict[str, Any]:
        return {
            "content": "dummy response",
            "model": model,
            "usage": {"input_tokens": 10, "output_tokens": 5},
            "stop_reason": "end_turn",
        }


class TestAuthProfile:
    """Tests del perfil de autenticación."""

    def test_initial_state(self) -> None:
        auth = AuthProfile("test")
        assert auth.is_available
        assert auth.failure_count == 0

    def test_record_success(self) -> None:
        auth = AuthProfile("test")
        auth.record_failure()
        assert auth.failure_count == 1
        auth.record_success()
        assert auth.failure_count == 0
        assert auth.is_available

    def test_record_failure_cooldown(self) -> None:
        auth = AuthProfile("test", cooldown_secs=1.0)
        cooldown = auth.record_failure()
        assert cooldown >= 1.0
        assert not auth.is_available

    def test_exponential_backoff(self) -> None:
        auth = AuthProfile("test", cooldown_secs=1.0)
        c1 = auth.record_failure()
        c2 = auth.record_failure()
        assert c2 > c1

    def test_billing_error_long_cooldown(self) -> None:
        auth = AuthProfile("test", cooldown_secs=1.0)
        cooldown = auth.record_failure(is_billing=True)
        assert cooldown >= 10.0  # Billing = 10x cooldown

    def test_reset(self) -> None:
        auth = AuthProfile("test")
        auth.record_failure()
        auth.reset()
        assert auth.is_available
        assert auth.failure_count == 0


class TestBaseProvider:
    """Tests del BaseProvider."""

    @pytest.mark.asyncio
    async def test_complete(self) -> None:
        provider = DummyProvider()
        result = await provider.complete(
            [{"role": "user", "content": "hello"}],
            "dummy-model",
        )
        assert result["content"] == "dummy response"

    def test_list_models(self) -> None:
        provider = DummyProvider()
        models = provider.list_models()
        assert len(models) == 1
        assert models[0].id == "dummy-model"

    def test_get_model(self) -> None:
        provider = DummyProvider()
        model = provider.get_model("dummy-model")
        assert model is not None
        assert model.id == "dummy-model"

    def test_get_model_not_found(self) -> None:
        provider = DummyProvider()
        assert provider.get_model("nonexistent") is None

    @pytest.mark.asyncio
    async def test_health_check(self) -> None:
        provider = DummyProvider()
        assert await provider.health_check()

    @pytest.mark.asyncio
    async def test_health_check_no_key(self) -> None:
        provider = DummyProvider()
        provider.api_key = None
        assert not await provider.health_check()


class TestProviderRegistry:
    """Tests del ProviderRegistry."""

    def test_register(self) -> None:
        registry = ProviderRegistry()
        provider = DummyProvider()
        registry.register(provider)
        assert registry.provider_count == 1

    def test_get_provider(self) -> None:
        registry = ProviderRegistry()
        provider = DummyProvider()
        registry.register(provider)
        assert registry.get_provider("dummy") is provider

    def test_get_provider_for_model(self) -> None:
        registry = ProviderRegistry()
        provider = DummyProvider()
        registry.register(provider)
        found = registry.get_provider_for_model("dummy-model")
        assert found is provider

    def test_get_provider_for_unknown_model(self) -> None:
        registry = ProviderRegistry()
        assert registry.get_provider_for_model("unknown") is None

    def test_unregister(self) -> None:
        registry = ProviderRegistry()
        provider = DummyProvider()
        registry.register(provider)
        registry.unregister("dummy")
        assert registry.provider_count == 0

    def test_list_all_models(self) -> None:
        registry = ProviderRegistry()
        p1 = DummyProvider("p1", [
            ModelDefinition(id="m1", name="M1", api="openai-completions", provider="p1")
        ])
        p2 = DummyProvider("p2", [
            ModelDefinition(id="m2", name="M2", api="openai-completions", provider="p2")
        ])
        registry.register(p1)
        registry.register(p2)
        models = registry.list_all_models()
        assert len(models) == 2

    def test_find_fallback(self) -> None:
        registry = ProviderRegistry()
        p1 = DummyProvider("p1")
        p2 = DummyProvider("p2")
        registry.register(p1)
        registry.register(p2)
        fallback = registry.find_fallback("p1")
        assert fallback is p2

    def test_find_fallback_none_available(self) -> None:
        registry = ProviderRegistry()
        p1 = DummyProvider("p1")
        registry.register(p1)
        assert registry.find_fallback("p1") is None

    def test_list_available_filters_cooldown(self) -> None:
        registry = ProviderRegistry()
        p1 = DummyProvider("p1")
        p2 = DummyProvider("p2")
        p1.auth.record_failure()  # En cooldown
        registry.register(p1)
        registry.register(p2)
        available = registry.list_available_providers()
        assert len(available) == 1
        assert available[0].provider_id == "p2"


class TestNewProviders:
    """Tests de instanciación de todos los providers portados de OpenClaw."""

    def test_xai_provider(self) -> None:
        from providers.xai import XAIProvider, XAI_MODELS
        p = XAIProvider(api_key="test")
        assert p.provider_id == "xai"
        assert len(XAI_MODELS) >= 2

    def test_openrouter_provider(self) -> None:
        from providers.openrouter import OpenRouterProvider, OPENROUTER_MODELS
        p = OpenRouterProvider(api_key="test")
        assert p.provider_id == "openrouter"
        assert len(OPENROUTER_MODELS) >= 2

    def test_mistral_provider(self) -> None:
        from providers.mistral import MistralProvider, MISTRAL_MODELS
        p = MistralProvider(api_key="test")
        assert p.provider_id == "mistral"
        assert len(MISTRAL_MODELS) >= 1

    def test_together_provider(self) -> None:
        from providers.together import TogetherProvider, TOGETHER_MODELS
        p = TogetherProvider(api_key="test")
        assert p.provider_id == "together"
        assert len(TOGETHER_MODELS) >= 2

    def test_groq_provider(self) -> None:
        from providers.groq import GroqProvider, GROQ_MODELS
        p = GroqProvider(api_key="test")
        assert p.provider_id == "groq"
        assert len(GROQ_MODELS) >= 2

    def test_nvidia_provider(self) -> None:
        from providers.nvidia import NvidiaProvider, NVIDIA_MODELS
        p = NvidiaProvider(api_key="test")
        assert p.provider_id == "nvidia"
        assert len(NVIDIA_MODELS) >= 2

    def test_huggingface_provider(self) -> None:
        from providers.huggingface import HuggingFaceProvider
        p = HuggingFaceProvider(api_key="test")
        assert p.provider_id == "huggingface"

    def test_perplexity_provider(self) -> None:
        from providers.perplexity import PerplexityProvider, PERPLEXITY_MODELS
        p = PerplexityProvider(api_key="test")
        assert p.provider_id == "perplexity"
        assert len(PERPLEXITY_MODELS) >= 2

    def test_moonshot_provider(self) -> None:
        from providers.moonshot import MoonshotProvider
        p = MoonshotProvider(api_key="test")
        assert p.provider_id == "moonshot"

    def test_venice_provider(self) -> None:
        from providers.venice import VeniceProvider
        p = VeniceProvider(api_key="test")
        assert p.provider_id == "venice"

    def test_qianfan_provider(self) -> None:
        from providers.qianfan import QianfanProvider
        p = QianfanProvider(api_key="test")
        assert p.provider_id == "qianfan"

    def test_volcengine_provider(self) -> None:
        from providers.volcengine import VolcengineProvider
        p = VolcengineProvider(api_key="test")
        assert p.provider_id == "volcengine"

    def test_minimax_provider(self) -> None:
        from providers.minimax import MiniMaxProvider
        p = MiniMaxProvider(api_key="test")
        assert p.provider_id == "minimax"

    def test_vllm_provider(self) -> None:
        from providers.vllm import VLLMProvider
        p = VLLMProvider()
        assert p.provider_id == "vllm"

    def test_sglang_provider(self) -> None:
        from providers.sglang import SGLangProvider
        p = SGLangProvider()
        assert p.provider_id == "sglang"

    def test_all_providers_have_models_or_empty(self) -> None:
        """Verifica que todos los providers se instancian sin error."""
        from providers.xai import XAIProvider
        from providers.openrouter import OpenRouterProvider
        from providers.mistral import MistralProvider
        from providers.together import TogetherProvider
        from providers.groq import GroqProvider
        from providers.nvidia import NvidiaProvider
        from providers.huggingface import HuggingFaceProvider
        from providers.perplexity import PerplexityProvider
        from providers.moonshot import MoonshotProvider
        from providers.venice import VeniceProvider
        from providers.qianfan import QianfanProvider
        from providers.volcengine import VolcengineProvider
        from providers.minimax import MiniMaxProvider
        from providers.vllm import VLLMProvider
        from providers.sglang import SGLangProvider

        providers = [
            XAIProvider(api_key="t"), OpenRouterProvider(api_key="t"),
            MistralProvider(api_key="t"), TogetherProvider(api_key="t"),
            GroqProvider(api_key="t"), NvidiaProvider(api_key="t"),
            HuggingFaceProvider(api_key="t"), PerplexityProvider(api_key="t"),
            MoonshotProvider(api_key="t"), VeniceProvider(api_key="t"),
            QianfanProvider(api_key="t"), VolcengineProvider(api_key="t"),
            MiniMaxProvider(api_key="t"), VLLMProvider(), SGLangProvider(),
        ]
        assert len(providers) == 15

    def test_all_providers_auth_id_consistency(self) -> None:
        """Verifica que provider_id y auth.provider_id son consistentes."""
        from providers.openai import OpenAIProvider
        from providers.deepseek import DeepSeekProvider
        from providers.xai import XAIProvider
        from providers.openrouter import OpenRouterProvider
        from providers.mistral import MistralProvider
        from providers.together import TogetherProvider
        from providers.groq import GroqProvider
        from providers.nvidia import NvidiaProvider
        from providers.huggingface import HuggingFaceProvider
        from providers.perplexity import PerplexityProvider
        from providers.moonshot import MoonshotProvider
        from providers.venice import VeniceProvider
        from providers.qianfan import QianfanProvider
        from providers.volcengine import VolcengineProvider
        from providers.minimax import MiniMaxProvider
        from providers.vllm import VLLMProvider
        from providers.sglang import SGLangProvider

        all_providers = [
            OpenAIProvider(api_key="t"), DeepSeekProvider(api_key="t"),
            XAIProvider(api_key="t"), OpenRouterProvider(api_key="t"),
            MistralProvider(api_key="t"), TogetherProvider(api_key="t"),
            GroqProvider(api_key="t"), NvidiaProvider(api_key="t"),
            HuggingFaceProvider(api_key="t"), PerplexityProvider(api_key="t"),
            MoonshotProvider(api_key="t"), VeniceProvider(api_key="t"),
            QianfanProvider(api_key="t"), VolcengineProvider(api_key="t"),
            MiniMaxProvider(api_key="t"), VLLMProvider(), SGLangProvider(),
        ]

        for p in all_providers:
            assert p.provider_id == p.auth.provider_id, (
                f"{p.__class__.__name__}: provider_id='{p.provider_id}' "
                f"!= auth.provider_id='{p.auth.provider_id}'"
            )


class TestOllamaProvider:
    """Tests del provider Ollama con auto-discovery y streaming."""

    def test_init_defaults(self) -> None:
        from providers.ollama import OllamaProvider, OLLAMA_DEFAULT_URL
        p = OllamaProvider()
        assert p.provider_id == "ollama"
        assert p.base_url == OLLAMA_DEFAULT_URL
        assert p.api_key == "local"
        assert p.api == "ollama"

    def test_init_custom_url(self) -> None:
        from providers.ollama import OllamaProvider
        p = OllamaProvider(base_url="http://myhost:11434")
        assert p.base_url == "http://myhost:11434"

    def test_url_strips_v1(self) -> None:
        from providers.ollama import OllamaProvider
        p = OllamaProvider(base_url="http://myhost:11434/v1")
        assert p.base_url == "http://myhost:11434"

    def test_reasoning_detection(self) -> None:
        from providers.ollama import _is_reasoning_model
        assert _is_reasoning_model("deepseek-r1:latest")
        assert _is_reasoning_model("qwen-reasoning:7b")
        assert _is_reasoning_model("my-think-model:latest")
        assert not _is_reasoning_model("llama3.1:8b")
        assert not _is_reasoning_model("mistral:7b")

    def test_build_model_definition(self) -> None:
        from providers.ollama import OllamaProvider
        p = OllamaProvider()
        defn = p._build_model_definition({
            "name": "llama3.1:8b",
            "context_window": 131072,
            "size": 4_700_000_000,
            "details": {"family": "llama", "parameter_size": "8B"},
        })
        assert defn.id == "llama3.1:8b"
        assert defn.provider == "ollama"
        assert defn.api == "ollama"
        assert defn.max_input_tokens == 131072
        assert defn.metadata.get("reasoning") is False
        assert defn.metadata.get("local") is True
        assert defn.cost_per_input_token == 0.0

    def test_build_reasoning_model(self) -> None:
        from providers.ollama import OllamaProvider
        p = OllamaProvider()
        defn = p._build_model_definition({
            "name": "deepseek-r1:14b",
            "context_window": 128000,
        })
        assert defn.metadata.get("reasoning") is True

    def test_convert_messages(self) -> None:
        from providers.ollama import OllamaProvider
        msgs = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello"},
        ]
        converted = OllamaProvider._convert_messages(msgs)
        assert len(converted) == 2
        assert converted[0]["role"] == "system"
        assert converted[1]["content"] == "Hello"

    def test_convert_tools_passthrough(self) -> None:
        from providers.ollama import OllamaProvider
        tools = [
            {"type": "function", "function": {"name": "get_weather", "parameters": {}}}
        ]
        assert OllamaProvider._convert_tools(tools) == tools

    @pytest.mark.asyncio
    async def test_health_check_failure(self) -> None:
        from providers.ollama import OllamaProvider
        p = OllamaProvider(base_url="http://localhost:99999")
        assert not await p.health_check()

    @pytest.mark.asyncio
    async def test_list_local_models_failure(self) -> None:
        from providers.ollama import OllamaProvider
        p = OllamaProvider(base_url="http://localhost:99999")
        models = await p.list_local_models()
        assert models == []

    @pytest.mark.asyncio
    async def test_discover_models_no_server(self) -> None:
        from providers.ollama import OllamaProvider
        p = OllamaProvider(base_url="http://localhost:99999")
        models = await p.discover_models()
        assert models == []

    @pytest.mark.asyncio
    async def test_discover_models_mock(self) -> None:
        from providers.ollama import OllamaProvider
        p = OllamaProvider()

        # Mock _fetch_models y _query_context_window directamente
        p._fetch_models = AsyncMock(return_value=[
            {"name": "llama3.1:8b", "size": 4_700_000_000,
             "details": {"family": "llama", "parameter_size": "8B"}},
            {"name": "deepseek-r1:14b", "size": 8_500_000_000,
             "details": {"family": "deepseek", "parameter_size": "14B"}},
        ])
        p._query_context_window = AsyncMock(return_value=128000)

        models = await p.discover_models()

        assert len(models) == 2
        assert models[0].id == "llama3.1:8b"
        assert models[1].id == "deepseek-r1:14b"
        assert models[1].metadata.get("reasoning") is True
        assert models[0].max_input_tokens == 128000


class TestDeepSeekProvider:
    """Tests del provider DeepSeek."""

    def test_init(self) -> None:
        from providers.deepseek import DeepSeekProvider, DEEPSEEK_MODELS
        p = DeepSeekProvider(api_key="test")
        assert p.provider_id == "deepseek"
        assert p.base_url == "https://api.deepseek.com/v1"
        assert len(DEEPSEEK_MODELS) == 2

    def test_models_use_openai_api(self) -> None:
        from providers.deepseek import DEEPSEEK_MODELS
        for model in DEEPSEEK_MODELS:
            assert model.api == "openai-completions"

    def test_chat_model(self) -> None:
        from providers.deepseek import DEEPSEEK_MODELS
        chat = next(m for m in DEEPSEEK_MODELS if m.id == "deepseek-chat")
        assert chat.name == "DeepSeek V3 (Chat)"
        assert chat.max_input_tokens == 64_000
        assert chat.metadata.get("reasoning") is False

    def test_reasoner_model(self) -> None:
        from providers.deepseek import DEEPSEEK_MODELS
        reasoner = next(m for m in DEEPSEEK_MODELS if m.id == "deepseek-reasoner")
        assert reasoner.name == "DeepSeek R1 (Reasoner)"
        assert reasoner.metadata.get("reasoning") is True

    def test_streaming_support(self) -> None:
        from providers.deepseek import DEEPSEEK_MODELS
        for model in DEEPSEEK_MODELS:
            assert model.supports_streaming is True
            assert model.supports_tools is True
