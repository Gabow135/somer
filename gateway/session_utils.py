"""Utilidades de sesión para el Gateway — portado de OpenClaw.

Maneja resolución de session keys, metadata de sesiones,
mapeo conexión-sesión, validación, cleanup y listado.

Ref: OpenClaw src/gateway/session-utils.ts,
     src/gateway/session-utils.types.ts,
     src/routing/session-key.ts
"""

from __future__ import annotations

import json
import logging
import re
import time
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Set, Tuple

from pydantic import BaseModel, Field

from shared.constants import DEFAULT_SESSIONS_DIR
from shared.types import ChannelType, SessionStatus

logger = logging.getLogger(__name__)


# ── Constantes ───────────────────────────────────────────────

DERIVED_TITLE_MAX_LEN = 60
DEFAULT_AGENT_ID = "default"
SESSION_KEY_SEPARATOR = ":"


# ── Tipos de fila de sesión (GatewaySessionRow) ──────────────
# Portado de OpenClaw: session-utils.types.ts

class SessionKind(str, Enum):
    """Tipo de sesión según su clave."""

    DIRECT = "direct"
    GROUP = "group"
    GLOBAL = "global"
    UNKNOWN = "unknown"


class SessionRunStatus(str, Enum):
    """Estado de ejecución de una sesión."""

    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    KILLED = "killed"
    TIMEOUT = "timeout"


class GatewaySessionsDefaults(BaseModel):
    """Valores por defecto para sesiones del gateway."""

    model_provider: Optional[str] = None
    model: Optional[str] = None
    context_tokens: Optional[int] = None


class GatewaySessionRow(BaseModel):
    """Fila completa de una sesión para el gateway.

    Portado de OpenClaw: GatewaySessionRow en session-utils.types.ts.
    Representa la vista enriquecida de una sesión con todos los campos
    resueltos para la UI y API del gateway.
    """

    key: str
    spawned_by: Optional[str] = None
    kind: SessionKind = SessionKind.DIRECT
    label: Optional[str] = None
    display_name: Optional[str] = None
    derived_title: Optional[str] = None
    last_message_preview: Optional[str] = None
    channel: Optional[str] = None
    subject: Optional[str] = None
    group_channel: Optional[str] = None
    space: Optional[str] = None
    chat_type: Optional[str] = None
    origin: Optional[Dict[str, Any]] = None
    updated_at: Optional[float] = None
    session_id: Optional[str] = None
    system_sent: Optional[bool] = None
    aborted_last_run: Optional[bool] = None
    thinking_level: Optional[str] = None
    verbose_level: Optional[str] = None
    reasoning_level: Optional[str] = None
    elevated_level: Optional[str] = None
    send_policy: Optional[Literal["allow", "deny"]] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    total_tokens_fresh: Optional[bool] = None
    estimated_cost_usd: Optional[float] = None
    status: Optional[SessionRunStatus] = None
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    runtime_ms: Optional[float] = None
    parent_session_key: Optional[str] = None
    child_sessions: Optional[List[str]] = None
    response_usage: Optional[Literal["on", "off", "tokens", "full"]] = None
    model_provider: Optional[str] = None
    model: Optional[str] = None
    context_tokens: Optional[int] = None
    last_channel: Optional[str] = None
    last_to: Optional[str] = None
    last_account_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class GatewayAgentRow(BaseModel):
    """Fila de un agente para el gateway.

    Portado de OpenClaw: GatewayAgentRow.
    """

    id: str
    name: Optional[str] = None
    identity: Optional[Dict[str, Any]] = None


class SessionsListResult(BaseModel):
    """Resultado de sessions.list."""

    ts: float = Field(default_factory=time.time)
    path: str = ""
    count: int = 0
    defaults: GatewaySessionsDefaults = Field(
        default_factory=GatewaySessionsDefaults
    )
    sessions: List[GatewaySessionRow] = Field(default_factory=list)


class SessionsPatchResult(BaseModel):
    """Resultado de sessions.patch."""

    ok: bool = True
    key: str = ""
    resolved: Optional[Dict[str, str]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SessionPreviewItem(BaseModel):
    """Un item de preview de sesión."""

    role: Literal["user", "assistant", "tool", "system", "other"]
    text: str


class SessionsPreviewEntry(BaseModel):
    """Entrada de preview para una sesión."""

    key: str
    status: Literal["ok", "empty", "missing", "error"] = "ok"
    items: List[SessionPreviewItem] = Field(default_factory=list)


class SessionsPreviewResult(BaseModel):
    """Resultado de sessions.preview."""

    ts: float = Field(default_factory=time.time)
    previews: List[SessionsPreviewEntry] = Field(default_factory=list)


# ── Entrada de sesión en store ───────────────────────────────

class SessionEntry(BaseModel):
    """Entrada de sesión en el store persistente.

    Equivalente a SessionEntry de OpenClaw (config/sessions.ts).
    """

    session_id: Optional[str] = None
    session_file: Optional[str] = None
    display_name: Optional[str] = None
    label: Optional[str] = None
    subject: Optional[str] = None
    channel: Optional[str] = None
    group_channel: Optional[str] = None
    space: Optional[str] = None
    chat_type: Optional[str] = None
    origin: Optional[Dict[str, Any]] = None
    status: Optional[str] = None
    model: Optional[str] = None
    model_provider: Optional[str] = None
    model_override: Optional[str] = None
    provider_override: Optional[str] = None
    spawned_by: Optional[str] = None
    parent_session_key: Optional[str] = None
    system_sent: Optional[bool] = None
    aborted_last_run: Optional[bool] = None
    thinking_level: Optional[str] = None
    verbose_level: Optional[str] = None
    reasoning_level: Optional[str] = None
    elevated_level: Optional[str] = None
    send_policy: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    context_tokens: Optional[int] = None
    estimated_cost_usd: Optional[float] = None
    cache_read: Optional[int] = None
    cache_write: Optional[int] = None
    response_usage: Optional[str] = None
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    runtime_ms: Optional[float] = None
    last_channel: Optional[str] = None
    last_to: Optional[str] = None
    last_account_id: Optional[str] = None
    created_at: Optional[float] = None
    updated_at: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ── Resolución de session keys ───────────────────────────────
# Portado de OpenClaw: session-utils.ts + routing/session-key.ts

def normalize_agent_id(agent_id: str) -> str:
    """Normaliza un agent ID a lowercase sin espacios."""
    return agent_id.strip().lower()


def normalize_main_key(main_key: Optional[str]) -> str:
    """Normaliza la clave de sesión principal."""
    if not main_key or not main_key.strip():
        return "work"
    return main_key.strip().lower()


def parse_agent_session_key(
    key: str,
) -> Optional[Tuple[str, str]]:
    """Parsea una clave de sesión con formato agent:<agentId>:<rest>.

    Retorna (agent_id, rest) o None si no tiene formato de agente.
    """
    lower = key.lower().strip()
    if not lower.startswith("agent:"):
        return None
    parts = lower.split(":", 2)
    if len(parts) < 3:
        return None
    return (parts[1], parts[2])


def canonicalize_session_key_for_agent(agent_id: str, key: str) -> str:
    """Canonicaliza una clave de sesión para un agente específico.

    Portado de OpenClaw: canonicalizeSessionKeyForAgent()
    """
    lowered = key.lower().strip()
    if lowered in ("global", "unknown"):
        return lowered
    if lowered.startswith("agent:"):
        return lowered
    return f"agent:{normalize_agent_id(agent_id)}:{lowered}"


def resolve_session_store_key(
    session_key: str,
    default_agent_id: str = DEFAULT_AGENT_ID,
    main_key: str = "work",
) -> str:
    """Resuelve la clave canónica de store para una sesión.

    Portado de OpenClaw: resolveSessionStoreKey()
    """
    raw = session_key.strip()
    if not raw:
        return raw
    raw_lower = raw.lower()
    if raw_lower in ("global", "unknown"):
        return raw_lower

    parsed = parse_agent_session_key(raw)
    if parsed:
        return raw_lower

    # Sesión "main" se resuelve a la clave principal configurada
    if raw_lower == "main" or raw_lower == main_key:
        agent_id = normalize_agent_id(default_agent_id)
        return f"agent:{agent_id}:{main_key}"

    agent_id = normalize_agent_id(default_agent_id)
    return canonicalize_session_key_for_agent(agent_id, raw_lower)


def resolve_session_store_agent_id(
    canonical_key: str,
    default_agent_id: str = DEFAULT_AGENT_ID,
) -> str:
    """Resuelve el agent ID desde una clave canónica de sesión.

    Portado de OpenClaw: resolveSessionStoreAgentId()
    """
    if canonical_key in ("global", "unknown"):
        return normalize_agent_id(default_agent_id)
    parsed = parse_agent_session_key(canonical_key)
    if parsed:
        return normalize_agent_id(parsed[0])
    return normalize_agent_id(default_agent_id)


# ── Clasificación de sesiones ────────────────────────────────

def classify_session_key(
    key: str, entry: Optional[SessionEntry] = None
) -> SessionKind:
    """Clasifica una clave de sesión según su tipo.

    Portado de OpenClaw: classifySessionKey()
    """
    if key == "global":
        return SessionKind.GLOBAL
    if key == "unknown":
        return SessionKind.UNKNOWN
    if entry:
        if entry.chat_type in ("group", "channel"):
            return SessionKind.GROUP
    if ":group:" in key or ":channel:" in key:
        return SessionKind.GROUP
    return SessionKind.DIRECT


def parse_group_key(
    key: str,
) -> Optional[Dict[str, Optional[str]]]:
    """Parsea una clave de sesión de grupo.

    Portado de OpenClaw: parseGroupKey()
    Retorna {channel, kind, id} o None.
    """
    parsed = parse_agent_session_key(key)
    raw_key = parsed[1] if parsed else key
    parts = [p for p in raw_key.split(":") if p]
    if len(parts) >= 3:
        channel = parts[0]
        kind = parts[1]
        if kind in ("group", "channel"):
            id_part = ":".join(parts[2:])
            return {"channel": channel, "kind": kind, "id": id_part}
    return None


# ── Derivación de títulos ────────────────────────────────────

def truncate_title(text: str, max_len: int) -> str:
    """Trunca un título a un largo máximo con elipsis.

    Portado de OpenClaw: truncateTitle()
    """
    if len(text) <= max_len:
        return text
    cut = text[: max_len - 1]
    last_space = cut.rfind(" ")
    if last_space > max_len * 0.6:
        return cut[:last_space] + "\u2026"
    return cut + "\u2026"


def format_session_id_prefix(
    session_id: str, updated_at: Optional[float] = None
) -> str:
    """Formatea un prefijo legible para un session ID.

    Portado de OpenClaw: formatSessionIdPrefix()
    """
    prefix = session_id[:8]
    if updated_at and updated_at > 0:
        import datetime

        dt = datetime.datetime.fromtimestamp(
            updated_at / 1000 if updated_at > 1e12 else updated_at,
            tz=datetime.timezone.utc,
        )
        date_str = dt.strftime("%Y-%m-%d")
        return f"{prefix} ({date_str})"
    return prefix


def derive_session_title(
    entry: Optional[SessionEntry],
    first_user_message: Optional[str] = None,
) -> Optional[str]:
    """Deriva un título para una sesión.

    Portado de OpenClaw: deriveSessionTitle()
    Prioridad: displayName → subject → primer mensaje de usuario → session ID.
    """
    if not entry:
        return None

    if entry.display_name and entry.display_name.strip():
        return entry.display_name.strip()

    if entry.subject and entry.subject.strip():
        return entry.subject.strip()

    if first_user_message and first_user_message.strip():
        normalized = re.sub(r"\s+", " ", first_user_message).strip()
        return truncate_title(normalized, DERIVED_TITLE_MAX_LEN)

    if entry.session_id:
        return format_session_id_prefix(entry.session_id, entry.updated_at)

    return None


# ── Store de sesiones ────────────────────────────────────────

class SessionStore:
    """Store de sesiones en disco (JSONL).

    Portado y extendido de OpenClaw: loadSessionStore() + saveSessionStore().
    Provee operaciones CRUD sobre sesiones con persistencia JSONL.
    """

    def __init__(self, sessions_dir: Optional[Path] = None) -> None:
        self._dir = sessions_dir or DEFAULT_SESSIONS_DIR
        self._entries: Dict[str, SessionEntry] = {}
        self._loaded = False

    @property
    def directory(self) -> Path:
        """Directorio del store."""
        return self._dir

    def ensure_dir(self) -> None:
        """Asegura que el directorio existe."""
        self._dir.mkdir(parents=True, exist_ok=True)

    def load(self) -> Dict[str, SessionEntry]:
        """Carga todas las entradas del store desde el índice."""
        index_path = self._dir / "_sessions.json"
        if index_path.exists():
            try:
                raw = json.loads(index_path.read_text(encoding="utf-8"))
                self._entries = {
                    k: SessionEntry.model_validate(v)
                    for k, v in raw.items()
                    if isinstance(v, dict)
                }
            except Exception as exc:
                logger.warning("Error cargando session store: %s", exc)
                self._entries = {}
        self._loaded = True
        return self._entries

    def save(self) -> None:
        """Persiste el store al disco."""
        self.ensure_dir()
        index_path = self._dir / "_sessions.json"
        data = {
            k: v.model_dump(exclude_none=True) for k, v in self._entries.items()
        }
        index_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def get(self, key: str) -> Optional[SessionEntry]:
        """Obtiene una entrada por clave."""
        if not self._loaded:
            self.load()
        return self._entries.get(key)

    def set(self, key: str, entry: SessionEntry) -> None:
        """Establece una entrada."""
        if not self._loaded:
            self.load()
        self._entries[key] = entry

    def delete(self, key: str) -> bool:
        """Elimina una entrada."""
        if not self._loaded:
            self.load()
        if key in self._entries:
            del self._entries[key]
            return True
        return False

    def keys(self) -> List[str]:
        """Lista todas las claves."""
        if not self._loaded:
            self.load()
        return list(self._entries.keys())

    @property
    def entries(self) -> Dict[str, SessionEntry]:
        """Acceso directo a las entradas."""
        if not self._loaded:
            self.load()
        return self._entries


# ── Búsqueda de sesiones en store ────────────────────────────
# Portado de OpenClaw: findStoreMatch(), findStoreKeysIgnoreCase()

def find_store_match(
    store: Dict[str, SessionEntry],
    *candidates: str,
) -> Optional[Tuple[str, SessionEntry]]:
    """Encuentra una entrada por coincidencia exacta o case-insensitive.

    Portado de OpenClaw: findStoreMatch()
    Retorna (key, entry) o None.
    """
    # Coincidencia exacta primero
    for candidate in candidates:
        if candidate and candidate in store:
            return (candidate, store[candidate])

    # Scan case-insensitive para TODOS los candidatos
    lowered_set = {c.lower() for c in candidates if c}
    for key, entry in store.items():
        if key.lower() in lowered_set:
            return (key, entry)

    return None


def find_store_keys_ignore_case(
    store: Dict[str, Any], target_key: str
) -> List[str]:
    """Encuentra todas las claves que coinciden case-insensitive.

    Portado de OpenClaw: findStoreKeysIgnoreCase()
    """
    lowered = target_key.lower()
    return [k for k in store if k.lower() == lowered]


def prune_legacy_store_keys(
    store: Dict[str, Any],
    canonical_key: str,
    candidates: List[str],
) -> None:
    """Elimina variantes legacy de claves de sesión.

    Portado de OpenClaw: pruneLegacyStoreKeys()
    """
    keys_to_delete: Set[str] = set()
    for candidate in candidates:
        trimmed = (candidate or "").strip()
        if not trimmed:
            continue
        if trimmed != canonical_key:
            keys_to_delete.add(trimmed)
        for match in find_store_keys_ignore_case(store, trimmed):
            if match != canonical_key:
                keys_to_delete.add(match)
    for key in keys_to_delete:
        store.pop(key, None)


# ── Construcción de session rows para el gateway ─────────────

def build_gateway_session_row(
    key: str,
    entry: Optional[SessionEntry] = None,
    store: Optional[Dict[str, SessionEntry]] = None,
    *,
    include_derived_titles: bool = False,
    include_last_message: bool = False,
    now: Optional[float] = None,
    sessions_dir: Optional[Path] = None,
) -> GatewaySessionRow:
    """Construye un GatewaySessionRow completo para una sesión.

    Portado de OpenClaw: buildGatewaySessionRow()
    Resuelve todos los campos derivados, tokens, costos, sesiones hijas.
    """
    now_ts = now or time.time()
    updated_at = entry.updated_at if entry else None
    parsed = parse_group_key(key)
    channel = (entry.channel if entry else None) or (
        parsed["channel"] if parsed else None
    )

    display_name = None
    if entry:
        display_name = entry.display_name or entry.label

    kind = classify_session_key(key, entry)

    # Derivar título si se solicita
    derived_title: Optional[str] = None
    if include_derived_titles and entry:
        derived_title = derive_session_title(entry)

    # Preview del último mensaje
    last_message_preview: Optional[str] = None
    if include_last_message and entry and entry.session_id:
        last_message_preview = _read_last_message_preview(
            entry.session_id, sessions_dir
        )

    # Resolver sesiones hija
    child_sessions: Optional[List[str]] = None
    if store:
        child_sessions = _resolve_child_session_keys(key, store)

    # Resolver modelo
    model_provider = entry.model_provider if entry else None
    model = entry.model if entry else None

    # Tokens
    total_tokens = _resolve_positive(
        entry.total_tokens if entry else None
    )
    context_tokens = _resolve_positive(
        entry.context_tokens if entry else None
    )

    return GatewaySessionRow(
        key=key,
        spawned_by=entry.spawned_by if entry else None,
        kind=kind,
        label=entry.label if entry else None,
        display_name=display_name,
        derived_title=derived_title,
        last_message_preview=last_message_preview,
        channel=channel,
        subject=entry.subject if entry else None,
        group_channel=entry.group_channel if entry else None,
        space=entry.space if entry else None,
        chat_type=entry.chat_type if entry else None,
        origin=entry.origin if entry else None,
        updated_at=updated_at,
        session_id=entry.session_id if entry else None,
        system_sent=entry.system_sent if entry else None,
        aborted_last_run=entry.aborted_last_run if entry else None,
        thinking_level=entry.thinking_level if entry else None,
        verbose_level=entry.verbose_level if entry else None,
        reasoning_level=entry.reasoning_level if entry else None,
        elevated_level=entry.elevated_level if entry else None,
        send_policy=entry.send_policy if entry else None,
        input_tokens=entry.input_tokens if entry else None,
        output_tokens=entry.output_tokens if entry else None,
        total_tokens=total_tokens,
        total_tokens_fresh=total_tokens is not None,
        estimated_cost_usd=entry.estimated_cost_usd if entry else None,
        status=_parse_run_status(entry.status) if entry and entry.status else None,
        started_at=entry.started_at if entry else None,
        ended_at=entry.ended_at if entry else None,
        runtime_ms=entry.runtime_ms if entry else None,
        parent_session_key=entry.parent_session_key if entry else None,
        child_sessions=child_sessions,
        response_usage=entry.response_usage if entry else None,
        model_provider=model_provider,
        model=model,
        context_tokens=context_tokens,
        last_channel=entry.last_channel if entry else None,
        last_to=entry.last_to if entry else None,
        last_account_id=entry.last_account_id if entry else None,
    )


# ── Listado de sesiones ──────────────────────────────────────

def list_sessions_from_store(
    store: Dict[str, SessionEntry],
    *,
    limit: Optional[int] = None,
    active_minutes: Optional[int] = None,
    include_global: bool = False,
    include_unknown: bool = False,
    include_derived_titles: bool = False,
    include_last_message: bool = False,
    label: Optional[str] = None,
    spawned_by: Optional[str] = None,
    agent_id: Optional[str] = None,
    search: Optional[str] = None,
    sessions_dir: Optional[Path] = None,
    defaults: Optional[GatewaySessionsDefaults] = None,
    store_path: str = "",
) -> SessionsListResult:
    """Lista sesiones desde un store con filtros.

    Portado de OpenClaw: listSessionsFromStore()
    """
    now = time.time()
    normalized_agent_id = normalize_agent_id(agent_id) if agent_id else ""
    search_lower = search.strip().lower() if search else ""

    # Filtrar y construir rows
    sessions: List[GatewaySessionRow] = []
    for key, entry in store.items():
        # Excluir global/unknown si no se piden
        if not include_global and key == "global":
            continue
        if not include_unknown and key == "unknown":
            continue

        # Filtro por agentId
        if normalized_agent_id:
            if key in ("global", "unknown"):
                continue
            parsed = parse_agent_session_key(key)
            if not parsed:
                continue
            if normalize_agent_id(parsed[0]) != normalized_agent_id:
                continue

        # Filtro por spawnedBy
        if spawned_by:
            if key in ("unknown", "global"):
                continue
            if entry.spawned_by != spawned_by:
                continue

        # Filtro por label
        if label:
            if entry.label != label:
                continue

        row = build_gateway_session_row(
            key,
            entry,
            store,
            include_derived_titles=include_derived_titles,
            include_last_message=include_last_message,
            now=now,
            sessions_dir=sessions_dir,
        )
        sessions.append(row)

    # Ordenar por updated_at descendente
    sessions.sort(key=lambda s: s.updated_at or 0, reverse=True)

    # Filtro de búsqueda
    if search_lower:
        sessions = [
            s
            for s in sessions
            if any(
                isinstance(f, str) and search_lower in f.lower()
                for f in [
                    s.display_name,
                    s.label,
                    s.subject,
                    s.session_id,
                    s.key,
                ]
            )
        ]

    # Filtro por actividad reciente
    if active_minutes is not None:
        cutoff = now - (active_minutes * 60)
        sessions = [s for s in sessions if (s.updated_at or 0) >= cutoff]

    # Límite
    if limit is not None and limit > 0:
        sessions = sessions[:limit]

    return SessionsListResult(
        ts=now,
        path=store_path,
        count=len(sessions),
        defaults=defaults or GatewaySessionsDefaults(),
        sessions=sessions,
    )


# ── Mapeo de conexiones WebSocket a sesiones ─────────────────

class ConnectionSessionMap:
    """Mapeo bidireccional entre conexiones WebSocket y sesiones.

    Permite rastrear qué conexión está asociada a qué sesión,
    soportando múltiples conexiones por sesión (eg. varios tabs)
    y una conexión asociada a múltiples sesiones.
    """

    def __init__(self) -> None:
        self._conn_to_sessions: Dict[str, Set[str]] = {}
        self._session_to_conns: Dict[str, Set[str]] = {}
        self._conn_metadata: Dict[str, Dict[str, Any]] = {}

    def bind(self, conn_id: str, session_key: str) -> None:
        """Asocia una conexión a una sesión."""
        self._conn_to_sessions.setdefault(conn_id, set()).add(session_key)
        self._session_to_conns.setdefault(session_key, set()).add(conn_id)

    def unbind(self, conn_id: str, session_key: str) -> None:
        """Desasocia una conexión de una sesión."""
        if conn_id in self._conn_to_sessions:
            self._conn_to_sessions[conn_id].discard(session_key)
            if not self._conn_to_sessions[conn_id]:
                del self._conn_to_sessions[conn_id]
        if session_key in self._session_to_conns:
            self._session_to_conns[session_key].discard(conn_id)
            if not self._session_to_conns[session_key]:
                del self._session_to_conns[session_key]

    def unbind_connection(self, conn_id: str) -> List[str]:
        """Desasocia completamente una conexión. Retorna las sesiones que tenía."""
        sessions = list(self._conn_to_sessions.pop(conn_id, set()))
        for session_key in sessions:
            if session_key in self._session_to_conns:
                self._session_to_conns[session_key].discard(conn_id)
                if not self._session_to_conns[session_key]:
                    del self._session_to_conns[session_key]
        self._conn_metadata.pop(conn_id, None)
        return sessions

    def get_sessions(self, conn_id: str) -> List[str]:
        """Obtiene las sesiones asociadas a una conexión."""
        return list(self._conn_to_sessions.get(conn_id, set()))

    def get_connections(self, session_key: str) -> List[str]:
        """Obtiene las conexiones asociadas a una sesión."""
        return list(self._session_to_conns.get(session_key, set()))

    def has_connections(self, session_key: str) -> bool:
        """Verifica si una sesión tiene conexiones activas."""
        return bool(self._session_to_conns.get(session_key))

    def set_metadata(self, conn_id: str, metadata: Dict[str, Any]) -> None:
        """Establece metadata para una conexión."""
        self._conn_metadata[conn_id] = metadata

    def get_metadata(self, conn_id: str) -> Dict[str, Any]:
        """Obtiene metadata de una conexión."""
        return self._conn_metadata.get(conn_id, {})

    @property
    def connection_count(self) -> int:
        """Número de conexiones registradas."""
        return len(self._conn_to_sessions)

    @property
    def session_count(self) -> int:
        """Número de sesiones con al menos una conexión."""
        return len(self._session_to_conns)

    def cleanup_stale(self, active_conn_ids: Set[str]) -> List[str]:
        """Limpia conexiones que ya no están activas.

        Retorna las conexiones eliminadas.
        """
        stale = [
            cid for cid in list(self._conn_to_sessions.keys())
            if cid not in active_conn_ids
        ]
        for conn_id in stale:
            self.unbind_connection(conn_id)
        return stale


# ── Validación de sesiones ───────────────────────────────────

def validate_session_key(key: str) -> Optional[str]:
    """Valida una clave de sesión.

    Retorna None si es válida, o un mensaje de error si no.
    """
    if not key or not key.strip():
        return "La clave de sesión no puede estar vacía"
    trimmed = key.strip()
    if len(trimmed) > 256:
        return "La clave de sesión excede 256 caracteres"
    # Permitir: letras, números, :, -, _, .
    if not re.match(r"^[a-zA-Z0-9:._-]+$", trimmed):
        return "La clave contiene caracteres inválidos (solo a-z, 0-9, :, -, _, .)"
    return None


def validate_session_entry(entry: SessionEntry) -> List[str]:
    """Valida una entrada de sesión.

    Retorna lista de problemas (vacía si todo OK).
    """
    issues: List[str] = []
    if entry.session_id and not entry.session_id.strip():
        issues.append("session_id vacío")
    if entry.model and not entry.model.strip():
        issues.append("model vacío")
    if (
        entry.input_tokens is not None
        and entry.input_tokens < 0
    ):
        issues.append("input_tokens negativo")
    if (
        entry.output_tokens is not None
        and entry.output_tokens < 0
    ):
        issues.append("output_tokens negativo")
    return issues


# ── Funciones de archivo de sesión (JSONL) ───────────────────
# Mantenidas de la versión original para compatibilidad

def get_session_file(
    session_id: str, sessions_dir: Optional[Path] = None
) -> Path:
    """Retorna la ruta al archivo de sesión."""
    base = sessions_dir or DEFAULT_SESSIONS_DIR
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{session_id}.jsonl"


def session_exists(
    session_id: str, sessions_dir: Optional[Path] = None
) -> bool:
    """Verifica si una sesión existe en disco."""
    return get_session_file(session_id, sessions_dir).exists()


def list_sessions(sessions_dir: Optional[Path] = None) -> List[str]:
    """Lista todos los IDs de sesión en disco."""
    base = sessions_dir or DEFAULT_SESSIONS_DIR
    if not base.exists():
        return []
    return [f.stem for f in base.iterdir() if f.suffix == ".jsonl"]


def append_to_session(
    session_id: str,
    event: Dict[str, Any],
    sessions_dir: Optional[Path] = None,
) -> None:
    """Añade un evento al archivo de sesión (JSONL)."""
    path = get_session_file(session_id, sessions_dir)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def read_session(
    session_id: str,
    sessions_dir: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Lee todos los eventos de una sesión."""
    path = get_session_file(session_id, sessions_dir)
    if not path.exists():
        return []
    events: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def delete_session(
    session_id: str,
    sessions_dir: Optional[Path] = None,
) -> bool:
    """Elimina una sesión del disco."""
    path = get_session_file(session_id, sessions_dir)
    if path.exists():
        path.unlink()
        return True
    return False


def archive_session(
    session_id: str,
    sessions_dir: Optional[Path] = None,
    archive_dir: Optional[Path] = None,
) -> bool:
    """Archiva una sesión moviéndola a un directorio de archivo.

    Portado de OpenClaw: archiveSessionTranscripts()
    """
    src = get_session_file(session_id, sessions_dir)
    if not src.exists():
        return False
    dest_dir = archive_dir or (sessions_dir or DEFAULT_SESSIONS_DIR) / "_archive"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    src.rename(dest)
    return True


# ── Helpers privados ─────────────────────────────────────────

def _resolve_positive(value: Optional[int]) -> Optional[int]:
    """Retorna el valor solo si es un entero positivo."""
    if isinstance(value, int) and value > 0:
        return value
    return None


def _resolve_non_negative(value: Optional[float]) -> Optional[float]:
    """Retorna el valor solo si es un número no negativo."""
    if isinstance(value, (int, float)) and value >= 0:
        return value
    return None


def _parse_run_status(status: str) -> Optional[SessionRunStatus]:
    """Parsea un string de status a SessionRunStatus."""
    try:
        return SessionRunStatus(status.lower())
    except ValueError:
        return None


def _resolve_child_session_keys(
    controller_key: str,
    store: Dict[str, SessionEntry],
) -> Optional[List[str]]:
    """Resuelve las claves de sesiones hija de un controlador.

    Portado de OpenClaw: resolveChildSessionKeys()
    """
    child_keys: Set[str] = set()
    for key, entry in store.items():
        if key == controller_key:
            continue
        spawned = (entry.spawned_by or "").strip()
        parent = (entry.parent_session_key or "").strip()
        if spawned == controller_key or parent == controller_key:
            child_keys.add(key)
    return list(child_keys) if child_keys else None


def _read_last_message_preview(
    session_id: str,
    sessions_dir: Optional[Path] = None,
) -> Optional[str]:
    """Lee una preview del último mensaje de una sesión.

    Lee los últimos bytes del transcript JSONL para extraer
    el último mensaje.
    """
    path = get_session_file(session_id, sessions_dir)
    if not path.exists():
        return None
    try:
        # Leer últimos 16KB
        size = path.stat().st_size
        read_size = min(size, 16384)
        with open(path, "rb") as f:
            if size > read_size:
                f.seek(size - read_size)
            chunk = f.read().decode("utf-8", errors="replace")

        lines = [l.strip() for l in chunk.split("\n") if l.strip()]
        if not lines:
            return None

        # Tomar el último evento que tenga contenido
        for line in reversed(lines):
            try:
                event = json.loads(line)
                content = event.get("content") or event.get("text")
                if content and isinstance(content, str):
                    return truncate_title(content, 120)
            except (json.JSONDecodeError, AttributeError):
                continue
        return None
    except Exception:
        return None
