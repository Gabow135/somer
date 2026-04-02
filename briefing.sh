#!/bin/bash
# briefing.sh — Generador de briefing diario SOMER
# Fix OOM: ulimit -v 2097152 previene que procesos hijos (claude CLI) mapeen 22GB+ virtual
cd /var/www/somer

# ── Protección anti-OOM ──────────────────────────────────────────────
# Virtual memory cap: 2GB — suficiente para Python/SOMER, previene claude CLI (22GB)
ulimit -v 2097152
# Timeout: 5 minutos máximo — si se cuelga, muere limpio
TIMEOUT=300

# ── Variables de entorno ─────────────────────────────────────────────
if [ -f ~/.somer/.env ]; then
    set -a
    source ~/.somer/.env
    set +a
fi

TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
echo "[$TIMESTAMP] Iniciando briefing..."

# ── Ejecutar briefing ────────────────────────────────────────────────
OUTPUT=$(timeout $TIMEOUT /var/www/somer/venv/bin/python3 entry.py agent run \
    "dame el briefing de hoy" 2>&1)

EXIT_CODE=$?
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

if [ $EXIT_CODE -eq 124 ]; then
    echo "[$TIMESTAMP] ERROR: Briefing timeout (>5 min) — proceso terminado"
    exit 1
elif [ $EXIT_CODE -ne 0 ]; then
    echo "[$TIMESTAMP] ERROR: Briefing falló (exit $EXIT_CODE)"
    echo "$OUTPUT"
    exit 1
fi

# ── Enviar a WhatsApp ────────────────────────────────────────────────
if [ -n "$OUTPUT" ]; then
    /var/www/somer/venv/bin/python3 /var/www/somer/notify_wa.py \
        593995466833 "$(echo -e "$OUTPUT")" 2>&1
    echo "[$TIMESTAMP] Briefing enviado a WhatsApp"
else
    echo "[$TIMESTAMP] WARN: Briefing vacío — no se envió"
fi
