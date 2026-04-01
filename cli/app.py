"""CLI principal de SOMER 2.0.

Portado de OpenClaw: program.ts — entry point de CLI con todos los comandos.
Usa Typer + Rich para UX profesional de línea de comandos.

Comandos disponibles:
  version    — Versión e información del sistema
  info       — Información detallada del entorno
  gateway    — Control plane WebSocket (start, stop, status, restart, health, logs)
  agent      — Interacción con agentes (run, chat, status, list, config)
  config     — Gestión de configuración (show, init, validate, edit, get, set, diff, reset)
  channels   — Gestión de canales (list, status, test, enable, disable, setup)
  doctor     — Health check completo (check, env, providers)
  plugins    — Gestión de plugins (list, info, install, uninstall, enable, disable, update)
  cron       — Tareas programadas (list, add, remove, enable, disable, history, run-now)
  secrets    — Credenciales (list, set, delete, validate, rotate)
  memory     — Sistema de memoria (search, stats, export, import, compact, clear)
  skills     — Skills disponibles (list, info, check, search)
  onboard    — Wizard de setup interactivo
"""

from __future__ import annotations

import json
import os
import platform
import sys
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from shared.constants import VERSION

console = Console()

app = typer.Typer(
    name="somer",
    help="SOMER 2.0 — System for Optimized Modular Execution & Reasoning",
    no_args_is_help=True,
)


# ── Comandos raíz ────────────────────────────────────────────


@app.command()
def version() -> None:
    """Muestra la versión de SOMER."""
    typer.echo(f"SOMER {VERSION}")


@app.command()
def info(
    as_json: bool = typer.Option(False, "--json", help="Salida en JSON"),
) -> None:
    """Muestra información detallada del sistema.

    Portado de OpenClaw: system-cli.ts — resumen de entorno y capacidades.
    """
    from shared.constants import (
        DEFAULT_HOME,
        DEFAULT_MODEL,
        DEFAULT_FAST_MODEL,
        GATEWAY_HOST,
        GATEWAY_PORT,
    )

    data = {
        "version": VERSION,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "platform": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "home": str(DEFAULT_HOME),
        "config_exists": (DEFAULT_HOME / "config.json").exists(),
        "default_model": DEFAULT_MODEL,
        "fast_model": DEFAULT_FAST_MODEL,
        "gateway": f"ws://{GATEWAY_HOST}:{GATEWAY_PORT}",
    }

    # Contar skills
    try:
        from skills.loader import discover_skills
        skills = discover_skills(["skills"])
        data["skills_count"] = len(skills)
    except Exception:
        data["skills_count"] = 0

    # Verificar gateway
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            data["gateway_running"] = s.connect_ex((GATEWAY_HOST, GATEWAY_PORT)) == 0
    except Exception:
        data["gateway_running"] = False

    if as_json:
        console.print(json.dumps(data, indent=2))
        return

    console.print(Panel(
        f"[bold cyan]SOMER {VERSION}[/bold cyan]\n\n"
        f"Python:     {data['python']}\n"
        f"Plataforma: {data['platform']}\n"
        f"Home:       {data['home']}\n"
        f"Config:     {'encontrada' if data['config_exists'] else 'no existe'}\n"
        f"Gateway:    {data['gateway']} ({'activo' if data['gateway_running'] else 'inactivo'})\n"
        f"Skills:     {data['skills_count']}\n"
        f"Modelo:     {data['default_model']}",
        title="Información del sistema",
        border_style="cyan",
    ))


# ── Importar y registrar sub-comandos ────────────────────────

from cli.gateway_cmd import gateway_app
from cli.agent_cmd import agent_app
from cli.config_cmd import config_app
from cli.channels_cmd import channels_app
from cli.doctor_cmd import doctor_app
from cli.plugin_cmd import plugin_app
from cli.cron_cmd import cron_app
from cli.secret_cmd import secret_app
from cli.memory_cmd import memory_app
from cli.skill_cmd import skill_app
from cli.onboard_cmd import onboard
from cli.pairing_cmd import pairing_app

app.add_typer(gateway_app, name="gateway", help="Control plane WebSocket")
app.add_typer(agent_app, name="agent", help="Interacción con agentes")
app.add_typer(config_app, name="config", help="Gestión de configuración")
app.add_typer(channels_app, name="channels", help="Gestión de canales")
app.add_typer(doctor_app, name="doctor", help="Health check completo")
app.add_typer(plugin_app, name="plugins", help="Gestión de plugins")
app.add_typer(cron_app, name="cron", help="Tareas programadas")
app.add_typer(secret_app, name="secrets", help="Credenciales y secretos")
app.add_typer(memory_app, name="memory", help="Sistema de memoria")
app.add_typer(skill_app, name="skills", help="Skills disponibles")
app.add_typer(pairing_app, name="pairing", help="Emparejamiento de canales")
app.command("onboard")(onboard)
