"""Módulo de envío de mensajes WhatsApp Business Cloud API para SOMER 2.0.

Proporciona funciones síncronas y una clase async para enviar mensajes,
templates, media y marcar mensajes como leídos via Meta Graph API.

Credenciales cargadas EXCLUSIVAMENTE desde variables de entorno — nunca
se hardcodean valores en este archivo.

Variables de entorno requeridas:
    WHATSAPP_ACCESS_TOKEN     Token de acceso de la Meta App
    WHATSAPP_PHONE_NUMBER_ID  ID del número de teléfono de negocio

Variables de entorno opcionales:
    WHATSAPP_API_VERSION      Versión de la API (default: "v20.0")
    WHATSAPP_TOKEN            Alias heredado del token (retrocompatibilidad)
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _load_dotenv() -> None:
    """Carga ~/.somer/.env en os.environ si el archivo existe.

    Solo setea variables que no estén ya definidas en el entorno, de modo
    que los valores del shell siempre tienen precedencia sobre el archivo.
    """
    env_path = os.path.join(os.path.expanduser("~"), ".somer", ".env")
    if not os.path.isfile(env_path):
        return
    try:
        with open(env_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if key and key not in os.environ:
                    os.environ[key] = value
    except Exception as exc:  # pragma: no cover
        logger.warning("No se pudo cargar %s: %s", env_path, exc)


_load_dotenv()

# ── Credenciales y constantes ──────────────────────────────────────────────────

WHATSAPP_ACCESS_TOKEN: str = (
    os.getenv("WHATSAPP_ACCESS_TOKEN")
    or os.getenv("WHATSAPP_TOKEN")
    or ""
)
WHATSAPP_PHONE_NUMBER_ID: str = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_API_VERSION: str = os.getenv("WHATSAPP_API_VERSION", "v20.0")

BASE_URL: str = (
    f"https://graph.facebook.com/{WHATSAPP_API_VERSION}"
    f"/{WHATSAPP_PHONE_NUMBER_ID}/messages"
)


def _headers() -> Dict[str, str]:
    """Construye las cabeceras HTTP con el token de autorización actual.

    Lee el token en tiempo de ejecución para respetar variables de entorno
    cargadas después de la importación del módulo.

    Returns:
        Dict con las cabeceras Authorization y Content-Type.
    """
    token = (
        os.getenv("WHATSAPP_ACCESS_TOKEN")
        or os.getenv("WHATSAPP_TOKEN")
        or WHATSAPP_ACCESS_TOKEN
    )
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _base_url() -> str:
    """Construye la URL base del endpoint de mensajes en tiempo de ejecución.

    Respeta variables de entorno cargadas después de la importación.

    Returns:
        URL completa del endpoint de mensajes de la Graph API.
    """
    version = os.getenv("WHATSAPP_API_VERSION", WHATSAPP_API_VERSION)
    phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", WHATSAPP_PHONE_NUMBER_ID)
    return f"https://graph.facebook.com/{version}/{phone_id}/messages"


# ── Funciones síncronas ────────────────────────────────────────────────────────


def send_template(
    celular: str,
    template_name: str,
    language_code: str = "es_EC",
    components: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Envía un template aprobado por Meta a un número de WhatsApp.

    Args:
        celular:       Número destino en formato internacional (ej: "593987654321").
        template_name: Nombre del template aprobado en Meta Business Manager.
        language_code: Código de idioma del template (default: "es_EC").
        components:    Lista de componentes del template (parámetros de header,
                       body, buttons, etc.). Si es None se envía sin componentes.

    Returns:
        Dict con http_code, response (JSON de Meta) y success (bool).
    """
    import httpx

    payload: Dict[str, Any] = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": celular.lstrip("+"),
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language_code},
        },
    }
    if components:
        payload["template"]["components"] = components

    try:
        with httpx.Client(timeout=30) as client:
            response = client.post(_base_url(), headers=_headers(), json=payload)

        logger.info(
            "Template '%s' enviado a %s — HTTP %d",
            template_name, celular, response.status_code,
        )
        return {
            "http_code": response.status_code,
            "response": response.json() if response.content else {},
            "success": response.status_code == 200,
        }
    except Exception as exc:
        logger.error("Error enviando template '%s' a %s: %s", template_name, celular, exc)
        return {"http_code": 0, "response": {}, "success": False, "error": str(exc)}


def send_template_dtirols(
    celular: str,
    razonsocial: str,
    body_text: str,
) -> Dict[str, Any]:
    """Envía el template 'dtirols' a un número de WhatsApp.

    Template específico con componente header (razón social) y body (texto
    del mensaje). Template debe estar aprobado en Meta Business Manager con
    idioma es_EC.

    Args:
        celular:     Número destino en formato internacional (ej: "593987654321").
        razonsocial: Texto para el parámetro del header del template.
        body_text:   Texto para el parámetro del body del template.

    Returns:
        Dict con http_code, response (JSON de Meta) y success (bool).
    """
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
    return send_template(
        celular=celular,
        template_name="dtirols",
        language_code="es_EC",
        components=components,
    )


def send_text(celular: str, text: str) -> Dict[str, Any]:
    """Envía un mensaje de texto simple a un número de WhatsApp.

    Args:
        celular: Número destino en formato internacional (ej: "593987654321").
        text:    Cuerpo del mensaje de texto (máx 65536 caracteres).

    Returns:
        Dict con http_code, response (JSON de Meta) y success (bool).
    """
    import httpx

    payload: Dict[str, Any] = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": celular.lstrip("+"),
        "type": "text",
        "text": {"preview_url": False, "body": text},
    }

    try:
        with httpx.Client(timeout=30) as client:
            response = client.post(_base_url(), headers=_headers(), json=payload)

        logger.info("Texto enviado a %s — HTTP %d", celular, response.status_code)
        return {
            "http_code": response.status_code,
            "response": response.json() if response.content else {},
            "success": response.status_code == 200,
        }
    except Exception as exc:
        logger.error("Error enviando texto a %s: %s", celular, exc)
        return {"http_code": 0, "response": {}, "success": False, "error": str(exc)}


def send_media(
    celular: str,
    media_type: str,
    media_url: str,
    caption: Optional[str] = None,
) -> Dict[str, Any]:
    """Envía un mensaje con media (imagen, video, documento, audio) por URL.

    El media debe ser accesible públicamente. Meta descarga el archivo desde
    la URL proporcionada al momento del envío.

    Args:
        celular:    Número destino en formato internacional (ej: "593987654321").
        media_type: Tipo de media: "image", "video", "document", "audio", "sticker".
        media_url:  URL pública del archivo media a enviar.
        caption:    Texto de descripción (solo para image, video, document).

    Returns:
        Dict con http_code, response (JSON de Meta) y success (bool).
    """
    import httpx

    media_payload: Dict[str, Any] = {"link": media_url}
    if caption and media_type in ("image", "video", "document"):
        media_payload["caption"] = caption

    payload: Dict[str, Any] = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": celular.lstrip("+"),
        "type": media_type,
        media_type: media_payload,
    }

    try:
        with httpx.Client(timeout=60) as client:
            response = client.post(_base_url(), headers=_headers(), json=payload)

        logger.info(
            "Media (%s) enviado a %s — HTTP %d", media_type, celular, response.status_code
        )
        return {
            "http_code": response.status_code,
            "response": response.json() if response.content else {},
            "success": response.status_code == 200,
        }
    except Exception as exc:
        logger.error("Error enviando media (%s) a %s: %s", media_type, celular, exc)
        return {"http_code": 0, "response": {}, "success": False, "error": str(exc)}


def mark_as_read(message_id: str) -> Dict[str, Any]:
    """Marca un mensaje como leído en WhatsApp (envía estado 'read' a Meta).

    Elimina el contador de mensajes no leídos en el dispositivo del remitente.

    Args:
        message_id: ID del mensaje a marcar como leído (wamid.xxx).

    Returns:
        Dict con http_code, response (JSON de Meta) y success (bool).
    """
    import httpx

    payload: Dict[str, Any] = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
    }

    try:
        with httpx.Client(timeout=15) as client:
            response = client.post(_base_url(), headers=_headers(), json=payload)

        logger.debug("Mensaje %s marcado como leído — HTTP %d", message_id, response.status_code)
        return {
            "http_code": response.status_code,
            "response": response.json() if response.content else {},
            "success": response.status_code == 200,
        }
    except Exception as exc:
        logger.error("Error marcando como leído message_id=%s: %s", message_id, exc)
        return {"http_code": 0, "response": {}, "success": False, "error": str(exc)}


# ── Clase async ────────────────────────────────────────────────────────────────


class WhatsAppSender:
    """Cliente async para enviar mensajes via WhatsApp Business Cloud API.

    Carga credenciales exclusivamente desde variables de entorno. Usa httpx
    en modo async para compatibilidad con el gateway SOMER.

    Uso básico:
        sender = WhatsAppSender()
        await sender.send("593987654321", {"type": "text", "text": {"body": "Hola!"}})
        await sender.send_text("593987654321", "Hola!")
        await sender.send_template_dtirols("593987654321", "Empresa SA", "Su pedido listo")
    """

    def __init__(self) -> None:
        self._token: str = (
            os.getenv("WHATSAPP_ACCESS_TOKEN")
            or os.getenv("WHATSAPP_TOKEN")
            or ""
        )
        self._phone_number_id: str = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
        self._api_version: str = os.getenv("WHATSAPP_API_VERSION", "v20.0")
        self._base_url: str = (
            f"https://graph.facebook.com/{self._api_version}"
            f"/{self._phone_number_id}/messages"
        )
        self._headers: Dict[str, str] = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    async def send(self, celular: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Envía un payload genérico a un número de WhatsApp.

        Método de bajo nivel que acepta cualquier estructura de payload
        válida según la Meta Graph API. Agrega automáticamente messaging_product
        y to si no están presentes.

        Args:
            celular: Número destino en formato internacional (ej: "593987654321").
            payload: Diccionario con el cuerpo del mensaje según la API de Meta.

        Returns:
            Dict con http_code, response (JSON de Meta) y success (bool).
        """
        import httpx

        payload.setdefault("messaging_product", "whatsapp")
        payload.setdefault("recipient_type", "individual")
        payload.setdefault("to", celular.lstrip("+"))

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    self._base_url, headers=self._headers, json=payload
                )

            logger.debug(
                "WhatsAppSender.send — tipo=%s, destino=%s, HTTP %d",
                payload.get("type", "?"), celular, response.status_code,
            )
            return {
                "http_code": response.status_code,
                "response": response.json() if response.content else {},
                "success": response.status_code == 200,
            }
        except Exception as exc:
            logger.error("Error en WhatsAppSender.send a %s: %s", celular, exc)
            return {"http_code": 0, "response": {}, "success": False, "error": str(exc)}

    async def send_text(self, celular: str, text: str) -> Dict[str, Any]:
        """Envía un mensaje de texto simple (async).

        Args:
            celular: Número destino en formato internacional.
            text:    Cuerpo del mensaje de texto.

        Returns:
            Dict con http_code, response y success.
        """
        payload: Dict[str, Any] = {
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }
        return await self.send(celular, payload)

    async def send_template(
        self,
        celular: str,
        template_name: str,
        language_code: str = "es_EC",
        components: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Envía un template aprobado por Meta (async).

        Args:
            celular:       Número destino en formato internacional.
            template_name: Nombre del template aprobado en Meta Business Manager.
            language_code: Código de idioma del template (default: "es_EC").
            components:    Componentes del template (header, body, buttons, etc.).

        Returns:
            Dict con http_code, response y success.
        """
        template_data: Dict[str, Any] = {
            "name": template_name,
            "language": {"code": language_code},
        }
        if components:
            template_data["components"] = components

        payload: Dict[str, Any] = {
            "type": "template",
            "template": template_data,
        }
        return await self.send(celular, payload)

    async def send_template_dtirols(
        self,
        celular: str,
        razonsocial: str,
        body_text: str,
    ) -> Dict[str, Any]:
        """Envía el template 'dtirols' con header y body (async).

        Args:
            celular:     Número destino en formato internacional.
            razonsocial: Texto para el parámetro del header del template.
            body_text:   Texto para el parámetro del body del template.

        Returns:
            Dict con http_code, response y success.
        """
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
        return await self.send_template(
            celular=celular,
            template_name="dtirols",
            language_code="es_EC",
            components=components,
        )

    async def send_media(
        self,
        celular: str,
        media_type: str,
        media_url: str,
        caption: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Envía un mensaje con media por URL (async).

        Args:
            celular:    Número destino en formato internacional.
            media_type: Tipo de media: "image", "video", "document", "audio", "sticker".
            media_url:  URL pública del archivo media a enviar.
            caption:    Texto de descripción (solo para image, video, document).

        Returns:
            Dict con http_code, response y success.
        """
        media_payload: Dict[str, Any] = {"link": media_url}
        if caption and media_type in ("image", "video", "document"):
            media_payload["caption"] = caption

        payload: Dict[str, Any] = {
            "type": media_type,
            media_type: media_payload,
        }
        return await self.send(celular, payload)

    async def mark_as_read(self, message_id: str) -> Dict[str, Any]:
        """Marca un mensaje como leído en WhatsApp (async).

        Args:
            message_id: ID del mensaje a marcar como leído (wamid.xxx).

        Returns:
            Dict con http_code, response y success.
        """
        import httpx

        payload: Dict[str, Any] = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    self._base_url, headers=self._headers, json=payload
                )
            logger.debug(
                "Mensaje %s marcado como leído — HTTP %d", message_id, response.status_code
            )
            return {
                "http_code": response.status_code,
                "response": response.json() if response.content else {},
                "success": response.status_code == 200,
            }
        except Exception as exc:
            logger.error("Error marcando como leído message_id=%s: %s", message_id, exc)
            return {"http_code": 0, "response": {}, "success": False, "error": str(exc)}


# ── Compatibilidad heredada ────────────────────────────────────────────────────

async def send_template_dtirols_async(
    celular: str,
    razonsocial: str,
    body_text: str,
) -> Dict[str, Any]:
    """Versión async de send_template_dtirols (alias de compatibilidad).

    Preferir WhatsAppSender.send_template_dtirols() para código nuevo.

    Args:
        celular:     Número destino en formato internacional.
        razonsocial: Texto para el parámetro del header del template.
        body_text:   Texto para el parámetro del body del template.

    Returns:
        Dict con http_code, response y success.
    """
    sender = WhatsAppSender()
    return await sender.send_template_dtirols(celular, razonsocial, body_text)


def send_text_message(celular: str, message: str) -> Dict[str, Any]:
    """Alias heredado de send_text — para retrocompatibilidad.

    Preferir send_text() para código nuevo.

    Args:
        celular:  Número destino en formato internacional.
        message:  Cuerpo del mensaje de texto.

    Returns:
        Dict con http_code, response y success.
    """
    return send_text(celular, message)


# ── Script standalone ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) >= 4:
        result = send_template_dtirols(
            celular=sys.argv[1],
            razonsocial=sys.argv[2],
            body_text=sys.argv[3],
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Uso: python sender.py <celular> <razonsocial> <body_text>")
        print("Ejemplo: python sender.py 593987654321 'Empresa SA' 'Su pedido #123 fue procesado'")
