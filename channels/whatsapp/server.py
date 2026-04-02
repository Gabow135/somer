"""Servidor HTTP de webhook para WhatsApp Business Cloud API — SOMER 2.0.

Levanta un servidor aiohttp en el puerto configurado y expone dos endpoints:

  GET  /webhook  — verificación de Meta (hub.mode, hub.verify_token, hub.challenge)
  POST /webhook  — recepción de mensajes y eventos entrantes de Meta

La ruta del endpoint es configurable (default: ``/webhook``).

Principio crítico de Meta:
  El servidor DEBE responder ``HTTP 200 OK`` al POST en menos de 5 segundos.
  Todo procesamiento real se realiza en background (asyncio.create_task).

Credenciales:
  WHATSAPP_VERIFY_TOKEN cargado exclusivamente desde ~/.somer/.env o
  variables de entorno del shell — nunca hardcodeado.

Uso directo:

    from channels.whatsapp.server import WhatsAppServer

    servidor = WhatsAppServer(port=8080)
    await servidor.start()
    # ...esperar señal de parada...
    await servidor.stop()

Uso como script (ver scripts/start_whatsapp_webhook.sh):

    python3 -m channels.whatsapp.server
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Any, Optional

from channels.whatsapp.security import verify_signature

logger = logging.getLogger(__name__)

# ── Carga de .env ─────────────────────────────────────────────

_SOMER_DIR = Path.home() / ".somer"


def _load_env() -> None:
    """Carga ~/.somer/.env en os.environ respetando valores ya definidos.

    Las variables del shell tienen precedencia sobre el archivo .env.
    Solo carga variables que aún no estén definidas en el entorno.
    """
    env_path = _SOMER_DIR / ".env"
    if not env_path.exists():
        logger.debug(".env no encontrado en %s — usando solo variables de entorno", env_path)
        return

    try:
        with open(env_path, encoding="utf-8") as fh:
            for linea in fh:
                linea = linea.strip()
                if not linea or linea.startswith("#") or "=" not in linea:
                    continue
                clave, _, valor = linea.partition("=")
                clave = clave.strip()
                valor = valor.strip()
                # Respetar comillas simples/dobles opcionales en el valor
                if len(valor) >= 2 and valor[0] in ('"', "'") and valor[-1] == valor[0]:
                    valor = valor[1:-1]
                if clave and clave not in os.environ:
                    os.environ[clave] = valor
        logger.debug("Variables de entorno cargadas desde %s", env_path)
    except Exception as exc:
        logger.warning("No se pudo cargar %s: %s", env_path, exc)


# Cargar .env en la importación del módulo
_load_env()


# ── Servidor ──────────────────────────────────────────────────


class WhatsAppServer:
    """Servidor HTTP aiohttp para el webhook de WhatsApp Business Cloud API.

    Expone los endpoints requeridos por Meta:
      - GET  {webhook_path} → verificación del webhook
      - POST {webhook_path} → mensajes y eventos entrantes

    El token de verificación se lee de la variable de entorno
    WHATSAPP_VERIFY_TOKEN (cargada desde ~/.somer/.env si existe).

    Args:
        port:          Puerto donde escuchar (default 8080).
        host:          Host donde escuchar (default "0.0.0.0").
        webhook_path:  Ruta del endpoint (default "/webhook").
        verify_token:  Token de verificación. Si es None, lee
                       WHATSAPP_VERIFY_TOKEN del entorno.
        auto_reply:    Si es True (default), responde automáticamente
                       a comandos simples (AYUDA, ESTADO, INFO).
    """

    def __init__(
        self,
        port: int = 8080,
        host: str = "0.0.0.0",
        webhook_path: str = "/webhook",
        verify_token: Optional[str] = None,
        auto_reply: bool = True,
    ) -> None:
        self._port = port
        self._host = host
        self._webhook_path = webhook_path
        self._verify_token: str = verify_token or os.environ.get(
            "WHATSAPP_VERIFY_TOKEN", ""
        )
        self._auto_reply = auto_reply

        # Objetos de aiohttp — inicializados en start()
        self._app: Any = None       # aiohttp.web.Application
        self._runner: Any = None    # aiohttp.web.AppRunner
        self._site: Any = None      # aiohttp.web.TCPSite

        # Handler de mensajes entrantes
        self._handler: Any = None   # WhatsAppMessageHandler

    # ── Ciclo de vida ─────────────────────────────────────────

    async def start(self) -> None:
        """Construye la app aiohttp e inicia el servidor TCP.

        Raises:
            RuntimeError: Si aiohttp no está instalado.
            RuntimeError: Si WHATSAPP_VERIFY_TOKEN no está configurado.
        """
        try:
            from aiohttp import web
        except ImportError:
            raise RuntimeError(
                "aiohttp no instalado. Ejecuta: pip install aiohttp"
            )

        if not self._verify_token:
            logger.warning(
                "WHATSAPP_VERIFY_TOKEN no configurado — la verificación de Meta fallará. "
                "Agrega WHATSAPP_VERIFY_TOKEN a ~/.somer/.env"
            )

        from channels.whatsapp.handler import WhatsAppMessageHandler

        self._handler = WhatsAppMessageHandler(auto_reply=self._auto_reply)

        self._app = web.Application()
        self._app.router.add_get(self._webhook_path, self._handle_get)
        self._app.router.add_post(self._webhook_path, self._handle_post)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self._host, self._port)
        await self._site.start()

        logger.info(
            "WhatsApp webhook servidor iniciado — http://%s:%d%s",
            self._host,
            self._port,
            self._webhook_path,
        )

        try:
            from rich.console import Console
            Console().print(
                f"  [bold green]WhatsApp webhook activo:[/bold green] "
                f"http://{self._host}:{self._port}{self._webhook_path}"
            )
        except Exception:
            print(
                f"WhatsApp webhook activo: "
                f"http://{self._host}:{self._port}{self._webhook_path}"
            )

    async def stop(self) -> None:
        """Detiene el servidor HTTP limpiamente."""
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
            self._site = None
            self._app = None
        logger.info("WhatsApp webhook servidor detenido")

    # ── Handlers HTTP ─────────────────────────────────────────

    async def _handle_get(self, request: Any) -> Any:
        """GET {webhook_path} — verificación del webhook según protocolo de Meta.

        Meta envía estos parámetros al configurar el webhook en el panel de
        Meta Developers. Debemos responder con hub.challenge si el token coincide.

        Query params esperados:
          hub.mode         = "subscribe"
          hub.verify_token = <token que configuramos en Meta>
          hub.challenge    = <número aleatorio que debemos devolver>

        Returns:
            HTTP 200 con el valor de hub.challenge si la verificación es exitosa.
            HTTP 403 Forbidden si el token no coincide o el modo es incorrecto.
        """
        from aiohttp import web

        mode = request.rel_url.query.get("hub.mode", "")
        token = request.rel_url.query.get("hub.verify_token", "")
        challenge = request.rel_url.query.get("hub.challenge", "")

        logger.info(
            "GET /webhook — verificación Meta: mode=%s, token_match=%s",
            mode,
            token == self._verify_token,
        )

        if mode == "subscribe" and token == self._verify_token:
            logger.info("Webhook de WhatsApp verificado correctamente por Meta")
            return web.Response(text=challenge, status=200)

        logger.warning(
            "Verificación de webhook rechazada: mode=%r, token_match=%s",
            mode,
            token == self._verify_token,
        )
        return web.Response(text="Forbidden", status=403)

    async def _handle_post(self, request: Any) -> Any:
        """POST {webhook_path} — mensajes y eventos entrantes de Meta.

        CRÍTICO: Meta reintentará el POST si no recibe HTTP 200 en < 5 segundos.
        Por eso respondemos 200 inmediatamente y procesamos en background.

        Body esperado:
          JSON con "object": "whatsapp_business_account" y la estructura
          estándar de Meta (entry → changes → value → messages/statuses).

        Returns:
            HTTP 403 si la firma HMAC no es válida.
            HTTP 200 OK si la firma pasa (incluso si el payload no es de WhatsApp).
            El procesamiento real se realiza en background vía asyncio.create_task.
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
            logger.warning(
                "POST /webhook — payload no es JSON válido: %s", exc
            )
            return web.json_response({"error": "payload invalido"}, status=400)

        objeto = payload.get("object", "")
        logger.debug("POST /webhook — object=%s", objeto)

        # Solo procesar eventos de WhatsApp Business
        if objeto != "whatsapp_business_account":
            logger.debug("Evento no-WhatsApp ignorado (object=%s)", objeto)
            return web.Response(text="OK", status=200)

        # Despachar procesamiento en background — no bloquear la respuesta
        asyncio.create_task(self._procesar_payload_safe(payload))

        # Responder 200 inmediatamente según el requerimiento de Meta
        return web.Response(text="OK", status=200)

    # ── Procesamiento interno ─────────────────────────────────

    async def _procesar_payload_safe(self, payload: dict) -> None:  # type: ignore[type-arg]
        """Procesa el payload de Meta capturando todas las excepciones.

        Invoca procesar_payload_whatsapp() que parsea el payload y
        delega cada evento al WhatsAppMessageHandler.

        El bloque try/except asegura que ningún error en el procesamiento
        derribe el servidor de webhook.

        Args:
            payload: Payload JSON completo recibido de Meta.
        """
        try:
            from channels.whatsapp.handler import procesar_payload_whatsapp

            eventos = await procesar_payload_whatsapp(payload, self._handler)
            logger.debug(
                "Payload procesado — %d evento(s) extraídos", len(eventos)
            )
        except Exception:
            logger.exception(
                "Error procesando payload de WhatsApp — el servidor sigue activo"
            )


# ── Función de arranque standalone ────────────────────────────


async def _run_server(
    port: int = 8080,
    host: str = "0.0.0.0",
    webhook_path: str = "/webhook",
) -> None:
    """Inicia el servidor y espera señales de terminación (SIGINT/SIGTERM).

    Se bloquea hasta que se reciba una señal de parada o se llame a
    asyncio.get_event_loop().stop().

    Args:
        port:         Puerto donde escuchar.
        host:         Host donde escuchar.
        webhook_path: Ruta del endpoint del webhook.
    """
    servidor = WhatsAppServer(
        port=port,
        host=host,
        webhook_path=webhook_path,
    )

    # Instalar manejadores de señales para parada limpia
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _parar() -> None:
        logger.info("Señal de parada recibida — deteniendo servidor...")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _parar)
        except NotImplementedError:
            # Windows no soporta add_signal_handler para todos los signals
            pass

    await servidor.start()

    # Iniciar worker SOMER en background
    from channels.whatsapp.somer_worker import run_worker_loop
    worker_task = asyncio.create_task(run_worker_loop(), name="whatsapp-somer-worker")
    logger.info("Worker SOMER-WhatsApp iniciado")

    try:
        await stop_event.wait()
    finally:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        await servidor.stop()


def main() -> None:
    """Punto de entrada para ejecución directa como módulo.

    Lee configuración de variables de entorno:
      WHATSAPP_WEBHOOK_PORT  — puerto del servidor (default: 8080)
      WHATSAPP_WEBHOOK_HOST  — host del servidor (default: 0.0.0.0)
      WHATSAPP_WEBHOOK_PATH  — ruta del endpoint (default: /webhook)

    Configurar estas variables en ~/.somer/.env o en el entorno del shell.
    """
    # Configurar logging básico si no está ya configurado
    if not logging.root.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    port = int(os.environ.get("WHATSAPP_WEBHOOK_PORT", "8080"))
    host = os.environ.get("WHATSAPP_WEBHOOK_HOST", "0.0.0.0")
    path = os.environ.get("WHATSAPP_WEBHOOK_PATH", "/webhook")

    logger.info(
        "Iniciando servidor webhook WhatsApp en http://%s:%d%s",
        host, port, path,
    )

    try:
        asyncio.run(_run_server(port=port, host=host, webhook_path=path))
    except KeyboardInterrupt:
        logger.info("Servidor detenido por el usuario (KeyboardInterrupt)")
    except Exception as exc:
        logger.critical("Error fatal en el servidor webhook: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
