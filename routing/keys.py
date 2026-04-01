"""Session key — generacion, parsing y normalizacion de claves de sesion.

Portado de OpenClaw: session-key.ts + account-id.ts.
Formato canonico: ``agent:<agent_id>:<rest>``
"""

from __future__ import annotations

import re
import logging
from typing import Dict, List, Optional

from shared.types import ChatType

logger = logging.getLogger(__name__)

# ── Constantes ──────────────────────────────────────────────
DEFAULT_AGENT_ID = "main"
DEFAULT_ACCOUNT_ID = "default"
DEFAULT_MAIN_KEY = "main"

# ── Regex pre-compiladas ────────────────────────────────────
_VALID_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$", re.IGNORECASE)
_INVALID_CHARS_RE = re.compile(r"[^a-z0-9_-]+")
_LEADING_DASH_RE = re.compile(r"^-+")
_TRAILING_DASH_RE = re.compile(r"-+$")
_AGENT_KEY_RE = re.compile(r"^agent:([^:]+):(.+)$", re.IGNORECASE)

# ── Blocked keys (proteccion proto) ─────────────────────────
_BLOCKED_KEYS = frozenset({
    "__proto__", "constructor", "prototype",
    "hasOwnProperty", "isPrototypeOf", "toString",
    "valueOf", "toLocaleString", "propertyIsEnumerable",
})

# ── Cache con tamano limitado ───────────────────────────────
_CACHE_MAX = 512
_account_id_cache: Dict[str, str] = {}


def _set_cache(cache: Dict[str, str], key: str, value: str) -> None:
    """Inserta en cache con eviccion LRU simplificada."""
    cache[key] = value
    if len(cache) > _CACHE_MAX:
        oldest = next(iter(cache))
        del cache[oldest]


# ── Normalizacion ───────────────────────────────────────────

def _normalize_token(value: Optional[str]) -> str:
    """Normaliza un token a minusculas sin espacios."""
    return (value or "").strip().lower()


def _normalize_id(value: object) -> str:
    """Normaliza un ID numerico o string."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(int(value)).strip()
    return ""


def _canonicalize_id(value: str) -> str:
    """Canonicaliza un ID: minusculas, caracteres invalidos -> guion."""
    if _VALID_ID_RE.match(value):
        return value.lower()
    result = _INVALID_CHARS_RE.sub("-", value.lower())
    result = _LEADING_DASH_RE.sub("", result)
    result = _TRAILING_DASH_RE.sub("", result)
    return result[:64]


def normalize_agent_id(value: Optional[str]) -> str:
    """Normaliza un agent_id a formato seguro para rutas.

    Portado de OpenClaw: ``normalizeAgentId``.

    Args:
        value: ID del agente (puede ser None o vacio).

    Returns:
        ID normalizado o ``DEFAULT_AGENT_ID`` si vacio.
    """
    trimmed = (value or "").strip()
    if not trimmed:
        return DEFAULT_AGENT_ID
    if _VALID_ID_RE.match(trimmed):
        return trimmed.lower()
    return _canonicalize_id(trimmed) or DEFAULT_AGENT_ID


def sanitize_agent_id(value: Optional[str]) -> str:
    """Alias de ``normalize_agent_id``."""
    return normalize_agent_id(value)


def is_valid_agent_id(value: Optional[str]) -> bool:
    """Verifica si un agent_id es valido."""
    trimmed = (value or "").strip()
    return bool(trimmed) and bool(_VALID_ID_RE.match(trimmed))


def normalize_account_id(value: Optional[str]) -> str:
    """Normaliza un account_id.

    Portado de OpenClaw: ``normalizeAccountId`` en account-id.ts.

    Args:
        value: ID de cuenta (puede ser None o vacio).

    Returns:
        ID normalizado o ``DEFAULT_ACCOUNT_ID``.
    """
    trimmed = (value or "").strip()
    if not trimmed:
        return DEFAULT_ACCOUNT_ID
    cached = _account_id_cache.get(trimmed)
    if cached is not None:
        return cached
    canonical = _canonicalize_id(trimmed)
    if not canonical or canonical in _BLOCKED_KEYS:
        result = DEFAULT_ACCOUNT_ID
    else:
        result = canonical
    _set_cache(_account_id_cache, trimmed, result)
    return result


def normalize_optional_account_id(value: Optional[str]) -> Optional[str]:
    """Normaliza un account_id, retornando None si esta vacio."""
    trimmed = (value or "").strip()
    if not trimmed:
        return None
    canonical = _canonicalize_id(trimmed)
    if not canonical or canonical in _BLOCKED_KEYS:
        return None
    return canonical


def normalize_main_key(value: Optional[str]) -> str:
    """Normaliza la main key."""
    trimmed = (value or "").strip()
    return trimmed.lower() if trimmed else DEFAULT_MAIN_KEY


# ── Parsing de session keys ─────────────────────────────────

class ParsedSessionKey:
    """Session key parseada en componentes.

    Formato: ``agent:<agent_id>:<rest>``
    """

    __slots__ = ("agent_id", "rest")

    def __init__(self, agent_id: str, rest: str) -> None:
        self.agent_id = agent_id
        self.rest = rest

    def __repr__(self) -> str:
        return f"ParsedSessionKey(agent_id={self.agent_id!r}, rest={self.rest!r})"


def parse_session_key(value: Optional[str]) -> Optional[ParsedSessionKey]:
    """Parsea una session key en formato ``agent:<id>:<rest>``.

    Portado de OpenClaw: ``parseAgentSessionKey``.

    Returns:
        ``ParsedSessionKey`` si el formato es valido, ``None`` si no.
    """
    raw = (value or "").strip()
    if not raw:
        return None
    match = _AGENT_KEY_RE.match(raw)
    if not match:
        return None
    return ParsedSessionKey(agent_id=match.group(1), rest=match.group(2))


def resolve_agent_id_from_session_key(session_key: Optional[str]) -> str:
    """Extrae el agent_id de una session key."""
    parsed = parse_session_key(session_key)
    return normalize_agent_id(parsed.agent_id if parsed else DEFAULT_AGENT_ID)


# ── Tipos de session key ────────────────────────────────────

SessionKeyShape = str  # "missing" | "agent" | "legacy_or_alias" | "malformed_agent"


def classify_session_key_shape(session_key: Optional[str]) -> SessionKeyShape:
    """Clasifica la forma de una session key.

    Returns:
        ``"missing"``, ``"agent"``, ``"legacy_or_alias"`` o ``"malformed_agent"``.
    """
    raw = (session_key or "").strip()
    if not raw:
        return "missing"
    if parse_session_key(raw) is not None:
        return "agent"
    return "malformed_agent" if raw.lower().startswith("agent:") else "legacy_or_alias"


# ── Construccion de session keys ────────────────────────────

def build_agent_main_session_key(
    agent_id: str,
    main_key: Optional[str] = None,
) -> str:
    """Construye la session key principal de un agente.

    Formato: ``agent:<agent_id>:<main_key>``

    Portado de OpenClaw: ``buildAgentMainSessionKey``.
    """
    norm_agent = normalize_agent_id(agent_id)
    norm_main = normalize_main_key(main_key)
    return f"agent:{norm_agent}:{norm_main}"


def _resolve_linked_peer_id(
    identity_links: Optional[Dict[str, List[str]]],
    channel: str,
    peer_id: str,
) -> Optional[str]:
    """Resuelve un peer_id alternativo via identity links.

    Portado de OpenClaw: ``resolveLinkedPeerId``.
    Si el peer_id aparece en algun grupo de identidad, retorna
    el nombre canonico de ese grupo.
    """
    if not identity_links:
        return None
    trimmed = peer_id.strip()
    if not trimmed:
        return None
    candidates = set()
    raw = _normalize_token(trimmed)
    if raw:
        candidates.add(raw)
    norm_channel = _normalize_token(channel)
    if norm_channel:
        scoped = _normalize_token(f"{norm_channel}:{trimmed}")
        if scoped:
            candidates.add(scoped)
    if not candidates:
        return None
    for canonical, ids in identity_links.items():
        canonical_name = canonical.strip()
        if not canonical_name:
            continue
        if not isinstance(ids, list):
            continue
        for id_val in ids:
            normalized = _normalize_token(str(id_val))
            if normalized and normalized in candidates:
                return canonical_name
    return None


def build_agent_peer_session_key(
    agent_id: str,
    channel: str,
    account_id: Optional[str] = None,
    peer_kind: Optional[ChatType] = None,
    peer_id: Optional[str] = None,
    main_key: Optional[str] = None,
    dm_scope: str = "main",
    identity_links: Optional[Dict[str, List[str]]] = None,
) -> str:
    """Construye la session key completa para un peer.

    Portado de OpenClaw: ``buildAgentPeerSessionKey``.
    Soporta distintos modos de DM scope:
    - ``main``: sesion unica por agente.
    - ``per-peer``: sesion por peer_id.
    - ``per-channel-peer``: sesion por canal + peer_id.
    - ``per-account-channel-peer``: sesion por account + canal + peer_id.

    Para peers de tipo group/channel, siempre genera key con canal.
    """
    kind = peer_kind or ChatType.DIRECT
    norm_agent = normalize_agent_id(agent_id)

    if kind == ChatType.DIRECT:
        pid = (peer_id or "").strip()

        # Resolver identity links si aplica
        if dm_scope != "main":
            linked = _resolve_linked_peer_id(identity_links, channel, pid)
            if linked:
                pid = linked

        pid = pid.lower()
        norm_channel = _normalize_token(channel) or "unknown"
        norm_account = normalize_account_id(account_id)

        if dm_scope == "per-account-channel-peer" and pid:
            return f"agent:{norm_agent}:{norm_channel}:{norm_account}:direct:{pid}"
        if dm_scope == "per-channel-peer" and pid:
            return f"agent:{norm_agent}:{norm_channel}:direct:{pid}"
        if dm_scope == "per-peer" and pid:
            return f"agent:{norm_agent}:direct:{pid}"
        # Fallback: main session
        return build_agent_main_session_key(agent_id, main_key)

    # Group / Channel / Thread
    norm_channel = _normalize_token(channel) or "unknown"
    norm_peer_id = ((peer_id or "").strip() or "unknown").lower()
    return f"agent:{norm_agent}:{norm_channel}:{kind.value}:{norm_peer_id}"


def build_agent_session_key(
    agent_id: str,
    channel: str,
    account_id: Optional[str] = None,
    peer_kind: Optional[ChatType] = None,
    peer_id: Optional[str] = None,
    dm_scope: str = "main",
    identity_links: Optional[Dict[str, List[str]]] = None,
) -> str:
    """Wrapper principal para construir session keys.

    Portado de OpenClaw: ``buildAgentSessionKey``.
    """
    norm_channel = _normalize_token(channel) or "unknown"
    return build_agent_peer_session_key(
        agent_id=agent_id,
        channel=norm_channel,
        account_id=account_id,
        peer_kind=peer_kind,
        peer_id=_normalize_id(peer_id) or None if peer_id else None,
        main_key=DEFAULT_MAIN_KEY,
        dm_scope=dm_scope,
        identity_links=identity_links,
    )


# ── Conversion entre keys de request/store ──────────────────

def to_agent_request_session_key(store_key: Optional[str]) -> Optional[str]:
    """Convierte una store key a request key (quita prefijo ``agent:<id>:``)."""
    raw = (store_key or "").strip()
    if not raw:
        return None
    parsed = parse_session_key(raw)
    return parsed.rest if parsed else raw


def to_agent_store_session_key(
    agent_id: str,
    request_key: Optional[str],
    main_key: Optional[str] = None,
) -> str:
    """Convierte una request key a store key (agrega prefijo ``agent:<id>:``)."""
    raw = (request_key or "").strip()
    if not raw or raw.lower() == DEFAULT_MAIN_KEY:
        return build_agent_main_session_key(agent_id, main_key)
    parsed = parse_session_key(raw)
    if parsed:
        return f"agent:{parsed.agent_id}:{parsed.rest}"
    lowered = raw.lower()
    if lowered.startswith("agent:"):
        return lowered
    return f"agent:{normalize_agent_id(agent_id)}:{lowered}"


# ── Group history key ───────────────────────────────────────

def build_group_history_key(
    channel: str,
    peer_kind: str,
    peer_id: str,
    account_id: Optional[str] = None,
) -> str:
    """Construye la clave de historial para un grupo/canal.

    Portado de OpenClaw: ``buildGroupHistoryKey``.
    """
    norm_channel = _normalize_token(channel) or "unknown"
    norm_account = normalize_account_id(account_id)
    norm_peer = (peer_id.strip().lower()) or "unknown"
    return f"{norm_channel}:{norm_account}:{peer_kind}:{norm_peer}"


# ── Thread session keys ────────────────────────────────────

def resolve_thread_session_keys(
    base_session_key: str,
    thread_id: Optional[str] = None,
    parent_session_key: Optional[str] = None,
    use_suffix: bool = True,
) -> Dict[str, Optional[str]]:
    """Resuelve session keys para threads.

    Portado de OpenClaw: ``resolveThreadSessionKeys``.

    Returns:
        Dict con ``session_key`` y opcionalmente ``parent_session_key``.
    """
    tid = (thread_id or "").strip()
    if not tid:
        return {"session_key": base_session_key, "parent_session_key": None}
    normalized_tid = tid.lower()
    session_key = (
        f"{base_session_key}:thread:{normalized_tid}"
        if use_suffix
        else base_session_key
    )
    return {"session_key": session_key, "parent_session_key": parent_session_key}


# ── Utilidades de session keys especiales ───────────────────

def is_cron_session_key(session_key: Optional[str]) -> bool:
    """Verifica si una session key corresponde a un cron job."""
    parsed = parse_session_key(session_key)
    if not parsed:
        return False
    return parsed.rest.startswith("cron:")


def is_subagent_session_key(session_key: Optional[str]) -> bool:
    """Verifica si una session key corresponde a un sub-agente."""
    parsed = parse_session_key(session_key)
    if not parsed:
        return False
    return ":sub:" in parsed.rest


def get_subagent_depth(session_key: Optional[str]) -> int:
    """Cuenta la profundidad de sub-agente en una session key."""
    parsed = parse_session_key(session_key)
    if not parsed:
        return 0
    return parsed.rest.count(":sub:")
