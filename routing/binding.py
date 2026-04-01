"""Binding management — gestion de vinculaciones agente ↔ ruta.

Portado de OpenClaw: bindings.ts.
Permite vincular agentes a contextos especificos (canal, cuenta,
peer, guild, team, roles) y consultarlos eficientemente.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Set, Tuple

from config.schema import (
    AgentRouteBinding,
    BindingMatchConfig,
    SomerConfig,
)
from routing.keys import (
    DEFAULT_ACCOUNT_ID,
    normalize_account_id,
    normalize_agent_id,
    _normalize_token,
)
from shared.types import ChatType

logger = logging.getLogger(__name__)


# ── Tipos internos ──────────────────────────────────────────

class NormalizedPeerConstraint:
    """Restriccion de peer normalizada."""

    __slots__ = ("state", "kind", "id")

    def __init__(
        self,
        state: str,
        kind: Optional[ChatType] = None,
        id: Optional[str] = None,
    ) -> None:
        self.state = state  # "none" | "invalid" | "valid"
        self.kind = kind
        self.id = id or ""


class NormalizedBindingMatch:
    """Match de binding normalizado."""

    __slots__ = ("account_pattern", "peer", "guild_id", "team_id", "roles")

    def __init__(
        self,
        account_pattern: str,
        peer: NormalizedPeerConstraint,
        guild_id: Optional[str],
        team_id: Optional[str],
        roles: Optional[List[str]],
    ) -> None:
        self.account_pattern = account_pattern
        self.peer = peer
        self.guild_id = guild_id
        self.team_id = team_id
        self.roles = roles


class EvaluatedBinding:
    """Binding evaluado con su match normalizado y orden de fuente."""

    __slots__ = ("binding", "match", "order")

    def __init__(
        self,
        binding: AgentRouteBinding,
        match: NormalizedBindingMatch,
        order: int,
    ) -> None:
        self.binding = binding
        self.match = match
        self.order = order


# ── Normalizacion de ChatType ───────────────────────────────

_CHAT_TYPE_MAP: Dict[str, ChatType] = {
    "direct": ChatType.DIRECT,
    "dm": ChatType.DIRECT,
    "group": ChatType.GROUP,
    "channel": ChatType.CHANNEL,
    "thread": ChatType.THREAD,
}


def normalize_chat_type(value: Optional[str]) -> Optional[ChatType]:
    """Normaliza un string a ChatType."""
    if not value:
        return None
    return _CHAT_TYPE_MAP.get(value.strip().lower())


def _normalize_peer_constraint(
    peer: Optional[BindingMatchConfig],
) -> NormalizedPeerConstraint:
    """Normaliza una restriccion de peer de un binding.

    Portado de OpenClaw: ``normalizePeerConstraint``.
    """
    if peer is None:
        return NormalizedPeerConstraint(state="none")
    # peer aqui es el sub-objeto peer del BindingMatchConfig
    # Lo recibimos como BindingPeerMatch o similar
    return NormalizedPeerConstraint(state="none")


def _normalize_binding_peer(
    peer_config: Optional[object],
) -> NormalizedPeerConstraint:
    """Normaliza peer desde la config de binding."""
    if peer_config is None:
        return NormalizedPeerConstraint(state="none")

    # Acceder a kind e id del peer config
    kind_raw = getattr(peer_config, "kind", None)
    id_raw = getattr(peer_config, "id", None)

    kind = normalize_chat_type(kind_raw)
    peer_id = (str(id_raw).strip() if id_raw else "")

    if not kind or not peer_id:
        return NormalizedPeerConstraint(state="invalid")

    return NormalizedPeerConstraint(state="valid", kind=kind, id=peer_id)


def _normalize_binding_match(
    match: Optional[BindingMatchConfig],
) -> NormalizedBindingMatch:
    """Normaliza los criterios de match de un binding.

    Portado de OpenClaw: ``normalizeBindingMatch``.
    """
    if match is None:
        return NormalizedBindingMatch(
            account_pattern="",
            peer=NormalizedPeerConstraint(state="none"),
            guild_id=None,
            team_id=None,
            roles=None,
        )

    account_pattern = (match.account_id or "").strip()
    peer = _normalize_binding_peer(match.peer)
    guild_id = (str(match.guild_id).strip() if match.guild_id else None) or None
    team_id = (str(match.team_id).strip() if match.team_id else None) or None

    raw_roles = match.roles
    roles = raw_roles if raw_roles and len(raw_roles) > 0 else None

    return NormalizedBindingMatch(
        account_pattern=account_pattern,
        peer=peer,
        guild_id=guild_id,
        team_id=team_id,
        roles=roles,
    )


# ── Indice de bindings ──────────────────────────────────────

class BindingsIndex:
    """Indice optimizado para busqueda rapida de bindings.

    Portado de OpenClaw: ``EvaluatedBindingsIndex``.
    """

    def __init__(self) -> None:
        self.by_peer: Dict[str, List[EvaluatedBinding]] = {}
        self.by_guild_with_roles: Dict[str, List[EvaluatedBinding]] = {}
        self.by_guild: Dict[str, List[EvaluatedBinding]] = {}
        self.by_team: Dict[str, List[EvaluatedBinding]] = {}
        self.by_account: List[EvaluatedBinding] = []
        self.by_channel: List[EvaluatedBinding] = []


def _peer_lookup_keys(kind: ChatType, peer_id: str) -> List[str]:
    """Genera las claves de lookup para un peer.

    ``group`` y ``channel`` son intercambiables en la busqueda.
    """
    if kind == ChatType.GROUP:
        return [f"group:{peer_id}", f"channel:{peer_id}"]
    if kind == ChatType.CHANNEL:
        return [f"channel:{peer_id}", f"group:{peer_id}"]
    return [f"{kind.value}:{peer_id}"]


def _push_to_index_map(
    index_map: Dict[str, List[EvaluatedBinding]],
    key: Optional[str],
    binding: EvaluatedBinding,
) -> None:
    """Agrega un binding a un mapa indexado."""
    if not key:
        return
    if key not in index_map:
        index_map[key] = []
    index_map[key].append(binding)


def _build_bindings_index(bindings: List[EvaluatedBinding]) -> BindingsIndex:
    """Construye un indice de bindings para busqueda rapida.

    Portado de OpenClaw: ``buildEvaluatedBindingsIndex``.
    """
    index = BindingsIndex()

    for evaluated in bindings:
        match = evaluated.match
        # Peer constraint
        if match.peer.state == "valid" and match.peer.kind is not None:
            for key in _peer_lookup_keys(match.peer.kind, match.peer.id):
                _push_to_index_map(index.by_peer, key, evaluated)
            continue

        # Guild + roles
        if match.guild_id and match.roles:
            _push_to_index_map(index.by_guild_with_roles, match.guild_id, evaluated)
            continue

        # Guild sin roles
        if match.guild_id and not match.roles:
            _push_to_index_map(index.by_guild, match.guild_id, evaluated)
            continue

        # Team
        if match.team_id:
            _push_to_index_map(index.by_team, match.team_id, evaluated)
            continue

        # Account-scoped (no wildcard)
        if match.account_pattern != "*":
            index.by_account.append(evaluated)
            continue

        # Channel-level (wildcard)
        index.by_channel.append(evaluated)

    return index


def _collect_peer_indexed_bindings(
    index: BindingsIndex,
    kind: Optional[ChatType],
    peer_id: Optional[str],
) -> List[EvaluatedBinding]:
    """Recolecta bindings que coinciden con un peer."""
    if not kind or not peer_id:
        return []
    out: List[EvaluatedBinding] = []
    seen: Set[int] = set()
    for key in _peer_lookup_keys(kind, peer_id):
        matches = index.by_peer.get(key)
        if not matches:
            continue
        for m in matches:
            oid = id(m)
            if oid not in seen:
                seen.add(oid)
                out.append(m)
    return out


# ── Evaluacion y merge ──────────────────────────────────────

def _resolve_account_pattern_key(account_pattern: str) -> str:
    """Normaliza el patron de account para usar como clave."""
    trimmed = account_pattern.strip()
    if not trimmed:
        return DEFAULT_ACCOUNT_ID
    return normalize_account_id(trimmed)


def _merge_in_source_order(
    account_scoped: List[EvaluatedBinding],
    any_account: List[EvaluatedBinding],
) -> List[EvaluatedBinding]:
    """Mezcla dos listas de bindings manteniendo el orden de fuente.

    Portado de OpenClaw: ``mergeEvaluatedBindingsInSourceOrder``.
    """
    if not account_scoped:
        return any_account
    if not any_account:
        return account_scoped

    merged: List[EvaluatedBinding] = []
    ai = 0
    bi = 0
    while ai < len(account_scoped) and bi < len(any_account):
        if account_scoped[ai].order <= any_account[bi].order:
            merged.append(account_scoped[ai])
            ai += 1
        else:
            merged.append(any_account[bi])
            bi += 1
    merged.extend(account_scoped[ai:])
    merged.extend(any_account[bi:])
    return merged


# ── Binding store ───────────────────────────────────────────

class BindingStore:
    """Almacen y evaluador de bindings de routing.

    Portado de OpenClaw: funciones de bindings.ts + resolve-route.ts.
    Construye indices internos para busqueda eficiente de vinculaciones.

    Uso::

        store = BindingStore(config)
        bindings = store.get_bindings_for("telegram", "my-account")
        index = store.get_index_for("telegram", "my-account")
    """

    def __init__(self, config: SomerConfig) -> None:
        self._config = config
        self._by_channel: Dict[str, _ChannelBindings] = {}
        self._cache: Dict[str, List[EvaluatedBinding]] = {}
        self._index_cache: Dict[str, BindingsIndex] = {}
        self._max_cache_keys = 2000
        self._build_channel_index()

    def _build_channel_index(self) -> None:
        """Pre-procesa bindings agrupados por canal."""
        self._by_channel.clear()
        order = 0
        for binding in self._config.bindings:
            if not binding or not binding.match:
                continue
            channel = _normalize_token(
                binding.match.channel
            )
            if not channel:
                continue

            match = _normalize_binding_match(binding.match)
            evaluated = EvaluatedBinding(binding, match, order)
            order += 1

            if channel not in self._by_channel:
                self._by_channel[channel] = _ChannelBindings()

            bucket = self._by_channel[channel]
            if match.account_pattern == "*":
                bucket.any_account.append(evaluated)
            else:
                key = _resolve_account_pattern_key(match.account_pattern)
                if key not in bucket.by_account:
                    bucket.by_account[key] = []
                bucket.by_account[key].append(evaluated)

    def get_bindings_for(
        self,
        channel: str,
        account_id: str,
    ) -> List[EvaluatedBinding]:
        """Obtiene bindings evaluados para un canal + cuenta.

        Combina bindings especificos de la cuenta con los wildcard (*),
        manteniendo el orden de definicion original.
        """
        cache_key = f"{channel}\t{account_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        channel_bindings = self._by_channel.get(channel)
        account_scoped = (
            channel_bindings.by_account.get(account_id, [])
            if channel_bindings
            else []
        )
        any_account = (
            channel_bindings.any_account if channel_bindings else []
        )
        evaluated = _merge_in_source_order(account_scoped, any_account)

        self._cache[cache_key] = evaluated
        self._index_cache[cache_key] = _build_bindings_index(evaluated)

        if len(self._cache) > self._max_cache_keys:
            self._cache.clear()
            self._index_cache.clear()
            self._cache[cache_key] = evaluated
            self._index_cache[cache_key] = _build_bindings_index(evaluated)

        return evaluated

    def get_index_for(
        self,
        channel: str,
        account_id: str,
    ) -> BindingsIndex:
        """Obtiene el indice de bindings para un canal + cuenta."""
        cache_key = f"{channel}\t{account_id}"
        cached = self._index_cache.get(cache_key)
        if cached is not None:
            return cached

        # Asegurar que los bindings estan evaluados
        self.get_bindings_for(channel, account_id)
        return self._index_cache.get(
            cache_key, BindingsIndex()
        )

    def list_bound_account_ids(self, channel_id: str) -> List[str]:
        """Lista los account_ids vinculados a un canal especifico.

        Portado de OpenClaw: ``listBoundAccountIds``.
        """
        norm_channel = _normalize_token(channel_id)
        if not norm_channel:
            return []
        ids: Set[str] = set()
        for binding in self._config.bindings:
            resolved = self._resolve_normalized_match(binding)
            if resolved and resolved[2] == norm_channel:
                ids.add(resolved[1])
        return sorted(ids)

    def resolve_default_agent_bound_account_id(
        self,
        channel_id: str,
    ) -> Optional[str]:
        """Obtiene el account_id vinculado al agente default para un canal.

        Portado de OpenClaw: ``resolveDefaultAgentBoundAccountId``.
        """
        norm_channel = _normalize_token(channel_id)
        if not norm_channel:
            return None
        default_agent = normalize_agent_id(
            self._config.agents.default
        )
        for binding in self._config.bindings:
            resolved = self._resolve_normalized_match(binding)
            if (
                resolved
                and resolved[2] == norm_channel
                and resolved[0] == default_agent
            ):
                return resolved[1]
        return None

    def build_channel_account_bindings(
        self,
    ) -> Dict[str, Dict[str, List[str]]]:
        """Construye mapa de canal -> agente -> cuentas.

        Portado de OpenClaw: ``buildChannelAccountBindings``.
        """
        result: Dict[str, Dict[str, List[str]]] = {}
        for binding in self._config.bindings:
            resolved = self._resolve_normalized_match(binding)
            if not resolved:
                continue
            agent_id, account_id, channel_id = resolved
            if channel_id not in result:
                result[channel_id] = {}
            by_agent = result[channel_id]
            if agent_id not in by_agent:
                by_agent[agent_id] = []
            if account_id not in by_agent[agent_id]:
                by_agent[agent_id].append(account_id)
        return result

    def _resolve_normalized_match(
        self,
        binding: AgentRouteBinding,
    ) -> Optional[Tuple[str, str, str]]:
        """Normaliza un binding y retorna (agent_id, account_id, channel_id).

        Retorna None si el binding es invalido o no tiene channel/account.
        """
        if not binding or not binding.match:
            return None
        channel_id = _normalize_token(binding.match.channel)
        if not channel_id:
            return None
        account_raw = (binding.match.account_id or "").strip()
        if not account_raw or account_raw == "*":
            return None
        return (
            normalize_agent_id(binding.agent_id),
            normalize_account_id(account_raw),
            channel_id,
        )


class _ChannelBindings:
    """Bindings agrupados por canal, separados por account."""

    __slots__ = ("by_account", "any_account")

    def __init__(self) -> None:
        self.by_account: Dict[str, List[EvaluatedBinding]] = {}
        self.any_account: List[EvaluatedBinding] = []
