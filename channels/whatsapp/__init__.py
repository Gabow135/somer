"""Canal WhatsApp Business Cloud API para SOMER 2.0.

Exporta las clases y funciones principales para envío y recepción
de mensajes via Meta Graph API.

Componentes disponibles:
  - WhatsAppPlugin      — plugin de canal para el gateway SOMER
  - WhatsAppSender      — cliente async para envío de mensajes
  - WhatsAppWebhook     — clase liviana de verificación/parseo (sin servidor propio)
  - WhatsAppWebhookServer — servidor aiohttp integrado en el gateway
  - WhatsAppServer      — servidor HTTP standalone para webhook (puerto 8080)
  - WhatsAppMessageHandler — procesador de mensajes entrantes con integración SRI
  - WhatsAppNotifier    — dispatcher de notificaciones a usuarios SRI
  - Funciones de envío  — send_text, send_template, send_media, mark_as_read
"""

from channels.whatsapp.handler import (
    WhatsAppMessageHandler,
    get_incoming_queue,
    procesar_payload_whatsapp,
)
from channels.whatsapp.notifier import WhatsAppNotifier
from channels.whatsapp.plugin import WhatsAppPlugin
from channels.whatsapp.sender import (
    WhatsAppSender,
    mark_as_read,
    send_media,
    send_template,
    send_template_dtirols,
    send_text,
)
from channels.whatsapp.server import WhatsAppServer
from channels.whatsapp.webhook import WhatsAppWebhook, WhatsAppWebhookServer

__all__ = [
    # Plugin del gateway
    "WhatsAppPlugin",
    # Cliente de envío
    "WhatsAppSender",
    # Webhook (clase liviana + servidor integrado en gateway)
    "WhatsAppWebhook",
    "WhatsAppWebhookServer",
    # Servidor standalone
    "WhatsAppServer",
    # Procesamiento de mensajes entrantes
    "WhatsAppMessageHandler",
    "get_incoming_queue",
    "procesar_payload_whatsapp",
    # Notificaciones
    "WhatsAppNotifier",
    # Funciones de envío síncronas
    "send_template",
    "send_template_dtirols",
    "send_text",
    "send_media",
    "mark_as_read",
]
