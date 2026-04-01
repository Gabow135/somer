"""Routing jerárquico de sesiones con utilidades de session key y send policy.

Portado de OpenClaw:
- session-key-utils.ts — parseo y clasificación de session keys
- send-policy.ts — políticas de envío basadas en reglas

Jerarquía: peer -> guild -> team -> account -> channel.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

from config.schema import SendPolicyConfig, SomerConfig
from routing.keys import (
    build_agent_peer_session_key,
    normalize_account_id,
    normalize_agent_id,
    resolve_thread_session_keys,
    DEFAULT_AGENT_ID,
    DEFAULT_MAIN_KEY,
)
from shared.errors import SessionSendDeniedError
from shared.types import (
    ChatType,
    ChannelType,
    IncomingMessage,
    ParsedSessionKey,
    RoutePeer,
    SendPolicyDecision,
    SessionChatType,
    SessionInfo,
    SessionStatus,
)

logger = logging.getLogger(__name__)

# ── Marcadores de thread en session keys ────────────────────
_THREAD_SESSION_MARKERS = [":thread:", ":topic:"]

# ── Regex legacy Discord ────────────────────────────────────
_DISCORD_LEGACY_RE = re.compile(
    r"^discord:(?:[^:]+:)?guild-[^:]+:channel-[^:]+$"
)


# ═══════════════════════════════════════════════════════════
#  Session Key Utils (portado de session-key-utils.ts)
# ═══════════════════════════════════════════════════════════

def parse_session_key(session_key: Optional[str]) -> Optional[ParsedSessionKey]:
    """Parsea una session key con prefijo de agente.

    Formato canónico: ``agent:<agentId>:<rest>``.
    Los valores se normalizan a minúsculas para comparaciones estables.

    Portado de OpenClaw: ``parseAgentSessionKey``.
    """
    raw = (session_key or "").strip().lower()
    if not raw:
        return None

    parts = [p for p in raw.split(":") if p]
    if len(parts) < 3:
        return None
    if parts[0] != "agent":
        return None

    agent_id = parts[1].strip()
    rest = ":".join(parts[2:])
    if not agent_id or not rest:
        return None

    return ParsedSessionKey(agent_id=agent_id, rest=rest)


def derive_chat_type(session_key: Optional[str]) -> SessionChatType:
    """Deriva el tipo de chat desde una session key.

    Portado de OpenClaw: ``deriveSessionChatType``.
    Soporta formatos canónicos y legacy.
    """
    raw = (session_key or "").strip().lower()
    if not raw:
        return SessionChatType.UNKNOWN

    parsed = parse_session_key(raw)
    scoped = parsed.rest if parsed else raw
    tokens = set(p for p in scoped.split(":") if p)

    if "group" in tokens:
        return SessionChatType.GROUP
    if "channel" in tokens:
        return SessionChatType.CHANNEL
    if "direct" in tokens or "dm" in tokens:
        return SessionChatType.DIRECT

    # Legacy Discord: discord:<accountId>:guild-<guildId>:channel-<channelId>
    if _DISCORD_LEGACY_RE.match(scoped):
        return SessionChatType.CHANNEL

    return SessionChatType.UNKNOWN


def is_cron_run_session_key(session_key: Optional[str]) -> bool:
    """Verifica si la key corresponde a una ejecución de cron.

    Portado de OpenClaw: ``isCronRunSessionKey``.
    """
    parsed = parse_session_key(session_key)
    if parsed is None:
        return False
    return bool(re.match(r"^cron:[^:]+:run:[^:]+$", parsed.rest))


def is_cron_session_key(session_key: Optional[str]) -> bool:
    """Verifica si la key es de tipo cron.

    Portado de OpenClaw: ``isCronSessionKey``.
    """
    parsed = parse_session_key(session_key)
    if parsed is None:
        return False
    return parsed.rest.startswith("cron:")


def is_subagent_session_key(session_key: Optional[str]) -> bool:
    """Verifica si la key es de un subagente.

    Portado de OpenClaw: ``isSubagentSessionKey``.
    """
    raw = (session_key or "").strip()
    if not raw:
        return False
    if raw.lower().startswith("subagent:"):
        return True
    parsed = parse_session_key(raw)
    return bool(parsed and parsed.rest.startswith("subagent:"))


def get_subagent_depth(session_key: Optional[str]) -> int:
    """Obtiene la profundidad de anidamiento de subagentes.

    Portado de OpenClaw: ``getSubagentDepth``.
    """
    raw = (session_key or "").strip().lower()
    if not raw:
        return 0
    return raw.split(":subagent:").count("") - 1 if ":subagent:" in raw else 0


def is_acp_session_key(session_key: Optional[str]) -> bool:
    """Verifica si la key es de tipo ACP (Agent Communication Protocol).

    Portado de OpenClaw: ``isAcpSessionKey``.
    """
    raw = (session_key or "").strip()
    if not raw:
        return False
    normalized = raw.lower()
    if normalized.startswith("acp:"):
        return True
    parsed = parse_session_key(raw)
    return bool(parsed and parsed.rest.startswith("acp:"))


def resolve_thread_parent_key(session_key: Optional[str]) -> Optional[str]:
    """Resuelve la session key del padre de un thread.

    Portado de OpenClaw: ``resolveThreadParentSessionKey``.
    Busca el último marcador ``:thread:`` o ``:topic:`` y retorna
    la porción anterior como key del padre.
    """
    raw = (session_key or "").strip()
    if not raw:
        return None

    normalized = raw.lower()
    idx = -1
    for marker in _THREAD_SESSION_MARKERS:
        candidate = normalized.rfind(marker)
        if candidate > idx:
            idx = candidate

    if idx <= 0:
        return None

    parent = raw[:idx].strip()
    return parent if parent else None


# ═══════════════════════════════════════════════════════════
#  Send Policy (portado de send-policy.ts)
# ═══════════════════════════════════════════════════════════

def normalize_send_policy(raw: Optional[str]) -> Optional[SendPolicyDecision]:
    """Normaliza un string a una decisión de send policy.

    Portado de OpenClaw: ``normalizeSendPolicy``.
    """
    value = (raw or "").strip().lower()
    if value == "allow":
        return SendPolicyDecision.ALLOW
    if value == "deny":
        return SendPolicyDecision.DENY
    return None


def _normalize_match_value(raw: Optional[str]) -> Optional[str]:
    """Normaliza un valor de match a minúsculas."""
    value = (raw or "").strip().lower()
    return value if value else None


def _strip_agent_key_prefix(key: Optional[str]) -> Optional[str]:
    """Elimina el prefijo ``agent:<id>:`` de una session key."""
    if not key:
        return None
    parts = [p for p in key.split(":") if p]
    if len(parts) >= 3 and parts[0] == "agent":
        return ":".join(parts[2:])
    return key


def _derive_channel_from_key(key: Optional[str]) -> Optional[str]:
    """Deriva el canal desde una session key.

    Portado de OpenClaw: ``deriveChannelFromKey``.
    """
    normalized_key = _strip_agent_key_prefix(key)
    if not normalized_key:
        return None
    parts = [p for p in normalized_key.split(":") if p]
    if len(parts) >= 3 and parts[1] in ("group", "channel"):
        return _normalize_match_value(parts[0])
    return None


def _derive_chat_type_from_key(key: Optional[str]) -> Optional[SessionChatType]:
    """Deriva el tipo de chat desde una session key para matching."""
    chat_type = derive_chat_type(key)
    return chat_type if chat_type != SessionChatType.UNKNOWN else None


def _normalize_chat_type(raw: Optional[str]) -> Optional[SessionChatType]:
    """Normaliza un string a SessionChatType."""
    if raw is None:
        return None
    value = raw.strip().lower()
    try:
        return SessionChatType(value)
    except ValueError:
        return None


def resolve_send_policy(
    config: SomerConfig,
    entry: Optional[SessionInfo] = None,
    session_key: Optional[str] = None,
    channel: Optional[str] = None,
    chat_type: Optional[SessionChatType] = None,
) -> SendPolicyDecision:
    """Resuelve la política de envío para una sesión.

    Portado de OpenClaw: ``resolveSendPolicy``.
    Evalúa las reglas de send policy del config en orden:
    1. Override explícito en la sesión
    2. Reglas del config (primera coincidencia gana)
    3. Fallback al default del policy
    4. Si no hay policy, permite todo

    Returns:
        ``allow`` o ``deny``.
    """
    # Override explícito en la sesión
    if entry and entry.send_policy:
        override = normalize_send_policy(entry.send_policy.value)
        if override:
            return override

    policy = config.sessions.send_policy
    if policy is None:
        return SendPolicyDecision.ALLOW

    # Resolver canal
    resolved_channel = (
        _normalize_match_value(channel)
        or (
            _normalize_match_value(entry.channel.value)
            if entry and entry.channel
            else None
        )
        or (
            _normalize_match_value(entry.last_channel)
            if entry
            else None
        )
        or _derive_channel_from_key(session_key)
    )

    # Resolver chat type
    resolved_chat_type = (
        _normalize_chat_type(
            chat_type.value if chat_type else None
        )
        or (
            _normalize_chat_type(entry.chat_type.value)
            if entry and entry.chat_type
            else None
        )
        or _derive_chat_type_from_key(session_key)
    )

    raw_key = session_key or ""
    stripped_key = _strip_agent_key_prefix(raw_key) or ""
    raw_key_norm = raw_key.lower()
    stripped_key_norm = stripped_key.lower()

    allowed_match = False
    for rule in policy.rules:
        if rule is None:
            continue

        action = normalize_send_policy(rule.action) or SendPolicyDecision.ALLOW
        match = rule.match
        match_channel = _normalize_match_value(match.channel)
        match_chat_type = _normalize_chat_type(match.chat_type)
        match_prefix = _normalize_match_value(match.key_prefix)
        match_raw_prefix = _normalize_match_value(match.raw_key_prefix)

        if match_channel and match_channel != resolved_channel:
            continue
        if match_chat_type and match_chat_type != resolved_chat_type:
            continue
        if match_raw_prefix and not raw_key_norm.startswith(match_raw_prefix):
            continue
        if match_prefix:
            if (
                not raw_key_norm.startswith(match_prefix)
                and not stripped_key_norm.startswith(match_prefix)
            ):
                continue

        if action == SendPolicyDecision.DENY:
            return SendPolicyDecision.DENY
        allowed_match = True

    if allowed_match:
        return SendPolicyDecision.ALLOW

    fallback = normalize_send_policy(policy.default)
    return fallback or SendPolicyDecision.ALLOW


# ═══════════════════════════════════════════════════════════
#  Session Router
# ═══════════════════════════════════════════════════════════

class SessionRouter:
    """Resuelve qué sesión debe manejar un mensaje entrante.

    Jerarquía de resolución:
    1. Thread ID (si el canal soporta threads)
    2. User ID + Channel (peer session)
    3. Guild/Team (shared session)

    Integra las utilidades de session key y send policy
    portadas de OpenClaw.
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, SessionInfo] = {}

    def resolve(self, message: IncomingMessage) -> str:
        """Resuelve el session_id para un mensaje entrante.

        Returns:
            session_id existente o nuevo.
        """
        # 1. Thread-level session
        if message.channel_thread_id:
            key = self._thread_key(message)
            if key in self._sessions:
                return self._sessions[key].session_id
            return self._create_session(key, message).session_id

        # 2. Peer-level session (user + channel)
        key = self._peer_key(message)
        if key in self._sessions:
            return self._sessions[key].session_id

        return self._create_session(key, message).session_id

    def get_session(self, session_id: str) -> Optional[SessionInfo]:
        """Obtiene info de sesión por ID."""
        for info in self._sessions.values():
            if info.session_id == session_id:
                return info
        return None

    def get_session_by_key(self, session_key: str) -> Optional[SessionInfo]:
        """Obtiene info de sesión por session key."""
        for info in self._sessions.values():
            if info.session_key == session_key:
                return info
        return None

    def close_session(self, session_id: str) -> bool:
        """Cierra una sesión."""
        for key, info in list(self._sessions.items()):
            if info.session_id == session_id:
                info.status = SessionStatus.CLOSED
                del self._sessions[key]
                return True
        return False

    def active_sessions(self) -> List[SessionInfo]:
        """Lista sesiones activas."""
        return [s for s in self._sessions.values() if s.status == SessionStatus.ACTIVE]

    def resolve_with_agent(
        self,
        message: IncomingMessage,
        agent_id: str = DEFAULT_AGENT_ID,
        dm_scope: str = "main",
        identity_links: Optional[Dict[str, List[str]]] = None,
    ) -> str:
        """Resuelve el session_id usando session keys canonicas del AgentRouter.

        Genera session keys en formato ``agent:<id>:<rest>`` usando
        la logica portada de OpenClaw.

        Args:
            message: Mensaje entrante.
            agent_id: ID del agente resuelto.
            dm_scope: Alcance de sesion para DMs.
            identity_links: Links de identidad entre canales.

        Returns:
            session_id existente o nuevo.
        """
        peer = message.peer
        peer_kind = peer.kind if peer else ChatType.DIRECT
        peer_id = peer.id if peer else message.channel_user_id

        base_key = build_agent_peer_session_key(
            agent_id=agent_id,
            channel=message.channel.value,
            account_id=message.metadata.get("account_id"),
            peer_kind=peer_kind,
            peer_id=peer_id,
            dm_scope=dm_scope,
            identity_links=identity_links,
        ).lower()

        # Resolver thread si aplica
        if message.channel_thread_id:
            keys = resolve_thread_session_keys(
                base_session_key=base_key,
                thread_id=message.channel_thread_id,
            )
            session_key = keys["session_key"]
        else:
            session_key = base_key

        if session_key in self._sessions:
            return self._sessions[session_key].session_id

        return self._create_session(session_key, message).session_id

    def _create_session(self, key: str, msg: IncomingMessage) -> SessionInfo:
        """Crea una nueva sesion con session key y chat type derivado."""
        chat_type = derive_chat_type(key)
        info = SessionInfo(
            session_key=key,
            channel=msg.channel,
            channel_user_id=msg.channel_user_id,
            channel_thread_id=msg.channel_thread_id,
            guild_id=msg.guild_id,
            team_id=msg.team_id,
            chat_type=chat_type,
        )
        self._sessions[key] = info
        logger.debug("Sesion creada: %s (key=%s, chat_type=%s)",
                      info.session_id, key, chat_type.value)
        return info

    @staticmethod
    def _peer_key(msg: IncomingMessage) -> str:
        return f"peer:{msg.channel.value}:{msg.channel_user_id}"

    @staticmethod
    def _thread_key(msg: IncomingMessage) -> str:
        return f"thread:{msg.channel.value}:{msg.channel_thread_id}"
