"""
WhatsApp Notifier — dispatcher central para todas las notificaciones del sistema.

Enruta notificaciones a los usuarios por su número de WhatsApp registrado en la
base de datos de credenciales SRI o mediante número explícito.

Uso rápido:
    from channels.whatsapp.notifier import WhatsAppNotifier

    notifier = WhatsAppNotifier()

    # Notificar usuario específico
    resultado = notifier.notify_user("593987654321", "Su declaración vence mañana", "Empresa SA")

    # Notificar por obligaciones SRI
    notifier.notify_sri_obligation("593987654321", "1791234560001", "Empresa SA", "IVA mensual vence 10/04/2026")

    # Notificar a todos los usuarios SRI con WhatsApp configurado
    resultados = notifier.notify_all_sri_users("Recordatorio: vence declaración IVA")
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Directorio base de SOMER
_SOMER_DIR = Path.home() / ".somer"
_DB_PATH = _SOMER_DIR / "sri_credentials.db"


def _load_env() -> None:
    """Carga ~/.somer/.env en os.environ si el archivo existe.

    Solo establece variables que no estén ya definidas en el entorno,
    respetando la precedencia del shell sobre el archivo.
    """
    env_path = _SOMER_DIR / ".env"
    if not env_path.exists():
        return
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    key = key.strip()
                    val = val.strip()
                    if key and key not in os.environ:
                        os.environ[key] = val
    except Exception as exc:
        logger.warning("No se pudo cargar %s: %s", env_path, exc)


# Cargar variables de entorno al importar el módulo
_load_env()


class WhatsAppNotifier:
    """Dispatcher central de notificaciones WhatsApp para SOMER.

    Envía mensajes usando el template 'dtirols' de la WhatsApp Business Cloud API.
    Las credenciales se leen exclusivamente desde variables de entorno o ~/.somer/.env.

    Atributos de entorno requeridos:
        WHATSAPP_ACCESS_TOKEN     Token de acceso de la Meta App
        WHATSAPP_PHONE_NUMBER_ID  ID del número de teléfono de negocio
    """

    def notify_user(
        self,
        whatsapp_number: str,
        message: str,
        razonsocial: str = "SOMER",
    ) -> dict:
        """Envía un mensaje simple como template dtirols a un número de WhatsApp.

        Args:
            whatsapp_number: Número destino en formato internacional sin + (ej: '593987654321').
            message:         Texto del cuerpo del mensaje (body del template).
            razonsocial:     Texto para el header del template (nombre del remitente).

        Returns:
            dict con {success, http_code, whatsapp_number, message} o {success, error}.
        """
        from channels.whatsapp.sender import send_template_dtirols

        # Normalizar número: quitar +, espacios y guiones
        numero = whatsapp_number.strip().lstrip("+").replace(" ", "").replace("-", "")

        if not numero:
            logger.warning("WhatsAppNotifier.notify_user: número vacío, ignorando")
            return {"success": False, "error": "Número WhatsApp vacío"}

        logger.info("Enviando notificación WhatsApp a %s — razonsocial='%s'", numero, razonsocial)
        try:
            resultado = send_template_dtirols(
                celular=numero,
                razonsocial=razonsocial,
                body_text=message,
            )
            resultado["whatsapp_number"] = numero
            return resultado
        except Exception as exc:
            logger.error("Error enviando notificación WhatsApp a %s: %s", numero, exc)
            return {"success": False, "error": str(exc), "whatsapp_number": numero}

    def notify_sri_obligation(
        self,
        whatsapp_number: str,
        ruc: str,
        razonsocial: str,
        obligation_detail: str,
    ) -> dict:
        """Envía una notificación específica de obligaciones SRI.

        Construye un mensaje estandarizado con el detalle de la obligación
        y lo envía al número WhatsApp indicado usando el template dtirols.

        Args:
            whatsapp_number:    Número destino en formato internacional sin + (ej: '593987654321').
            ruc:                RUC del contribuyente al que pertenece la obligación.
            razonsocial:        Nombre o razón social del contribuyente.
            obligation_detail:  Descripción de la obligación (ej: 'IVA mensual vence 10/04/2026').

        Returns:
            dict con {success, http_code, whatsapp_number} o {success, error}.
        """
        mensaje = f"RUC {ruc} — Obligación SRI: {obligation_detail}"
        logger.info(
            "Notificación SRI a %s — RUC %s: %s",
            whatsapp_number, ruc, obligation_detail[:80],
        )
        return self.notify_user(
            whatsapp_number=whatsapp_number,
            message=mensaje,
            razonsocial=razonsocial or "SOMER SRI",
        )

    def notify_all_sri_users(self, message: str) -> list[dict]:
        """Notifica a todos los usuarios SRI que tienen whatsapp_number configurado.

        Consulta la tabla sri_users en ~/.somer/sri_credentials.db y envía
        el mensaje a cada usuario que tenga un número WhatsApp registrado.

        Args:
            message: Texto del cuerpo del mensaje a enviar a todos los usuarios.

        Returns:
            Lista de dicts, uno por usuario notificado, con {success, ruc, whatsapp_number, ...}.
            Los usuarios sin whatsapp_number configurado son omitidos (no se incluyen en la lista).
        """
        resultados: list[dict] = []

        if not _DB_PATH.exists():
            logger.warning("Base de datos SRI no encontrada en %s", _DB_PATH)
            return resultados

        try:
            conn = sqlite3.connect(str(_DB_PATH))
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT ruc, name, alias, whatsapp_number FROM sri_users "
                "WHERE whatsapp_number IS NOT NULL AND whatsapp_number != '' "
                "ORDER BY ruc"
            ).fetchall()
            conn.close()
        except Exception as exc:
            logger.error("Error consultando sri_credentials.db: %s", exc)
            return resultados

        if not rows:
            logger.info("notify_all_sri_users: ningún usuario tiene whatsapp_number configurado")
            return resultados

        logger.info(
            "notify_all_sri_users: enviando a %d usuario(s) — mensaje: %s",
            len(rows), message[:60],
        )

        for row in rows:
            ruc = row["ruc"]
            numero = row["whatsapp_number"]
            razonsocial = row["name"] or row["alias"] or "SOMER"

            resultado = self.notify_user(
                whatsapp_number=numero,
                message=message,
                razonsocial=razonsocial,
            )
            resultado["ruc"] = ruc
            resultados.append(resultado)

            if resultado.get("success"):
                logger.info("Notificación enviada a RUC %s (%s)", ruc, numero)
            else:
                logger.warning(
                    "Fallo al notificar RUC %s (%s): %s",
                    ruc, numero, resultado.get("error", "error desconocido"),
                )

        return resultados

    def get_user_whatsapp(self, user_id: str) -> Optional[str]:
        """Obtiene el número de WhatsApp de un usuario desde sri_credentials.db.

        Busca primero por RUC exacto; si no coincide con 13 dígitos, busca
        por owner_user_id en el campo correspondiente.

        Args:
            user_id: RUC (13 dígitos) u owner_user_id del usuario a buscar.

        Returns:
            Número WhatsApp como string (ej: '593987654321') o None si no existe
            o no tiene número configurado.
        """
        if not _DB_PATH.exists():
            logger.warning("Base de datos SRI no encontrada en %s", _DB_PATH)
            return None

        try:
            conn = sqlite3.connect(str(_DB_PATH))
            conn.row_factory = sqlite3.Row

            # Intentar por RUC exacto
            if user_id and user_id.isdigit() and len(user_id) == 13:
                row = conn.execute(
                    "SELECT whatsapp_number FROM sri_users WHERE ruc = ?", (user_id,)
                ).fetchone()
            else:
                # Buscar por owner_user_id
                row = conn.execute(
                    "SELECT whatsapp_number FROM sri_users WHERE owner_user_id = ? "
                    "ORDER BY updated_at DESC LIMIT 1",
                    (user_id,),
                ).fetchone()

            conn.close()

            if row and row["whatsapp_number"]:
                return row["whatsapp_number"]
            return None

        except Exception as exc:
            logger.error("Error obteniendo whatsapp de user_id=%s: %s", user_id, exc)
            return None
