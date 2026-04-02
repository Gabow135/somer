#!/usr/bin/env python3
"""Script standalone para enviar mensajes de texto por WhatsApp.

Uso:
    python3 /var/www/somer/notify_wa.py <phone_number> <message>

Ejemplo:
    python3 /var/www/somer/notify_wa.py 593995466833 "Texto del mensaje"

Exit codes:
    0 — Mensaje enviado correctamente
    1 — Error al enviar el mensaje
"""

from __future__ import annotations

import asyncio
import os
import sys

# Asegurar que el directorio del proyecto esté en el path
sys.path.insert(0, "/var/www/somer")

# Cargar variables de entorno desde ~/.somer/.env
_env_path = os.path.join(os.path.expanduser("~"), ".somer", ".env")
if os.path.isfile(_env_path):
    with open(_env_path, "r", encoding="utf-8") as _fh:
        for _line in _fh:
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _key, _, _value = _line.partition("=")
            _key = _key.strip()
            _value = _value.strip()
            if _key and _key not in os.environ:
                os.environ[_key] = _value


async def main() -> int:
    """Punto de entrada principal del script."""
    if len(sys.argv) < 3:
        print(
            "Uso: python3 notify_wa.py <phone_number> <message>",
            file=sys.stderr,
        )
        print(
            'Ejemplo: python3 notify_wa.py 593995466833 "Texto del mensaje"',
            file=sys.stderr,
        )
        return 1

    phone_number = sys.argv[1]
    message = sys.argv[2]

    try:
        from channels.whatsapp.sender import WhatsAppSender

        sender = WhatsAppSender()
        result = await sender.send_text(phone_number, message)

        if result.get("success"):
            print(f"Mensaje enviado correctamente a {phone_number}")
            return 0
        else:
            http_code = result.get("http_code", 0)
            response = result.get("response", {})
            error = result.get("error", "")
            print(
                f"Error al enviar mensaje a {phone_number}: HTTP {http_code}",
                file=sys.stderr,
            )
            if error:
                print(f"Detalle: {error}", file=sys.stderr)
            if response:
                print(f"Respuesta API: {response}", file=sys.stderr)
            return 1

    except Exception as exc:
        print(f"Error inesperado: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
