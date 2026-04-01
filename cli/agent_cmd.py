"""Comando: somer agent — interacción con agentes.

Portado de OpenClaw: commands/agent.ts, agents.commands.*.ts.
Incluye: run, chat (interactivo), status, list, config.
"""

from __future__ import annotations

import asyncio
import sys
import time
from typing import Optional

import typer
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

console = Console()
agent_app = typer.Typer(no_args_is_help=True)


def _load_runner(model: Optional[str] = None) -> tuple:
    """Carga el runner de agente con su config.

    Registra providers desde la configuración (misma lógica que el gateway)
    para que el CLI funcione de forma independiente.

    Returns:
        Tupla (runner, config).
    """
    import os
    from agents.runner import AgentRunner
    from config.loader import load_config
    from config.runtime_overrides import apply_env_overrides
    from providers.registry import ProviderRegistry

    config = apply_env_overrides(load_config())
    registry = ProviderRegistry()

    # Registrar providers desde config (portado de gateway/bootstrap._setup_providers)
    for provider_id, settings in config.providers.items():
        if not getattr(settings, "enabled", True):
            continue
        try:
            provider = _create_provider(provider_id, settings)
            if provider:
                registry.register(provider)
        except Exception:
            pass

    runner = AgentRunner(
        provider_registry=registry,
        default_model=model or config.default_model,
    )
    return runner, config


def _create_provider(provider_id: str, settings: object) -> Optional[object]:
    """Crea una instancia de provider según el ID.

    Versión simplificada de gateway/bootstrap._create_provider para el CLI.
    """
    import os

    auth = getattr(settings, "auth", None)
    api_key = None
    if auth:
        api_key = getattr(auth, "api_key", None)
        if not api_key:
            env_var = getattr(auth, "api_key_env", None)
            if env_var:
                api_key = os.environ.get(env_var)

    factories = {
        "anthropic": ("providers.anthropic", "AnthropicProvider", True),
        "openai": ("providers.openai", "OpenAIProvider", True),
        "deepseek": ("providers.deepseek", "DeepSeekProvider", True),
        "google": ("providers.google", "GoogleProvider", True),
        "ollama": ("providers.ollama", "OllamaProvider", False),
        "groq": ("providers.groq", "GroqProvider", True),
        "xai": ("providers.xai", "XAIProvider", True),
        "openrouter": ("providers.openrouter", "OpenRouterProvider", True),
        "mistral": ("providers.mistral", "MistralProvider", True),
        "together": ("providers.together", "TogetherProvider", True),
        "perplexity": ("providers.perplexity", "PerplexityProvider", True),
        "claude-code": ("providers.claude_code", "ClaudeCodeProvider", False),
    }

    entry = factories.get(provider_id)
    if not entry:
        return None

    module_path, class_name, needs_key = entry

    if needs_key and not api_key:
        return None

    import importlib
    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)

    if needs_key:
        return cls(api_key=api_key)
    if provider_id == "ollama":
        base_url = getattr(auth, "base_url", None) if auth else None
        return cls(base_url=base_url or "http://127.0.0.1:11434")
    return cls()


@agent_app.command("run")
def agent_run(
    message: str = typer.Argument(..., help="Mensaje para el agente"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Modelo a usar"),
    session: Optional[str] = typer.Option(None, "--session", "-s", help="ID de sesión"),
    channel: Optional[str] = typer.Option(None, "--channel", "-c", help="Canal donde enviar respuesta (telegram, discord, slack)"),
    chat_id: Optional[str] = typer.Option(None, "--chat-id", help="Chat ID destino (default: heartbeat target)"),
    as_json: bool = typer.Option(False, "--json", help="Salida en JSON"),
) -> None:
    """Envía un mensaje al agente y muestra la respuesta.

    Con --channel, ejecuta via gateway y entrega la respuesta por el canal.
    Sin --channel, ejecuta localmente y muestra en consola.
    """
    console.print(f"[dim]Procesando: {message}[/dim]")

    if channel:
        # Ejecutar via gateway RPC para tener acceso a canales
        _agent_run_via_gateway(message, channel, chat_id, model, as_json)
        return

    async def _run() -> None:
        import json

        runner, config = _load_runner(model)
        sid = session or "cli-session"
        start = time.time()
        turn = await runner.run(sid, message, model=model)
        elapsed_ms = int((time.time() - start) * 1000)

        if as_json:
            result = {
                "session_id": sid,
                "model": model or config.default_model,
                "elapsed_ms": elapsed_ms,
                "messages": [
                    {"role": m.role.value, "content": m.content}
                    for m in turn.messages
                ],
            }
            console.print(json.dumps(result, indent=2, ensure_ascii=False))
            return

        for msg in turn.messages:
            if msg.role.value == "assistant":
                console.print(msg.content)

        console.print(f"\n[dim]({elapsed_ms}ms | {model or config.default_model})[/dim]")

    try:
        asyncio.run(_run())
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(1)


def _agent_run_via_gateway(
    message: str,
    channel: str,
    chat_id: Optional[str],
    model: Optional[str],
    as_json: bool,
) -> None:
    """Ejecuta agente via gateway RPC y entrega por canal."""
    import json

    from shared.constants import GATEWAY_HOST, GATEWAY_PORT

    try:
        import websockets.sync.client as ws_sync
    except ImportError:
        console.print("[red]Dependencia faltante: pip install websockets[/red]")
        raise typer.Exit(1)

    params = {"message": message, "channel": channel}
    if chat_id:
        params["chat_id"] = chat_id
    if model:
        params["model"] = model

    try:
        with ws_sync.connect(
            f"ws://{GATEWAY_HOST}:{GATEWAY_PORT}",
            close_timeout=5,
            open_timeout=10,
            ping_interval=None,
        ) as ws:
            request = json.dumps({
                "jsonrpc": "2.0",
                "method": "agent.run",
                "params": params,
                "id": 1,
            })
            ws.send(request)
            response = json.loads(ws.recv(timeout=300))

            if "error" in response:
                msg = response["error"].get("message", "error desconocido")
                console.print(f"[red]Error del gateway: {msg}[/red]")
                raise typer.Exit(1)

            result = response.get("result", {})

            if result.get("error"):
                console.print(f"[red]{result['error']}[/red]")
                raise typer.Exit(1)

            if as_json:
                console.print(json.dumps(result, indent=2, ensure_ascii=False))
                return

            if result.get("delivered"):
                console.print(f"[green]Respuesta enviada a {channel}[/green]")
            else:
                console.print(f"[yellow]Respuesta generada pero no entregada a {channel}[/yellow]")

            console.print(f"\n[dim]{result.get('response', '')[:200]}...[/dim]")

    except ConnectionRefusedError:
        console.print("[red]Gateway no esta corriendo. Inicia con: somer gateway start[/red]")
        raise typer.Exit(1)
    except Exception as exc:
        if "ConnectionRefused" in type(exc).__name__:
            console.print("[red]Gateway no esta corriendo. Inicia con: somer gateway start[/red]")
        else:
            console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(1)


@agent_app.command("chat")
def agent_chat(
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Modelo a usar"),
    session: Optional[str] = typer.Option(None, "--session", "-s", help="ID de sesión"),
) -> None:
    """Modo chat interactivo con el agente.

    Portado de OpenClaw: modo interactivo con historial de sesión.
    Escribe 'salir', 'exit' o 'quit' para terminar. Ctrl+C para cancelar.
    """
    runner, config = _load_runner(model)
    sid = session or f"cli-chat-{int(time.time())}"
    model_name = model or config.default_model

    console.print(Panel(
        f"[bold cyan]SOMER Chat[/bold cyan]\n"
        f"Modelo: {model_name} | Sesión: {sid}\n"
        f"Escribe 'salir' para terminar.",
        border_style="cyan",
    ))

    async def _chat_loop() -> None:
        while True:
            try:
                user_input = console.input("[bold green]> [/bold green]")
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]Chat terminado[/dim]")
                break

            trimmed = user_input.strip()
            if not trimmed:
                continue
            if trimmed.lower() in ("salir", "exit", "quit", "/q"):
                console.print("[dim]Chat terminado[/dim]")
                break

            try:
                start = time.time()
                turn = await runner.run(sid, trimmed, model=model)
                elapsed_ms = int((time.time() - start) * 1000)

                for msg in turn.messages:
                    if msg.role.value == "assistant":
                        console.print(f"\n{msg.content}")
                console.print(f"[dim]({elapsed_ms}ms)[/dim]\n")
            except Exception as exc:
                console.print(f"[red]Error: {exc}[/red]\n")

    try:
        asyncio.run(_chat_loop())
    except KeyboardInterrupt:
        console.print("\n[dim]Chat terminado[/dim]")


@agent_app.command("status")
def agent_status(
    as_json: bool = typer.Option(False, "--json", help="Salida en JSON"),
) -> None:
    """Muestra el estado del agente y providers configurados.

    Portado de OpenClaw: commands/status.command.ts — resumen de estado.
    """
    import json

    from config.loader import load_config
    from config.runtime_overrides import apply_env_overrides

    config = apply_env_overrides(load_config())

    providers = list(config.providers.keys())
    enabled_providers = [
        pid for pid, p in config.providers.items()
        if getattr(p, "enabled", True)
    ]

    status_data = {
        "default_model": config.default_model,
        "fast_model": config.fast_model,
        "providers_configured": len(providers),
        "providers_enabled": len(enabled_providers),
        "providers": enabled_providers,
        "memory_enabled": config.memory.enabled,
        "channels": list(config.channels.entries.keys()),
    }

    if as_json:
        console.print(json.dumps(status_data, indent=2))
        return

    table = Table(title="Estado del Agente")
    table.add_column("Propiedad", style="cyan")
    table.add_column("Valor", style="green")

    table.add_row("Modelo principal", config.default_model)
    table.add_row("Modelo rápido", config.fast_model)
    table.add_row("Providers activos", ", ".join(enabled_providers) or "ninguno")
    table.add_row("Memoria", "[green]activada[/green]" if config.memory.enabled else "[dim]desactivada[/dim]")
    table.add_row("Canales", ", ".join(config.channels.entries.keys()) or "ninguno")

    console.print(table)


@agent_app.command("list")
def agent_list() -> None:
    """Lista los agentes configurados.

    Portado de OpenClaw: agents.commands.list.ts.
    """
    from config.loader import load_config
    from config.runtime_overrides import apply_env_overrides

    config = apply_env_overrides(load_config())

    # SOMER 2.0 tiene un agente por defecto; en el futuro, multi-agente
    table = Table(title="Agentes")
    table.add_column("ID", style="cyan")
    table.add_column("Modelo", style="green")
    table.add_column("Estado", style="yellow")

    table.add_row(
        "default",
        config.default_model,
        "[green]activo[/green]",
    )

    console.print(table)
    console.print("[dim]SOMER 2.0 usa un agente por defecto. Multi-agente próximamente.[/dim]")


@agent_app.command("config")
def agent_config() -> None:
    """Muestra la configuración del agente actual.

    Portado de OpenClaw: agents.config.ts — detalle de configuración del agente.
    """
    import json

    from config.loader import load_config
    from config.runtime_overrides import apply_env_overrides
    from rich.syntax import Syntax

    config = apply_env_overrides(load_config())

    agent_data = {
        "default_model": config.default_model,
        "fast_model": config.fast_model,
        "memory": {
            "enabled": config.memory.enabled,
            "backend": config.memory.backend,
        },
        "gateway": {
            "host": config.gateway.host,
            "port": config.gateway.port,
        },
        "providers": {
            pid: {
                "enabled": getattr(p, "enabled", True),
            }
            for pid, p in config.providers.items()
        },
    }

    console.print(Syntax(json.dumps(agent_data, indent=2, default=str), "json"))
