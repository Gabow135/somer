"""Interceptor proactivo de credenciales.

Detecta API keys en mensajes de usuario, las guarda automáticamente
en ~/.somer/.env y verifica la conexión con el servicio.

Corre ANTES del LLM en el pipeline de mensajes.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from secrets.patterns import CREDENTIAL_PATTERNS

logger = logging.getLogger(__name__)


# ── Definiciones de servicios ─────────────────────────────────────


@dataclass
class ServiceDefinition:
    """Define un servicio cuya API key puede detectarse en texto."""

    service_id: str
    display_name: str
    env_var: str
    key_pattern: str  # regex
    verify_url: str
    verify_type: str  # notion | openai_compat | anthropic | telegram | bearer
    context_clues: List[str] = field(default_factory=list)
    unique_prefix: bool = True  # patrón es único (no necesita contexto)


# ── Metadata extra por servicio (verify, clues) ──────────────────
# Solo lo que NO está en patterns.py

_SERVICE_META: Dict[str, Dict[str, Any]] = {
    "anthropic": {"display": "Anthropic (Claude)", "url": "https://api.anthropic.com", "type": "anthropic", "clues": ["anthropic", "claude"]},
    "openrouter": {"display": "OpenRouter", "url": "https://openrouter.ai/api", "type": "openai_compat", "clues": ["openrouter"]},
    "groq": {"display": "Groq", "url": "https://api.groq.com/openai", "type": "openai_compat", "clues": ["groq"]},
    "google": {"display": "Google", "url": "https://generativelanguage.googleapis.com", "type": "bearer", "clues": ["google", "gemini"]},
    "huggingface": {"display": "HuggingFace", "url": "https://huggingface.co/api", "type": "bearer", "clues": ["huggingface", "hugging face", "hf"]},
    "xai": {"display": "xAI (Grok)", "url": "https://api.x.ai", "type": "openai_compat", "clues": ["xai", "grok"]},
    "perplexity": {"display": "Perplexity", "url": "https://api.perplexity.ai", "type": "openai_compat", "clues": ["perplexity"]},
    "nvidia": {"display": "NVIDIA", "url": "https://integrate.api.nvidia.com", "type": "bearer", "clues": ["nvidia"]},
    "notion": {"display": "Notion", "url": "https://api.notion.com", "type": "notion", "clues": ["notion"]},
    "github_pat": {"display": "GitHub", "url": "https://api.github.com", "type": "bearer", "clues": ["github"]},
    "github_oauth": {"display": "GitHub", "url": "https://api.github.com", "type": "bearer", "clues": ["github"]},
    "gitlab": {"display": "GitLab", "url": "https://gitlab.com/api/v4", "type": "bearer", "clues": ["gitlab"]},
    "slack_bot": {"display": "Slack Bot", "url": "https://slack.com/api", "type": "bearer", "clues": ["slack"]},
    "slack_app": {"display": "Slack App", "url": "https://slack.com/api", "type": "bearer", "clues": ["slack"]},
    "tavily": {"display": "Tavily", "url": "https://api.tavily.com", "type": "tavily", "clues": ["tavily"]},
    "telegram": {"display": "Telegram Bot", "url": "https://api.telegram.org", "type": "telegram", "clues": ["telegram", "bot"]},
    "discord": {"display": "Discord Bot", "url": "https://discord.com/api", "type": "bearer", "clues": ["discord"]},
    "openai": {"display": "OpenAI", "url": "https://api.openai.com", "type": "openai_compat", "clues": ["openai", "gpt", "chatgpt"]},
    "deepseek": {"display": "DeepSeek", "url": "https://api.deepseek.com", "type": "openai_compat", "clues": ["deepseek"]},
    "trello_key": {"display": "Trello (API Key)", "url": "https://api.trello.com", "type": "trello", "clues": ["trello", "trello api key", "trello key"]},
    "trello_token": {"display": "Trello (Token)", "url": "https://api.trello.com", "type": "trello", "clues": ["trello token", "trello oauth"]},
    "mistral": {"display": "Mistral", "url": "https://api.mistral.ai", "type": "openai_compat", "clues": ["mistral"]},
    "together": {"display": "Together AI", "url": "https://api.together.xyz", "type": "openai_compat", "clues": ["together"]},
}


def _build_service_definitions() -> List[ServiceDefinition]:
    """Construye SERVICE_DEFINITIONS desde patterns.py + metadata local."""
    defs: List[ServiceDefinition] = []
    for p in CREDENTIAL_PATTERNS:
        meta = _SERVICE_META.get(p.service_id, {})
        defs.append(ServiceDefinition(
            service_id=p.service_id,
            display_name=meta.get("display", p.service_id.title()),
            env_var=p.env_var,
            key_pattern=p.pattern,
            verify_url=meta.get("url", ""),
            verify_type=meta.get("type", "bearer"),
            context_clues=meta.get("clues", []),
            unique_prefix=p.unique_prefix,
        ))
    return defs


# Orden importa: patrones más específicos primero (heredado de patterns.py)
SERVICE_DEFINITIONS: List[ServiceDefinition] = _build_service_definitions()


@dataclass
class InterceptResult:
    """Resultado de la intercepción."""

    intercepted: bool
    response: str = ""
    service_id: str = ""
    key_saved: bool = False
    key_verified: bool = False


# ── Frases que indican intención de configurar ────────────────────

_INTENT_PHRASES = [
    "quiero usar", "quiero configurar", "configurar", "conectar",
    "activar", "integrar", "agregar", "añadir", "setup",
    "la api es", "mi api key", "mi key", "mi token", "api key",
]


# ── Interceptor ───────────────────────────────────────────────────


class CredentialInterceptor:
    """Detecta credenciales en mensajes y las procesa proactivamente."""

    def __init__(self) -> None:
        self._services = SERVICE_DEFINITIONS

    async def intercept(self, text: str) -> InterceptResult:
        """Analiza un mensaje buscando credenciales o intención de configurar.

        Returns:
            InterceptResult indicando si se interceptó el mensaje.
        """
        if not text or len(text) < 5:
            return InterceptResult(intercepted=False)

        text_lower = text.lower()

        # Fase 1: Buscar key en el texto
        detected = self._detect_key(text, text_lower)
        if detected:
            svc, key = detected
            return await self._handle_key_found(svc, key)

        # Fase 2: Buscar intención sin key
        service = self._detect_intent(text_lower)
        if service:
            return InterceptResult(
                intercepted=True,
                response=self._format_intent_response(service),
                service_id=service.service_id,
            )

        return InterceptResult(intercepted=False)

    # ── Detección ─────────────────────────────────────────────

    def _detect_key(
        self, text: str, text_lower: str
    ) -> Optional[Tuple[ServiceDefinition, str]]:
        """Detecta una API key en el texto.

        Fase 1: Patrones con contexto (si el texto menciona el servicio).
        Fase 2: Patrones con prefijo único.
        """
        # Fase 1: Contexto + patrón (para servicios no únicos como DeepSeek)
        for svc in self._services:
            if not svc.unique_prefix:
                has_context = any(
                    clue in text_lower for clue in svc.context_clues
                )
                if has_context:
                    match = re.search(svc.key_pattern, text)
                    if match:
                        return (svc, match.group(0))

        # Fase 2: Prefijo único (ntn_, sk-ant-, gsk_, etc.)
        for svc in self._services:
            if svc.unique_prefix:
                match = re.search(svc.key_pattern, text)
                if match:
                    return (svc, match.group(0))

        return None

    def _detect_intent(self, text_lower: str) -> Optional[ServiceDefinition]:
        """Detecta intención de configurar un servicio (sin key presente).

        Si el servicio ya tiene su env var configurada, NO intercepta —
        el mensaje debe llegar al LLM para que use el servicio normalmente.
        """
        has_intent = any(phrase in text_lower for phrase in _INTENT_PHRASES)
        if not has_intent:
            return None

        for svc in self._services:
            if any(clue in text_lower for clue in svc.context_clues):
                # Si la key ya está configurada, no interceptar
                existing = os.environ.get(svc.env_var, "").strip()
                if existing:
                    logger.debug(
                        "Servicio %s ya configurado (%s), no se intercepta",
                        svc.display_name, svc.env_var,
                    )
                    continue
                return svc
        return None

    # ── Manejo de key encontrada ──────────────────────────────

    async def _handle_key_found(
        self, svc: ServiceDefinition, key: str
    ) -> InterceptResult:
        """Guarda la key y verifica la conexión."""
        # Guardar siempre
        saved = False
        try:
            from infra.env import save_env_var

            save_env_var(svc.env_var, key)
            saved = True
            logger.info("Credencial guardada: %s", svc.env_var)
        except Exception as exc:
            logger.error("Error guardando credencial %s: %s", svc.env_var, exc)

        # Verificar conexión
        verified = False
        details = ""
        try:
            verified, details = await self._verify_service(svc, key)
        except Exception as exc:
            logger.warning("Error verificando %s: %s", svc.service_id, exc)
            details = str(exc)

        response = self._format_key_response(svc, key, saved, verified, details)
        return InterceptResult(
            intercepted=True,
            response=response,
            service_id=svc.service_id,
            key_saved=saved,
            key_verified=verified,
        )

    # ── Verificación ──────────────────────────────────────────

    async def _verify_service(
        self, svc: ServiceDefinition, key: str
    ) -> Tuple[bool, str]:
        """Verifica la conexión con el servicio. Returns (ok, details)."""
        import httpx

        timeout = httpx.Timeout(10.0)

        if svc.verify_type == "notion":
            return await self._verify_notion(key, svc.verify_url, timeout)
        elif svc.verify_type == "anthropic":
            return await self._verify_anthropic(key, svc.verify_url, timeout)
        elif svc.verify_type == "openai_compat":
            return await self._verify_openai_compat(key, svc.verify_url, timeout)
        elif svc.verify_type == "telegram":
            return await self._verify_telegram(key, timeout)
        elif svc.verify_type == "bearer":
            return await self._verify_bearer(key, svc.verify_url, timeout)
        elif svc.verify_type == "tavily":
            return await self._verify_tavily(key, timeout)
        elif svc.verify_type == "trello":
            return await self._verify_trello(svc, key, timeout)

        return (False, "Tipo de verificacion no soportado")

    async def _verify_notion(
        self, key: str, base_url: str, timeout: Any
    ) -> Tuple[bool, str]:
        import httpx

        headers = {
            "Authorization": f"Bearer {key}",
            "Notion-Version": "2022-06-28",
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            # Verificar autenticación
            resp = await client.get(f"{base_url}/v1/users/me", headers=headers)
            if resp.status_code != 200:
                return (False, f"HTTP {resp.status_code}")

            user_data = resp.json()
            bot_name = user_data.get("name", "Bot")
            owner = user_data.get("bot", {}).get("owner", {})
            owner_name = owner.get("user", {}).get("name", "")

            # Listar bases de datos
            search_resp = await client.post(
                f"{base_url}/v1/search",
                headers=headers,
                json={"filter": {"property": "object", "value": "database"}},
            )
            db_names: List[str] = []
            if search_resp.status_code == 200:
                results = search_resp.json().get("results", [])
                for db in results:
                    title_parts = db.get("title", [])
                    if title_parts:
                        name = title_parts[0].get("plain_text", "")
                        if name:
                            db_names.append(name)

            parts = [f"Bot: {bot_name}"]
            if owner_name:
                parts.append(f"Owner: {owner_name}")
            if db_names:
                parts.append(
                    f"{len(db_names)} base(s) de datos: {', '.join(db_names[:5])}"
                )

            return (True, " | ".join(parts))

    async def _verify_anthropic(
        self, key: str, base_url: str, timeout: Any
    ) -> Tuple[bool, str]:
        import httpx

        headers = {
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{base_url}/v1/models", headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                models = data.get("data", [])
                count = len(models)
                return (True, f"{count} modelo(s) disponibles")
            return (False, f"HTTP {resp.status_code}")

    async def _verify_openai_compat(
        self, key: str, base_url: str, timeout: Any
    ) -> Tuple[bool, str]:
        import httpx

        headers = {"Authorization": f"Bearer {key}"}
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{base_url}/v1/models", headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                models = data.get("data", [])
                count = len(models)
                return (True, f"{count} modelo(s) disponibles")
            return (False, f"HTTP {resp.status_code}")

    async def _verify_telegram(
        self, key: str, timeout: Any
    ) -> Tuple[bool, str]:
        import httpx

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(
                f"https://api.telegram.org/bot{key}/getMe"
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    bot = data.get("result", {})
                    name = bot.get("first_name", "Bot")
                    username = bot.get("username", "")
                    return (True, f"{name} (@{username})")
            return (False, f"HTTP {resp.status_code}")

    async def _verify_bearer(
        self, key: str, base_url: str, timeout: Any
    ) -> Tuple[bool, str]:
        import httpx

        headers = {"Authorization": f"Bearer {key}"}
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{base_url}/whoami-v2", headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                name = data.get("name", data.get("fullname", ""))
                return (True, f"Usuario: {name}" if name else "Conexion OK")
            return (False, f"HTTP {resp.status_code}")

    async def _verify_tavily(
        self, key: str, timeout: Any
    ) -> Tuple[bool, str]:
        import httpx

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={"api_key": key, "query": "test", "max_results": 1},
            )
            if resp.status_code == 200:
                return (True, "Busqueda OK")
            return (False, f"HTTP {resp.status_code}")

    async def _verify_trello(
        self, svc: ServiceDefinition, key: str, timeout: Any
    ) -> Tuple[bool, str]:
        import httpx

        # Trello necesita api_key + token juntos para verificar
        api_key = os.environ.get("TRELLO_API_KEY", "")
        token = os.environ.get("TRELLO_TOKEN", "")
        # Usar el valor recién guardado según qué variable es
        if svc.env_var == "TRELLO_API_KEY":
            api_key = key
        elif svc.env_var == "TRELLO_TOKEN":
            token = key

        if not api_key or not token:
            return (True, "Guardada. Falta el otro valor (key o token) para verificar.")

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(
                f"https://api.trello.com/1/members/me?key={api_key}&token={token}"
            )
            if resp.status_code == 200:
                data = resp.json()
                name = data.get("fullName", data.get("username", ""))
                return (True, f"Usuario: {name}")
            return (False, f"HTTP {resp.status_code}")

    # ── Formateo de respuestas ────────────────────────────────

    @staticmethod
    def _mask_key(key: str) -> str:
        """Enmascara una key mostrando solo inicio y final."""
        if len(key) <= 10:
            return key[:4] + "..."
        return key[:8] + "..." + key[-4:]

    def _format_key_response(
        self,
        svc: ServiceDefinition,
        key: str,
        saved: bool,
        verified: bool,
        details: str,
    ) -> str:
        """Formatea la respuesta mostrando solo el resultado final."""
        masked = self._mask_key(key)

        if not saved:
            return (
                f"No pude guardar la key de {svc.display_name}. "
                f"Intentalo de nuevo o configurala manualmente."
            )

        if verified:
            lines = [f"Listo, {svc.display_name} configurado ({masked})."]
            if details:
                lines.append(details)
            suggestions = _USAGE_SUGGESTIONS.get(svc.service_id)
            if suggestions:
                lines.append("")
                lines.append("Puedes pedirme cosas como:")
                for s in suggestions:
                    lines.append(f'  - "{s}"')
            return "\n".join(lines)

        # Guardada pero no verificada
        return (
            f"Guarde la key de {svc.display_name} ({masked}) "
            f"pero no pude verificar la conexion. "
            f"Revisa que sea correcta."
        )

    def _format_intent_response(self, svc: ServiceDefinition) -> str:
        """Formatea respuesta cuando se detecta intención sin key."""
        example = _KEY_EXAMPLES.get(svc.service_id, "tu-api-key-aqui")

        return (
            f"Para configurar {svc.display_name} necesito tu API key.\n"
            f"Enviamela en un mensaje, por ejemplo:\n"
            f"  {example}"
        )


# ── Datos de respuesta por servicio ───────────────────────────────

_KEY_EXAMPLES: Dict[str, str] = {
    "notion": "ntn_xxxxxxxxxxxx",
    "anthropic": "sk-ant-xxxxxxxxxxxx",
    "openai": "sk-xxxxxxxxxxxx",
    "groq": "gsk_xxxxxxxxxxxx",
    "huggingface": "hf_xxxxxxxxxxxx",
    "telegram": "123456789:ABCdefGHIjklMNOpqrsTUVwxyz",
    "openrouter": "sk-or-v1-xxxxxxxxxxxx",
    "perplexity": "pplx-xxxxxxxxxxxx",
    "xai": "xai-xxxxxxxxxxxx",
    "deepseek": "sk-xxxxxxxxxxxx",
    "mistral": "tu-api-key-de-mistral",
    "together": "tu-api-key-de-together",
    "tavily": "tvly-xxxxxxxxxxxx",
    "trello_key": "tu-api-key-de-32-caracteres-hex",
    "trello_token": "ATTA-tu-token-de-trello",
    "github": "ghp_xxxxxxxxxxxx",
    "gitlab": "glpat-xxxxxxxxxxxx",
}

_USAGE_SUGGESTIONS: Dict[str, List[str]] = {
    "notion": [
        "lista mis paginas de Notion",
        "busca en mi base de datos Tareas",
        "crea una pagina nueva en Notion",
    ],
    "anthropic": [
        "usa Claude para responder",
        "cambia el modelo a claude-sonnet",
    ],
    "openai": [
        "usa GPT para responder",
        "cambia el modelo a gpt-4o",
    ],
    "telegram": [
        "envia un mensaje por Telegram",
    ],
    "groq": [
        "usa Groq para responder mas rapido",
    ],
    "tavily": [
        "busca en internet sobre...",
    ],
    "perplexity": [
        "preguntale a Perplexity sobre...",
    ],
    "trello_key": [
        "muestra mis boards de Trello",
        "lista las tarjetas pendientes",
    ],
    "trello_token": [
        "muestra mis boards de Trello",
        "crea una tarjeta en Trello",
    ],
    "github": [
        "lista mis repos de GitHub",
        "muestra los issues abiertos",
    ],
}
