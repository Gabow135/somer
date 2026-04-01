"""Modulo de routing de SOMER 2.0.

Portado de OpenClaw: resolve-route.ts, session-key.ts, bindings.ts, account-id.ts.

Componentes principales:
- ``keys`` — Generacion, parsing y normalizacion de session keys.
- ``binding`` — Gestion de vinculaciones agente ↔ ruta.
- ``ttl`` — Gestion de tiempo de vida para rutas.
- ``router`` — Resolucion completa de rutas (mensaje → agente + sesion).
"""

from routing.binding import BindingStore
from routing.keys import (
    DEFAULT_ACCOUNT_ID,
    DEFAULT_AGENT_ID,
    DEFAULT_MAIN_KEY,
    build_agent_main_session_key,
    build_agent_peer_session_key,
    build_agent_session_key,
    build_group_history_key,
    normalize_account_id,
    normalize_agent_id,
    parse_session_key,
    resolve_thread_session_keys,
    sanitize_agent_id,
)
from routing.router import (
    AgentRouter,
    MessageRouter,
    ResolvedRoute,
    Route,
    RouteKey,
    derive_last_route_policy,
)
from routing.ttl import TTLEntry, TTLStore

__all__ = [
    # Keys
    "DEFAULT_ACCOUNT_ID",
    "DEFAULT_AGENT_ID",
    "DEFAULT_MAIN_KEY",
    "build_agent_main_session_key",
    "build_agent_peer_session_key",
    "build_agent_session_key",
    "build_group_history_key",
    "normalize_account_id",
    "normalize_agent_id",
    "parse_session_key",
    "resolve_thread_session_keys",
    "sanitize_agent_id",
    # Bindings
    "BindingStore",
    # Router
    "AgentRouter",
    "MessageRouter",
    "ResolvedRoute",
    "Route",
    "RouteKey",
    "derive_last_route_policy",
    # TTL
    "TTLEntry",
    "TTLStore",
]
