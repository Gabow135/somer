"""Comando: somer channels — gestión de canales.

Portado de OpenClaw: channels-cli.ts, commands/channels.ts.
Incluye: list, status, test, enable, disable, setup.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

console = Console()
channels_app = typer.Typer(no_args_is_help=True)


def _load_channel_config() -> tuple:
    """Carga la config y retorna (config, channels_dict)."""
    from config.loader import load_config
    from config.runtime_overrides import apply_env_overrides

    config = apply_env_overrides(load_config())
    return config, config.channels.entries


@channels_app.command("list")
def channels_list(
    as_json: bool = typer.Option(False, "--json", help="Salida en JSON"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Mostrar detalles"),
) -> None:
    """Lista los canales configurados.

    Portado de OpenClaw: channels list con detalles de auth y estado.
    """
    config, entries = _load_channel_config()

    if not entries:
        console.print("[yellow]No hay canales configurados[/yellow]")
        console.print("[dim]Configura canales con: somer onboard  o  somer channels setup[/dim]")
        return

    if as_json:
        result = {
            name: {
                "plugin": ch.plugin,
                "enabled": ch.enabled,
                "config": ch.config if verbose else {},
            }
            for name, ch in entries.items()
        }
        console.print(json.dumps(result, indent=2))
        return

    table = Table(title="Canales configurados")
    table.add_column("Canal", style="cyan")
    table.add_column("Plugin", style="green")
    table.add_column("Estado", style="yellow")
    if verbose:
        table.add_column("Config", style="dim")

    for name, ch in entries.items():
        status = "[green]activo[/green]" if ch.enabled else "[dim]desactivado[/dim]"
        row = [name, ch.plugin, status]
        if verbose:
            row.append(json.dumps(ch.config, default=str)[:60] if ch.config else "")
        table.add_row(*row)

    console.print(table)


@channels_app.command("status")
def channels_status(
    channel: Optional[str] = typer.Option(None, "--channel", "-c", help="Canal específico"),
    as_json: bool = typer.Option(False, "--json", help="Salida en JSON"),
) -> None:
    """Muestra el estado de los canales.

    Portado de OpenClaw: channels status con probe de credenciales.
    """
    config, entries = _load_channel_config()

    if not entries:
        console.print("[dim]No hay canales configurados[/dim]")
        return

    # Filtrar si se especifica canal
    if channel:
        if channel not in entries:
            console.print(f"[red]Canal '{channel}' no encontrado[/red]")
            raise typer.Exit(1)
        entries = {channel: entries[channel]}

    status_data = {}
    for name, ch in entries.items():
        # Verificar token/config
        token_env = ch.config.get("token_env") if ch.config else None
        has_token = bool(os.environ.get(token_env)) if token_env else None
        status_data[name] = {
            "enabled": ch.enabled,
            "plugin": ch.plugin,
            "has_credentials": has_token,
            "token_env": token_env,
        }

    if as_json:
        console.print(json.dumps(status_data, indent=2))
        return

    table = Table(title="Estado de canales")
    table.add_column("Canal", style="cyan")
    table.add_column("Estado", width=12)
    table.add_column("Credenciales", width=14)
    table.add_column("Detalle", style="dim")

    for name, info in status_data.items():
        enabled_str = "[green]activo[/green]" if info["enabled"] else "[dim]desactivado[/dim]"
        if info["has_credentials"] is None:
            cred_str = "[dim]N/A[/dim]"
        elif info["has_credentials"]:
            cred_str = "[green]OK[/green]"
        else:
            cred_str = "[red]falta[/red]"
        detail = info["token_env"] or info["plugin"]
        table.add_row(name, enabled_str, cred_str, detail)

    console.print(table)

    # Aviso si gateway no está corriendo
    import socket
    from shared.constants import GATEWAY_HOST, GATEWAY_PORT
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            gw_ok = s.connect_ex((GATEWAY_HOST, GATEWAY_PORT)) == 0
    except Exception:
        gw_ok = False
    if not gw_ok:
        console.print("\n[dim]Gateway no está corriendo — los canales no están activos.[/dim]")
        console.print("[dim]Inicia con: somer gateway start[/dim]")


@channels_app.command("test")
def channels_test(
    channel: str = typer.Argument(..., help="Nombre del canal a probar"),
    message: str = typer.Option("Mensaje de prueba SOMER", help="Mensaje de prueba"),
) -> None:
    """Envía un mensaje de prueba a un canal.

    Portado de OpenClaw: verificación de credenciales y envío de prueba.
    """
    config, entries = _load_channel_config()

    if channel not in entries:
        console.print(f"[red]Canal '{channel}' no encontrado[/red]")
        available = ", ".join(entries.keys())
        console.print(f"[dim]Canales disponibles: {available}[/dim]")
        raise typer.Exit(1)

    ch = entries[channel]
    if not ch.enabled:
        console.print(f"[yellow]Canal '{channel}' está desactivado[/yellow]")
        raise typer.Exit(1)

    console.print(f"[dim]Probando canal '{channel}' ({ch.plugin})...[/dim]")

    async def _test() -> None:
        from channels.registry import ChannelRegistry

        registry = ChannelRegistry()
        try:
            plugin = registry.create_plugin(channel, ch)
            await plugin.setup()
            console.print(f"[green]Canal '{channel}' configurado correctamente[/green]")
        except Exception as exc:
            console.print(f"[red]Error al configurar canal '{channel}': {exc}[/red]")
            raise typer.Exit(1)

    try:
        asyncio.run(_test())
    except typer.Exit:
        raise
    except Exception as exc:
        console.print(f"[red]Error de prueba: {exc}[/red]")
        raise typer.Exit(1)


@channels_app.command("enable")
def channels_enable(
    channel: str = typer.Argument(..., help="Nombre del canal"),
) -> None:
    """Activa un canal en la configuración.

    Portado de OpenClaw: channels add con flag --enable.
    """
    from config.loader import load_config, save_config

    config = load_config()
    if channel not in config.channels.entries:
        console.print(f"[red]Canal '{channel}' no encontrado[/red]")
        raise typer.Exit(1)

    config.channels.entries[channel].enabled = True
    save_config(config)
    console.print(f"[green]Canal '{channel}' activado[/green]")


@channels_app.command("disable")
def channels_disable(
    channel: str = typer.Argument(..., help="Nombre del canal"),
) -> None:
    """Desactiva un canal en la configuración.

    Portado de OpenClaw: channels remove con soft-disable.
    """
    from config.loader import load_config, save_config

    config = load_config()
    if channel not in config.channels.entries:
        console.print(f"[red]Canal '{channel}' no encontrado[/red]")
        raise typer.Exit(1)

    config.channels.entries[channel].enabled = False
    save_config(config)
    console.print(f"[yellow]Canal '{channel}' desactivado[/yellow]")


@channels_app.command("setup")
def channels_setup() -> None:
    """Wizard interactivo para configurar un canal.

    Portado de OpenClaw: commands/channel-setup/ con wizard interactivo.
    """
    from config.loader import load_config, save_config
    from config.schema import ChannelConfig
    from infra.env import save_env_var

    # Definiciones de canales soportados
    channel_defs = [
        ("telegram", "Telegram", "TELEGRAM_BOT_TOKEN", "channels.telegram"),
        ("discord", "Discord", "DISCORD_BOT_TOKEN", "channels.discord"),
        ("slack", "Slack", "SLACK_BOT_TOKEN", "channels.slack"),
        ("whatsapp", "WhatsApp", "WHATSAPP_API_TOKEN", "channels.whatsapp"),
        ("matrix", "Matrix", "MATRIX_ACCESS_TOKEN", "channels.matrix"),
        ("webchat", "WebChat", None, "channels.webchat"),
    ]

    console.print(Panel(
        "[bold cyan]Setup de canal[/bold cyan]\n"
        "Selecciona el canal que quieres configurar.",
        border_style="cyan",
    ))

    # Mostrar opciones
    for i, (cid, name, env, _) in enumerate(channel_defs, 1):
        has_token = bool(os.environ.get(env)) if env else None
        token_status = " [green](token detectado)[/green]" if has_token else ""
        console.print(f"  {i}. {name}{token_status}")

    choice = Prompt.ask(
        "\nNúmero del canal",
        choices=[str(i) for i in range(1, len(channel_defs) + 1)],
    )
    idx = int(choice) - 1
    cid, name, env_var, plugin = channel_defs[idx]

    config = load_config()

    if env_var:
        existing = os.environ.get(env_var)
        if existing:
            console.print(f"[green]Token ya detectado para {name}[/green]")
            save_env_var(env_var, existing)
        else:
            token = Prompt.ask(f"  {env_var}", password=True, default="")
            if token:
                save_env_var(env_var, token)
                console.print(f"[green]Token guardado en ~/.somer/.env[/green]")
            else:
                console.print("[yellow]Sin token — canal se configurará pero puede no funcionar[/yellow]")

    channel_config = ChannelConfig(
        enabled=True,
        plugin=plugin,
        config={"token_env": env_var} if env_var else {},
    )
    config.channels.entries[cid] = channel_config
    save_config(config)
    console.print(f"\n[green]Canal '{name}' configurado y activado[/green]")
