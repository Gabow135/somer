#!/bin/bash
cd /var/www/somer

# Cargar variables de entorno
if [ -f ~/.somer/.env ]; then
    source ~/.somer/.env
fi

# Ejecutar briefing y capturar output
OUTPUT=$(/var/www/somer/venv/bin/python3 entry.py agent run "dame el briefing de hoy dia" 2>&1)

# Extraer solo el briefing (últimas líneas después de "Procesando:")
BRIEFING=$(echo "$OUTPUT" | sed -n '/Procesando:/,/^$/p' | tail -n +2)

# Si hay briefing, enviar a Telegram
if [ -n "$BRIEFING" ]; then
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d "chat_id=881607309" \
        -d "text=$(echo -e "📊 BRIEFING DIARIO\\n\\n$BRIEFING")" \
        -d "parse_mode=HTML"
    echo "Briefing enviado a Telegram"
else
    echo "No se generó briefing"
fi
