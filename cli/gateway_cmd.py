"""Comando: somer gateway — control plane WebSocket.

Portado de OpenClaw: gateway-cli/ (register.ts, run.ts, call.ts, discover.ts).
Incluye: start, stop, status, restart, health, logs, call.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import time
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from shared.constants import GATEWAY_HOST, GATEWAY_PORT

console = Console()
gateway_app = typer.Typer(no_args_is_help=True)

# ── PID file para gestión de proceso ─────────────────────────

_PID_FILE = os.path.expanduser("~/.somer/gateway.pid")


def _write_pid(pid: int) -> None:
    """Escribe el PID del gateway al archivo."""
    os.makedirs(os.path.dirname(_PID_FILE), exist_ok=True)
    with open(_PID_FILE, "w") as f:
        f.write(str(pid))


def _read_pid() -> Optional[int]:
    """Lee el PID del gateway si el archivo existe."""
    try:
        with open(_PID_FILE) as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return None


def _clear_pid() -> None:
    """Elimina el archivo PID."""
    try:
        os.unlink(_PID_FILE)
    except FileNotFoundError:
        pass


def _is_gateway_running(host: str = GATEWAY_HOST, port: int = GATEWAY_PORT) -> bool:
    """Verifica si el gateway está escuchando."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            return s.connect_ex((host, port)) == 0
    except Exception:
        return False


def _is_process_alive(pid: int) -> bool:
    """Verifica si un proceso con el PID dado sigue vivo."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


# ── Comandos ─────────────────────────────────────────────────


@gateway_app.command("start")
def gateway_start(
    host: str = typer.Option(GATEWAY_HOST, help="Host del gateway"),
    port: int = typer.Option(GATEWAY_PORT, help="Puerto del gateway"),
    detach: bool = typer.Option(False, "--detach", "-d", help="Ejecutar en background"),
) -> None:
    """Inicia el gateway con todos los servicios (providers, canales, agente).

    Portado de OpenClaw: gateway run con gestión de proceso foreground/background.
    """
    if _is_gateway_running(host, port):
        console.print(f"[yellow]Gateway ya está corriendo en ws://{host}:{port}[/yellow]")
        raise typer.Exit(1)

    if detach:
        import subprocess
        import sys

        console.print(f"[cyan]Iniciando gateway en background ws://{host}:{port}...[/cyan]")
        proc = subprocess.Popen(
            [sys.executable, "-m", "gateway.server", "--host", host, "--port", str(port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        _write_pid(proc.pid)
        # Esperar brevemente y verificar
        time.sleep(1.5)
        if _is_gateway_running(host, port):
            console.print(f"[green]Gateway iniciado (PID: {proc.pid})[/green]")
        else:
            console.print("[yellow]Gateway iniciado pero aún no responde. Verifica con: somer gateway status[/yellow]")
        return

    console.print(f"[cyan]SOMER Gateway — Iniciando en ws://{host}:{port}[/cyan]\n")
    _write_pid(os.getpid())

    async def _run() -> None:
        from gateway.bootstrap import GatewayBootstrap

        bootstrap = GatewayBootstrap(host=host, port=port)
        await bootstrap.start()

        console.print(f"\n[bold green]Sistema listo. Ctrl+C para detener.[/bold green]\n")

        try:
            await asyncio.Future()  # Run forever
        except asyncio.CancelledError:
            pass
        finally:
            await bootstrap.stop()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        console.print("\n[yellow]Gateway detenido[/yellow]")
    finally:
        _clear_pid()


@gateway_app.command("stop")
def gateway_stop() -> None:
    """Detiene el gateway en ejecución.

    Portado de OpenClaw: gateway stop con señal SIGTERM y verificación.
    """
    pid = _read_pid()

    if pid and _is_process_alive(pid):
        console.print(f"[dim]Enviando SIGTERM al proceso {pid}...[/dim]")
        try:
            os.kill(pid, signal.SIGTERM)
            # Esperar a que termine
            for _ in range(10):
                time.sleep(0.5)
                if not _is_process_alive(pid):
                    break
            else:
                console.print("[yellow]Proceso no terminó, enviando SIGKILL...[/yellow]")
                os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        _clear_pid()
        console.print("[green]Gateway detenido[/green]")
    elif _is_gateway_running():
        console.print("[yellow]Gateway está corriendo pero no se conoce su PID.[/yellow]")
        console.print("[dim]Intenta detenerlo manualmente o reinicia.[/dim]")
    else:
        console.print("[dim]Gateway no está corriendo[/dim]")


@gateway_app.command("restart")
def gateway_restart(
    host: str = typer.Option(GATEWAY_HOST, help="Host del gateway"),
    port: int = typer.Option(GATEWAY_PORT, help="Puerto del gateway"),
) -> None:
    """Reinicia el gateway (stop + start).

    Portado de OpenClaw: secuencia stop-start con espera.
    """
    console.print("[dim]Deteniendo gateway...[/dim]")
    gateway_stop()
    time.sleep(1)
    console.print("[dim]Reiniciando...[/dim]")
    gateway_start(host=host, port=port, detach=True)


@gateway_app.command("status")
def gateway_status(
    as_json: bool = typer.Option(False, "--json", help="Salida en JSON"),
) -> None:
    """Muestra el estado del gateway.

    Portado de OpenClaw: gateway probe con status, health y resumen.
    """
    host = GATEWAY_HOST
    port = GATEWAY_PORT
    running = _is_gateway_running(host, port)
    pid = _read_pid()
    pid_alive = _is_process_alive(pid) if pid else False

    if as_json:
        result = {
            "running": running,
            "url": f"ws://{host}:{port}",
            "pid": pid if pid_alive else None,
        }
        console.print(json.dumps(result, indent=2))
        return

    table = Table(title="Gateway Status")
    table.add_column("Propiedad", style="cyan")
    table.add_column("Valor", style="green")

    status_str = "[green]activo[/green]" if running else "[red]inactivo[/red]"
    table.add_row("Estado", status_str)
    table.add_row("URL", f"ws://{host}:{port}")
    table.add_row("PID", str(pid) if pid_alive else "N/A")
    table.add_row("Reachable", "si" if running else "no")

    console.print(table)


@gateway_app.command("health")
def gateway_health() -> None:
    """Verifica la salud del gateway con un probe.

    Portado de OpenClaw: gateway health con WebSocket ping.
    """
    if not _is_gateway_running():
        console.print("[red]Gateway no está corriendo[/red]")
        raise typer.Exit(1)

    start = time.time()
    try:
        import websockets.sync.client as ws_sync
        with ws_sync.connect(f"ws://{GATEWAY_HOST}:{GATEWAY_PORT}", close_timeout=3) as ws:
            request = json.dumps({
                "jsonrpc": "2.0",
                "method": "health",
                "id": 1,
            })
            ws.send(request)
            response = json.loads(ws.recv(timeout=5))
            elapsed_ms = int((time.time() - start) * 1000)

            if "result" in response:
                console.print(f"[green]Gateway saludable[/green] ({elapsed_ms}ms)")
            else:
                error = response.get("error", {}).get("message", "desconocido")
                console.print(f"[yellow]Gateway respondió con error: {error}[/yellow]")
    except ImportError:
        # Fallback si websockets sync no está disponible
        console.print("[green]Gateway alcanzable[/green] (puerto abierto)")
    except Exception as exc:
        console.print(f"[red]Health check falló: {exc}[/red]")
        raise typer.Exit(1)


@gateway_app.command("logs")
def gateway_logs(
    lines: int = typer.Option(50, "--lines", "-n", help="Número de líneas a mostrar"),
    follow: bool = typer.Option(False, "--follow", "-f", help="Seguir log en tiempo real"),
) -> None:
    """Muestra logs recientes del gateway.

    Portado de OpenClaw: logs-cli.ts con tail y follow.
    """
    from shared.constants import DEFAULT_LOGS_DIR

    log_file = DEFAULT_LOGS_DIR / "gateway.log"

    if not log_file.exists():
        console.print("[dim]No hay logs de gateway disponibles[/dim]")
        console.print(f"[dim]Ruta esperada: {log_file}[/dim]")
        return

    content = log_file.read_text(encoding="utf-8", errors="replace")
    log_lines = content.splitlines()

    if not follow:
        for line in log_lines[-lines:]:
            console.print(line)
        console.print(f"\n[dim]{min(lines, len(log_lines))}/{len(log_lines)} líneas mostradas[/dim]")
        return

    # Follow mode — tail -f equivalente
    console.print(f"[dim]Siguiendo {log_file} (Ctrl+C para salir)...[/dim]\n")
    for line in log_lines[-lines:]:
        console.print(line)

    try:
        pos = log_file.stat().st_size
        while True:
            time.sleep(0.5)
            new_size = log_file.stat().st_size
            if new_size > pos:
                with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(pos)
                    new_content = f.read()
                    if new_content:
                        console.print(new_content, end="")
                pos = new_size
    except KeyboardInterrupt:
        console.print("\n[dim]Log follow detenido[/dim]")
