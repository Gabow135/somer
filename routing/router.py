"""Message router — resolucion de rutas de mensajes a sesiones y agentes.

Portado de OpenClaw: resolve-route.ts.
Implementa el sistema completo de route resolution con soporte para:
- Bindings jerárquicos (peer → parent_peer → guild+roles → guild → team → account → channel)
- Session keys canonicas (agent:<id>:<rest>)
- DM scope configurable
- Identity links (consolidar peers de distintos canales)
- Cache de rutas resueltas
- Deteccion de ruta default con warning

Jerarquía de resolución (en orden de prioridad):
1. binding.peer — match exacto de peer (group/channel intercambiables)
2. binding.peer.parent — herencia de thread parent
3. binding.guild+roles — match de guild con roles de member
4. binding.guild — match de guild sin roles
5. binding.team — match de team
6. binding.account — match de account (no wildcard)
7. binding.channel — match de canal (wildcard)
8. default — agente por defecto
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from config.schema import SomerConfig
from routing.binding import (
    BindingStore,
    BindingsIndex,
    EvaluatedBinding,
    NormalizedBindingMatch,
    _collect_peer_indexed_bindings,
)
from routing.keys import (
    DEFAULT_AGENT_ID,
    DEFAULT_MAIN_KEY,
    build_agent_main_session_key,
    build_agent_session_key,
    normalize_account_id,
    normalize_agent_id,
    sanitize_agent_id,
    _normalize_id,
    _normalize_token,
)
from routing.ttl import TTLStore
from shared.errors import RoutingError
from shared.types import ChatType, IncomingMessage, RoutePeer

logger = logging.getLogger(__name__)

# ── Constantes ──────────────────────────────────────────────
MAX_ROUTE_CACHE_KEYS = 4000

# ── Tipos ───────────────────────────────────────────────────
MatchedBy = str
"""Tipo de match que resolvio la ruta.

Valores posibles:
- ``binding.peer``
- ``binding.peer.parent``
- ``binding.guild+roles``
- ``binding.guild``
- ``binding.team``
- ``binding.account``
- ``binding.channel``
- ``default``
"""

LastRoutePolicy = str  # "main" | "session"


@dataclass(frozen=True)
class RouteKey:
    """Clave compuesta para identificar una ruta de mensaje.

    Cualquier combinacion de campos identifica un contexto de conversacion
    unico. Los campos son opcionales — se usa lo que este disponible.
    """

    channel_id: Optional[str] = None
    account_id: Optional[str] = None
    peer_id: Optional[str] = None
    group_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not any([self.channel_id, self.account_id, self.peer_id, self.group_id]):
            raise RoutingError("RouteKey necesita al menos un campo no-nulo")

    @property
    def key_str(self) -> str:
        """Representacion string para usar como clave de dict."""
        parts = []
        if self.channel_id:
            parts.append(f"ch:{self.channel_id}")
        if self.account_id:
            parts.append(f"acc:{self.account_id}")
        if self.peer_id:
            parts.append(f"peer:{self.peer_id}")
        if self.group_id:
            parts.append(f"grp:{self.group_id}")
        return "|".join(parts)


@dataclass
class ResolvedRoute:
    """Ruta completamente resuelta.

    Portado de OpenClaw: ``ResolvedAgentRoute``.
    Contiene toda la informacion necesaria para enrutar un mensaje
    a la sesion y agente correctos.
    """

    agent_id: str
    channel: str
    account_id: str
    session_key: str
    main_session_key: str
    last_route_policy: LastRoutePolicy
    matched_by: MatchedBy

    # ── Compat con Route legacy ─────────────────────────────
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    message_count: int = 0


@dataclass
class Route:
    """Ruta legacy simple — mantenida por compatibilidad."""

    route_key: RouteKey
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    agent_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    message_count: int = 0


# ── Helpers ─────────────────────────────────────────────────

def derive_last_route_policy(
    session_key: str,
    main_session_key: str,
) -> LastRoutePolicy:
    """Determina la politica de last-route.

    Portado de OpenClaw: ``deriveLastRoutePolicy``.
    """
    return "main" if session_key == main_session_key else "session"


def resolve_inbound_last_route_session_key(
    policy: LastRoutePolicy,
    main_session_key: str,
    session_key: str,
) -> str:
    """Resuelve la session key para updates de last-route.

    Portado de OpenClaw: ``resolveInboundLastRouteSessionKey``.
    """
    return main_session_key if policy == "main" else session_key


def _peer_kind_matches(binding_kind: ChatType, scope_kind: ChatType) -> bool:
    """Verifica si dos tipos de peer coinciden.

    ``group`` y ``channel`` se consideran equivalentes.
    """
    if binding_kind == scope_kind:
        return True
    both = {binding_kind, scope_kind}
    return ChatType.GROUP in both and ChatType.CHANNEL in both


def _matches_binding_scope(
    match: NormalizedBindingMatch,
    peer: Optional[RoutePeer],
    guild_id: str,
    team_id: str,
    member_role_ids: Set[str],
) -> bool:
    """Verifica si un binding match coincide con el scope actual.

    Portado de OpenClaw: ``matchesBindingScope``.
    """
    # Peer constraint
    if match.peer.state == "invalid":
        return False
    if match.peer.state == "valid" and match.peer.kind is not None:
        if not peer:
            return False
        if not _peer_kind_matches(match.peer.kind, peer.kind):
            return False
        if peer.id != match.peer.id:
            return False

    # Guild constraint
    if match.guild_id and match.guild_id != guild_id:
        return False

    # Team constraint
    if match.team_id and match.team_id != team_id:
        return False

    # Roles constraint (OR: cualquier rol que coincida)
    if match.roles:
        for role in match.roles:
            if role in member_role_ids:
                return True
        return False

    return True


def _format_peer(peer: Optional[RoutePeer]) -> str:
    """Formatea un peer para logging."""
    if not peer or not peer.id:
        return "none"
    return f"{peer.kind.value}:{peer.id}"


def _format_role_ids_cache_key(role_ids: List[str]) -> str:
    """Formatea role_ids para la cache key."""
    count = len(role_ids)
    if count == 0:
        return "-"
    if count == 1:
        return role_ids[0]
    if count == 2:
        a, b = role_ids[0], role_ids[1]
        return f"{a},{b}" if a <= b else f"{b},{a}"
    return ",".join(sorted(role_ids))


def _build_route_cache_key(
    channel: str,
    account_id: str,
    peer: Optional[RoutePeer],
    parent_peer: Optional[RoutePeer],
    guild_id: str,
    team_id: str,
    member_role_ids: List[str],
    dm_scope: str,
) -> str:
    """Construye la clave de cache para una ruta resuelta."""
    return (
        f"{channel}\t{account_id}\t{_format_peer(peer)}\t"
        f"{_format_peer(parent_peer)}\t{guild_id or '-'}\t"
        f"{team_id or '-'}\t{_format_role_ids_cache_key(member_role_ids)}\t"
        f"{dm_scope}"
    )


# ── Agent lookup ────────────────────────────────────────────

class _AgentLookup:
    """Cache de lookup de agentes por ID normalizado.

    Portado de OpenClaw: ``resolveAgentLookupCache``.
    """

    def __init__(self, config: SomerConfig) -> None:
        self._by_normalized: Dict[str, str] = {}
        self._default_agent_id = sanitize_agent_id(
            config.agents.default if config.agents else DEFAULT_AGENT_ID
        )
        agents = config.agents.list if config.agents else []
        for agent in agents:
            raw_id = (agent.id or "").strip()
            if not raw_id:
                continue
            self._by_normalized[normalize_agent_id(raw_id)] = sanitize_agent_id(raw_id)

    def pick_first_existing(self, agent_id: str) -> str:
        """Busca un agente existente por ID, o retorna el default.

        Portado de OpenClaw: ``pickFirstExistingAgentId``.
        """
        trimmed = (agent_id or "").strip()
        if not trimmed:
            return self._default_agent_id
        normalized = normalize_agent_id(trimmed)
        if not self._by_normalized:
            return sanitize_agent_id(trimmed)
        resolved = self._by_normalized.get(normalized)
        if resolved:
            return resolved
        return self._default_agent_id

    @property
    def default_agent_id(self) -> str:
        return self._default_agent_id


# ── Router principal ────────────────────────────────────────

class AgentRouter:
    """Router de agentes con binding resolution completo.

    Portado de OpenClaw: ``resolveAgentRoute``.
    Resuelve mensajes entrantes al agente correcto usando la jerarquia
    de bindings configurada.

    Uso::

        config = SomerConfig(...)
        router = AgentRouter(config)
        route = router.resolve_route(
            channel="telegram",
            account_id="my-bot",
            peer=RoutePeer(kind=ChatType.GROUP, id="12345"),
        )
        print(route.agent_id, route.session_key)
    """

    def __init__(self, config: SomerConfig) -> None:
        self._config = config
        self._binding_store = BindingStore(config)
        self._agent_lookup = _AgentLookup(config)
        self._route_cache: Dict[str, ResolvedRoute] = {}
        self._ttl = TTLStore(
            default_ttl=float(config.sessions.idle_timeout_secs),
        )

    def resolve_route(
        self,
        channel: str,
        account_id: Optional[str] = None,
        peer: Optional[RoutePeer] = None,
        parent_peer: Optional[RoutePeer] = None,
        guild_id: Optional[str] = None,
        team_id: Optional[str] = None,
        member_role_ids: Optional[List[str]] = None,
    ) -> ResolvedRoute:
        """Resuelve la ruta completa para un mensaje entrante.

        Portado de OpenClaw: ``resolveAgentRoute``.
        Evalua los bindings en orden de prioridad jerárquica y retorna
        la primera coincidencia. Si ninguno coincide, usa el agente default.

        Args:
            channel: Nombre del canal (telegram, discord, etc.).
            account_id: ID de la cuenta del bot en el canal.
            peer: Peer destino (tipo + id del chat/grupo).
            parent_peer: Peer padre (para threads).
            guild_id: ID de guild (Discord).
            team_id: ID de team (Slack).
            member_role_ids: IDs de roles del usuario (Discord).

        Returns:
            ``ResolvedRoute`` con agent_id, session_key, matched_by, etc.
        """
        norm_channel = _normalize_token(channel)
        norm_account = normalize_account_id(account_id)
        norm_peer = self._normalize_peer(peer)
        norm_parent = self._normalize_peer(parent_peer)
        norm_guild = _normalize_id(guild_id)
        norm_team = _normalize_id(team_id)
        roles = member_role_ids or []
        role_set = set(roles)
        dm_scope = self._config.dm_scope or "main"
        identity_links = self._config.identity_links or {}

        # ── Cache lookup ────────────────────────────────────
        use_cache = not identity_links
        cache_key = ""
        if use_cache:
            cache_key = _build_route_cache_key(
                norm_channel, norm_account, norm_peer, norm_parent,
                norm_guild, norm_team, roles, dm_scope,
            )
            cached = self._route_cache.get(cache_key)
            if cached is not None:
                return ResolvedRoute(
                    agent_id=cached.agent_id,
                    channel=cached.channel,
                    account_id=cached.account_id,
                    session_key=cached.session_key,
                    main_session_key=cached.main_session_key,
                    last_route_policy=cached.last_route_policy,
                    matched_by=cached.matched_by,
                )

        # ── Obtener bindings evaluados ──────────────────────
        bindings = self._binding_store.get_bindings_for(
            norm_channel, norm_account,
        )
        index = self._binding_store.get_index_for(
            norm_channel, norm_account,
        )

        def choose(agent_id: str, matched_by: MatchedBy) -> ResolvedRoute:
            """Construye la ruta resuelta para un agente."""
            resolved_id = self._agent_lookup.pick_first_existing(agent_id)
            session_key = build_agent_session_key(
                agent_id=resolved_id,
                channel=norm_channel,
                account_id=norm_account,
                peer_kind=norm_peer.kind if norm_peer else None,
                peer_id=norm_peer.id if norm_peer else None,
                dm_scope=dm_scope,
                identity_links=identity_links if identity_links else None,
            ).lower()
            main_key = build_agent_main_session_key(
                resolved_id, DEFAULT_MAIN_KEY,
            ).lower()
            route = ResolvedRoute(
                agent_id=resolved_id,
                channel=norm_channel,
                account_id=norm_account,
                session_key=session_key,
                main_session_key=main_key,
                last_route_policy=derive_last_route_policy(session_key, main_key),
                matched_by=matched_by,
            )
            if use_cache and cache_key:
                self._route_cache[cache_key] = route
                if len(self._route_cache) > MAX_ROUTE_CACHE_KEYS:
                    self._route_cache.clear()
                    self._route_cache[cache_key] = route
            return route

        # ── Evaluacion jerarquica de tiers ──────────────────
        tiers = self._build_tiers(
            index, norm_peer, norm_parent,
            norm_guild, norm_team, roles,
        )

        for tier_matched_by, tier_enabled, scope_peer, candidates, predicate in tiers:
            if not tier_enabled:
                continue
            for candidate in candidates:
                if not predicate(candidate):
                    continue
                if _matches_binding_scope(
                    candidate.match,
                    scope_peer,
                    norm_guild,
                    norm_team,
                    role_set,
                ):
                    logger.debug(
                        "[routing] match: matched_by=%s agent_id=%s",
                        tier_matched_by,
                        candidate.binding.agent_id,
                    )
                    return choose(candidate.binding.agent_id, tier_matched_by)

        # ── Fallback: agente default ────────────────────────
        logger.debug(
            "[routing] default route para channel=%s account=%s peer=%s",
            norm_channel, norm_account, _format_peer(norm_peer),
        )
        return choose(self._agent_lookup.default_agent_id, "default")

    def resolve_from_message(self, message: IncomingMessage) -> ResolvedRoute:
        """Resuelve la ruta desde un IncomingMessage.

        Conveniencia que extrae los campos relevantes del mensaje.
        """
        return self.resolve_route(
            channel=message.channel.value,
            account_id=message.metadata.get("account_id"),
            peer=message.peer,
            parent_peer=message.parent_peer,
            guild_id=message.guild_id,
            team_id=message.team_id,
            member_role_ids=message.member_role_ids,
        )

    def invalidate_cache(self) -> None:
        """Invalida toda la cache de rutas."""
        self._route_cache.clear()

    @property
    def cached_route_count(self) -> int:
        """Cantidad de rutas en cache."""
        return len(self._route_cache)

    # ── Internos ────────────────────────────────────────────

    @staticmethod
    def _normalize_peer(peer: Optional[RoutePeer]) -> Optional[RoutePeer]:
        """Normaliza un peer."""
        if not peer:
            return None
        return RoutePeer(
            kind=peer.kind,
            id=_normalize_id(peer.id),
        )

    @staticmethod
    def _build_tiers(
        index: BindingsIndex,
        peer: Optional[RoutePeer],
        parent_peer: Optional[RoutePeer],
        guild_id: str,
        team_id: str,
        member_role_ids: List[str],
    ) -> List[tuple]:
        """Construye los tiers de evaluacion jerarquica.

        Portado de OpenClaw: array ``tiers`` en ``resolveAgentRoute``.
        Cada tier es: (matched_by, enabled, scope_peer, candidates, predicate).
        """
        tiers = []

        # Tier 1: binding.peer
        tiers.append((
            "binding.peer",
            bool(peer and peer.id),
            peer,
            _collect_peer_indexed_bindings(
                index,
                peer.kind if peer else None,
                peer.id if peer else None,
            ),
            lambda c: c.match.peer.state == "valid",
        ))

        # Tier 2: binding.peer.parent (herencia de thread)
        has_parent = bool(parent_peer and parent_peer.id)
        tiers.append((
            "binding.peer.parent",
            has_parent,
            parent_peer if has_parent else None,
            _collect_peer_indexed_bindings(
                index,
                parent_peer.kind if parent_peer else None,
                parent_peer.id if parent_peer else None,
            ) if has_parent else [],
            lambda c: c.match.peer.state == "valid",
        ))

        # Tier 3: binding.guild+roles
        tiers.append((
            "binding.guild+roles",
            bool(guild_id and member_role_ids),
            peer,
            index.by_guild_with_roles.get(guild_id, []) if guild_id else [],
            lambda c: bool(c.match.guild_id) and bool(c.match.roles),
        ))

        # Tier 4: binding.guild
        tiers.append((
            "binding.guild",
            bool(guild_id),
            peer,
            index.by_guild.get(guild_id, []) if guild_id else [],
            lambda c: bool(c.match.guild_id) and not c.match.roles,
        ))

        # Tier 5: binding.team
        tiers.append((
            "binding.team",
            bool(team_id),
            peer,
            index.by_team.get(team_id, []) if team_id else [],
            lambda c: bool(c.match.team_id),
        ))

        # Tier 6: binding.account
        tiers.append((
            "binding.account",
            True,
            peer,
            index.by_account,
            lambda c: c.match.account_pattern != "*",
        ))

        # Tier 7: binding.channel
        tiers.append((
            "binding.channel",
            True,
            peer,
            index.by_channel,
            lambda c: c.match.account_pattern == "*",
        ))

        return tiers


# ── Legacy MessageRouter (compatibilidad) ───────────────────

class MessageRouter:
    """Router de mensajes basado en claves compuestas.

    Mantenido por compatibilidad con codigo existente.
    Para nuevo codigo, usar ``AgentRouter``.

    Uso::

        router = MessageRouter()
        route = router.resolve_route(channel_id="telegram", peer_id="12345")
        router.bind_agent(route.route_key, "code_agent")
    """

    def __init__(self, session_ttl_secs: float = 3600.0) -> None:
        self._routes: Dict[str, Route] = {}
        self._session_ttl = session_ttl_secs

    def resolve_route(
        self,
        channel_id: Optional[str] = None,
        account_id: Optional[str] = None,
        peer_id: Optional[str] = None,
        group_id: Optional[str] = None,
    ) -> Route:
        """Resuelve o crea una ruta para la combinacion de IDs dada."""
        key = RouteKey(
            channel_id=channel_id,
            account_id=account_id,
            peer_id=peer_id,
            group_id=group_id,
        )
        key_str = key.key_str

        existing = self._routes.get(key_str)
        if existing is not None:
            age = time.time() - existing.last_activity
            if age < self._session_ttl:
                existing.last_activity = time.time()
                existing.message_count += 1
                return existing
            else:
                logger.info("Ruta expirada para %s, creando nueva sesion", key_str)
                del self._routes[key_str]

        route = Route(route_key=key)
        self._routes[key_str] = route
        logger.info(
            "Nueva ruta: %s -> session=%s", key_str, route.session_id[:8]
        )
        return route

    def bind_agent(self, route_key: RouteKey, agent_id: str) -> None:
        """Vincula un agente a una ruta existente."""
        key_str = route_key.key_str
        route = self._routes.get(key_str)
        if route is None:
            raise RoutingError(f"Ruta no encontrada: {key_str}")
        route.agent_id = agent_id
        logger.info("Agente '%s' vinculado a ruta %s", agent_id, key_str)

    def unbind_agent(self, route_key: RouteKey) -> None:
        """Desvincula el agente de una ruta."""
        key_str = route_key.key_str
        route = self._routes.get(key_str)
        if route is None:
            raise RoutingError(f"Ruta no encontrada: {key_str}")
        prev = route.agent_id
        route.agent_id = None
        logger.info("Agente '%s' desvinculado de ruta %s", prev, key_str)

    def list_routes(self) -> List[Route]:
        """Lista todas las rutas activas."""
        return list(self._routes.values())

    def get_route(self, route_key: RouteKey) -> Optional[Route]:
        """Obtiene una ruta por su key, o None si no existe."""
        return self._routes.get(route_key.key_str)

    def remove_route(self, route_key: RouteKey) -> bool:
        """Elimina una ruta. Retorna True si existia."""
        removed = self._routes.pop(route_key.key_str, None)
        return removed is not None

    def cleanup_expired(self) -> int:
        """Elimina rutas expiradas. Retorna cantidad eliminada."""
        now = time.time()
        expired = [
            key_str for key_str, route in self._routes.items()
            if (now - route.last_activity) >= self._session_ttl
        ]
        for key_str in expired:
            del self._routes[key_str]
        if expired:
            logger.info("Eliminadas %d rutas expiradas", len(expired))
        return len(expired)

    @property
    def route_count(self) -> int:
        """Cantidad de rutas activas."""
        return len(self._routes)
