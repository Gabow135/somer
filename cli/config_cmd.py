"""Comando: somer config — gestión de configuración.

Portado de OpenClaw: config-cli.ts (1380 líneas).
Incluye: show, init, validate, edit, get/set, help por sección, diff, reset, path.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.tree import Tree

console = Console()
config_app = typer.Typer(no_args_is_help=True)


# ── Helpers internos ─────────────────────────────────────────


def _load_config(path: Optional[str] = None) -> Any:
    """Carga config con overrides de entorno."""
    from config.loader import load_config
    from config.runtime_overrides import apply_env_overrides

    config_path = Path(path) if path else None
    return apply_env_overrides(load_config(config_path))


def _get_nested(obj: Any, key_path: str) -> Any:
    """Accede a un valor anidado con notación de puntos.

    Portado de OpenClaw: getAtPath() en config-cli.ts.
    """
    parts = key_path.split(".")
    current = obj
    for part in parts:
        if isinstance(current, dict):
            if part not in current:
                raise KeyError(f"Clave '{part}' no encontrada en ruta '{key_path}'")
            current = current[part]
        elif hasattr(current, part):
            current = getattr(current, part)
        else:
            raise KeyError(f"Clave '{part}' no encontrada en ruta '{key_path}'")
    return current


def _set_nested(data: Dict[str, Any], key_path: str, value: Any) -> None:
    """Establece un valor anidado con notación de puntos.

    Portado de OpenClaw: setAtPath() en config-cli.ts.
    """
    parts = key_path.split(".")
    current = data
    for part in parts[:-1]:
        if part not in current:
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


def _parse_value(raw: str) -> Any:
    """Parsea un valor de config (intenta JSON, luego literal).

    Portado de OpenClaw: parseValue() en config-cli.ts.
    """
    trimmed = raw.strip()
    # Booleanos
    if trimmed.lower() == "true":
        return True
    if trimmed.lower() == "false":
        return False
    # Números
    try:
        if "." in trimmed:
            return float(trimmed)
        return int(trimmed)
    except ValueError:
        pass
    # JSON
    try:
        return json.loads(trimmed)
    except (json.JSONDecodeError, ValueError):
        pass
    # String literal
    return trimmed


# ── Secciones de ayuda ───────────────────────────────────────

_SECTION_HELP: Dict[str, str] = {
    "gateway": (
        "Configuración del gateway WebSocket.\n"
        "  gateway.host    — Host de escucha (default: 127.0.0.1)\n"
        "  gateway.port    — Puerto de escucha (default: 18789)\n"
        "  gateway.timeout — Timeout de conexión en segundos"
    ),
    "providers": (
        "Providers LLM configurados.\n"
        "  providers.<id>.enabled    — Activar/desactivar\n"
        "  providers.<id>.auth       — Configuración de autenticación\n"
        "  Providers disponibles: anthropic, openai, deepseek, google, groq, etc."
    ),
    "memory": (
        "Sistema de memoria híbrida (BM25 + vector).\n"
        "  memory.enabled   — Activar/desactivar\n"
        "  memory.backend   — Backend (sqlite)\n"
        "  memory.max_results — Resultados máximos por búsqueda"
    ),
    "channels": (
        "Canales de comunicación.\n"
        "  channels.entries.<id>.enabled — Activar/desactivar canal\n"
        "  channels.entries.<id>.plugin  — Plugin del canal\n"
        "  channels.entries.<id>.config  — Configuración específica del canal"
    ),
    "models": (
        "Configuración de modelos.\n"
        "  default_model — Modelo principal para tareas complejas\n"
        "  fast_model    — Modelo rápido para clasificación y tareas simples"
    ),
}


# ── Comandos ─────────────────────────────────────────────────


@config_app.command("show")
def config_show(
    path: Optional[str] = typer.Option(None, help="Ruta al config file"),
    section: Optional[str] = typer.Option(None, "--section", "-s", help="Sección específica"),
    as_json: bool = typer.Option(False, "--json", help="Salida en formato JSON"),
) -> None:
    """Muestra la configuración actual."""
    config = _load_config(path)

    if as_json:
        data = config.model_dump() if hasattr(config, "model_dump") else config.dict()
        if section:
            try:
                data = _get_nested(data, section)
            except KeyError:
                console.print(f"[red]Sección '{section}' no encontrada[/red]")
                raise typer.Exit(1)
        console.print(Syntax(json.dumps(data, indent=2, default=str), "json"))
        return

    if section:
        data = config.model_dump() if hasattr(config, "model_dump") else config.dict()
        try:
            value = _get_nested(data, section)
        except KeyError:
            console.print(f"[red]Sección '{section}' no encontrada[/red]")
            raise typer.Exit(1)
        if isinstance(value, dict):
            console.print(Syntax(json.dumps(value, indent=2, default=str), "json"))
        else:
            console.print(f"{section} = {value}")
        return

    table = Table(title="Configuración SOMER 2.0")
    table.add_column("Clave", style="cyan")
    table.add_column("Valor", style="green")

    table.add_row("version", config.version)
    table.add_row("default_model", config.default_model)
    table.add_row("fast_model", config.fast_model)
    table.add_row("gateway", f"{config.gateway.host}:{config.gateway.port}")
    table.add_row("memory.backend", config.memory.backend)
    table.add_row("memory.enabled", str(config.memory.enabled))
    table.add_row("providers", ", ".join(config.providers.keys()) or "ninguno")
    table.add_row("channels", ", ".join(config.channels.entries.keys()) or "ninguno")

    console.print(table)


@config_app.command("init")
def config_init(
    force: bool = typer.Option(False, "--force", "-f", help="Sobrescribir sin confirmar"),
) -> None:
    """Crea configuración por defecto."""
    from config.loader import save_config
    from config.schema import SomerConfig
    from shared.constants import DEFAULT_CONFIG_PATH

    if DEFAULT_CONFIG_PATH.exists() and not force:
        if not typer.confirm("Config ya existe. Sobrescribir?"):
            raise typer.Abort()

    config = SomerConfig()
    save_config(config)
    console.print(f"[green]Config creada en {DEFAULT_CONFIG_PATH}[/green]")


@config_app.command("validate")
def config_validate(
    path: Optional[str] = typer.Option(None, help="Ruta al config file"),
    strict: bool = typer.Option(False, "--strict", help="Modo estricto (warnings son errores)"),
) -> None:
    """Valida la configuración y muestra errores/warnings.

    Portado de OpenClaw: config validate con normalización de issues.
    """
    from config.loader import validate_config

    try:
        config_path = Path(path) if path else None
        issues = validate_config(config_path)

        if not issues:
            console.print("[green]Configuración válida - sin problemas detectados[/green]")
            return

        errors = [i for i in issues if i.get("level") == "error"]
        warnings = [i for i in issues if i.get("level") == "warning"]

        if errors:
            console.print(f"\n[red]{len(errors)} error(es):[/red]")
            for err in errors:
                console.print(f"  [red]x[/red] {err.get('message', str(err))}")

        if warnings:
            console.print(f"\n[yellow]{len(warnings)} advertencia(s):[/yellow]")
            for warn in warnings:
                console.print(f"  [yellow]![/yellow] {warn.get('message', str(warn))}")

        if errors or (strict and warnings):
            raise typer.Exit(1)

    except typer.Exit:
        raise
    except Exception as exc:
        console.print(f"[red]Error de validación: {exc}[/red]")
        raise typer.Exit(1)


@config_app.command("edit")
def config_edit(
    editor: Optional[str] = typer.Option(None, "--editor", "-e", help="Editor a usar"),
) -> None:
    """Abre la configuración en el editor por defecto.

    Portado de OpenClaw: config edit con detección de $EDITOR.
    """
    from shared.constants import DEFAULT_CONFIG_PATH

    if not DEFAULT_CONFIG_PATH.exists():
        console.print("[yellow]No existe configuración. Ejecuta 'somer config init' primero.[/yellow]")
        raise typer.Exit(1)

    ed = editor or os.environ.get("EDITOR") or os.environ.get("VISUAL")
    if not ed:
        # Detectar editor disponible
        for candidate in ("code", "nano", "vim", "vi", "notepad"):
            try:
                subprocess.run(
                    ["which", candidate] if sys.platform != "win32" else ["where", candidate],
                    capture_output=True, check=True,
                )
                ed = candidate
                break
            except (subprocess.CalledProcessError, FileNotFoundError):
                continue

    if not ed:
        console.print("[red]No se encontró editor. Establece $EDITOR o usa --editor.[/red]")
        raise typer.Exit(1)

    console.print(f"[dim]Abriendo {DEFAULT_CONFIG_PATH} con {ed}...[/dim]")
    try:
        subprocess.run([ed, str(DEFAULT_CONFIG_PATH)], check=True)
    except Exception as exc:
        console.print(f"[red]Error al abrir editor: {exc}[/red]")
        raise typer.Exit(1)


@config_app.command("get")
def config_get(
    key: str = typer.Argument(..., help="Clave (notación de puntos, ej: gateway.port)"),
    path: Optional[str] = typer.Option(None, help="Ruta al config file"),
) -> None:
    """Obtiene un valor de configuración por clave.

    Portado de OpenClaw: config get con parseo de rutas anidadas.
    """
    config = _load_config(path)
    data = config.model_dump() if hasattr(config, "model_dump") else config.dict()

    try:
        value = _get_nested(data, key)
    except KeyError:
        console.print(f"[red]Clave '{key}' no encontrada[/red]")
        raise typer.Exit(1)

    if isinstance(value, (dict, list)):
        console.print(Syntax(json.dumps(value, indent=2, default=str), "json"))
    else:
        console.print(str(value))


@config_app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Clave (notación de puntos, ej: gateway.port)"),
    value: str = typer.Argument(..., help="Valor a establecer"),
    path: Optional[str] = typer.Option(None, help="Ruta al config file"),
) -> None:
    """Establece un valor de configuración.

    Portado de OpenClaw: config set con parseo de paths y valores tipados.
    """
    from config.loader import load_config, save_config
    from shared.constants import DEFAULT_CONFIG_PATH

    config_path = Path(path) if path else None
    config = load_config(config_path)
    data = config.model_dump() if hasattr(config, "model_dump") else config.dict()

    parsed_value = _parse_value(value)
    try:
        _set_nested(data, key, parsed_value)
    except Exception as exc:
        console.print(f"[red]Error al establecer '{key}': {exc}[/red]")
        raise typer.Exit(1)

    # Reconstruir config desde data
    from config.schema import SomerConfig
    try:
        new_config = SomerConfig(**data)
    except Exception as exc:
        console.print(f"[red]Valor inválido para '{key}': {exc}[/red]")
        raise typer.Exit(1)

    save_config(new_config, config_path or DEFAULT_CONFIG_PATH)
    console.print(f"[green]{key} = {parsed_value}[/green]")


@config_app.command("help-section")
def config_help_section(
    section: str = typer.Argument(
        ..., help="Sección (gateway, providers, memory, channels, models)"
    ),
) -> None:
    """Muestra ayuda detallada de una sección de configuración.

    Portado de OpenClaw: config help con documentación por sección.
    """
    text = _SECTION_HELP.get(section)
    if not text:
        available = ", ".join(_SECTION_HELP.keys())
        console.print(f"[red]Sección '{section}' no reconocida. Disponibles: {available}[/red]")
        raise typer.Exit(1)

    console.print(Panel(text, title=f"Config: {section}", border_style="cyan"))


@config_app.command("diff")
def config_diff(
    path: Optional[str] = typer.Option(None, help="Ruta al config file"),
) -> None:
    """Muestra diferencias entre config actual y la por defecto.

    Portado de OpenClaw: diff entre configuración activa y defaults.
    """
    from config.schema import SomerConfig

    config = _load_config(path)
    default = SomerConfig()

    current_data = config.model_dump() if hasattr(config, "model_dump") else config.dict()
    default_data = default.model_dump() if hasattr(default, "model_dump") else default.dict()

    diffs: List[tuple] = []

    def _compare(cur: Any, dflt: Any, prefix: str = "") -> None:
        """Compara recursivamente dos dicts."""
        if isinstance(cur, dict) and isinstance(dflt, dict):
            all_keys = set(list(cur.keys()) + list(dflt.keys()))
            for k in sorted(all_keys):
                path_key = f"{prefix}.{k}" if prefix else k
                if k not in dflt:
                    diffs.append((path_key, "agregado", str(cur[k]), ""))
                elif k not in cur:
                    diffs.append((path_key, "eliminado", "", str(dflt[k])))
                else:
                    _compare(cur[k], dflt[k], path_key)
        elif cur != dflt:
            diffs.append((prefix, "modificado", str(cur), str(dflt)))

    _compare(current_data, default_data)

    if not diffs:
        console.print("[green]Sin diferencias - config coincide con defaults[/green]")
        return

    table = Table(title="Diferencias vs. defaults")
    table.add_column("Clave", style="cyan")
    table.add_column("Cambio", style="yellow")
    table.add_column("Actual", style="green")
    table.add_column("Default", style="dim")

    for key, change, current, default in diffs:
        table.add_row(key, change, current[:60], default[:60])

    console.print(table)
    console.print(f"\n[dim]{len(diffs)} diferencia(s) encontradas[/dim]")


@config_app.command("reset")
def config_reset(
    confirm_flag: bool = typer.Option(False, "--yes", "-y", help="Confirmar sin preguntar"),
) -> None:
    """Resetea la configuración a valores por defecto.

    Portado de OpenClaw: reset con backup automático.
    """
    from config.loader import save_config
    from config.schema import SomerConfig
    from shared.constants import DEFAULT_CONFIG_PATH

    if not DEFAULT_CONFIG_PATH.exists():
        console.print("[yellow]No existe configuración para resetear[/yellow]")
        raise typer.Exit(1)

    if not confirm_flag:
        if not typer.confirm("Esto reseteará TODA la configuración. Continuar?"):
            raise typer.Abort()

    # Backup antes de resetear
    import shutil
    backup_path = DEFAULT_CONFIG_PATH.with_suffix(".json.bak")
    shutil.copy2(DEFAULT_CONFIG_PATH, backup_path)
    console.print(f"[dim]Backup guardado en {backup_path}[/dim]")

    config = SomerConfig()
    save_config(config)
    console.print("[green]Configuración reseteada a valores por defecto[/green]")


@config_app.command("path")
def config_path() -> None:
    """Muestra la ruta de la configuración."""
    from shared.constants import DEFAULT_CONFIG_PATH, DEFAULT_HOME
    console.print(f"Home: {DEFAULT_HOME}")
    console.print(f"Config: {DEFAULT_CONFIG_PATH}")
