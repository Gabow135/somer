"""Enrutamiento de mensajes de canales — portado de OpenClaw routing.

Gestiona cómo los mensajes entrantes de los canales se enrutan a sesiones
del agente, con soporte para:
  - Resolución de sesión basada en sender/canal/thread
  - Filtros de allow/deny por canal
  - Enrutamiento a suites específicas
  - Fallback y prioridad de rutas
  - Target resolution para mensajes salientes
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Coroutine,
    Dict,
    List,
    Optional,
    Tuple,
)

from config.schema import SomerConfig
from routing.router import AgentRouter, ResolvedRoute
from shared.types import ChannelType, IncomingMessage, RoutePeer

logger = logging.getLogger(__name__)

# ── Tipos auxiliares ──────────────────────────────────────────

RouteHandler = Callable[[IncomingMessage], Coroutine[Any, Any, str]]


@dataclass
class RouteKey:
    """Clave de enrutamiento para un mensaje entrante.

    Combina canal + usuario + thread para determinar la sesión destino.
    Portado del concepto de session keys de OpenClaw.
    """

    channel: str
    sender_id: str
    thread_id: Optional[str] = None
    guild_id: Optional[str] = None

    @classmethod
    def from_message(cls, message: IncomingMessage) -> RouteKey:
        """Crea un RouteKey desde un IncomingMessage."""
        return cls(
            channel=message.channel.value if isinstance(message.channel, ChannelType) else str(message.channel),
            sender_id=message.channel_user_id,
            thread_id=message.channel_thread_id,
            guild_id=message.guild_id,
        )

    @property
    def session_key(self) -> str:
        """Genera una clave de sesión determinista.

        Formato: ``{channel}:{sender_id}`` o
        ``{channel}:{guild_id}:{thread_id}:{sender_id}`` si hay thread/guild.
        """
        parts = [self.channel]
        if self.guild_id:
            parts.append(self.guild_id)
        if self.thread_id:
            parts.append(self.thread_id)
        parts.append(self.sender_id)
        return ":".join(parts)

    def __hash__(self) -> int:
        return hash(self.session_key)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RouteKey):
            return NotImplemented
        return self.session_key == other.session_key


@dataclass
class RouteResult:
    """Resultado de resolver una ruta.

    Contiene el session_id destino y metadata adicional.
    """

    session_id: str
    route_key: RouteKey
    agent_id: Optional[str] = None
    matched_rule: Optional[str] = None
    created: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RouteRule:
    """Regla de enrutamiento con condiciones y destino.

    Permite definir reglas como:
    - "mensajes de Telegram del usuario X van al agente Y"
    - "mensajes del canal Discord #general van a sesión Z"
    """

    rule_id: str
    priority: int = 0
    channels: Optional[List[str]] = None
    sender_pattern: Optional[str] = None
    thread_pattern: Optional[str] = None
    guild_ids: Optional[List[str]] = None
    agent_id: Optional[str] = None
    session_prefix: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def matches(self, key: RouteKey) -> bool:
        """Verifica si esta regla aplica a un RouteKey dado.

        Args:
            key: Clave de enrutamiento del mensaje.

        Returns:
            True si todas las condiciones de la regla se cumplen.
        """
        # Filtro por canal
        if self.channels and key.channel not in self.channels:
            return False

        # Filtro por sender (regex)
        if self.sender_pattern:
            if not re.match(self.sender_pattern, key.sender_id):
                return False

        # Filtro por thread (regex)
        if self.thread_pattern and key.thread_id:
            if not re.match(self.thread_pattern, key.thread_id):
                return False

        # Filtro por guild
        if self.guild_ids:
            if not key.guild_id or key.guild_id not in self.guild_ids:
                return False

        return True


@dataclass
class OutboundTarget:
    """Destino resuelto para un mensaje saliente.

    Inspirado en OpenClaw ChannelOutboundContext.
    """

    channel_id: str
    to: str
    thread_id: Optional[str] = None
    account_id: Optional[str] = None
    reply_to_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


# ── Filtros allow/deny ────────────────────────────────────────


@dataclass
class ChannelFilter:
    """Filtro de allow/deny para mensajes entrantes por canal.

    Portado del concepto de allowlists de OpenClaw.
    """

    channel: str
    allow_senders: Optional[List[str]] = None
    deny_senders: Optional[List[str]] = None
    allow_guilds: Optional[List[str]] = None
    deny_guilds: Optional[List[str]] = None

    def is_allowed(self, key: RouteKey) -> bool:
        """Verifica si el RouteKey pasa el filtro.

        Lógica: deny tiene precedencia sobre allow.
        Si no hay filtros, todo está permitido.

        Args:
            key: Clave de enrutamiento.

        Returns:
            True si el mensaje está permitido.
        """
        if key.channel != self.channel:
            return True  # No aplica a este canal

        # Deny tiene precedencia
        if self.deny_senders and key.sender_id in self.deny_senders:
            return False
        if self.deny_guilds and key.guild_id and key.guild_id in self.deny_guilds:
            return False

        # Si hay allow-list, debe estar incluido
        if self.allow_senders:
            if key.sender_id not in self.allow_senders:
                return False
        if self.allow_guilds and key.guild_id:
            if key.guild_id not in self.allow_guilds:
                return False

        return True


# ── Router principal ──────────────────────────────────────────


class ChannelRouter:
    """Enruta mensajes entrantes de canales al session manager.

    Funcionalidades completas portadas de OpenClaw:
      - Resolución de sesión por RouteKey
      - Reglas de enrutamiento con prioridad
      - Filtros allow/deny
      - Handler por defecto configurable
      - Cache de sesiones activas con TTL
      - Resolución de targets salientes
    """

    def __init__(
        self,
        handler: RouteHandler,
        *,
        session_ttl_seconds: float = 3600.0,
        default_agent_id: Optional[str] = None,
    ) -> None:
        self._handler = handler
        self._session_ttl = session_ttl_seconds
        self._default_agent_id = default_agent_id

        self._rules: List[RouteRule] = []
        self._filters: List[ChannelFilter] = []
        self._session_cache: Dict[str, Tuple[str, float]] = {}

    # ── Reglas de enrutamiento ────────────────────────────────

    def add_rule(self, rule: RouteRule) -> None:
        """Agrega una regla de enrutamiento y reordena por prioridad.

        Las reglas con mayor prioridad se evalúan primero.

        Args:
            rule: Regla a agregar.
        """
        self._rules.append(rule)
        self._rules.sort(key=lambda r: r.priority, reverse=True)

    def remove_rule(self, rule_id: str) -> bool:
        """Remueve una regla de enrutamiento por ID.

        Returns:
            True si la regla fue encontrada y removida.
        """
        initial = len(self._rules)
        self._rules = [r for r in self._rules if r.rule_id != rule_id]
        return len(self._rules) < initial

    def list_rules(self) -> List[RouteRule]:
        """Lista todas las reglas de enrutamiento."""
        return list(self._rules)

    # ── Filtros ───────────────────────────────────────────────

    def add_filter(self, channel_filter: ChannelFilter) -> None:
        """Agrega un filtro allow/deny."""
        self._filters.append(channel_filter)

    def remove_filter(self, channel: str) -> bool:
        """Remueve filtros de un canal específico.

        Returns:
            True si se removió al menos un filtro.
        """
        initial = len(self._filters)
        self._filters = [f for f in self._filters if f.channel != channel]
        return len(self._filters) < initial

    def is_allowed(self, key: RouteKey) -> bool:
        """Verifica si un RouteKey pasa todos los filtros.

        Args:
            key: Clave de enrutamiento.

        Returns:
            True si el mensaje está permitido por todos los filtros.
        """
        return all(f.is_allowed(key) for f in self._filters)

    # ── Resolución de ruta ────────────────────────────────────

    def _resolve_rule(self, key: RouteKey) -> Optional[RouteRule]:
        """Encuentra la primera regla que coincide con un RouteKey.

        Las reglas se evalúan en orden de prioridad descendente.

        Args:
            key: Clave de enrutamiento.

        Returns:
            La regla que matcheó o None.
        """
        for rule in self._rules:
            if rule.matches(key):
                return rule
        return None

    def _check_session_cache(self, session_key: str) -> Optional[str]:
        """Busca un session_id en cache, respetando TTL.

        Args:
            session_key: Clave de sesión.

        Returns:
            Session ID cacheado o None si expiró/no existe.
        """
        cached = self._session_cache.get(session_key)
        if not cached:
            return None
        session_id, cached_at = cached
        if time.time() - cached_at > self._session_ttl:
            del self._session_cache[session_key]
            return None
        return session_id

    def _cache_session(self, session_key: str, session_id: str) -> None:
        """Guarda un session_id en cache."""
        self._session_cache[session_key] = (session_id, time.time())

    async def route(self, message: IncomingMessage) -> str:
        """Enruta un mensaje entrante y retorna el session_id.

        Flujo de resolución:
        1. Construir RouteKey desde el mensaje
        2. Verificar filtros allow/deny
        3. Buscar en cache de sesiones
        4. Evaluar reglas de enrutamiento
        5. Fallback al handler por defecto

        Args:
            message: Mensaje entrante a enrutar.

        Returns:
            Session ID al que se enrutó el mensaje.

        Raises:
            PermissionError: Si el mensaje es rechazado por filtros.
        """
        key = RouteKey.from_message(message)

        # Verificar filtros
        if not self.is_allowed(key):
            logger.warning(
                "Mensaje rechazado por filtro: canal=%s sender=%s",
                key.channel, key.sender_id,
            )
            raise PermissionError(
                f"Mensaje de {key.sender_id} en {key.channel} rechazado por filtro"
            )

        # Cache
        cached = self._check_session_cache(key.session_key)
        if cached:
            logger.debug(
                "Sesión en cache para %s → %s", key.session_key, cached
            )
            return cached

        # Evaluar reglas
        rule = self._resolve_rule(key)
        if rule and rule.session_prefix:
            session_id = f"{rule.session_prefix}:{key.session_key}"
            self._cache_session(key.session_key, session_id)
            logger.debug(
                "Regla %s matcheó para %s → %s",
                rule.rule_id, key.session_key, session_id,
            )
            return session_id

        # Fallback al handler
        session_id = await self._handler(message)
        self._cache_session(key.session_key, session_id)
        return session_id

    async def resolve_route(self, message: IncomingMessage) -> RouteResult:
        """Resolución completa de ruta con metadata enriquecida.

        Similar a ``route()`` pero retorna un RouteResult con información
        detallada sobre cómo se resolvió la ruta.

        Args:
            message: Mensaje entrante.

        Returns:
            RouteResult con toda la información de enrutamiento.
        """
        key = RouteKey.from_message(message)

        if not self.is_allowed(key):
            raise PermissionError(
                f"Mensaje de {key.sender_id} en {key.channel} rechazado por filtro"
            )

        # Cache check
        cached = self._check_session_cache(key.session_key)
        if cached:
            return RouteResult(
                session_id=cached,
                route_key=key,
                matched_rule="cache",
                created=False,
            )

        # Rule matching
        rule = self._resolve_rule(key)
        if rule:
            prefix = rule.session_prefix or ""
            session_id = f"{prefix}:{key.session_key}" if prefix else key.session_key
            self._cache_session(key.session_key, session_id)
            return RouteResult(
                session_id=session_id,
                route_key=key,
                agent_id=rule.agent_id or self._default_agent_id,
                matched_rule=rule.rule_id,
                created=True,
                metadata=rule.metadata,
            )

        # Handler fallback
        session_id = await self._handler(message)
        self._cache_session(key.session_key, session_id)
        return RouteResult(
            session_id=session_id,
            route_key=key,
            agent_id=self._default_agent_id,
            matched_rule="default_handler",
            created=True,
        )

    # ── Resolución de targets salientes ───────────────────────

    def resolve_outbound_target(
        self,
        channel_id: str,
        to: str,
        *,
        thread_id: Optional[str] = None,
        account_id: Optional[str] = None,
        reply_to_id: Optional[str] = None,
    ) -> OutboundTarget:
        """Resuelve un target para mensaje saliente.

        Portado de OpenClaw ChannelOutboundContext.resolveTarget.

        Args:
            channel_id: ID del canal por el que enviar.
            to: Identificador del destinatario.
            thread_id: ID de thread para respuestas en hilo.
            account_id: ID de la cuenta del canal (multi-account).
            reply_to_id: ID del mensaje al que responder.

        Returns:
            OutboundTarget resuelto.
        """
        return OutboundTarget(
            channel_id=channel_id,
            to=to,
            thread_id=thread_id,
            account_id=account_id,
            reply_to_id=reply_to_id,
        )

    # ── Mantenimiento ─────────────────────────────────────────

    def clear_cache(self) -> int:
        """Limpia toda la cache de sesiones.

        Returns:
            Número de entradas eliminadas.
        """
        count = len(self._session_cache)
        self._session_cache.clear()
        return count

    def evict_expired(self) -> int:
        """Elimina entradas expiradas de la cache.

        Returns:
            Número de entradas eliminadas.
        """
        now = time.time()
        expired = [
            key for key, (_, ts) in self._session_cache.items()
            if now - ts > self._session_ttl
        ]
        for key in expired:
            del self._session_cache[key]
        return len(expired)

    @property
    def cache_size(self) -> int:
        """Número de sesiones en cache."""
        return len(self._session_cache)

    def describe(self) -> Dict[str, Any]:
        """Retorna descripción del router para debug/CLI."""
        return {
            "rules": len(self._rules),
            "filters": len(self._filters),
            "cached_sessions": len(self._session_cache),
            "session_ttl_seconds": self._session_ttl,
            "default_agent_id": self._default_agent_id,
        }


# ── Agent-aware channel router ──────────────────────────────


class AgentChannelRouter:
    """Router de canal con resolucion de agente via bindings.

    Combina el ``ChannelRouter`` existente con el ``AgentRouter``
    para resolver tanto la sesion como el agente destino de un
    mensaje entrante basandose en los bindings configurados.

    Portado de la integracion OpenClaw: resolve-route.ts + channel routing.

    Uso::

        config = SomerConfig(...)
        router = AgentChannelRouter(config, handler=my_handler)

        # Resuelve agente + sesion
        resolved = router.resolve_agent_route(message)
        print(resolved.agent_id, resolved.session_key)

        # Tambien funciona como ChannelRouter clasico
        session_id = await router.route(message)
    """

    def __init__(
        self,
        config: SomerConfig,
        handler: RouteHandler,
        *,
        session_ttl_seconds: float = 3600.0,
    ) -> None:
        self._agent_router = AgentRouter(config)
        self._channel_router = ChannelRouter(
            handler,
            session_ttl_seconds=session_ttl_seconds,
            default_agent_id=config.agents.default if config.agents else None,
        )
        self._config = config

    def resolve_agent_route(
        self,
        message: IncomingMessage,
    ) -> ResolvedRoute:
        """Resuelve la ruta completa (agente + sesion) para un mensaje.

        Usa el sistema de bindings jerárquico del ``AgentRouter``.

        Args:
            message: Mensaje entrante del canal.

        Returns:
            ``ResolvedRoute`` con agent_id, session_key, matched_by, etc.
        """
        key = RouteKey.from_message(message)

        # Verificar filtros allow/deny del ChannelRouter
        if not self._channel_router.is_allowed(key):
            logger.warning(
                "Mensaje rechazado por filtro: canal=%s sender=%s",
                key.channel, key.sender_id,
            )
            raise PermissionError(
                f"Mensaje de {key.sender_id} en {key.channel} rechazado"
            )

        return self._agent_router.resolve_from_message(message)

    async def route(self, message: IncomingMessage) -> str:
        """Enruta un mensaje y retorna el session_id.

        Delega al ChannelRouter clasico.
        """
        return await self._channel_router.route(message)

    async def resolve_route(self, message: IncomingMessage) -> RouteResult:
        """Resolucion completa con metadata enriquecida.

        Combina la resolucion del ChannelRouter con la del AgentRouter.
        """
        # Resolver agente via bindings
        agent_route = self._agent_router.resolve_from_message(message)

        # Resolver sesion via channel router
        channel_result = await self._channel_router.resolve_route(message)

        # Enriquecer con info del agent route
        channel_result.agent_id = agent_route.agent_id
        channel_result.metadata["session_key"] = agent_route.session_key
        channel_result.metadata["matched_by"] = agent_route.matched_by
        channel_result.metadata["last_route_policy"] = agent_route.last_route_policy

        return channel_result

    # ── Delegacion de metodos del ChannelRouter ──────────────

    def add_rule(self, rule: RouteRule) -> None:
        """Agrega una regla de enrutamiento."""
        self._channel_router.add_rule(rule)

    def remove_rule(self, rule_id: str) -> bool:
        """Remueve una regla por ID."""
        return self._channel_router.remove_rule(rule_id)

    def add_filter(self, channel_filter: ChannelFilter) -> None:
        """Agrega un filtro allow/deny."""
        self._channel_router.add_filter(channel_filter)

    def invalidate_cache(self) -> None:
        """Invalida cache de ambos routers."""
        self._channel_router.clear_cache()
        self._agent_router.invalidate_cache()

    @property
    def agent_router(self) -> AgentRouter:
        """Acceso directo al AgentRouter."""
        return self._agent_router

    @property
    def channel_router(self) -> ChannelRouter:
        """Acceso directo al ChannelRouter."""
        return self._channel_router
