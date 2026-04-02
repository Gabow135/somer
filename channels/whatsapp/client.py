"""Cliente HTTP para WhatsApp Business Cloud API (Meta Graph API v20.0).

Todas las credenciales se leen exclusivamente desde variables de entorno —
nunca se hardcodean valores en este archivo.

Variables de entorno soportadas (en orden de prioridad):
  - WHATSAPP_ACCESS_TOKEN  → nombre canónico preferido
  - WHATSAPP_TOKEN         → alias heredado (retrocompatibilidad)
  - WHATSAPP_PHONE_NUMBER_ID → ID del número de teléfono de negocio
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────

GRAPH_API_VERSION = "v20.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

# Plantilla por defecto para notificaciones de roles (Ecuador)
DEFAULT_TEMPLATE_NAME = "dtirols"
DEFAULT_TEMPLATE_LANGUAGE = "es_EC"


class WhatsAppClient:
    """Cliente async para la WhatsApp Cloud API (Meta Graph API v20.0).

    Carga credenciales desde variables de entorno:
      - WHATSAPP_ACCESS_TOKEN o WHATSAPP_TOKEN → token de acceso de la app de Meta
      - WHATSAPP_PHONE_NUMBER_ID               → ID del número de teléfono de negocio
      - WHATSAPP_BUSINESS_ACCOUNT_ID           → ID de la cuenta de negocio (opcional)

    Uso básico:
        client = WhatsAppClient()
        await client.start()
        await client.send_text("+593987654321", "Hola!")
        await client.send_template("+593987654321", "Empresa S.A.", "Su rol es...")
        await client.stop()
    """

    def __init__(
        self,
        token: Optional[str] = None,
        phone_number_id: Optional[str] = None,
        business_account_id: Optional[str] = None,
    ) -> None:
        # WHATSAPP_ACCESS_TOKEN tiene prioridad; WHATSAPP_TOKEN como alias heredado
        self._token: Optional[str] = (
            token
            or os.environ.get("WHATSAPP_ACCESS_TOKEN")
            or os.environ.get("WHATSAPP_TOKEN")
        )
        self._phone_number_id: Optional[str] = phone_number_id or os.environ.get(
            "WHATSAPP_PHONE_NUMBER_ID"
        )
        self._business_account_id: Optional[str] = (
            business_account_id or os.environ.get("WHATSAPP_BUSINESS_ACCOUNT_ID")
        )
        self._http: Any = None  # httpx.AsyncClient

    # ── Ciclo de vida ─────────────────────────────────────────

    async def start(self) -> None:
        """Inicializa el cliente HTTP."""
        try:
            import httpx
        except ImportError:
            raise RuntimeError(
                "httpx no instalado. Ejecuta: pip install httpx"
            )
        self._http = httpx.AsyncClient(
            base_url=GRAPH_API_BASE,
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=30.0,
        )
        logger.debug("WhatsAppClient iniciado (phone_number_id=%s)", self._phone_number_id)

    async def stop(self) -> None:
        """Cierra el cliente HTTP."""
        if self._http:
            await self._http.aclose()
            self._http = None
        logger.debug("WhatsAppClient detenido")

    # ── Propiedades ───────────────────────────────────────────

    @property
    def phone_number_id(self) -> Optional[str]:
        return self._phone_number_id

    # ── Métodos de envío ──────────────────────────────────────

    async def send_text_message(self, to: str, text: str) -> Dict[str, Any]:
        """Envía un mensaje de texto plano a un número de WhatsApp.

        Args:
            to:   Número destino en formato internacional sin '+' (ej: "521234567890").
            text: Cuerpo del mensaje (máx 65536 caracteres).

        Returns:
            Respuesta JSON de la API de Meta.
        """
        payload: Dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": text,
            },
        }
        return await self._post_message(payload)

    # ── Métodos de conveniencia (API simplificada) ────────────

    async def send_text(self, celular: str, mensaje: str) -> Dict[str, Any]:
        """Envía un mensaje de texto simple a un número de WhatsApp.

        Alias de alto nivel de send_text_message con nombre más descriptivo.

        Args:
            celular: Número destino en formato internacional (ej: "+593987654321"
                     o "593987654321" — el '+' se normaliza automáticamente).
            mensaje: Cuerpo del mensaje de texto (máx 65536 caracteres).

        Returns:
            Respuesta JSON de la API de Meta con el wamid asignado.
        """
        numero = celular.lstrip("+")
        return await self.send_text_message(to=numero, text=mensaje)

    async def send_template(
        self,
        celular: str,
        razonsocial: str,
        body_text: str,
        template_name: str = DEFAULT_TEMPLATE_NAME,
        language: str = DEFAULT_TEMPLATE_LANGUAGE,
    ) -> Dict[str, Any]:
        """Envía una notificación usando la plantilla 'dtirols' (o cualquier template).

        Construye los componentes header + body según la estructura esperada
        por el template aprobado en Meta Business Manager.

        Equivalente Python del payload PHP de referencia::

            {
              "template": {
                "name": "dtirols",
                "language": {"code": "es_EC"},
                "components": [
                  {"type": "header", "parameters": [{"type": "text", "text": razonsocial}]},
                  {"type": "body",   "parameters": [{"type": "text", "text": body_text}]}
                ]
              }
            }

        Args:
            celular:       Número destino en formato internacional
                           (ej: "+593987654321" o "593987654321").
            razonsocial:   Texto para el parámetro del header de la plantilla.
            body_text:     Texto para el parámetro del body de la plantilla.
            template_name: Nombre del template aprobado en Meta (default: "dtirols").
            language:      Código de idioma del template (default: "es_EC").

        Returns:
            Respuesta JSON de la API de Meta con el wamid asignado.

        Raises:
            RuntimeError: Si el cliente no ha sido iniciado con start().
            httpx.HTTPStatusError: Si la API devuelve un código de error HTTP.
        """
        numero = celular.lstrip("+")

        components: List[Dict[str, Any]] = [
            {
                "type": "header",
                "parameters": [{"type": "text", "text": razonsocial}],
            },
            {
                "type": "body",
                "parameters": [{"type": "text", "text": body_text}],
            },
        ]

        logger.info(
            "Enviando template '%s' a %s (razonsocial=%r)",
            template_name,
            numero,
            razonsocial,
        )
        return await self.send_template_message(
            to=numero,
            template_name=template_name,
            language=language,
            components=components,
        )

    async def send_template_message(
        self,
        to: str,
        template_name: str,
        language: str = "es",
        components: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Envía un mensaje usando una plantilla (template) aprobada por Meta.

        Necesario para iniciar conversaciones o enviar notificaciones proactivas
        fuera de la ventana de 24 horas.

        Args:
            to:            Número destino.
            template_name: Nombre de la plantilla aprobada en Meta Business.
            language:      Código de idioma (ej: "es", "en_US").
            components:    Componentes de la plantilla (variables, botones, etc.).

        Returns:
            Respuesta JSON de la API de Meta.
        """
        payload: Dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language},
            },
        }
        if components:
            payload["template"]["components"] = components
        return await self._post_message(payload)

    async def send_reaction(
        self,
        to: str,
        message_id: str,
        emoji: str,
    ) -> Dict[str, Any]:
        """Envía una reacción emoji a un mensaje específico.

        Args:
            to:         Número destino.
            message_id: ID del mensaje al que reaccionar (wamid.xxx).
            emoji:      Emoji de la reacción (ej: "👍").

        Returns:
            Respuesta JSON de la API de Meta.
        """
        payload: Dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "reaction",
            "reaction": {
                "message_id": message_id,
                "emoji": emoji,
            },
        }
        return await self._post_message(payload)

    async def mark_as_read(self, message_id: str) -> Dict[str, Any]:
        """Marca un mensaje como leído (envía estado 'read' a Meta).

        Esto elimina el contador de mensajes no leídos en el dispositivo del usuario.

        Args:
            message_id: ID del mensaje a marcar como leído (wamid.xxx).

        Returns:
            Respuesta JSON de la API de Meta.
        """
        if not self._http:
            raise RuntimeError("Cliente no iniciado. Llama start() primero.")
        payload: Dict[str, Any] = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }
        resp = await self._http.post(
            f"/{self._phone_number_id}/messages",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()

    async def get_media_url(self, media_id: str) -> str:
        """Obtiene la URL temporal de descarga de un media recibido.

        La URL caduca después de 5 minutos — descargar inmediatamente.

        Args:
            media_id: ID del media recibido en el webhook (ej: "1234567890").

        Returns:
            URL de descarga del archivo media.

        Raises:
            RuntimeError: Si no se puede obtener la URL.
        """
        if not self._http:
            raise RuntimeError("Cliente no iniciado. Llama start() primero.")
        resp = await self._http.get(f"/{media_id}")
        resp.raise_for_status()
        data = resp.json()
        url = data.get("url")
        if not url:
            raise RuntimeError(f"No se encontró URL para media_id={media_id}")
        return str(url)

    async def download_media(self, media_id: str) -> bytes:
        """Descarga el contenido binario de un media.

        Primero obtiene la URL temporal con get_media_url(), luego descarga
        el archivo con la cabecera de autorización correcta.

        Args:
            media_id: ID del media a descargar.

        Returns:
            Bytes del archivo descargado.
        """
        url = await self.get_media_url(media_id)
        if not self._http:
            raise RuntimeError("Cliente no iniciado. Llama start() primero.")
        # La URL de media requiere el mismo token de autorización
        resp = await self._http.get(url)
        resp.raise_for_status()
        return resp.content

    async def upload_media(self, file_path: str, mime_type: str) -> str:
        """Sube un archivo local a los servidores de Meta y devuelve su media_id.

        Args:
            file_path: Ruta al archivo local a subir.
            mime_type: Tipo MIME del archivo (ej: "image/jpeg", "application/pdf").

        Returns:
            media_id asignado por Meta para usar en mensajes posteriores.
        """
        import mimetypes
        from pathlib import Path

        if not self._http:
            raise RuntimeError("Cliente no iniciado. Llama start() primero.")

        fname = Path(file_path).name
        with open(file_path, "rb") as f:
            resp = await self._http.post(
                f"/{self._phone_number_id}/media",
                files={"file": (fname, f, mime_type)},
                data={"messaging_product": "whatsapp"},
            )
        resp.raise_for_status()
        return str(resp.json()["id"])

    # ── Internos ──────────────────────────────────────────────

    async def _post_message(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Ejecuta un POST al endpoint de mensajes de la Graph API.

        Args:
            payload: Diccionario con el cuerpo del mensaje según la API de Meta.

        Returns:
            Respuesta JSON de la API.

        Raises:
            RuntimeError: Si el cliente no ha sido iniciado.
            httpx.HTTPStatusError: Si la API devuelve un código de error.
        """
        if not self._http:
            raise RuntimeError("Cliente no iniciado. Llama start() primero.")
        resp = await self._http.post(
            f"/{self._phone_number_id}/messages",
            json=payload,
        )
        resp.raise_for_status()
        result: Dict[str, Any] = resp.json()
        logger.debug(
            "WhatsApp API response: wamid=%s",
            result.get("messages", [{}])[0].get("id", "?"),
        )
        return result
