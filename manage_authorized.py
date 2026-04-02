#!/usr/bin/env python3
"""
Gestión de números de WhatsApp autorizados para el bot SOMER.

Uso:
  python3 manage_authorized.py list              # Listar números autorizados
  python3 manage_authorized.py add 593991234567  # Agregar número
  python3 manage_authorized.py remove 593991234567  # Quitar número
  python3 manage_authorized.py clear             # Limpiar lista (todos pueden escribir)
"""

import json
import sys
from pathlib import Path

AUTHORIZED_FILE = Path.home() / ".somer" / "authorized_numbers.json"

def load():
    if not AUTHORIZED_FILE.exists():
        return []
    try:
        return json.loads(AUTHORIZED_FILE.read_text())
    except Exception:
        return []

def save(numbers):
    AUTHORIZED_FILE.parent.mkdir(parents=True, exist_ok=True)
    AUTHORIZED_FILE.write_text(json.dumps(sorted(set(numbers)), indent=2))

def cmd_list():
    numbers = load()
    if not numbers:
        print("Lista vacía — todos los números pueden escribir al bot")
    else:
        print(f"Números autorizados ({len(numbers)}):")
        for n in numbers:
            print(f"  + {n}")

def cmd_add(number):
    number = number.strip().lstrip("+")
    numbers = load()
    if number in numbers:
        print(f"Ya existe: {number}")
    else:
        numbers.append(number)
        save(numbers)
        print(f"Agregado: {number}")
        print(f"Total autorizados: {len(numbers)}")

def cmd_remove(number):
    number = number.strip().lstrip("+")
    numbers = load()
    if number not in numbers:
        print(f"No encontrado: {number}")
    else:
        numbers.remove(number)
        save(numbers)
        print(f"Eliminado: {number}")
        print(f"Quedan: {len(numbers)}")

def cmd_clear():
    if AUTHORIZED_FILE.exists():
        AUTHORIZED_FILE.unlink()
    print("Lista limpiada — ahora todos los números pueden escribir al bot")

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] == "list":
        cmd_list()
    elif args[0] == "add" and len(args) >= 2:
        cmd_add(args[1])
    elif args[0] == "remove" and len(args) >= 2:
        cmd_remove(args[1])
    elif args[0] == "clear":
        cmd_clear()
    else:
        print(__doc__)
