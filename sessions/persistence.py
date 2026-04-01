"""Persistencia de sesiones en formato JSONL con soporte de transcript.

Portado de OpenClaw: integra serialización de eventos de transcript
con el sistema de persistencia JSONL existente.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from sessions.events import SessionEventBus
from shared.constants import DEFAULT_SESSIONS_DIR
from shared.types import (
    AgentMessage,
    InputProvenance,
    SessionInfo,
    SessionTranscriptUpdate,
)

logger = logging.getLogger(__name__)


class SessionPersistence:
    """Persiste sesiones como archivos JSONL.

    Integra con el bus de eventos para emitir actualizaciones de
    transcript al guardar mensajes. Soporta serialización de
    provenance y metadata extendida.
    """

    def __init__(
        self,
        sessions_dir: Optional[Path] = None,
        event_bus: Optional[SessionEventBus] = None,
    ):
        self._dir = sessions_dir or DEFAULT_SESSIONS_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._event_bus = event_bus

    def save_event(self, session_id: str, event: Dict[str, Any]) -> None:
        """Añade un evento al archivo de sesión.

        Serializa con soporte para tipos Pydantic, datetime y UUID.
        """
        path = self._session_path(session_id)
        # Inyectar timestamp si no existe
        if "timestamp" not in event:
            event["timestamp"] = time.time()
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, default=_json_serializer) + "\n")

    def save_message(
        self,
        session_id: str,
        message: AgentMessage,
        session_key: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> None:
        """Persiste un mensaje de agente y emite transcript update.

        Portado de OpenClaw: la emisión de transcript update se
        inspira en ``emitSessionTranscriptUpdate``.
        """
        data = message.model_dump()
        self.save_event(session_id, {
            "type": "message",
            "data": data,
        })

        # Emitir transcript update si hay event bus
        if self._event_bus is not None:
            update = SessionTranscriptUpdate(
                session_file=str(self._session_path(session_id)),
                session_key=session_key,
                message=data,
                message_id=message_id,
            )
            self._event_bus.emit_transcript_update_sync(update)

    def save_session_info(self, info: SessionInfo) -> None:
        """Persiste metadata de sesión."""
        self.save_event(info.session_id, {
            "type": "session_info",
            "data": info.model_dump(),
        })

    def save_model_override(
        self,
        session_id: str,
        provider: Optional[str],
        model: Optional[str],
        auth_profile: Optional[str] = None,
    ) -> None:
        """Persiste un evento de cambio de modelo override.

        Portado de OpenClaw: complementa ``applyModelOverrideToSessionEntry``.
        """
        self.save_event(session_id, {
            "type": "model_override",
            "data": {
                "provider": provider,
                "model": model,
                "auth_profile": auth_profile,
                "timestamp": time.time(),
            },
        })

    def save_provenance(
        self,
        session_id: str,
        provenance: InputProvenance,
    ) -> None:
        """Persiste un evento de input provenance.

        Portado de OpenClaw: complementa ``applyInputProvenanceToUserMessage``.
        """
        self.save_event(session_id, {
            "type": "input_provenance",
            "data": provenance.model_dump(),
        })

    def load_events(self, session_id: str) -> List[Dict[str, Any]]:
        """Carga todos los eventos de una sesión."""
        path = self._session_path(session_id)
        if not path.exists():
            return []
        events: List[Dict[str, Any]] = []
        with open(path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning(
                        "Línea %d malformada en %s, ignorando",
                        line_num, path,
                    )
        return events

    def load_messages(self, session_id: str) -> List[AgentMessage]:
        """Carga solo los mensajes de una sesión."""
        events = self.load_events(session_id)
        messages: List[AgentMessage] = []
        for event in events:
            if event.get("type") == "message":
                try:
                    messages.append(AgentMessage.model_validate(event["data"]))
                except Exception:
                    logger.warning(
                        "Mensaje malformado en sesión %s, ignorando",
                        session_id,
                    )
        return messages

    def load_events_by_type(
        self, session_id: str, event_type: str
    ) -> List[Dict[str, Any]]:
        """Carga eventos de un tipo específico."""
        return [
            e for e in self.load_events(session_id)
            if e.get("type") == event_type
        ]

    def load_session_info(self, session_id: str) -> Optional[SessionInfo]:
        """Carga la última info de sesión persistida."""
        infos = self.load_events_by_type(session_id, "session_info")
        if not infos:
            return None
        try:
            return SessionInfo.model_validate(infos[-1]["data"])
        except Exception:
            logger.warning(
                "SessionInfo malformado en sesión %s", session_id
            )
            return None

    def session_exists(self, session_id: str) -> bool:
        return self._session_path(session_id).exists()

    def list_sessions(self) -> List[str]:
        """Lista todos los session IDs persistidos."""
        return [f.stem for f in self._dir.iterdir() if f.suffix == ".jsonl"]

    def delete_session(self, session_id: str) -> bool:
        """Elimina el archivo de sesión."""
        path = self._session_path(session_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def session_size_bytes(self, session_id: str) -> int:
        """Retorna el tamaño en bytes del archivo de sesión."""
        path = self._session_path(session_id)
        if path.exists():
            return path.stat().st_size
        return 0

    def _session_path(self, session_id: str) -> Path:
        return self._dir / f"{session_id}.jsonl"


def _json_serializer(obj: Any) -> Any:
    """Serializer personalizado para json.dumps.

    Maneja tipos Pydantic, Enum y otros objetos comunes.
    """
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "value"):
        return obj.value
    return str(obj)
