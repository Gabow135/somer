"""Comando: somer memory — gestión de memoria.

Portado de OpenClaw: memory-cli.ts (30623 líneas).
Incluye: search, stats, export, import, compact, clear, sources.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()
memory_app = typer.Typer(no_args_is_help=True)


def _get_manager() -> "MemoryManager":
    """Obtiene una instancia del gestor de memoria."""
    from memory.manager import MemoryManager

    return MemoryManager()


@memory_app.command("search")
def memory_search(
    query: str = typer.Argument(..., help="Texto de búsqueda"),
    limit: int = typer.Option(10, "--limit", "-n", help="Número máximo de resultados"),
    category: Optional[str] = typer.Option(None, "--category", "-c", help="Filtrar por categoría"),
    as_json: bool = typer.Option(False, "--json", help="Salida en JSON"),
) -> None:
    """Busca en la memoria del agente.

    Portado de OpenClaw: memory search con búsqueda híbrida BM25 + vector.
    """
    manager = _get_manager()

    async def _search() -> None:
        start = time.time()
        results = await manager.search(query, limit=limit)
        elapsed_ms = int((time.time() - start) * 1000)

        if as_json:
            result = {
                "query": query,
                "elapsed_ms": elapsed_ms,
                "count": len(results),
                "results": [
                    {
                        "id": r.id,
                        "content": r.content[:500],
                        "score": getattr(r, "score", None),
                        "category": r.category.value if hasattr(r.category, "value") else str(r.category),
                        "tags": r.tags,
                        "created_at": r.created_at,
                    }
                    for r in results
                ],
            }
            console.print(json.dumps(result, indent=2, default=str))
            return

        if not results:
            console.print(f"[dim]Sin resultados para '{query}'[/dim]")
            return

        console.print(f"[dim]{len(results)} resultado(s) en {elapsed_ms}ms[/dim]\n")

        for i, r in enumerate(results, 1):
            score_str = f" (score: {getattr(r, 'score', 'N/A')})" if hasattr(r, "score") else ""
            cat = r.category.value if hasattr(r.category, "value") else str(r.category)
            tags = ", ".join(r.tags) if r.tags else ""

            console.print(Panel(
                r.content[:300] + ("..." if len(r.content) > 300 else ""),
                title=f"[cyan]#{i}[/cyan] [{cat}]{score_str}",
                subtitle=f"id={r.id[:12]} | tags={tags}" if tags else f"id={r.id[:12]}",
                border_style="dim",
            ))

    try:
        asyncio.run(_search())
    except Exception as exc:
        console.print(f"[red]Error de búsqueda: {exc}[/red]")
        raise typer.Exit(1)
    finally:
        manager.close()


@memory_app.command("stats")
def memory_stats(
    as_json: bool = typer.Option(False, "--json", help="Salida en JSON"),
) -> None:
    """Muestra estadísticas del sistema de memoria.

    Portado de OpenClaw: memory status con métricas completas.
    """
    try:
        manager = _get_manager()
    except Exception as exc:
        if as_json:
            console.print(json.dumps({"error": str(exc), "total_entries": 0}, indent=2))
        else:
            console.print("[dim]Memoria no inicializada o no disponible[/dim]")
            console.print(f"[dim]({exc})[/dim]")
        return

    try:
        stats = manager.stats()

        if as_json:
            data = stats.model_dump() if hasattr(stats, "model_dump") else stats.__dict__
            console.print(json.dumps(data, indent=2, default=str))
            return

        table = Table(title="Estadísticas de memoria")
        table.add_column("Métrica", style="cyan")
        table.add_column("Valor", style="green")

        table.add_row("Total entradas", str(stats.total_entries))
        table.add_row("Entradas activas", str(stats.active_entries))
        table.add_row("Archivadas", str(stats.archived_entries))
        table.add_row("Con embedding", str(stats.embedded_entries))
        table.add_row("Tamaño en disco", _format_bytes(stats.size_bytes))

        # Categorías
        if hasattr(stats, "categories") and stats.categories:
            cat_str = ", ".join(f"{k}: {v}" for k, v in stats.categories.items())
            table.add_row("Categorías", cat_str[:80])

        console.print(table)
    except Exception as exc:
        if as_json:
            console.print(json.dumps({"error": str(exc), "total_entries": 0}, indent=2))
        else:
            console.print(f"[dim]Memoria vacía o no inicializada: {exc}[/dim]")
    finally:
        try:
            manager.close()
        except Exception:
            pass


@memory_app.command("export")
def memory_export(
    output: str = typer.Argument(..., help="Ruta del archivo de salida (JSON)"),
    limit: int = typer.Option(0, "--limit", "-n", help="Límite de entradas (0 = todas)"),
    as_json: bool = typer.Option(True, help="Formato JSON"),
) -> None:
    """Exporta la memoria a un archivo JSON.

    Portado de OpenClaw: memory export con backup y migración.
    """
    manager = _get_manager()

    async def _export() -> None:
        console.print(f"[dim]Exportando memoria a {output}...[/dim]")
        start = time.time()

        json_data = await manager.export_to_json(limit=limit if limit > 0 else None)
        elapsed = time.time() - start

        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json_data, encoding="utf-8")

        # Contar entradas
        data = json.loads(json_data)
        count = len(data) if isinstance(data, list) else data.get("count", "?")

        console.print(f"[green]Exportadas {count} entradas a {output}[/green]")
        console.print(f"[dim]({elapsed:.1f}s, {_format_bytes(out_path.stat().st_size)})[/dim]")

    try:
        asyncio.run(_export())
    except Exception as exc:
        console.print(f"[red]Error de exportación: {exc}[/red]")
        raise typer.Exit(1)
    finally:
        manager.close()


@memory_app.command("import")
def memory_import(
    input_file: str = typer.Argument(..., help="Ruta del archivo JSON a importar"),
    merge: bool = typer.Option(True, "--merge/--replace", help="Merge o reemplazar"),
) -> None:
    """Importa memoria desde un archivo JSON.

    Portado de OpenClaw: memory import con merge y deduplicación.
    """
    manager = _get_manager()
    in_path = Path(input_file)

    if not in_path.exists():
        console.print(f"[red]Archivo no encontrado: {input_file}[/red]")
        raise typer.Exit(1)

    async def _import() -> None:
        console.print(f"[dim]Importando desde {input_file}...[/dim]")
        start = time.time()

        json_data = in_path.read_text(encoding="utf-8")
        count = await manager.import_from_json(json_data)
        elapsed = time.time() - start

        console.print(f"[green]Importadas {count} entradas[/green]")
        console.print(f"[dim]({elapsed:.1f}s)[/dim]")

    try:
        asyncio.run(_import())
    except Exception as exc:
        console.print(f"[red]Error de importación: {exc}[/red]")
        raise typer.Exit(1)
    finally:
        manager.close()


@memory_app.command("compact")
def memory_compact(
    threshold: float = typer.Option(0.85, "--threshold", "-t", help="Umbral de similitud (0.0-1.0)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Solo mostrar qué se compactaría"),
    as_json: bool = typer.Option(False, "--json", help="Salida en JSON"),
) -> None:
    """Compacta entradas similares en la memoria.

    Portado de OpenClaw: memory compact con merge de entradas similares
    y deduplicación.
    """
    manager = _get_manager()

    async def _compact() -> None:
        console.print(f"[dim]Compactando memoria (umbral: {threshold})...[/dim]")
        start = time.time()

        result = await manager.compact(similarity_threshold=threshold, dry_run=dry_run)
        elapsed = time.time() - start

        if as_json:
            console.print(json.dumps({
                "merged": result.get("merged", 0),
                "removed": result.get("removed", 0),
                "dry_run": dry_run,
                "elapsed_secs": round(elapsed, 2),
            }, indent=2))
            return

        merged = result.get("merged", 0)
        removed = result.get("removed", 0)

        if dry_run:
            console.print(f"[dim](dry-run) Se compactarían {merged} grupo(s), eliminando {removed} entrada(s)[/dim]")
        elif merged > 0:
            console.print(f"[green]Compactados {merged} grupo(s), {removed} entrada(s) eliminadas[/green]")
        else:
            console.print("[dim]Sin entradas para compactar[/dim]")

        console.print(f"[dim]({elapsed:.1f}s)[/dim]")

    try:
        asyncio.run(_compact())
    except Exception as exc:
        console.print(f"[red]Error de compactación: {exc}[/red]")
        raise typer.Exit(1)
    finally:
        manager.close()


@memory_app.command("clear")
def memory_clear(
    confirm_flag: bool = typer.Option(False, "--yes", "-y", help="Confirmar sin preguntar"),
    backup: bool = typer.Option(True, "--backup/--no-backup", help="Crear backup antes de borrar"),
) -> None:
    """Elimina toda la memoria del agente.

    Portado de OpenClaw: memory clear con backup y confirmación.
    """
    if not confirm_flag:
        if not typer.confirm("Esto eliminará TODA la memoria. Continuar?"):
            raise typer.Abort()

    manager = _get_manager()

    async def _clear() -> None:
        # Backup opcional
        if backup:
            try:
                json_data = await manager.export_to_json()
                from shared.constants import DEFAULT_MEMORY_DIR
                backup_path = DEFAULT_MEMORY_DIR / f"backup_{int(time.time())}.json"
                backup_path.write_text(json_data, encoding="utf-8")
                console.print(f"[dim]Backup guardado en {backup_path}[/dim]")
            except Exception as exc:
                console.print(f"[yellow]No se pudo crear backup: {exc}[/yellow]")

        # Limpiar
        stats_before = manager.stats()
        manager._backend.clear()
        console.print(f"[green]Memoria limpiada ({stats_before.total_entries} entradas eliminadas)[/green]")

    try:
        asyncio.run(_clear())
    except Exception as exc:
        console.print(f"[red]Error al limpiar memoria: {exc}[/red]")
        raise typer.Exit(1)
    finally:
        manager.close()


@memory_app.command("sources")
def memory_sources() -> None:
    """Muestra las fuentes de memoria configuradas.

    Portado de OpenClaw: memory sources con scan de archivos.
    """
    from shared.constants import DEFAULT_HOME, DEFAULT_MEMORY_DIR

    table = Table(title="Fuentes de memoria")
    table.add_column("Fuente", style="cyan")
    table.add_column("Ruta", style="dim")
    table.add_column("Archivos", style="green")

    # Memory dir
    mem_files = list(DEFAULT_MEMORY_DIR.glob("*.db")) if DEFAULT_MEMORY_DIR.exists() else []
    table.add_row("SQLite DB", str(DEFAULT_MEMORY_DIR), str(len(mem_files)))

    # MEMORY.md
    memory_md = Path.cwd() / "MEMORY.md"
    table.add_row("MEMORY.md", str(memory_md), "1" if memory_md.exists() else "0")

    # Sessions JSONL
    sessions_dir = DEFAULT_HOME / "sessions"
    session_files = list(sessions_dir.glob("*.jsonl")) if sessions_dir.exists() else []
    table.add_row("Sessions", str(sessions_dir), str(len(session_files)))

    console.print(table)


def _format_bytes(size: int) -> str:
    """Formatea bytes a string legible."""
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{size / (1024 * 1024 * 1024):.1f} GB"
