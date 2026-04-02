#!/usr/bin/env bash
# =============================================================================
# start_whatsapp_webhook.sh — Inicia el servidor webhook de WhatsApp para SOMER
# =============================================================================
#
# Levanta el servidor HTTP que recibe los webhooks de Meta/WhatsApp Business
# Cloud API. El servidor escucha en el puerto configurado y expone:
#
#   GET  /webhook  — verificación de Meta (hub.challenge)
#   POST /webhook  — mensajes y eventos entrantes
#
# CONFIGURACIÓN
# -------------
# Todas las credenciales se leen de ~/.somer/.env — NUNCA hardcodeadas aquí.
# Crea el archivo si no existe y agrega las variables necesarias:
#
#   WHATSAPP_VERIFY_TOKEN=tu_token_secreto_de_verificacion
#   WHATSAPP_ACCESS_TOKEN=EAAxxxxxxxxxx...
#   WHATSAPP_PHONE_NUMBER_ID=123456789
#
# Variables opcionales para el servidor:
#   WHATSAPP_WEBHOOK_PORT  — puerto del servidor (default: 8080)
#   WHATSAPP_WEBHOOK_HOST  — host del servidor   (default: 0.0.0.0)
#   WHATSAPP_WEBHOOK_PATH  — ruta del endpoint   (default: /webhook)
#
# USO
# ---
#   ./scripts/start_whatsapp_webhook.sh           # Modo normal
#   ./scripts/start_whatsapp_webhook.sh --debug   # Modo debug (más logs)
#   ./scripts/start_whatsapp_webhook.sh --port 9090
#
# URL A REGISTRAR EN META DEVELOPERS
# ------------------------------------
# Una vez activo, registra en el panel de Meta Developers:
#   https://tu-dominio.com/webhook
#
# El servidor debe estar expuesto públicamente con HTTPS. Para desarrollo
# local puedes usar ngrok:
#   ngrok http 8080
# Y registrar la URL HTTPS de ngrok en Meta.
#
# =============================================================================

set -euo pipefail

# ── Directorio raíz del proyecto ──────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# ── Defaults configurables ────────────────────────────────────

WEBHOOK_PORT="${WHATSAPP_WEBHOOK_PORT:-8080}"
WEBHOOK_HOST="${WHATSAPP_WEBHOOK_HOST:-0.0.0.0}"
WEBHOOK_PATH="${WHATSAPP_WEBHOOK_PATH:-/webhook}"
LOG_LEVEL="INFO"

# ── Parseo de argumentos ──────────────────────────────────────

while [[ $# -gt 0 ]]; do
    case "$1" in
        --debug|-d)
            LOG_LEVEL="DEBUG"
            shift
            ;;
        --port|-p)
            WEBHOOK_PORT="$2"
            shift 2
            ;;
        --host)
            WEBHOOK_HOST="$2"
            shift 2
            ;;
        --path)
            WEBHOOK_PATH="$2"
            shift 2
            ;;
        --help|-h)
            echo "Uso: $0 [--debug] [--port PUERTO] [--host HOST] [--path RUTA]"
            echo ""
            echo "Opciones:"
            echo "  --debug, -d         Activa logging de nivel DEBUG"
            echo "  --port PUERTO       Puerto del servidor (default: 8080)"
            echo "  --host HOST         Host del servidor (default: 0.0.0.0)"
            echo "  --path RUTA         Ruta del webhook (default: /webhook)"
            echo ""
            echo "Credenciales: configura ~/.somer/.env"
            exit 0
            ;;
        *)
            echo "Argumento desconocido: $1" >&2
            exit 1
            ;;
    esac
done

# ── Cargar .env (para scripts de shell) ──────────────────────

ENV_FILE="$HOME/.somer/.env"
if [[ -f "$ENV_FILE" ]]; then
    echo "Cargando variables desde $ENV_FILE"
    # shellcheck disable=SC1090
    set -a
    source "$ENV_FILE"
    set +a
else
    echo "ADVERTENCIA: No se encontró $ENV_FILE"
    echo "Crea el archivo con: WHATSAPP_VERIFY_TOKEN=tu_token_secreto"
fi

# ── Verificaciones previas ────────────────────────────────────

echo ""
echo "==========================================="
echo "  SOMER — Servidor Webhook WhatsApp"
echo "==========================================="
echo ""

# Verificar Python
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 no encontrado en el PATH" >&2
    exit 1
fi

PYTHON_VERSION=$(python3 --version 2>&1)
echo "Python: $PYTHON_VERSION"

# Verificar que estamos en el directorio correcto
if [[ ! -f "$PROJECT_DIR/channels/whatsapp/server.py" ]]; then
    echo "ERROR: No se encontró channels/whatsapp/server.py en $PROJECT_DIR" >&2
    echo "Asegúrate de ejecutar este script desde la raíz del proyecto SOMER." >&2
    exit 1
fi

# Verificar token de verificación
if [[ -z "${WHATSAPP_VERIFY_TOKEN:-}" ]]; then
    echo ""
    echo "ADVERTENCIA: WHATSAPP_VERIFY_TOKEN no configurado."
    echo "El servidor arrancará pero Meta no podrá verificar el webhook."
    echo "Agrega a ~/.somer/.env:"
    echo "  WHATSAPP_VERIFY_TOKEN=tu_token_secreto"
    echo ""
fi

# Verificar dependencias de Python
if ! python3 -c "import aiohttp" 2>/dev/null; then
    echo ""
    echo "ADVERTENCIA: aiohttp no instalado. Instalando..."
    pip install aiohttp --quiet
fi

# ── Información del servidor ──────────────────────────────────

echo ""
echo "Configuración:"
echo "  Host:          $WEBHOOK_HOST"
echo "  Puerto:        $WEBHOOK_PORT"
echo "  Ruta:          $WEBHOOK_PATH"
echo "  Log level:     $LOG_LEVEL"
echo "  Verify token:  ${WHATSAPP_VERIFY_TOKEN:+configurado}${WHATSAPP_VERIFY_TOKEN:-NO CONFIGURADO}"
echo ""
echo "URL local:  http://$WEBHOOK_HOST:$WEBHOOK_PORT$WEBHOOK_PATH"
echo ""
echo "Registra en Meta Developers: https://TU-DOMINIO.com$WEBHOOK_PATH"
echo "(usa ngrok o similar para exponer el puerto localmente)"
echo ""
echo "Iniciando servidor... (Ctrl+C para detener)"
echo "-------------------------------------------"

# ── Iniciar servidor ──────────────────────────────────────────

export WHATSAPP_WEBHOOK_PORT="$WEBHOOK_PORT"
export WHATSAPP_WEBHOOK_HOST="$WEBHOOK_HOST"
export WHATSAPP_WEBHOOK_PATH="$WEBHOOK_PATH"
export PYTHONPATH="$PROJECT_DIR:${PYTHONPATH:-}"

exec python3 \
    -c "
import logging
import os
logging.basicConfig(
    level=getattr(logging, '${LOG_LEVEL}', logging.INFO),
    format='%(asctime)s [%(levelname)s] %(name)s — %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
from channels.whatsapp.server import main
main()
"
