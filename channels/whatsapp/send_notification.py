"""Script standalone para enviar notificaciones WhatsApp desde la línea de comandos.

Permite llamar al canal WhatsApp de SOMER desde scripts externos, cron jobs
o cualquier sistema sin necesidad de levantar el gateway completo.

Uso:
    python3 send_notification.py <celular> <razonsocial> <body_text> [template_name]

Ejemplos:
    python3 send_notification.py +593987654321 "Empresa S.A." "Su rol de pagos está listo"
    python3 send_notification.py 593987654321 "Empresa S.A." "Pago procesado" dtirols

Variables de entorno requeridas (cargar desde ~/.somer/.env o exportar):
    WHATSAPP_ACCESS_TOKEN       Token de acceso de la Meta App
    WHATSAPP_PHONE_NUMBER_ID    ID del número de teléfono de negocio

Variables de entorno opcionales:
    WHATSAPP_TOKEN              Alias heredado del token (retrocompatibilidad)

Notas:
    - El token NUNCA debe hardcodearse en este archivo.
    - Para producción, cargar el .env con: source ~/.somer/.env
    - Requiere: pip install httpx
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

# ── Configurar logging básico ─────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("somer.whatsapp.send_notification")


# ── Cargar .env si existe ─────────────────────────────────────────────────────

def _cargar_dotenv() -> None:
    """Carga variables de entorno desde ~/.somer/.env si el archivo existe.

    Solo carga las variables que aún no estén definidas en el entorno,
    respetando las variables ya exportadas en la sesión.
    """
    env_path = Path.home() / ".somer" / ".env"
    if not env_path.exists():
        return

    with open(env_path, encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            # Ignorar comentarios y líneas vacías
            if not linea or linea.startswith("#"):
                continue
            if "=" not in linea:
                continue
            clave, _, valor = linea.partition("=")
            clave = clave.strip()
            valor = valor.strip().strip('"').strip("'")
            # No sobreescribir variables ya definidas en el entorno
            if clave and clave not in os.environ:
                os.environ[clave] = valor

    logger.debug("Variables de entorno cargadas desde %s", env_path)


# ── Lógica principal ──────────────────────────────────────────────────────────

async def enviar_notificacion(
    celular: str,
    razonsocial: str,
    body_text: str,
    template_name: str = "dtirols",
) -> bool:
    """Envía una notificación WhatsApp usando la plantilla especificada.

    Args:
        celular:       Número destino en formato internacional
                       (con o sin '+', ej: "+593987654321").
        razonsocial:   Texto para el parámetro header del template.
        body_text:     Texto para el parámetro body del template.
        template_name: Nombre del template aprobado en Meta (default: "dtirols").

    Returns:
        True si el mensaje se envió correctamente, False si hubo error.
    """
    # Verificar credenciales antes de crear el cliente
    token = os.environ.get("WHATSAPP_ACCESS_TOKEN") or os.environ.get("WHATSAPP_TOKEN")
    phone_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")

    if not token:
        logger.error(
            "Token de WhatsApp no encontrado. "
            "Define la variable de entorno WHATSAPP_ACCESS_TOKEN en ~/.somer/.env"
        )
        return False

    if not phone_id:
        logger.error(
            "Phone Number ID no encontrado. "
            "Define la variable de entorno WHATSAPP_PHONE_NUMBER_ID en ~/.somer/.env"
        )
        return False

    # Importar el cliente desde el paquete (ajustar sys.path si hace falta)
    try:
        from channels.whatsapp.client import WhatsAppClient
    except ImportError:
        # Fallback: agregar raíz del proyecto al path si se ejecuta directamente
        proyecto_root = Path(__file__).resolve().parent.parent.parent
        if str(proyecto_root) not in sys.path:
            sys.path.insert(0, str(proyecto_root))
        from channels.whatsapp.client import WhatsAppClient  # type: ignore[no-redef]

    client = WhatsAppClient()
    try:
        await client.start()
        resultado = await client.send_template(
            celular=celular,
            razonsocial=razonsocial,
            body_text=body_text,
            template_name=template_name,
        )
        wamid = resultado.get("messages", [{}])[0].get("id", "desconocido")
        logger.info(
            "Notificacion enviada correctamente. wamid=%s | destino=%s | template=%s",
            wamid,
            celular,
            template_name,
        )
        return True

    except Exception as exc:
        logger.error("Error enviando notificacion a %s: %s", celular, exc)
        return False

    finally:
        await client.stop()


def main() -> None:
    """Punto de entrada del script standalone.

    Uso:
        python3 send_notification.py <celular> <razonsocial> <body_text> [template_name]

    Argumentos posicionales:
        celular       Número destino (ej: +593987654321)
        razonsocial   Nombre de la empresa o razón social (parámetro header)
        body_text     Cuerpo del mensaje (parámetro body)
        template_name Nombre del template (opcional, default: dtirols)
    """
    _cargar_dotenv()

    if len(sys.argv) < 4:
        print(
            "Uso: python3 send_notification.py <celular> <razonsocial> <body_text> [template_name]",
            file=sys.stderr,
        )
        print("Ejemplo:", file=sys.stderr)
        print(
            '  python3 send_notification.py +593987654321 "Empresa S.A." "Su rol esta listo"',
            file=sys.stderr,
        )
        sys.exit(1)

    celular: str = sys.argv[1]
    razonsocial: str = sys.argv[2]
    body_text: str = sys.argv[3]
    template_name: str = sys.argv[4] if len(sys.argv) > 4 else "dtirols"

    exito = asyncio.run(
        enviar_notificacion(
            celular=celular,
            razonsocial=razonsocial,
            body_text=body_text,
            template_name=template_name,
        )
    )
    sys.exit(0 if exito else 1)


if __name__ == "__main__":
    main()
