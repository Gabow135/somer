#!/usr/bin/env python3
"""Gestión de usuarios de WhatsApp para SOMER multi-usuario.

Uso:
    python3 manage_whatsapp_users.py list
    python3 manage_whatsapp_users.py add <numero> <nombre> [persona]
    python3 manage_whatsapp_users.py remove <numero>
"""

import json
import sys
from pathlib import Path

USERS_FILE = Path.home() / ".somer" / "whatsapp_users.json"


def load() -> dict:
    if USERS_FILE.exists():
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    return {}


def save(data: dict) -> None:
    USERS_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def cmd_list() -> None:
    data = load()
    if not data:
        print("No hay usuarios configurados.")
        return
    print(f"Usuarios registrados ({len(data)}):")
    for numero, perfil in data.items():
        data_dir = perfil.get("data_dir", "—")
        nombre = perfil.get("name", "?")
        agent_id = perfil.get("agent_id", "—")
        print(f"  {numero} → {nombre} (agent_id={agent_id}, data={data_dir})")


def cmd_add(numero: str, nombre: str, persona: str = None) -> None:
    data = load()
    agent_id = nombre.lower().replace(" ", "_")
    data_dir = str(Path.home() / ".somer" / "users" / agent_id)
    Path(data_dir).mkdir(parents=True, exist_ok=True)

    if persona is None:
        persona = (
            f"Eres SOMER, la asistente personal de {nombre}. "
            "Tienes acceso a sus datos personales de CRM, finanzas, bookmarks y todas sus herramientas. "
            "Responde siempre en español, de forma concisa y sin Markdown extenso "
            "ya que el usuario lee en WhatsApp."
        )

    data[numero] = {
        "name": nombre,
        "agent_id": agent_id,
        "data_dir": data_dir,
        "persona": persona,
    }
    save(data)
    print(f"[OK] {numero} → {nombre} agregado (data: {data_dir})")


def cmd_remove(numero: str) -> None:
    data = load()
    if numero in data:
        nombre = data[numero].get("name", numero)
        del data[numero]
        save(data)
        print(f"[OK] {numero} ({nombre}) eliminado")
    else:
        print(f"[!] {numero} no encontrado")


def usage() -> None:
    print(__doc__)


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] == "list":
        cmd_list()
    elif args[0] == "add" and len(args) >= 3:
        cmd_add(args[1], args[2], args[3] if len(args) > 3 else None)
    elif args[0] == "remove" and len(args) >= 2:
        cmd_remove(args[1])
    else:
        usage()
        sys.exit(1)
