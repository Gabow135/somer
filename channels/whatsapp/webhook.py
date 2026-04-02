"""Webhook y servidor de webhook para WhatsApp Business Cloud API (Meta).

Provee dos abstracciones complementarias:

1. ``WhatsAppWebhook`` — clase liviana para verificación y parsing de eventos.
   Útil para integrar en cualquier framework web (FastAPI, Flask, aiohttp, etc.)
   sin levantar un servidor propio.

2. ``WhatsAppWebhookServer`` — servidor aiohttp integrado que recibe los
   webhooks de Meta en un puerto dedicado.

Meta requiere dos tipos de requests:
  - GET  /webhook  → verificación inicial del endpoint (hub.challenge)
  - POST /webhook  → mensajes y eventos entrantes

Principio crítico: Meta espera un HTTP 200 OK inmediato (< 5s).
El procesamiento real se hace en background para no bloquear la respuesta.

Estructura del payload entrante de Meta:
    {
      "object": "whatsapp_business_account",
      "entry": [{
        "id": "BUSINESS_ACCOUNT_ID",
        "changes": [{
          "value": {
            "messaging_product": "whatsapp",
            "metadata": {...},
            "contacts": [...],
            "messages": [{...}],
            "statuses": [{...}]   # opcionales: delivered, read, sent
          },
          "field": "messages"
        }]
      }]
    }
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Awaitable, Callable, Dict, List, Optional

from channels.whatsapp.security import verify_signature

logger = logging.getLogger(__name__)

# Tipo del callback que recibirá los mensajes ya parseados
MessageHandler = Callable[[Dict[str, Any]], Awaitable[None]]


class WhatsAppWebhook:
    """Clase liviana para verificación y procesamiento de webhooks de Meta/WhatsApp.

    No levanta ningún servidor — se integra en cualquier framework web
    (FastAPI, Flask, aiohttp, Django, etc.) pasando los parámetros o el
    payload al método correspondiente.

    El token de verificación se lee desde la variable de entorno
    WHATSAPP_VERIFY_TOKEN, o puede pasarse directamente en el constructor.

    Uso con FastAPI::

        webhook = WhatsAppWebhook()

        @app.get("/webhook/whatsapp")
        def verificar(hub_mode, hub_verify_token, hub_challenge):
            return webhook.verify_webhook(hub_mode, hub_verify_token, hub_challenge)

        @app.post("/webhook/whatsapp")
        async def recibir(request: Request):
            payload = await request.json()
            eventos = webhook.process_event(payload)
            for evento in eventos:
                print(evento)
            return {"status": "ok"}
    """

    def __init__(self, verify_token: Optional[str] = None) -> None:
        """Inicializa el webhook con el token de verificación.

        Args:
            verify_token: Token secreto para verificación del webhook de Meta.
                          Si es None, se lee desde la variable de entorno
                          WHATSAPP_VERIFY_TOKEN.
        """
        self._verify_token: str = verify_token or os.environ.get(
            "WHATSAPP_VERIFY_TOKEN", ""
        )

    def verify_webhook(
        self,
        mode: str,
        token: str,
        challenge: str,
    ) -> Optional[str]:
        """Verifica el challenge de Meta para activar el webhook.

        Meta envía una solicitud GET con estos parámetros al configurar
        el webhook en el panel de Meta Developers. Se debe responder
        con el valor de hub.challenge si el token coincide.

        Args:
            mode:      Valor de hub.mode (debe ser "subscribe").
            token:     Valor de hub.verify_token enviado por Meta.
            challenge: Valor de hub.challenge enviado por Meta.

        Returns:
            El valor del challenge si la verificación es exitosa,
            None si el token no coincide o el modo es incorrecto.
        """
        if mode == "subscribe" and token == self._verify_token:
            logger.info("Webhook de WhatsApp verificado correctamente")
            return challenge

        logger.warning(
            "Verificación de webhook fallida: mode=%s, token_match=%s",
            mode, token == self._verify_token,
        )
        return None

    def process_event(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Procesa un payload de evento de Meta y retorna eventos estructurados.

        Extrae mensajes de texto, templates, media, mensajes interactivos y
        actualizaciones de estado (sent, delivered, read, failed).

        Args:
            payload: Diccionario con el payload JSON completo recibido por POST
                     en el endpoint del webhook.

        Returns:
            Lista de dicts estructurados. Cada elemento tiene la forma:

            Para mensajes::

                {
                    "type": "message",
                    "from": "593987654321",
                    "message_id": "wamid.xxx",
                    "timestamp": "1712345678",
                    "message_type": "text" | "image" | "audio" | ...,
                    "text": "Hola!",           # texto extraído o descripción
                    "contact_name": "Juan",
                    "phone_number_id": "123456",
                    "raw": {...},              # mensaje original de Meta
                }

            Para estados de entrega::

                {
                    "type": "status",
                    "message_id": "wamid.xxx",
                    "status": "sent" | "delivered" | "read" | "failed",
                    "timestamp": "1712345678",
                    "recipient_id": "593987654321",
                    "phone_number_id": "123456",
                    "error": {...},            # solo presente en status "failed"
                }
        """
        if payload.get("object") != "whatsapp_business_account":
            logger.debug(
                "Evento ignorado (object=%s)", payload.get("object")
            )
            return []

        eventos: List[Dict[str, Any]] = []

        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                if change.get("field") != "messages":
                    continue

                value: Dict[str, Any] = change.get("value", {})
                metadata: Dict[str, Any] = value.get("metadata", {})
                phone_number_id: str = metadata.get("phone_number_id", "")

                # Mapa wa_id → nombre de perfil
                contactos: Dict[str, str] = {}
                for c in value.get("contacts", []):
                    wa_id = c.get("wa_id", "")
                    nombre = c.get("profile", {}).get("name", "")
                    if wa_id:
                        contactos[wa_id] = nombre

                # ── Mensajes entrantes ─────────────────────────────
                for msg in value.get("messages", []):
                    remitente: str = msg.get("from", "")
                    msg_id: str = msg.get("id", "")
                    timestamp: str = msg.get("timestamp", "")
                    tipo: str = msg.get("type", "unknown")
                    contenido: str = _extraer_contenido(msg, tipo)

                    eventos.append({
                        "type": "message",
                        "from": remitente,
                        "message_id": msg_id,
                        "timestamp": timestamp,
                        "message_type": tipo,
                        "text": contenido,
                        "contact_name": contactos.get(remitente, ""),
                        "phone_number_id": phone_number_id,
                        "raw": msg,
                    })

                # ── Actualizaciones de estado ──────────────────────
                for status in value.get("statuses", []):
                    evento_status: Dict[str, Any] = {
                        "type": "status",
                        "message_id": status.get("id", ""),
                        "status": status.get("status", ""),
                        "timestamp": status.get("timestamp", ""),
                        "recipient_id": status.get("recipient_id", ""),
                        "phone_number_id": phone_number_id,
                    }
                    # Incluir info de error si el estado es "failed"
                    if status.get("errors"):
                        evento_status["error"] = status["errors"][0]

                    eventos.append(evento_status)

        return eventos


class WhatsAppWebhookServer:
    """Servidor aiohttp que maneja los webhooks de Meta/WhatsApp.

    Expone:
      GET  {webhook_path}  → verificación de webhook
      POST {webhook_path}  → mensajes y eventos entrantes

    Args:
        on_message:   Callback async que recibe el payload completo de Meta.
        port:         Puerto donde escuchar (default 8099).
        host:         Host donde escuchar (default "0.0.0.0").
        webhook_path: Ruta del endpoint (default "/webhook/whatsapp").
        verify_token: Token secreto para verificación. Si es None, lee
                      WHATSAPP_VERIFY_TOKEN del entorno.
    """

    def __init__(
        self,
        on_message: MessageHandler,
        port: int = 8099,
        host: str = "0.0.0.0",
        webhook_path: str = "/webhook/whatsapp",
        verify_token: Optional[str] = None,
    ) -> None:
        self._on_message = on_message
        self._port = port
        self._host = host
        self._webhook_path = webhook_path
        self._verify_token: str = verify_token or os.environ.get(
            "WHATSAPP_VERIFY_TOKEN", ""
        )
        self._runner: Any = None   # aiohttp.web.AppRunner
        self._site: Any = None     # aiohttp.web.TCPSite
        self._app: Any = None      # aiohttp.web.Application

    # ── Ciclo de vida ─────────────────────────────────────────

    async def start(self) -> None:
        """Construye la app aiohttp y arranca el servidor TCP."""
        try:
            from aiohttp import web
        except ImportError:
            raise RuntimeError(
                "aiohttp no instalado. Ejecuta: pip install aiohttp"
            )

        self._app = web.Application()
        self._app.router.add_get(self._webhook_path, self._handle_get)
        self._app.router.add_post(self._webhook_path, self._handle_post)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self._host, self._port)
        await self._site.start()

        logger.info(
            "WhatsApp webhook escuchando en http://%s:%d%s",
            self._host, self._port, self._webhook_path,
        )

    async def stop(self) -> None:
        """Detiene el servidor limpiamente."""
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
            self._site = None
        logger.info("WhatsApp webhook detenido")

    # ── Handlers HTTP ─────────────────────────────────────────

    async def _handle_get(self, request: Any) -> Any:
        """GET → verificación de webhook según protocolo de Meta.

        Meta envía:
          ?hub.mode=subscribe
          &hub.verify_token=<el_token_que_configuramos>
          &hub.challenge=<número_aleatorio>

        Debemos responder con hub.challenge para confirmar la propiedad.
        """
        from aiohttp import web

        mode = request.rel_url.query.get("hub.mode", "")
        token = request.rel_url.query.get("hub.verify_token", "")
        challenge = request.rel_url.query.get("hub.challenge", "")

        if mode == "subscribe" and token == self._verify_token:
            logger.info("Webhook de WhatsApp verificado correctamente")
            return web.Response(text=challenge, status=200)

        logger.warning(
            "Verificación de webhook fallida: mode=%s, token_match=%s",
            mode, token == self._verify_token,
        )
        return web.Response(text="Forbidden", status=403)

    async def _handle_post(self, request: Any) -> Any:
        """POST → mensajes y eventos entrantes de Meta.

        CRÍTICO: responder 200 OK inmediatamente, antes de cualquier
        procesamiento. Meta reintentará si no recibe 200 en < 5 segundos.

        Retorna HTTP 403 si la firma HMAC-SHA256 no es válida.
        """
        from aiohttp import web

        # 1. Leer body raw ANTES de parsear JSON
        raw_body = await request.read()

        # 2. Verificar firma HMAC
        sig_header = request.headers.get("X-Hub-Signature-256")
        if not verify_signature(raw_body, sig_header):
            logger.warning(
                "POST /webhook — firma inválida rechazada (IP: %s)",
                request.remote,
            )
            return web.json_response({"error": "firma invalida"}, status=403)

        # 3. Ahora sí parsear el JSON
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            logger.warning("Payload de webhook no es JSON válido: %s", exc)
            return web.json_response({"error": "payload invalido"}, status=400)

        # Verificar que es un evento de WhatsApp
        if payload.get("object") != "whatsapp_business_account":
            logger.debug("Evento ignorado (object=%s)", payload.get("object"))
            return web.Response(text="OK", status=200)

        # Despachar procesamiento en background — no bloquear la respuesta
        asyncio.create_task(self._process_payload_safe(payload))

        return web.Response(text="OK", status=200)

    # ── Procesamiento interno ─────────────────────────────────

    async def _process_payload_safe(self, payload: Dict[str, Any]) -> None:
        """Ejecuta el callback de mensajes capturando excepciones.

        Envuelto en try/except para que errores en el procesamiento no
        crasheen el servidor de webhook.
        """
        try:
            await self._on_message(payload)
        except Exception:
            logger.exception("Error procesando webhook de WhatsApp")


def parse_whatsapp_messages(payload: Dict[str, Any]) -> list[Dict[str, Any]]:
    """Extrae y normaliza todos los mensajes del payload de Meta.

    Soporta los tipos de mensaje de WhatsApp:
      - text         → mensaje de texto plano
      - image        → imagen
      - audio        → audio
      - video        → video
      - document     → documento/archivo
      - sticker      → sticker
      - location     → ubicación GPS
      - contacts     → tarjeta(s) de contacto
      - interactive  → respuestas a botones/listas
      - template     → respuestas a templates
      - reaction     → reacción a un mensaje
      - unsupported  → tipo no soportado (fallback)

    Args:
        payload: Payload completo de Meta tal como llega al webhook.

    Returns:
        Lista de dicts normalizados con:
          - from_number: número del remitente
          - message_id:  wamid del mensaje
          - timestamp:   unix timestamp como string
          - type:        tipo de mensaje
          - content:     texto extraído o descripción
          - raw:         dict original del mensaje para acceso a campos extra
          - contact_name: nombre del contacto (de la sección contacts[])
          - phone_number_id: phone number ID del receptor (de metadata)
    """
    mensajes: list[Dict[str, Any]] = []

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "messages":
                continue

            value: Dict[str, Any] = change.get("value", {})

            # Mapa de contactos wa_id → nombre de perfil
            contactos: Dict[str, str] = {}
            for c in value.get("contacts", []):
                wa_id = c.get("wa_id", "")
                nombre = c.get("profile", {}).get("name", "")
                if wa_id:
                    contactos[wa_id] = nombre

            # Metadata del receptor
            metadata_receptor = value.get("metadata", {})
            phone_number_id = metadata_receptor.get("phone_number_id", "")

            for msg in value.get("messages", []):
                remitente = msg.get("from", "")
                msg_id = msg.get("id", "")
                timestamp = msg.get("timestamp", "")
                tipo = msg.get("type", "unknown")

                # Extraer contenido según el tipo
                contenido = _extraer_contenido(msg, tipo)

                mensajes.append({
                    "from_number": remitente,
                    "message_id": msg_id,
                    "timestamp": timestamp,
                    "type": tipo,
                    "content": contenido,
                    "raw": msg,
                    "contact_name": contactos.get(remitente, ""),
                    "phone_number_id": phone_number_id,
                })

    return mensajes


def _extraer_contenido(msg: Dict[str, Any], tipo: str) -> str:
    """Extrae el texto o descripción relevante de un mensaje según su tipo.

    Args:
        msg:  Dict del mensaje individual de Meta.
        tipo: Tipo de mensaje (text, image, audio, etc.)

    Returns:
        String con el contenido más útil para el agente.
    """
    if tipo == "text":
        return msg.get("text", {}).get("body", "")

    if tipo == "image":
        caption = msg.get("image", {}).get("caption", "")
        media_id = msg.get("image", {}).get("id", "")
        return caption or f"[Imagen recibida, media_id={media_id}]"

    if tipo == "audio":
        media_id = msg.get("audio", {}).get("id", "")
        return f"[Audio recibido, media_id={media_id}]"

    if tipo == "video":
        caption = msg.get("video", {}).get("caption", "")
        media_id = msg.get("video", {}).get("id", "")
        return caption or f"[Video recibido, media_id={media_id}]"

    if tipo == "document":
        filename = msg.get("document", {}).get("filename", "")
        caption = msg.get("document", {}).get("caption", "")
        media_id = msg.get("document", {}).get("id", "")
        nombre = filename or f"media_id={media_id}"
        return caption or f"[Documento: {nombre}]"

    if tipo == "sticker":
        media_id = msg.get("sticker", {}).get("id", "")
        return f"[Sticker recibido, media_id={media_id}]"

    if tipo == "location":
        loc = msg.get("location", {})
        lat = loc.get("latitude", "?")
        lon = loc.get("longitude", "?")
        nombre = loc.get("name", "")
        return (
            f"[Ubicación: {nombre} ({lat}, {lon})]"
            if nombre
            else f"[Ubicación: ({lat}, {lon})]"
        )

    if tipo == "contacts":
        nombres = []
        for c in msg.get("contacts", []):
            nombre = c.get("name", {}).get("formatted_name", "Contacto")
            nombres.append(nombre)
        return f"[Contacto(s) recibido(s): {', '.join(nombres)}]"

    if tipo == "interactive":
        interactive = msg.get("interactive", {})
        sub_tipo = interactive.get("type", "")
        if sub_tipo == "button_reply":
            titulo = interactive.get("button_reply", {}).get("title", "")
            return f"[Botón presionado: {titulo}]"
        if sub_tipo == "list_reply":
            titulo = interactive.get("list_reply", {}).get("title", "")
            desc = interactive.get("list_reply", {}).get("description", "")
            return f"[Lista seleccionada: {titulo}] {desc}".strip()
        return f"[Respuesta interactiva: {sub_tipo}]"

    if tipo == "template":
        # Las respuestas a templates suelen ser texto o botones
        return msg.get("text", {}).get("body", "[Respuesta de template]")

    if tipo == "reaction":
        emoji = msg.get("reaction", {}).get("emoji", "")
        msg_id_orig = msg.get("reaction", {}).get("message_id", "")
        return f"[Reacción {emoji} al mensaje {msg_id_orig}]"

    # Tipo desconocido — devolver descripción genérica
    return f"[Mensaje de tipo '{tipo}' recibido]"
