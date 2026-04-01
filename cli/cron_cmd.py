"""Comando: somer cron — gestión de tareas programadas.

Portado de OpenClaw: cron-cli/ (register.ts, register.cron-add.ts,
register.cron-simple.ts, register.cron-edit.ts).
Incluye: list, add, remove, enable, disable, history, run-now, status.

Se conecta al gateway via WebSocket JSON-RPC para gestionar el scheduler
que corre dentro del proceso del gateway.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import typer
from rich.console import Console
from rich.table import Table

console = Console()
cron_app = typer.Typer(no_args_is_help=True)


def _gateway_rpc(method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Envía un request JSON-RPC al gateway y retorna el resultado."""
    from shared.constants import GATEWAY_HOST, GATEWAY_PORT

    try:
        import websockets.sync.client as ws_sync
    except ImportError:
        console.print("[red]Dependencia faltante: pip install websockets[/red]")
        raise typer.Exit(1)

    try:
        with ws_sync.connect(
            f"ws://{GATEWAY_HOST}:{GATEWAY_PORT}",
            close_timeout=5,
            ping_interval=None,
        ) as ws:
            request = json.dumps({
                "jsonrpc": "2.0",
                "method": method,
                "params": params or {},
                "id": 1,
            })
            ws.send(request)
            response = json.loads(ws.recv(timeout=300))

            if "error" in response:
                msg = response["error"].get("message", "error desconocido")
                console.print(f"[red]Error del gateway: {msg}[/red]")
                raise typer.Exit(1)

            return response.get("result", {})
    except ConnectionRefusedError:
        console.print("[red]Gateway no esta corriendo. Inicia con: somer gateway start[/red]")
        raise typer.Exit(1)
    except Exception as exc:
        if "ConnectionRefused" in str(type(exc).__name__):
            console.print("[red]Gateway no esta corriendo. Inicia con: somer gateway start[/red]")
        else:
            console.print(f"[red]Error conectando al gateway: {exc}[/red]")
        raise typer.Exit(1)


def _format_timestamp(ts: Optional[float]) -> str:
    """Formatea un timestamp epoch a string legible."""
    if ts is None:
        return "-"
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def _format_status_str(job: Dict[str, Any]) -> str:
    """Formatea el estado de un job (desde dict RPC)."""
    if not job.get("enabled"):
        return "[dim]desactivado[/dim]"
    last = job.get("last_status")
    errors = job.get("consecutive_errors", 0)
    if last == "ok":
        return "[green]OK[/green]"
    elif last == "error":
        return f"[red]error ({errors})[/red]"
    elif last == "timeout":
        return "[yellow]timeout[/yellow]"
    elif last:
        return f"[yellow]{last}[/yellow]"
    return "[dim]pendiente[/dim]"


@cron_app.command("list")
def cron_list(
    as_json: bool = typer.Option(False, "--json", help="Salida en JSON"),
) -> None:
    """Lista todos los jobs cron registrados.

    Se conecta al gateway para obtener los jobs del scheduler en ejecucion.
    """
    result = _gateway_rpc("cron.list")

    if not result.get("enabled"):
        console.print("[yellow]Cron scheduler no esta habilitado en la configuracion.[/yellow]")
        console.print("[dim]Activa 'cron.enabled' en ~/.somer/config.json o ejecuta somer onboard[/dim]")
        return

    jobs = result.get("jobs", [])

    if as_json:
        console.print(json.dumps(jobs, indent=2))
        return

    if not jobs:
        console.print("[dim]No hay jobs cron registrados[/dim]")
        return

    table = Table(title="Jobs Cron")
    table.add_column("ID", style="cyan", width=14)
    table.add_column("Nombre", style="white", width=20)
    table.add_column("Expresion", style="green")
    table.add_column("Estado", width=16)
    table.add_column("Proxima ejecucion", style="dim")

    for j in jobs:
        table.add_row(
            j.get("id", ""),
            (j.get("name", "") or "")[:20],
            j.get("expression", ""),
            _format_status_str(j),
            _format_timestamp(j.get("next_run_at")),
        )

    console.print(table)
    console.print(f"\n[dim]{len(jobs)} job(s) total[/dim]")


@cron_app.command("status")
def cron_status(
    as_json: bool = typer.Option(False, "--json", help="Salida en JSON"),
) -> None:
    """Muestra el estado del scheduler cron y heartbeat.

    Se conecta al gateway via WebSocket para obtener estado en tiempo real.
    """
    result = _gateway_rpc("cron.status")

    if as_json:
        console.print(json.dumps(result, indent=2))
        return

    if not result.get("enabled"):
        console.print("[yellow]Cron scheduler no esta habilitado.[/yellow]")
        console.print("[dim]Activa 'cron.enabled' en config o ejecuta somer onboard[/dim]")
    else:
        sched = result.get("scheduler", {})
        table = Table(title="Cron Scheduler")
        table.add_column("Metrica", style="cyan")
        table.add_column("Valor", style="green")
        table.add_row("Estado", "[green]corriendo[/green]" if sched.get("running") else "[red]detenido[/red]")
        table.add_row("Total jobs", str(sched.get("total_jobs", 0)))
        table.add_row("Jobs activos", str(sched.get("enabled_jobs", 0)))
        table.add_row("En ejecucion", str(sched.get("active_jobs", 0)))
        table.add_row("Max concurrente", str(sched.get("max_concurrent", 1)))
        console.print(table)

    hb = result.get("heartbeat")
    if hb:
        console.print()
        hb_table = Table(title="Heartbeat")
        hb_table.add_column("Metrica", style="cyan")
        hb_table.add_column("Valor", style="green")
        hb_table.add_row("Estado", "[green]corriendo[/green]" if hb.get("running") else "[red]detenido[/red]")
        hb_table.add_row("Habilitado", "si" if hb.get("enabled") else "no")
        hb_table.add_row("Intervalo", f"{hb.get('interval_seconds', 0)}s")
        hb_table.add_row("Destino", hb.get("target", "none"))

        stats = hb.get("stats", {})
        hb_table.add_row("Total ejecuciones", str(stats.get("total_runs", 0)))
        hb_table.add_row("OK", str(stats.get("ok", 0)))
        hb_table.add_row("Alertas enviadas", str(stats.get("alerts", 0)))
        hb_table.add_row("Errores", str(stats.get("errors", 0)))
        hb_table.add_row("Ultimo resultado", stats.get("last_result", "-"))
        console.print(hb_table)
    else:
        console.print("\n[dim]Heartbeat: no configurado[/dim]")


@cron_app.command("run-now")
def cron_run_now(
    job_id: str = typer.Argument(..., help="ID del job a ejecutar"),
    force: bool = typer.Option(False, "--force", "-f", help="Ignorar overlap_policy y estado"),
) -> None:
    """Ejecuta un job cron inmediatamente."""
    result = _gateway_rpc("cron.run", {"job_id": job_id, "force": force})

    status = result.get("status", "error")
    if status == "error":
        msg = result.get("message", "error desconocido")
        console.print(f"[red]Error: {msg}[/red]")
        raise typer.Exit(1)
    elif status == "skipped":
        console.print(f"[yellow]Job '{job_id}' fue omitido (desactivado o ya en ejecucion)[/yellow]")
    elif status == "ok":
        console.print(f"[green]Job '{job_id}' ejecutado correctamente[/green]")
    elif status == "timeout":
        console.print(f"[yellow]Job '{job_id}' termino por timeout[/yellow]")
    else:
        console.print(f"[dim]Job '{job_id}' finalizo con estado: {status}[/dim]")


@cron_app.command("history")
def cron_history(
    job_id: str = typer.Argument(..., help="ID del job"),
    limit: int = typer.Option(20, "--limit", "-n", help="Numero de entradas"),
    as_json: bool = typer.Option(False, "--json", help="Salida en JSON"),
) -> None:
    """Muestra el historial de ejecucion de un job."""
    from cron.run_log import CronRunLog

    log = CronRunLog()
    entries = log.read_entries(job_id, limit=limit)

    if as_json:
        result = [
            {
                "ts": e.ts,
                "job_id": e.job_id,
                "action": e.action,
                "status": e.status,
                "error": e.error,
                "duration_secs": e.duration_secs,
            }
            for e in entries
        ]
        console.print(json.dumps(result, indent=2))
        return

    if not entries:
        console.print(f"[dim]Sin historial para job '{job_id}'[/dim]")
        return

    table = Table(title=f"Historial: {job_id}")
    table.add_column("Fecha", style="dim")
    table.add_column("Accion", style="cyan")
    table.add_column("Estado", width=10)
    table.add_column("Duracion", style="green")
    table.add_column("Error", style="red", max_width=40)

    for e in entries:
        dt_str = _format_timestamp(e.ts)
        status_color = "green" if e.status == "ok" else "red" if e.status == "error" else "yellow"
        dur_str = f"{e.duration_secs:.1f}s" if e.duration_secs else "-"
        table.add_row(
            dt_str,
            e.action,
            f"[{status_color}]{e.status or '-'}[/{status_color}]",
            dur_str,
            (e.error or "")[:40],
        )

    console.print(table)
