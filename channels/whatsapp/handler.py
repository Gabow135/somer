"""Manejador de mensajes entrantes de WhatsApp para SOMER 2.0.

Cuando llega un mensaje a través del webhook de Meta, este módulo:

1. Recibe el evento estructurado (ya parseado por WhatsAppWebhook).
2. Busca si el número del remitente corresponde a un usuario SRI
   registrado en ~/.somer/sri_credentials.db.
3. Si el mensaje es un comando simple (AYUDA, ESTADO, INFO), responde
   automáticamente con información básica.
4. En caso contrario, encola el mensaje en la cola asyncio global para
   que el agente SOMER lo procese de forma asíncrona.

Uso desde server.py:

    from channels.whatsapp.handler import WhatsAppMessageHandler

    handler = WhatsAppMessageHandler()
    await handler.handle(evento)
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────

_SOMER_DIR = Path.home() / ".somer"
_DB_PATH = _SOMER_DIR / "sri_credentials.db"

# Comandos de ayuda rápida reconocidos (insensible a mayúsculas/tildes)
_COMANDOS_AYUDA = {"ayuda", "help", "ayuda!", "help!"}
_COMANDOS_ESTADO = {"estado", "status", "status!"}
_COMANDOS_INFO = {"info", "información", "informacion", "hola"}

# Cola global para que el agente consuma los mensajes entrantes.
# Se inicializa aquí; server.py la reutiliza para la misma instancia.
_incoming_queue: asyncio.Queue = asyncio.Queue()  # type: ignore[type-arg]


def get_authorized_numbers() -> List[str]:
    """Lee la lista de números de WhatsApp autorizados desde ~/.somer/authorized_numbers.json.

    Si el archivo no existe o está vacío, devuelve lista vacía (modo abierto:
    todos los números pueden escribir al bot).

    Returns:
        Lista de números autorizados (strings), o lista vacía si no hay whitelist.
    """
    authorized_file = _SOMER_DIR / "authorized_numbers.json"
    if not authorized_file.exists():
        return []
    try:
        import json
        data = json.loads(authorized_file.read_text())
        if isinstance(data, list):
            return [str(n) for n in data if n]
        return []
    except Exception as exc:
        logger.warning("No se pudo leer authorized_numbers.json: %s", exc)
        return []


def get_incoming_queue() -> asyncio.Queue:  # type: ignore[type-arg]
    """Retorna la cola global de mensajes entrantes de WhatsApp.

    El servidor de webhook encola aquí los mensajes y el agente
    SOMER los consume desde esta misma cola.

    Returns:
        Instancia singleton de asyncio.Queue con mensajes pendientes.
    """
    return _incoming_queue


# ── Búsqueda de usuario SRI ───────────────────────────────────


def _buscar_usuario_sri(numero_whatsapp: str) -> Optional[Dict[str, Any]]:
    """Busca en sri_credentials.db si el número pertenece a un usuario registrado.

    Normaliza el número (quita +, espacios y guiones) antes de buscar.

    Args:
        numero_whatsapp: Número de teléfono del remitente (ej: "593987654321").

    Returns:
        Dict con {ruc, name, alias, whatsapp_number} si se encontró,
        None si no existe ningún usuario con ese número.
    """
    if not _DB_PATH.exists():
        logger.debug(
            "sri_credentials.db no encontrada en %s — omitiendo búsqueda de usuario",
            _DB_PATH,
        )
        return None

    numero = numero_whatsapp.strip().lstrip("+").replace(" ", "").replace("-", "")
    if not numero:
        return None

    try:
        conn = sqlite3.connect(str(_DB_PATH))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT ruc, name, alias, whatsapp_number FROM sri_users "
            "WHERE REPLACE(REPLACE(LTRIM(whatsapp_number, '+'), ' ', ''), '-', '') = ? "
            "LIMIT 1",
            (numero,),
        ).fetchone()
        conn.close()

        if row:
            return {
                "ruc": row["ruc"],
                "name": row["name"] or row["alias"] or "Usuario",
                "alias": row["alias"],
                "whatsapp_number": row["whatsapp_number"],
            }
        return None

    except Exception as exc:
        logger.error("Error buscando usuario SRI por whatsapp_number=%s: %s", numero, exc)
        return None


# ── Respuestas automáticas ────────────────────────────────────


def _generar_respuesta_automatica(
    texto: str,
    usuario_sri: Optional[Dict[str, Any]],
) -> Optional[str]:
    """Genera una respuesta automática si el mensaje es un comando reconocido.

    Comandos soportados:
      - AYUDA / HELP → instrucciones básicas de uso
      - ESTADO / STATUS → estado del sistema SOMER
      - INFO / HOLA → saludo y presentación

    Args:
        texto:       Texto del mensaje recibido (en crudo).
        usuario_sri: Datos del usuario SRI si fue identificado, None si no.

    Returns:
        Texto de la respuesta automática o None si no aplica ningún comando.
    """
    texto_norm = texto.strip().lower().rstrip("!")

    nombre = "Usuario"
    if usuario_sri:
        nombre = usuario_sri.get("name") or usuario_sri.get("alias") or "Usuario"

    if texto_norm in _COMANDOS_AYUDA:
        return (
            f"Hola {nombre}! Soy SOMER, tu asistente de obligaciones SRI.\n\n"
            "Puedes escribirme directamente tus consultas. Por ejemplo:\n"
            "  • ¿Cuáles son mis obligaciones pendientes?\n"
            "  • ¿Cuándo vence mi declaración de IVA?\n"
            "  • Revisar estado de mis obligaciones\n\n"
            "También puedes enviar:\n"
            "  ESTADO — para ver el estado del sistema\n"
            "  INFO   — para más información sobre SOMER"
        )

    if texto_norm in _COMANDOS_ESTADO:
        sri_msg = ""
        if usuario_sri:
            sri_msg = f"\nUsuario identificado: {nombre} (RUC {usuario_sri['ruc']})"
        return (
            "Estado del sistema SOMER: Activo\n"
            "Canal WhatsApp: Operativo\n"
            "Motor de agente: En línea"
            + sri_msg
        )

    if texto_norm in _COMANDOS_INFO:
        return (
            f"Hola {nombre}! Soy SOMER v2.0\n\n"
            "Sistema de Gestión de Obligaciones Tributarias SRI Ecuador.\n\n"
            "Envíame tus consultas en lenguaje natural y te responderé "
            "con información actualizada sobre tus obligaciones fiscales.\n\n"
            "Escribe AYUDA para ver los comandos disponibles."
        )

    return None


# ── Handler principal ─────────────────────────────────────────


class WhatsAppMessageHandler:
    """Procesa eventos de mensajes WhatsApp entrantes.

    Para cada evento de tipo "message":
      1. Identifica si el remitente es un usuario SRI registrado.
      2. Si es un comando simple (AYUDA, ESTADO, INFO), responde automáticamente.
      3. Si no, encola el mensaje para que el agente SOMER lo procese.

    Los eventos de tipo "status" (delivered, read, sent, failed) solo se
    registran en el log sin procesamiento adicional.

    Atributos:
        auto_reply: Si es True (default), responde automáticamente a comandos
                    simples usando WhatsAppSender.
        queue:      Cola asyncio donde se depositan los mensajes para el agente.
    """

    def __init__(self, auto_reply: bool = True) -> None:
        self.auto_reply = auto_reply
        self.queue = get_incoming_queue()

    async def handle(self, evento: Dict[str, Any]) -> None:
        """Punto de entrada principal para procesar un evento estructurado.

        Detecta el tipo del evento y delega al método correspondiente.

        Args:
            evento: Dict estructurado producido por WhatsAppWebhook.process_event()
                    o parse_whatsapp_messages(). Debe tener al menos la clave "type".
        """
        tipo = evento.get("type", "")

        if tipo == "message":
            await self._handle_message(evento)
        elif tipo == "status":
            self._handle_status(evento)
        else:
            logger.debug("Evento de tipo desconocido ignorado: %s", tipo)

    async def _handle_message(self, evento: Dict[str, Any]) -> None:
        """Procesa un mensaje entrante de WhatsApp.

        Flujo:
          1. Extraer datos del evento.
          2. Marcar el mensaje como recibido en el log.
          3. Buscar usuario SRI por número de teléfono.
          4. Si es comando simple → responder automáticamente.
          5. Si no → encolar para que el agente lo procese.

        Args:
            evento: Dict de tipo "message" con keys: from, text, message_id,
                    message_type, contact_name, phone_number_id, timestamp.
        """
        numero = evento.get("from", "")
        texto = evento.get("text", "")
        message_id = evento.get("message_id", "")
        message_type = evento.get("message_type", "text")
        contact_name = evento.get("contact_name", "")

        # Ofuscar datos sensibles en los logs: mostrar solo últimos 4 dígitos
        numero_ofuscado = ("*****" + numero[-4:]) if len(numero) >= 4 else "*****"
        logger.debug(
            "Mensaje entrante WhatsApp — de=%s, tipo=%s, id=%s",
            numero_ofuscado,
            message_type,
            message_id,
        )

        # Verificar whitelist de números autorizados
        authorized = get_authorized_numbers()
        if authorized and numero not in authorized:
            logger.info("Número no autorizado ignorado: %s", numero_ofuscado)
            return  # Ignora silenciosamente — no responde nada

        # Buscar usuario SRI
        usuario_sri = _buscar_usuario_sri(numero)
        if usuario_sri:
            ruc = usuario_sri["ruc"] or ""
            ruc_ofuscado = ("*****" + ruc[-4:]) if len(ruc) >= 4 else "*****"
            logger.debug(
                "Usuario SRI identificado: RUC=%s",
                ruc_ofuscado,
            )
        else:
            logger.debug(
                "Número %s no encontrado en sri_credentials.db", numero_ofuscado
            )

        # Solo procesar mensajes de texto para respuestas automáticas
        if message_type == "text" and texto and self.auto_reply:
            respuesta = _generar_respuesta_automatica(texto, usuario_sri)
            if respuesta:
                await self._responder(numero, respuesta)
                return

        # Encolar para procesamiento por el agente SOMER
        entrada_cola: Dict[str, Any] = {
            "from_number": numero,
            "contact_name": contact_name,
            "message_id": message_id,
            "message_type": message_type,
            "text": texto,
            "timestamp": evento.get("timestamp", ""),
            "phone_number_id": evento.get("phone_number_id", ""),
            "usuario_sri": usuario_sri,
            "raw": evento.get("raw", {}),
        }

        try:
            self.queue.put_nowait(entrada_cola)
            logger.debug(
                "Mensaje de %s encolado para agente SOMER (cola size=%d)",
                numero,
                self.queue.qsize(),
            )
        except asyncio.QueueFull:
            logger.warning(
                "Cola de mensajes llena — mensaje de %s descartado", numero
            )

    def _handle_status(self, evento: Dict[str, Any]) -> None:
        """Registra una actualización de estado de entrega en el log.

        Los estados (sent, delivered, read, failed) no requieren procesamiento
        adicional salvo en caso de fallo, donde se emite una advertencia.

        Args:
            evento: Dict de tipo "status" con keys: status, message_id,
                    recipient_id, timestamp, phone_number_id, error (opcional).
        """
        estado = evento.get("status", "")
        msg_id = evento.get("message_id", "")
        destinatario = evento.get("recipient_id", "")

        if estado == "failed":
            error = evento.get("error", {})
            logger.warning(
                "Entrega fallida — message_id=%s, destinatario=%s, error=%s",
                msg_id,
                destinatario,
                error,
            )
        else:
            logger.debug(
                "Estado de mensaje: %s — id=%s, destinatario=%s",
                estado,
                msg_id,
                destinatario,
            )

    async def _responder(self, numero: str, texto: str) -> None:
        """Envía una respuesta de texto al número indicado.

        Usa WhatsAppSender (async) para enviar el mensaje. Los errores
        se capturan y registran sin propagar al caller.

        Args:
            numero: Número de WhatsApp destino (ej: "593987654321").
            texto:  Texto del mensaje a enviar.
        """
        try:
            from channels.whatsapp.sender import WhatsAppSender

            sender = WhatsAppSender()
            resultado = await sender.send_text(numero, texto)

            if resultado.get("success"):
                logger.info(
                    "Respuesta automática enviada a %s (HTTP %s)",
                    numero,
                    resultado.get("http_code"),
                )
            else:
                logger.warning(
                    "Fallo al enviar respuesta automática a %s: %s",
                    numero,
                    resultado,
                )
        except Exception as exc:
            logger.error(
                "Error enviando respuesta automática a %s: %s", numero, exc
            )


# ── Procesador de payload completo ───────────────────────────


async def procesar_payload_whatsapp(
    payload: Dict[str, Any],
    handler: Optional[WhatsAppMessageHandler] = None,
) -> List[Dict[str, Any]]:
    """Parsea un payload de Meta y procesa todos los eventos encontrados.

    Función de alto nivel que combina WhatsAppWebhook.process_event()
    con WhatsAppMessageHandler para procesar un payload completo en un
    solo paso.

    Args:
        payload: Payload JSON completo recibido del webhook de Meta.
        handler: Instancia de WhatsAppMessageHandler a usar. Si es None,
                 crea una nueva instancia con configuración por defecto.

    Returns:
        Lista de eventos estructurados procesados (misma lista que
        WhatsAppWebhook.process_event() retorna).
    """
    from channels.whatsapp.webhook import WhatsAppWebhook

    webhook = WhatsAppWebhook()
    eventos = webhook.process_event(payload)

    if handler is None:
        handler = WhatsAppMessageHandler()

    for evento in eventos:
        await handler.handle(evento)

    return eventos
