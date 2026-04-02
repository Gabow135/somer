"""
Seguridad del webhook de WhatsApp.
Verifica que las peticiones POST realmente vienen de Meta usando HMAC-SHA256.
"""
import hashlib
import hmac
import os
from typing import Optional


def verify_signature(payload_bytes: bytes, signature_header: Optional[str]) -> bool:
    """
    Verifica el header X-Hub-Signature-256 enviado por Meta.

    Meta calcula: HMAC-SHA256(app_secret, raw_payload)
    y lo envía como: sha256=<hex_digest>

    Docs: https://developers.facebook.com/docs/graph-api/webhooks/getting-started#verification-requests

    Si WHATSAPP_APP_SECRET no está configurado en el entorno, emite un
    warning y deja pasar la petición (comportamiento non-breaking).
    Configura WHATSAPP_APP_SECRET en ~/.somer/.env para habilitar la
    verificación completa.
    """
    app_secret = os.environ.get("WHATSAPP_APP_SECRET", "")

    if not app_secret:
        # Si no está configurado el app secret, solo se loggea warning
        # (para no romper deployments que no lo tengan aún)
        import logging
        logging.getLogger(__name__).warning(
            "WHATSAPP_APP_SECRET no configurado — omitiendo verificación de firma. "
            "Configúralo en ~/.somer/.env para mayor seguridad."
        )
        return True

    if not signature_header:
        return False

    if not signature_header.startswith("sha256="):
        return False

    expected_sig = signature_header[7:]  # quitar "sha256="

    mac = hmac.new(
        app_secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256
    )
    computed_sig = mac.hexdigest()

    # Comparación en tiempo constante para evitar timing attacks
    return hmac.compare_digest(computed_sig, expected_sig)


def get_verify_token() -> str:
    """Obtiene el WHATSAPP_VERIFY_TOKEN del entorno."""
    token = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")
    if not token:
        raise RuntimeError(
            "WHATSAPP_VERIFY_TOKEN no configurado en ~/.somer/.env"
        )
    return token
