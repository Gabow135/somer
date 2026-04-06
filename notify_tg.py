#!/usr/bin/env python3
"""Envía mensaje de texto por Telegram Bot API.

Uso:
    python3 /var/www/somer/notify_tg.py <chat_id> <message>
"""
from __future__ import annotations
import os, sys, requests

def main():
    if len(sys.argv) < 3:
        print("Uso: notify_tg.py <chat_id> <message>", file=sys.stderr)
        sys.exit(1)

    chat_id = sys.argv[1]
    message = sys.argv[2]
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")

    if not token:
        print("ERROR: TELEGRAM_BOT_TOKEN no configurado", file=sys.stderr)
        sys.exit(1)

    # Truncar si excede límite de Telegram (4096 chars)
    if len(message) > 4000:
        message = message[:4000] + "\n\n[... truncado]"

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(url, json={
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }, timeout=30)

    if resp.status_code == 200:
        print(f"Mensaje enviado a chat {chat_id}")
    else:
        # Reintentar sin parse_mode si falla por markdown
        resp2 = requests.post(url, json={
            "chat_id": chat_id,
            "text": message,
            "disable_web_page_preview": True,
        }, timeout=30)
        if resp2.status_code == 200:
            print(f"Mensaje enviado a chat {chat_id} (sin markdown)")
        else:
            print(f"ERROR: {resp2.status_code} — {resp2.text}", file=sys.stderr)
            sys.exit(1)

if __name__ == "__main__":
    main()
