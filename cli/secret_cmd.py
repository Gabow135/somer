"""Comando: somer secrets — gestión de credenciales y secretos.

Portado de OpenClaw: secrets-cli.ts (10735 líneas).
Incluye: list, set, delete, validate, rotate, audit.
"""

from __future__ import annotations

import json
import os
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()
secret_app = typer.Typer(no_args_is_help=True)


def _get_store() -> "CredentialStore":
    """Obtiene una instancia del almacén de credenciales."""
    from secrets.store import CredentialStore

    return CredentialStore()


@secret_app.command("list")
def secret_list(
    as_json: bool = typer.Option(False, "--json", help="Salida en JSON"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Mostrar detalles"),
) -> None:
    """Lista los secretos/credenciales almacenados.

    Portado de OpenClaw: secrets audit — inventario de credenciales.
    """
    store = _get_store()
    services = store.list_services()

    if as_json:
        result = []
        for svc in services:
            entry = {"service": svc}
            if verbose:
                try:
                    creds = store.retrieve(svc)
                    entry["keys"] = list(creds.keys())
                except Exception as exc:
                    entry["error"] = str(exc)
            result.append(entry)
        console.print(json.dumps(result, indent=2))
        return

    if not services:
        console.print("[dim]No hay credenciales almacenadas[/dim]")
        console.print("[dim]Almacena credenciales con: somer secrets set <servicio> <key> <value>[/dim]")
        return

    table = Table(title="Credenciales almacenadas")
    table.add_column("Servicio", style="cyan")
    table.add_column("Estado", width=12)
    if verbose:
        table.add_column("Claves", style="dim")

    for svc in services:
        try:
            creds = store.retrieve(svc)
            status = "[green]OK[/green]"
            keys_str = ", ".join(creds.keys()) if verbose else ""
        except Exception:
            status = "[red]error[/red]"
            keys_str = "no descifrable" if verbose else ""

        row = [svc, status]
        if verbose:
            row.append(keys_str)
        table.add_row(*row)

    console.print(table)
    console.print(f"\n[dim]{len(services)} servicio(s)[/dim]")

    # Mostrar también variables de entorno de providers
    env_keys = [
        ("ANTHROPIC_API_KEY", "Anthropic"),
        ("OPENAI_API_KEY", "OpenAI"),
        ("GOOGLE_API_KEY", "Google"),
        ("DEEPSEEK_API_KEY", "DeepSeek"),
        ("GROQ_API_KEY", "Groq"),
        ("XAI_API_KEY", "xAI"),
        ("OPENROUTER_API_KEY", "OpenRouter"),
        ("MISTRAL_API_KEY", "Mistral"),
    ]

    env_found = [(var, name) for var, name in env_keys if os.environ.get(var)]
    if env_found:
        console.print("\n[dim]Variables de entorno detectadas:[/dim]")
        for var, name in env_found:
            val = os.environ[var]
            preview = val[:8] + "..." if len(val) > 8 else val
            console.print(f"  [cyan]{name}[/cyan]: {preview}")


@secret_app.command("set")
def secret_set(
    service: str = typer.Argument(..., help="Nombre del servicio (ej: anthropic)"),
    key: str = typer.Argument(..., help="Clave de la credencial (ej: api_key)"),
    value: Optional[str] = typer.Argument(None, help="Valor (o usa --prompt para entrada segura)"),
    prompt_input: bool = typer.Option(False, "--prompt", "-p", help="Pedir valor de forma segura"),
) -> None:
    """Almacena una credencial en el store encriptado.

    Portado de OpenClaw: secrets configure con almacenamiento seguro.
    """
    if prompt_input or value is None:
        value = typer.prompt(f"Valor para {service}.{key}", hide_input=True)

    if not value:
        console.print("[red]Valor vacío — operación cancelada[/red]")
        raise typer.Exit(1)

    store = _get_store()

    # Cargar credenciales existentes o crear nuevas
    try:
        creds = store.retrieve(service)
    except Exception:
        creds = {}

    creds[key] = value
    store.store(service, creds)
    console.print(f"[green]Credencial '{service}.{key}' almacenada[/green]")


@secret_app.command("delete")
def secret_delete(
    service: str = typer.Argument(..., help="Nombre del servicio"),
    key: Optional[str] = typer.Argument(None, help="Clave específica (o todo el servicio)"),
    force: bool = typer.Option(False, "--force", "-f", help="No pedir confirmación"),
) -> None:
    """Elimina credenciales del store.

    Portado de OpenClaw: eliminación de secretos con confirmación.
    """
    store = _get_store()

    if key:
        # Eliminar solo una clave
        try:
            creds = store.retrieve(service)
        except Exception:
            console.print(f"[red]Servicio '{service}' no encontrado[/red]")
            raise typer.Exit(1)

        if key not in creds:
            console.print(f"[red]Clave '{key}' no encontrada en '{service}'[/red]")
            raise typer.Exit(1)

        if not force:
            if not typer.confirm(f"Eliminar '{service}.{key}'?"):
                raise typer.Abort()

        del creds[key]
        if creds:
            store.store(service, creds)
        else:
            store.delete(service)
        console.print(f"[green]'{service}.{key}' eliminado[/green]")
    else:
        # Eliminar todo el servicio
        if not force:
            if not typer.confirm(f"Eliminar TODAS las credenciales de '{service}'?"):
                raise typer.Abort()

        deleted = store.delete(service)
        if deleted:
            console.print(f"[green]Credenciales de '{service}' eliminadas[/green]")
        else:
            console.print(f"[yellow]No había credenciales para '{service}'[/yellow]")


@secret_app.command("validate")
def secret_validate(
    service: Optional[str] = typer.Argument(None, help="Servicio específico (o todos)"),
    as_json: bool = typer.Option(False, "--json", help="Salida en JSON"),
) -> None:
    """Valida formato de API keys y credenciales.

    Portado de OpenClaw: secrets audit con validación de formato.
    """
    from secrets.validation import validate_api_key_format, PROVIDER_KEY_PATTERNS

    store = _get_store()
    services = [service] if service else store.list_services()
    results = []

    # Validar credenciales almacenadas
    for svc in services:
        try:
            creds = store.retrieve(svc)
            for key, val in creds.items():
                if key in ("api_key", "token", "secret"):
                    result = validate_api_key_format(svc, str(val))
                    results.append({
                        "source": "store",
                        "service": svc,
                        "key": key,
                        "valid": result.valid,
                        "message": result.message,
                    })
        except Exception as exc:
            results.append({
                "source": "store",
                "service": svc,
                "key": "*",
                "valid": False,
                "message": f"Error: {exc}",
            })

    # Validar variables de entorno
    env_providers = {
        "ANTHROPIC_API_KEY": "anthropic",
        "OPENAI_API_KEY": "openai",
        "GOOGLE_API_KEY": "google",
        "DEEPSEEK_API_KEY": "deepseek",
        "GROQ_API_KEY": "groq",
        "XAI_API_KEY": "xai",
        "OPENROUTER_API_KEY": "openrouter",
        "MISTRAL_API_KEY": "mistral",
    }

    for env_var, provider in env_providers.items():
        val = os.environ.get(env_var)
        if val:
            result = validate_api_key_format(provider, val)
            results.append({
                "source": "env",
                "service": provider,
                "key": env_var,
                "valid": result.valid,
                "message": result.message,
            })

    if as_json:
        console.print(json.dumps(results, indent=2))
        return

    if not results:
        console.print("[dim]No hay secretos para validar[/dim]")
        return

    table = Table(title="Validación de secretos")
    table.add_column("Fuente", style="dim")
    table.add_column("Servicio", style="cyan")
    table.add_column("Clave", style="dim")
    table.add_column("Válido", width=8)
    table.add_column("Mensaje", style="dim")

    for r in results:
        valid_str = "[green]OK[/green]" if r["valid"] else "[red]FAIL[/red]"
        table.add_row(r["source"], r["service"], r["key"], valid_str, r.get("message", "")[:40])

    console.print(table)

    valid_count = sum(1 for r in results if r["valid"])
    total = len(results)
    if valid_count == total:
        console.print(f"\n[green]Todos válidos ({total}/{total})[/green]")
    else:
        console.print(f"\n[yellow]{valid_count}/{total} válidos[/yellow]")


@secret_app.command("rotate")
def secret_rotate(
    service: str = typer.Argument(..., help="Servicio cuya clave rotar"),
    key: str = typer.Option("api_key", "--key", "-k", help="Clave a rotar"),
) -> None:
    """Rota una credencial (solicita nuevo valor).

    Portado de OpenClaw: rotación de secretos con verificación.
    """
    store = _get_store()

    # Verificar que existe
    try:
        creds = store.retrieve(service)
    except Exception:
        console.print(f"[red]Servicio '{service}' no encontrado[/red]")
        raise typer.Exit(1)

    if key not in creds:
        console.print(f"[yellow]Clave '{key}' no existe en '{service}'. Se creará.[/yellow]")

    old_preview = str(creds.get(key, ""))[:8] + "..." if creds.get(key) else "N/A"
    console.print(f"[dim]Valor actual: {old_preview}[/dim]")

    new_value = typer.prompt(f"Nuevo valor para {service}.{key}", hide_input=True)
    confirm_value = typer.prompt("Confirmar nuevo valor", hide_input=True)

    if new_value != confirm_value:
        console.print("[red]Los valores no coinciden — cancelado[/red]")
        raise typer.Exit(1)

    creds[key] = new_value
    store.store(service, creds)
    console.print(f"[green]Credencial '{service}.{key}' rotada correctamente[/green]")
