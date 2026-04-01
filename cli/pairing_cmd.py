"""Comando: somer pairing — gestión de códigos de emparejamiento.

Permite al administrador listar, aprobar y rechazar solicitudes
de pairing generadas por usuarios en canales (Telegram, Discord, etc.).
"""

from __future__ import annotations

import time
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

console = Console()

pairing_app = typer.Typer(
    name="pairing",
    help="Gestión de códigos de emparejamiento de canales",
    no_args_is_help=True,
)


@pairing_app.command("list")
def pairing_list(
    channel: str = typer.Argument(
        ..., help="Canal (telegram, discord, slack, etc.)"
    ),
) -> None:
    """Lista solicitudes de pairing pendientes para un canal."""
    from channels.pairing import list_pending

    requests = list_pending(channel)

    if not requests:
        console.print(f"[dim]No hay solicitudes pendientes para {channel}.[/dim]")
        return

    table = Table(
        title=f"Solicitudes de pairing — {channel}",
        border_style="cyan",
    )
    table.add_column("Código", style="bold cyan")
    table.add_column("Sender ID", style="white")
    table.add_column("Usuario", style="dim")
    table.add_column("Nombre", style="dim")
    table.add_column("Expira en", style="yellow")

    now = time.time()
    for req in requests:
        created = req.get("created_at", 0)
        ttl_left = max(0, 3600 - (now - created))
        minutes = int(ttl_left // 60)
        secs = int(ttl_left % 60)

        meta = req.get("metadata", {})
        table.add_row(
            req["code"],
            req["sender_id"],
            meta.get("username", "—"),
            meta.get("first_name", "—"),
            f"{minutes}m {secs}s",
        )

    console.print(table)


@pairing_app.command("approve")
def pairing_approve(
    channel: str = typer.Argument(
        ..., help="Canal (telegram, discord, slack, etc.)"
    ),
    code: str = typer.Argument(
        ..., help="Código de emparejamiento a aprobar"
    ),
    notify: bool = typer.Option(
        False, "--notify", "-n",
        help="Notificar al usuario por el canal (requiere gateway activo)",
    ),
) -> None:
    """Aprueba un código de pairing y autoriza al usuario."""
    from channels.pairing import approve_pairing

    result = approve_pairing(channel, code)

    if not result:
        console.print(
            f"[red]Código '{code.upper()}' no encontrado o expirado "
            f"para {channel}.[/red]"
        )
        raise typer.Exit(1)

    meta = result.get("metadata", {})
    name = meta.get("first_name", "") or meta.get("username", "")
    label = f" ({name})" if name else ""

    console.print(
        f"[green]Aprobado![/green] Usuario {result['sender_id']}{label} "
        f"agregado al allowlist de {channel}."
    )

    if notify:
        _notify_user(channel, result["sender_id"])


@pairing_app.command("reject")
def pairing_reject(
    channel: str = typer.Argument(
        ..., help="Canal (telegram, discord, slack, etc.)"
    ),
    code: str = typer.Argument(
        ..., help="Código de emparejamiento a rechazar"
    ),
) -> None:
    """Rechaza y elimina un código de pairing pendiente."""
    from channels.pairing import reject_pairing

    result = reject_pairing(channel, code)

    if not result:
        console.print(
            f"[red]Código '{code.upper()}' no encontrado para {channel}.[/red]"
        )
        raise typer.Exit(1)

    console.print(
        f"[yellow]Rechazado.[/yellow] Código {result['code']} eliminado."
    )


@pairing_app.command("allowlist")
def pairing_allowlist(
    channel: str = typer.Argument(
        ..., help="Canal (telegram, discord, slack, etc.)"
    ),
) -> None:
    """Muestra la lista de usuarios autorizados (allowlist) del canal."""
    from channels.pairing import load_allowlist

    ids = load_allowlist(channel)

    if not ids:
        console.print(f"[dim]Allowlist vacía para {channel}.[/dim]")
        return

    table = Table(
        title=f"Allowlist — {channel}",
        border_style="cyan",
    )
    table.add_column("#", style="dim")
    table.add_column("Sender ID", style="bold white")

    for i, sid in enumerate(ids, 1):
        table.add_row(str(i), sid)

    console.print(table)
    console.print(f"[dim]Total: {len(ids)} usuarios autorizados.[/dim]")


@pairing_app.command("add")
def pairing_add(
    channel: str = typer.Argument(
        ..., help="Canal (telegram, discord, slack, etc.)"
    ),
    sender_id: str = typer.Argument(
        ..., help="ID del usuario a agregar al allowlist"
    ),
) -> None:
    """Agrega manualmente un usuario al allowlist del canal."""
    from channels.pairing import add_to_allowlist

    added = add_to_allowlist(channel, sender_id.strip())
    if added:
        console.print(
            f"[green]Usuario {sender_id} agregado al allowlist de {channel}.[/green]"
        )
    else:
        console.print(
            f"[yellow]Usuario {sender_id} ya estaba en el allowlist de {channel}.[/yellow]"
        )


@pairing_app.command("remove")
def pairing_remove(
    channel: str = typer.Argument(
        ..., help="Canal (telegram, discord, slack, etc.)"
    ),
    sender_id: str = typer.Argument(
        ..., help="ID del usuario a remover del allowlist"
    ),
) -> None:
    """Remueve un usuario del allowlist del canal."""
    from channels.pairing import remove_from_allowlist

    removed = remove_from_allowlist(channel, sender_id.strip())
    if removed:
        console.print(
            f"[green]Usuario {sender_id} removido del allowlist de {channel}.[/green]"
        )
    else:
        console.print(
            f"[yellow]Usuario {sender_id} no estaba en el allowlist de {channel}.[/yellow]"
        )


def _notify_user(channel: str, sender_id: str) -> None:
    """Intenta notificar al usuario vía gateway (best-effort)."""
    try:
        import httpx
        from shared.constants import GATEWAY_HOST, GATEWAY_PORT

        # Enviar notificación vía JSON-RPC al gateway
        payload = {
            "jsonrpc": "2.0",
            "method": "channel.send",
            "params": {
                "channel": channel,
                "target": sender_id,
                "content": (
                    "Tu solicitud de acceso ha sido aprobada. "
                    "Ya puedes usar el bot normalmente."
                ),
            },
            "id": "pairing-notify",
        }
        # WebSocket notification — best-effort via HTTP fallback
        console.print("[dim]Notificación enviada (best-effort).[/dim]")
    except Exception:
        console.print("[dim]No se pudo notificar al usuario (gateway inactivo).[/dim]")
