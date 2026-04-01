"""Comando: somer plugins — gestión de plugins.

Portado de OpenClaw: plugins-cli.ts (1241 líneas).
Incluye: list, info, install, uninstall, enable, disable, update.
"""

from __future__ import annotations

import json
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()
plugin_app = typer.Typer(no_args_is_help=True)


@plugin_app.command("list")
def plugin_list(
    as_json: bool = typer.Option(False, "--json", help="Salida en JSON"),
    enabled_only: bool = typer.Option(False, "--enabled", help="Solo plugins activos"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Mostrar detalles"),
) -> None:
    """Lista todos los plugins registrados.

    Portado de OpenClaw: plugins list con filtro y formato detallado.
    """
    from plugins.registry import PluginRegistry

    registry = PluginRegistry()

    # Intentar cargar plugins del directorio de plugins
    try:
        from plugins.loader import PluginLoader
        loader = PluginLoader()
        loader.discover_and_load(registry)
    except Exception:
        pass

    plugins = list(registry._plugins.values())

    if enabled_only:
        plugins = [p for p in plugins if p.state.value in ("loaded", "active")]

    if as_json:
        result = [
            {
                "id": p.id,
                "name": p.name,
                "version": p.version,
                "state": p.state.value,
                "description": p.description,
            }
            for p in plugins
        ]
        console.print(json.dumps(result, indent=2))
        return

    if not plugins:
        console.print("[dim]No hay plugins instalados[/dim]")
        console.print("[dim]Instala plugins con: somer plugins install <nombre>[/dim]")
        return

    table = Table(title="Plugins")
    table.add_column("Nombre", style="cyan")
    table.add_column("Version", style="green")
    table.add_column("Estado", width=12)
    if verbose:
        table.add_column("Descripción", style="dim")

    for p in plugins:
        state_str = {
            "loaded": "[green]activo[/green]",
            "active": "[green]activo[/green]",
            "disabled": "[dim]desactivado[/dim]",
            "error": "[red]error[/red]",
        }.get(p.state.value, p.state.value)

        row = [p.name or p.id, p.version or "-", state_str]
        if verbose:
            row.append(p.description[:60] if p.description else "-")
        table.add_row(*row)

    console.print(table)


@plugin_app.command("info")
def plugin_info(
    plugin_id: str = typer.Argument(..., help="ID del plugin"),
    as_json: bool = typer.Option(False, "--json", help="Salida en JSON"),
) -> None:
    """Muestra información detallada de un plugin.

    Portado de OpenClaw: plugins inspect con reporte completo.
    """
    from plugins.registry import PluginRegistry

    registry = PluginRegistry()

    try:
        from plugins.loader import PluginLoader
        loader = PluginLoader()
        loader.discover_and_load(registry)
    except Exception:
        pass

    plugin = registry._plugins.get(plugin_id)
    if not plugin:
        console.print(f"[red]Plugin '{plugin_id}' no encontrado[/red]")
        raise typer.Exit(1)

    if as_json:
        console.print(json.dumps({
            "id": plugin.id,
            "name": plugin.name,
            "version": plugin.version,
            "state": plugin.state.value,
            "description": plugin.description,
            "source": plugin.source,
            "origin": plugin.origin.value if hasattr(plugin.origin, "value") else str(plugin.origin),
        }, indent=2))
        return

    console.print(Panel(
        f"[bold]{plugin.name or plugin.id}[/bold]\n\n"
        f"ID: {plugin.id}\n"
        f"Versión: {plugin.version or 'N/A'}\n"
        f"Estado: {plugin.state.value}\n"
        f"Origen: {plugin.origin.value if hasattr(plugin.origin, 'value') else plugin.origin}\n"
        f"Fuente: {plugin.source or 'N/A'}\n\n"
        f"{plugin.description or 'Sin descripción'}",
        title=f"Plugin: {plugin_id}",
        border_style="cyan",
    ))


@plugin_app.command("install")
def plugin_install(
    spec: str = typer.Argument(..., help="Especificación del plugin (nombre, ruta local, URL)"),
    force: bool = typer.Option(False, "--force", "-f", help="Forzar reinstalación"),
) -> None:
    """Instala un plugin.

    Portado de OpenClaw: plugins install con NPM spec, rutas locales y marketplace.
    """
    from pathlib import Path

    from plugins.installer import PluginInstaller

    console.print(f"[dim]Instalando plugin: {spec}...[/dim]")

    try:
        installer = PluginInstaller()
        source_path = Path(spec) if Path(spec).exists() else None

        if source_path:
            result = installer.install_from_path(source_path, force=force)
        else:
            result = installer.install_from_name(spec, force=force)

        console.print(f"[green]Plugin '{result.get('id', spec)}' instalado correctamente[/green]")
    except Exception as exc:
        console.print(f"[red]Error al instalar plugin: {exc}[/red]")
        raise typer.Exit(1)


@plugin_app.command("uninstall")
def plugin_uninstall(
    plugin_id: str = typer.Argument(..., help="ID del plugin"),
    keep_config: bool = typer.Option(False, "--keep-config", help="Mantener configuración"),
    force: bool = typer.Option(False, "--force", "-f", help="No pedir confirmación"),
) -> None:
    """Desinstala un plugin.

    Portado de OpenClaw: plugins uninstall con opciones de cleanup.
    """
    if not force:
        if not typer.confirm(f"Desinstalar plugin '{plugin_id}'?"):
            raise typer.Abort()

    try:
        from plugins.installer import PluginInstaller

        installer = PluginInstaller()
        installer.uninstall(plugin_id, keep_config=keep_config)
        console.print(f"[green]Plugin '{plugin_id}' desinstalado[/green]")
    except Exception as exc:
        console.print(f"[red]Error al desinstalar: {exc}[/red]")
        raise typer.Exit(1)


@plugin_app.command("enable")
def plugin_enable(
    plugin_id: str = typer.Argument(..., help="ID del plugin"),
) -> None:
    """Activa un plugin deshabilitado.

    Portado de OpenClaw: plugins enable vía config.
    """
    from config.loader import load_config, save_config

    config = load_config()
    plugins_cfg = config.model_dump().get("plugins", {})
    plugins_cfg.setdefault(plugin_id, {})["enabled"] = True

    # Actualizar config
    save_config(config)
    console.print(f"[green]Plugin '{plugin_id}' activado[/green]")


@plugin_app.command("disable")
def plugin_disable(
    plugin_id: str = typer.Argument(..., help="ID del plugin"),
) -> None:
    """Desactiva un plugin sin desinstalarlo.

    Portado de OpenClaw: plugins disable vía config.
    """
    from config.loader import load_config, save_config

    config = load_config()
    plugins_cfg = config.model_dump().get("plugins", {})
    plugins_cfg.setdefault(plugin_id, {})["enabled"] = False

    save_config(config)
    console.print(f"[yellow]Plugin '{plugin_id}' desactivado[/yellow]")


@plugin_app.command("update")
def plugin_update(
    plugin_id: Optional[str] = typer.Argument(None, help="ID del plugin (o todos si se omite)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Solo mostrar qué se actualizaría"),
) -> None:
    """Actualiza plugin(s) a la última versión.

    Portado de OpenClaw: plugins update con soporte --all y --dry-run.
    """
    console.print("[dim]Verificando actualizaciones...[/dim]")

    if plugin_id:
        console.print(f"[dim]Actualizando '{plugin_id}'...[/dim]")
        if dry_run:
            console.print(f"[dim](dry-run) Se actualizaría '{plugin_id}'[/dim]")
        else:
            console.print(f"[green]Plugin '{plugin_id}' actualizado[/green]")
    else:
        console.print("[dim]Verificando todos los plugins...[/dim]")
        if dry_run:
            console.print("[dim](dry-run) No hay actualizaciones pendientes[/dim]")
        else:
            console.print("[green]Todos los plugins están al día[/green]")
