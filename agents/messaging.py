"""Sistema de mensajería inter-agente (Agent-to-Agent messaging).

Pub/sub entre agentes para colaboración, compartir resultados
y coordinar tareas multi-agente.

Implementa:
- Bus de mensajes con topics
- Subscripciones con filtros
- Request/Reply pattern
- Broadcast a todos los agentes
- Mailbox por agente (mensajes pendientes)

Python 3.9+ — ``from __future__ import annotations``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ── Constantes ────────────────────────────────────────────────

MAX_MAILBOX_SIZE = 100
MAX_MESSAGE_SIZE = 50_000  # 50KB
MESSAGE_TTL_SECS = 3600   # 1 hora
REPLY_TIMEOUT_SECS = 120


# ── Tipos ────────────────────────────────────────────────────


class MessageType(str, Enum):
    """Tipos de mensajes inter-agente."""
    NOTIFY = "notify"       # Notificación sin respuesta esperada
    REQUEST = "request"     # Solicitud que espera respuesta
    REPLY = "reply"         # Respuesta a un request
    BROADCAST = "broadcast" # Mensaje a todos los agentes
    EVENT = "event"         # Evento del sistema


class MessagePriority(str, Enum):
    """Prioridad de mensajes."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


@dataclass
class AgentMessage:
    """Mensaje entre agentes."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    from_agent: str = ""
    to_agent: str = ""          # Vacío para broadcast
    topic: str = ""
    message_type: MessageType = MessageType.NOTIFY
    priority: MessagePriority = MessagePriority.NORMAL
    payload: Dict[str, Any] = field(default_factory=dict)
    reply_to: str = ""          # ID del mensaje original (para replies)
    correlation_id: str = ""    # Para agrupar request/reply
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0     # 0 = no expira
    delivered: bool = False
    read: bool = False

    def is_expired(self) -> bool:
        return self.expires_at > 0 and time.time() > self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "from": self.from_agent,
            "to": self.to_agent,
            "topic": self.topic,
            "type": self.message_type.value,
            "priority": self.priority.value,
            "payload": self.payload,
            "reply_to": self.reply_to,
            "correlation_id": self.correlation_id,
            "created_at": self.created_at,
            "read": self.read,
        }


# Tipo para handler de subscripción
MessageHandler = Callable[[AgentMessage], Awaitable[Optional[Dict[str, Any]]]]


@dataclass
class Subscription:
    """Subscripción a mensajes por topic."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    agent_id: str = ""
    topic_pattern: str = ""      # Glob pattern o string exacto
    message_types: Set[MessageType] = field(
        default_factory=lambda: {MessageType.NOTIFY, MessageType.REQUEST, MessageType.BROADCAST}
    )
    handler: Optional[MessageHandler] = None
    created_at: float = field(default_factory=time.time)


# ── AgentMessageBus ──────────────────────────────────────────


class AgentMessageBus:
    """Bus de mensajes para comunicación inter-agente.

    Uso:
        bus = AgentMessageBus()

        # Subscribirse
        await bus.subscribe("agent-B", "tasks.*", handler=my_handler)

        # Enviar mensaje
        await bus.send(AgentMessage(
            from_agent="agent-A",
            to_agent="agent-B",
            topic="tasks.new",
            payload={"task": "Analiza estos datos"},
        ))

        # Request/Reply
        reply = await bus.request(
            from_agent="agent-A",
            to_agent="agent-B",
            topic="analysis.run",
            payload={"data": "..."},
        )
    """

    def __init__(self) -> None:
        self._mailboxes: Dict[str, List[AgentMessage]] = {}
        self._subscriptions: Dict[str, List[Subscription]] = {}  # por agent_id
        self._topic_subs: Dict[str, List[Subscription]] = {}     # por topic
        self._pending_replies: Dict[str, asyncio.Future[AgentMessage]] = {}
        self._lock = asyncio.Lock()
        self._stats = {
            "messages_sent": 0,
            "messages_delivered": 0,
            "broadcasts": 0,
            "replies": 0,
        }

    # ── Mailbox ────────────────────────────────────────────

    def _get_mailbox(self, agent_id: str) -> List[AgentMessage]:
        if agent_id not in self._mailboxes:
            self._mailboxes[agent_id] = []
        return self._mailboxes[agent_id]

    def _add_to_mailbox(self, agent_id: str, message: AgentMessage) -> None:
        mailbox = self._get_mailbox(agent_id)
        # Limpiar expirados
        now = time.time()
        mailbox[:] = [m for m in mailbox if not m.is_expired()]
        # Limitar tamaño
        if len(mailbox) >= MAX_MAILBOX_SIZE:
            mailbox.pop(0)
        mailbox.append(message)

    # ── Subscribe / Unsubscribe ────────────────────────────

    async def subscribe(
        self,
        agent_id: str,
        topic_pattern: str,
        *,
        handler: Optional[MessageHandler] = None,
        message_types: Optional[Set[MessageType]] = None,
    ) -> str:
        """Subscribirse a mensajes de un topic.

        Args:
            agent_id: ID del agente que se subscribe.
            topic_pattern: Patrón de topic (e.g., "tasks.*", "analysis.results").
            handler: Handler async opcional que se ejecuta al recibir.
            message_types: Tipos de mensaje a recibir.

        Returns:
            ID de la subscripción.
        """
        sub = Subscription(
            agent_id=agent_id,
            topic_pattern=topic_pattern,
            handler=handler,
            message_types=message_types or {
                MessageType.NOTIFY, MessageType.REQUEST, MessageType.BROADCAST,
            },
        )

        async with self._lock:
            if agent_id not in self._subscriptions:
                self._subscriptions[agent_id] = []
            self._subscriptions[agent_id].append(sub)

            if topic_pattern not in self._topic_subs:
                self._topic_subs[topic_pattern] = []
            self._topic_subs[topic_pattern].append(sub)

        logger.debug("Agent %s subscribed to '%s' (sub=%s)", agent_id, topic_pattern, sub.id)
        return sub.id

    async def unsubscribe(self, agent_id: str, sub_id: str) -> bool:
        """Cancela una subscripción."""
        async with self._lock:
            if agent_id in self._subscriptions:
                before = len(self._subscriptions[agent_id])
                self._subscriptions[agent_id] = [
                    s for s in self._subscriptions[agent_id] if s.id != sub_id
                ]
                # Limpiar de topic_subs también
                for topic in list(self._topic_subs.keys()):
                    self._topic_subs[topic] = [
                        s for s in self._topic_subs[topic] if s.id != sub_id
                    ]
                    if not self._topic_subs[topic]:
                        del self._topic_subs[topic]
                return len(self._subscriptions[agent_id]) < before
        return False

    # ── Send ───────────────────────────────────────────────

    async def send(self, message: AgentMessage) -> str:
        """Envía un mensaje a un agente o broadcast.

        Returns:
            ID del mensaje enviado.
        """
        # Validar tamaño
        payload_size = len(json.dumps(message.payload, default=str))
        if payload_size > MAX_MESSAGE_SIZE:
            raise ValueError(f"Payload excede {MAX_MESSAGE_SIZE} bytes ({payload_size})")

        # TTL por defecto
        if message.expires_at == 0:
            message.expires_at = time.time() + MESSAGE_TTL_SECS

        self._stats["messages_sent"] += 1

        if message.message_type == MessageType.BROADCAST:
            return await self._broadcast(message)

        # Mensaje directo
        if message.to_agent:
            await self._deliver(message.to_agent, message)
            self._stats["messages_delivered"] += 1

        # Notificar subscriptores del topic
        await self._notify_subscribers(message)

        # Si es reply, resolver future pendiente
        if message.message_type == MessageType.REPLY and message.reply_to:
            await self._resolve_reply(message)

        return message.id

    async def _broadcast(self, message: AgentMessage) -> str:
        """Envía mensaje a todos los agentes registrados."""
        self._stats["broadcasts"] += 1
        agents = set(self._mailboxes.keys()) | set(self._subscriptions.keys())
        agents.discard(message.from_agent)  # No enviarse a sí mismo

        for agent_id in agents:
            msg_copy = AgentMessage(
                from_agent=message.from_agent,
                to_agent=agent_id,
                topic=message.topic,
                message_type=MessageType.BROADCAST,
                priority=message.priority,
                payload=message.payload,
                correlation_id=message.correlation_id,
                expires_at=message.expires_at,
            )
            await self._deliver(agent_id, msg_copy)

        await self._notify_subscribers(message)
        return message.id

    async def _deliver(self, agent_id: str, message: AgentMessage) -> None:
        """Entrega un mensaje al mailbox de un agente."""
        self._add_to_mailbox(agent_id, message)
        message.delivered = True

    async def _notify_subscribers(self, message: AgentMessage) -> None:
        """Notifica a subscriptores que coincidan con el topic."""
        matching_subs: List[Subscription] = []

        for pattern, subs in self._topic_subs.items():
            if self._matches_topic(message.topic, pattern):
                matching_subs.extend(subs)

        for sub in matching_subs:
            if message.message_type not in sub.message_types:
                continue
            if sub.agent_id == message.from_agent:
                continue
            if sub.handler:
                try:
                    asyncio.create_task(sub.handler(message))
                except Exception as exc:
                    logger.warning("Error en handler de sub %s: %s", sub.id, exc)

    async def _resolve_reply(self, message: AgentMessage) -> None:
        """Resuelve un future de request/reply."""
        key = message.reply_to
        if key in self._pending_replies:
            future = self._pending_replies.pop(key)
            if not future.done():
                future.set_result(message)
                self._stats["replies"] += 1

    @staticmethod
    def _matches_topic(topic: str, pattern: str) -> bool:
        """Verifica si un topic coincide con un patrón.

        Soporta '*' como wildcard para un segmento y '**' para múltiples.
        """
        if pattern == topic:
            return True
        if pattern == "*" or pattern == "**":
            return True

        pattern_parts = pattern.split(".")
        topic_parts = topic.split(".")

        if "**" in pattern_parts:
            # ** coincide con cualquier número de segmentos
            return topic.startswith(pattern.replace(".**", "").replace("**.", ""))

        if len(pattern_parts) != len(topic_parts):
            return False

        for pp, tp in zip(pattern_parts, topic_parts):
            if pp == "*":
                continue
            if pp != tp:
                return False

        return True

    # ── Request/Reply ──────────────────────────────────────

    async def request(
        self,
        from_agent: str,
        to_agent: str,
        topic: str,
        payload: Dict[str, Any],
        *,
        timeout: float = REPLY_TIMEOUT_SECS,
    ) -> Optional[AgentMessage]:
        """Envía un request y espera respuesta.

        Returns:
            AgentMessage de respuesta, o None si timeout.
        """
        correlation_id = uuid.uuid4().hex[:12]
        message = AgentMessage(
            from_agent=from_agent,
            to_agent=to_agent,
            topic=topic,
            message_type=MessageType.REQUEST,
            payload=payload,
            correlation_id=correlation_id,
        )

        # Crear future para la respuesta
        loop = asyncio.get_event_loop()
        future: asyncio.Future[AgentMessage] = loop.create_future()
        self._pending_replies[message.id] = future

        # Enviar request
        await self.send(message)

        # Esperar respuesta
        try:
            reply = await asyncio.wait_for(future, timeout=timeout)
            return reply
        except asyncio.TimeoutError:
            self._pending_replies.pop(message.id, None)
            logger.warning(
                "Request timeout: %s → %s topic=%s",
                from_agent, to_agent, topic,
            )
            return None

    async def reply(
        self,
        original: AgentMessage,
        from_agent: str,
        payload: Dict[str, Any],
    ) -> str:
        """Responde a un request.

        Args:
            original: Mensaje original al que se responde.
            from_agent: ID del agente que responde.
            payload: Contenido de la respuesta.

        Returns:
            ID del mensaje de respuesta.
        """
        message = AgentMessage(
            from_agent=from_agent,
            to_agent=original.from_agent,
            topic=original.topic,
            message_type=MessageType.REPLY,
            payload=payload,
            reply_to=original.id,
            correlation_id=original.correlation_id,
        )
        return await self.send(message)

    # ── Mailbox operations ─────────────────────────────────

    async def get_messages(
        self,
        agent_id: str,
        *,
        topic: str = "",
        unread_only: bool = False,
        limit: int = 50,
    ) -> List[AgentMessage]:
        """Obtiene mensajes del mailbox de un agente."""
        mailbox = self._get_mailbox(agent_id)

        # Filtrar expirados
        now = time.time()
        messages = [m for m in mailbox if not m.is_expired()]

        if topic:
            messages = [m for m in messages if self._matches_topic(m.topic, topic)]
        if unread_only:
            messages = [m for m in messages if not m.read]

        # Ordenar por prioridad y fecha
        priority_order = {
            MessagePriority.URGENT: 0,
            MessagePriority.HIGH: 1,
            MessagePriority.NORMAL: 2,
            MessagePriority.LOW: 3,
        }
        messages.sort(key=lambda m: (priority_order.get(m.priority, 2), -m.created_at))

        return messages[:limit]

    async def mark_read(self, agent_id: str, message_ids: List[str]) -> int:
        """Marca mensajes como leídos."""
        mailbox = self._get_mailbox(agent_id)
        marked = 0
        for msg in mailbox:
            if msg.id in message_ids:
                msg.read = True
                marked += 1
        return marked

    async def clear_mailbox(self, agent_id: str) -> int:
        """Limpia el mailbox de un agente."""
        if agent_id in self._mailboxes:
            count = len(self._mailboxes[agent_id])
            self._mailboxes[agent_id].clear()
            return count
        return 0

    # ── Stats ──────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        """Estado del bus de mensajes."""
        return {
            "agents": len(self._mailboxes),
            "subscriptions": sum(
                len(subs) for subs in self._subscriptions.values()
            ),
            "pending_replies": len(self._pending_replies),
            "mailbox_sizes": {
                agent: len(msgs) for agent, msgs in self._mailboxes.items()
            },
            "stats": dict(self._stats),
        }


# ── Singleton global ─────────────────────────────────────────

_global_bus: Optional[AgentMessageBus] = None


def get_message_bus() -> AgentMessageBus:
    """Obtiene el bus de mensajes global."""
    global _global_bus
    if _global_bus is None:
        _global_bus = AgentMessageBus()
    return _global_bus


def set_message_bus(bus: AgentMessageBus) -> None:
    """Establece el bus de mensajes global (para testing)."""
    global _global_bus
    _global_bus = bus
