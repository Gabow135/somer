"""Session Manager — ciclo de vida de sesiones con model overrides y provenance.

Portado de OpenClaw:
- model-overrides.ts — overrides de modelo/provider por sesión
- input-provenance.ts — procedencia de mensajes de entrada
"""

from __future__ import annotations

import logging
import time
from typing import Dict, List, Literal, Optional

from config.schema import SomerConfig
from context_engine.base import ContextEngine
from context_engine.default import DefaultContextEngine
from sessions.events import SessionEventBus
from sessions.persistence import SessionPersistence
from sessions.routing import (
    SessionRouter,
    resolve_send_policy,
)
from shared.constants import SESSION_IDLE_TIMEOUT_SECS, SESSION_MAX_TURNS
from shared.errors import (
    SessionExpiredError,
    SessionNotFoundError,
    SessionSendDeniedError,
)
from shared.types import (
    AgentMessage,
    IncomingMessage,
    InputProvenance,
    InputProvenanceKind,
    ModelOverrideSelection,
    Role,
    SendPolicyDecision,
    SessionInfo,
    SessionStatus,
    SessionTranscriptUpdate,
)

logger = logging.getLogger(__name__)


class SessionManager:
    """Coordina routing, contexto, persistencia y políticas de sesión.

    Integra funcionalidad portada de OpenClaw:
    - Model overrides (cambiar modelo/provider por sesión)
    - Input provenance (rastreo de origen de mensajes)
    - Send policy (políticas de envío por reglas)
    - Transcript events (notificaciones de cambios)
    """

    def __init__(
        self,
        config: Optional[SomerConfig] = None,
        context_engine: Optional[ContextEngine] = None,
        persistence: Optional[SessionPersistence] = None,
        event_bus: Optional[SessionEventBus] = None,
        idle_timeout: int = SESSION_IDLE_TIMEOUT_SECS,
        max_turns: int = SESSION_MAX_TURNS,
    ):
        self._config = config or SomerConfig()
        self.events = event_bus or SessionEventBus()
        self.router = SessionRouter()
        self.context = context_engine or DefaultContextEngine()
        self.persistence = persistence or SessionPersistence(event_bus=self.events)
        self._idle_timeout = idle_timeout
        self._max_turns = max_turns
        self._turn_counts: Dict[str, int] = {}

    async def handle_message(
        self,
        message: IncomingMessage,
        provenance: Optional[InputProvenance] = None,
    ) -> str:
        """Procesa un mensaje entrante: routing -> policy -> context -> persistencia.

        Portado de OpenClaw: integra send policy y input provenance
        en el flujo de procesamiento de mensajes.

        Args:
            message: Mensaje entrante desde un canal.
            provenance: Procedencia del mensaje (opcional).

        Returns:
            session_id asignado.

        Raises:
            SessionExpiredError: Si la sesión está cerrada.
            SessionSendDeniedError: Si la política de envío lo deniega.
        """
        session_id = self.router.resolve(message)
        info = self.router.get_session(session_id)

        if info and info.status == SessionStatus.CLOSED:
            raise SessionExpiredError(f"Sesion {session_id} esta cerrada")

        # Evaluar send policy
        send_decision = resolve_send_policy(
            config=self._config,
            entry=info,
            session_key=info.session_key if info else None,
            channel=message.channel.value,
        )
        if send_decision == SendPolicyDecision.DENY:
            raise SessionSendDeniedError(
                f"Envio denegado por politica para sesion {session_id}"
            )

        # Construir mensaje de agente con provenance
        agent_msg = AgentMessage(
            role=Role(message.metadata.get("role", "user")),
            content=message.content,
            metadata=message.metadata,
            timestamp=message.timestamp,
        )

        # Aplicar input provenance al mensaje
        agent_msg = apply_input_provenance(agent_msg, provenance)

        # Guardar provenance en la sesión
        if provenance and info:
            info.last_provenance = provenance

        # Ingestar en context engine
        await self.context.ingest(session_id, agent_msg)

        # Persistir con transcript update
        self.persistence.save_message(
            session_id,
            agent_msg,
            session_key=info.session_key if info else None,
        )

        # Incrementar turno
        self._turn_counts[session_id] = self._turn_counts.get(session_id, 0) + 1

        # Emitir evento
        await self.events.emit("session.message", {
            "session_id": session_id,
            "channel": message.channel.value,
            "user_id": message.channel_user_id,
            "provenance_kind": provenance.kind.value if provenance else None,
        })

        # Actualizar timestamp
        if info:
            info.updated_at = time.time()

        return session_id

    async def close_session(self, session_id: str) -> None:
        """Cierra una sesion."""
        info = self.router.get_session(session_id)
        if info:
            self.persistence.save_session_info(info)
        self.router.close_session(session_id)
        await self.events.emit("session.closed", {"session_id": session_id})

    # ── Model Overrides (portado de OpenClaw) ───────────────

    def apply_model_override(
        self,
        session_id: str,
        selection: ModelOverrideSelection,
        profile_override: Optional[str] = None,
        profile_override_source: Literal["auto", "user"] = "user",
    ) -> bool:
        """Aplica un override de modelo a una sesion.

        Portado de OpenClaw: ``applyModelOverrideToSessionEntry``.
        Actualiza el provider/modelo override de la sesion y limpia
        campos de runtime obsoletos.

        Args:
            session_id: ID de la sesion.
            selection: Nuevo modelo/provider seleccionado.
            profile_override: Perfil de auth override (opcional).
            profile_override_source: Fuente del override ("auto" o "user").

        Returns:
            True si hubo cambios.
        """
        info = self.router.get_session(session_id)
        if info is None:
            raise SessionNotFoundError(f"Sesion {session_id} no encontrada")

        updated = False
        selection_updated = False

        if selection.is_default:
            # Limpiar overrides — volver al modelo por defecto
            if info.provider_override is not None:
                info.provider_override = None
                updated = True
                selection_updated = True
            if info.model_override is not None:
                info.model_override = None
                updated = True
                selection_updated = True
        else:
            if info.provider_override != selection.provider:
                info.provider_override = selection.provider
                updated = True
                selection_updated = True
            if info.model_override != selection.model:
                info.model_override = selection.model
                updated = True
                selection_updated = True

        # Limpiar identidad de runtime obsoleta
        runtime_model = (info.model or "").strip()
        runtime_provider = (info.model_provider or "").strip()
        runtime_present = bool(runtime_model) or bool(runtime_provider)
        runtime_aligned = (
            runtime_model == selection.model
            and (not runtime_provider or runtime_provider == selection.provider)
        )

        if runtime_present and (selection_updated or not runtime_aligned):
            if info.model is not None:
                info.model = None
                updated = True
            if info.model_provider is not None:
                info.model_provider = None
                updated = True

        # Limpiar context_tokens obsoletos
        if info.context_tokens is not None and (
            selection_updated or (runtime_present and not runtime_aligned)
        ):
            info.context_tokens = None
            updated = True

        # Auth profile override
        if profile_override:
            if info.auth_profile_override != profile_override:
                info.auth_profile_override = profile_override
                updated = True
            if info.auth_profile_override_source != profile_override_source:
                info.auth_profile_override_source = profile_override_source
                updated = True
            if info.auth_profile_override_compaction_count is not None:
                info.auth_profile_override_compaction_count = None
                updated = True
        else:
            if info.auth_profile_override is not None:
                info.auth_profile_override = None
                updated = True
            if info.auth_profile_override_source is not None:
                info.auth_profile_override_source = None
                updated = True
            if info.auth_profile_override_compaction_count is not None:
                info.auth_profile_override_compaction_count = None
                updated = True

        # Limpiar fallback notice si hubo cambios
        if updated:
            info.fallback_notice_selected_model = None
            info.fallback_notice_active_model = None
            info.fallback_notice_reason = None
            info.updated_at = time.time()

            # Persistir el override
            self.persistence.save_model_override(
                session_id,
                provider=info.provider_override,
                model=info.model_override,
                auth_profile=info.auth_profile_override,
            )

        return updated

    def get_effective_model(self, session_id: str) -> Optional[str]:
        """Obtiene el modelo efectivo para una sesion.

        Prioridad: model_override > model (runtime) > config default.
        """
        info = self.router.get_session(session_id)
        if info is None:
            return self._config.default_model

        return (
            info.model_override
            or info.model
            or self._config.default_model
        )

    def get_effective_provider(self, session_id: str) -> Optional[str]:
        """Obtiene el provider efectivo para una sesion.

        Prioridad: provider_override > model_provider > None.
        """
        info = self.router.get_session(session_id)
        if info is None:
            return None

        return info.provider_override or info.model_provider

    # ── Consultas ───────────────────────────────────────────

    def get_session(self, session_id: str) -> Optional[SessionInfo]:
        return self.router.get_session(session_id)

    def get_turn_count(self, session_id: str) -> int:
        return self._turn_counts.get(session_id, 0)

    def active_sessions(self) -> List[SessionInfo]:
        return self.router.active_sessions()

    def check_send_policy(
        self,
        session_id: str,
        channel: Optional[str] = None,
    ) -> SendPolicyDecision:
        """Consulta la politica de envio para una sesion sin enviar.

        Util para UI que necesita saber si puede enviar antes de intentarlo.
        """
        info = self.router.get_session(session_id)
        return resolve_send_policy(
            config=self._config,
            entry=info,
            session_key=info.session_key if info else None,
            channel=channel,
        )


# ═══════════════════════════════════════════════════════════
#  Input Provenance (portado de input-provenance.ts)
# ═══════════════════════════════════════════════════════════

def normalize_input_provenance(value: Optional[dict]) -> Optional[InputProvenance]:
    """Normaliza un dict crudo a InputProvenance.

    Portado de OpenClaw: ``normalizeInputProvenance``.
    Valida el campo ``kind`` y normaliza strings opcionales.
    """
    if not value or not isinstance(value, dict):
        return None

    kind_raw = value.get("kind")
    if not isinstance(kind_raw, str):
        return None

    try:
        kind = InputProvenanceKind(kind_raw)
    except ValueError:
        return None

    return InputProvenance(
        kind=kind,
        origin_session_id=_normalize_optional_str(value.get("origin_session_id")),
        source_session_key=_normalize_optional_str(value.get("source_session_key")),
        source_channel=_normalize_optional_str(value.get("source_channel")),
        source_tool=_normalize_optional_str(value.get("source_tool")),
    )


def apply_input_provenance(
    message: AgentMessage,
    provenance: Optional[InputProvenance],
) -> AgentMessage:
    """Aplica provenance a un mensaje de usuario si no tiene ya una.

    Portado de OpenClaw: ``applyInputProvenanceToUserMessage``.
    Solo se aplica a mensajes con role=user que no tengan
    provenance existente.
    """
    if provenance is None:
        return message
    if message.role != Role.USER:
        return message
    if message.provenance is not None:
        return message

    message.provenance = provenance
    return message


def is_inter_session_provenance(value: Optional[dict]) -> bool:
    """Verifica si un dict de provenance es de tipo inter_session.

    Portado de OpenClaw: ``isInterSessionInputProvenance``.
    """
    normalized = normalize_input_provenance(value)
    return normalized is not None and normalized.kind == InputProvenanceKind.INTER_SESSION


def has_inter_session_user_provenance(message: Optional[AgentMessage]) -> bool:
    """Verifica si un mensaje de usuario tiene provenance inter_session.

    Portado de OpenClaw: ``hasInterSessionUserProvenance``.
    """
    if message is None or message.role != Role.USER:
        return False
    if message.provenance is None:
        return False
    return message.provenance.kind == InputProvenanceKind.INTER_SESSION


# ── Utilidades internas ─────────────────────────────────────

def _normalize_optional_str(value: object) -> Optional[str]:
    """Normaliza un valor a string o None."""
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    return trimmed if trimmed else None
