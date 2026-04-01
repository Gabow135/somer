"""Comando: somer skills — gestión de skills.

Portado de OpenClaw: skills-cli.ts, skills-cli.format.ts.
Incluye: list, info, check, search.
"""

from __future__ import annotations

import json
from typing import List, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()
skill_app = typer.Typer(no_args_is_help=True)


def _discover_all_skills() -> list:
    """Descubre y retorna todos los skills como SkillMeta.

    discover_skills() retorna List[Path], así que cargamos cada uno
    con load_skill_file() para obtener SkillMeta.
    """
    from skills.loader import discover_skills, load_skill_file

    paths = discover_skills(["skills"])
    skills = []
    for path in paths:
        try:
            meta = load_skill_file(path)
            # Almacenar el path de origen como atributo extra
            meta._source_path = str(path)
            skills.append(meta)
        except Exception:
            pass
    return skills


@skill_app.command("list")
def skill_list(
    as_json: bool = typer.Option(False, "--json", help="Salida en JSON"),
    enabled_only: bool = typer.Option(False, "--enabled", help="Solo skills activos"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Mostrar detalles"),
    category: Optional[str] = typer.Option(None, "--category", "-c", help="Filtrar por categoría"),
    tag: Optional[str] = typer.Option(None, "--tag", "-t", help="Filtrar por tag"),
) -> None:
    """Lista todos los skills disponibles.

    Portado de OpenClaw: skills list con filtros y formato.
    """
    skills = _discover_all_skills()

    # Filtros
    if enabled_only:
        skills = [s for s in skills if s.enabled]
    if category:
        skills = [s for s in skills if s.category.lower() == category.lower()]
    if tag:
        skills = [s for s in skills if tag.lower() in [t.lower() for t in s.tags]]

    if as_json:
        result = [
            {
                "name": s.name,
                "description": s.description,
                "category": s.category,
                "tags": s.tags,
                "enabled": s.enabled,
                "triggers": s.triggers,
            }
            for s in skills
        ]
        console.print(json.dumps(result, indent=2))
        return

    if not skills:
        console.print("[dim]No se encontraron skills[/dim]")
        return

    table = Table(title=f"Skills ({len(skills)})")
    table.add_column("Nombre", style="cyan", width=25)
    table.add_column("Categoría", style="green", width=15)
    table.add_column("Estado", width=12)
    if verbose:
        table.add_column("Tags", style="dim", width=20)
        table.add_column("Descripción", style="dim", max_width=40)

    for s in sorted(skills, key=lambda x: x.name):
        status = "[green]activo[/green]" if s.enabled else "[dim]desactivado[/dim]"
        row = [s.name, s.category, status]
        if verbose:
            row.append(", ".join(s.tags[:3]) if s.tags else "-")
            row.append(s.description[:40] if s.description else "-")
        table.add_row(*row)

    console.print(table)


@skill_app.command("info")
def skill_info(
    name: str = typer.Argument(..., help="Nombre del skill"),
    as_json: bool = typer.Option(False, "--json", help="Salida en JSON"),
) -> None:
    """Muestra información detallada de un skill.

    Portado de OpenClaw: skills info con metadata completa.
    """
    skills = _discover_all_skills()
    skill = next((s for s in skills if s.name.lower() == name.lower()), None)

    if not skill:
        console.print(f"[red]Skill '{name}' no encontrado[/red]")
        # Sugerencias
        similar = [s.name for s in skills if name.lower() in s.name.lower()]
        if similar:
            console.print(f"[dim]Quizás quisiste decir: {', '.join(similar[:5])}[/dim]")
        raise typer.Exit(1)

    source_path = getattr(skill, "_source_path", "")

    if as_json:
        console.print(json.dumps({
            "name": skill.name,
            "description": skill.description,
            "category": skill.category,
            "tags": skill.tags,
            "enabled": skill.enabled,
            "triggers": skill.triggers,
            "version": skill.version,
            "source_file": source_path,
        }, indent=2))
        return

    # Panel detallado
    triggers_str = ", ".join(skill.triggers) if skill.triggers else "-"
    details = [
        f"[bold]{skill.name}[/bold]",
        "",
        f"Descripción: {skill.description}" if skill.description else "",
        f"Categoría: {skill.category}",
        f"Versión: {skill.version}",
        f"Tags: {', '.join(skill.tags)}" if skill.tags else "Tags: -",
        f"Estado: {'activo' if skill.enabled else 'desactivado'}",
        f"Triggers: {triggers_str}",
        f"Archivo: {source_path}" if source_path else "",
    ]

    console.print(Panel(
        "\n".join(d for d in details if d),
        title=f"Skill: {skill.name}",
        border_style="cyan",
    ))


@skill_app.command("check")
def skill_check(
    as_json: bool = typer.Option(False, "--json", help="Salida en JSON"),
) -> None:
    """Verifica qué skills están listos vs. faltantes.

    Portado de OpenClaw: skills check con análisis de requisitos.
    """
    skills = _discover_all_skills()

    ready = [s for s in skills if s.enabled]
    disabled = [s for s in skills if not s.enabled]

    if as_json:
        console.print(json.dumps({
            "total": len(skills),
            "ready": len(ready),
            "disabled": len(disabled),
            "ready_skills": [s.name for s in ready],
            "disabled_skills": [s.name for s in disabled],
        }, indent=2))
        return

    console.print(f"[bold]Skills check:[/bold]\n")
    console.print(f"  [green]Listos:[/green] {len(ready)}")
    console.print(f"  [dim]Desactivados:[/dim] {len(disabled)}")
    console.print(f"  Total: {len(skills)}")

    if disabled:
        console.print(f"\n[dim]Skills desactivados: {', '.join(s.name for s in disabled[:10])}[/dim]")
        if len(disabled) > 10:
            console.print(f"[dim]  ...y {len(disabled) - 10} más[/dim]")


@skill_app.command("search")
def skill_search(
    query: str = typer.Argument(..., help="Texto de búsqueda"),
    as_json: bool = typer.Option(False, "--json", help="Salida en JSON"),
) -> None:
    """Busca skills por nombre, descripción o tags.

    Búsqueda fuzzy en todos los campos del skill.
    """
    skills = _discover_all_skills()
    query_lower = query.lower()

    matches = [
        s for s in skills
        if (
            query_lower in s.name.lower()
            or query_lower in (s.description or "").lower()
            or query_lower in s.category.lower()
            or any(query_lower in t.lower() for t in s.tags)
        )
    ]

    if as_json:
        result = [{"name": s.name, "category": s.category, "description": s.description} for s in matches]
        console.print(json.dumps(result, indent=2))
        return

    if not matches:
        console.print(f"[dim]Sin resultados para '{query}'[/dim]")
        return

    table = Table(title=f"Skills matching '{query}'")
    table.add_column("Nombre", style="cyan")
    table.add_column("Categoría", style="green")
    table.add_column("Descripción", style="dim", max_width=50)

    for s in matches:
        table.add_row(s.name, s.category, (s.description or "-")[:50])

    console.print(table)
    console.print(f"\n[dim]{len(matches)} resultado(s)[/dim]")
