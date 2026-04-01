"""Comando: somer doctor — health check comprehensivo.

Portado de OpenClaw: commands/doctor.ts, doctor-config-flow.ts,
doctor-gateway-services.ts, doctor-memory-search.ts, doctor-security.ts.
Incluye: check completo, categorías individuales, fix automático.
"""

from __future__ import annotations

import json
import os
import platform
import socket
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

console = Console()
doctor_app = typer.Typer(no_args_is_help=True)


# ── Tipos de check ───────────────────────────────────────────

CheckResult = Tuple[str, bool, str]  # (nombre, ok, detalle)


def _check(name: str, ok: bool, detail: str = "") -> CheckResult:
    """Crea un resultado de check."""
    return name, ok, detail


def _check_icon(ok: bool) -> str:
    """Icono de estado para un check."""
    return "[green]OK[/green]" if ok else "[red]FAIL[/red]"


# ── Categorías de checks ────────────────────────────────────


def _check_system() -> List[CheckResult]:
    """Checks de sistema: Python, plataforma, home directory."""
    from shared.constants import DEFAULT_HOME, VERSION

    checks = []
    checks.append(_check("Versión SOMER", True, VERSION))
    py_ok = sys.version_info >= (3, 9)
    checks.append(_check(
        "Python >= 3.9", py_ok,
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    ))
    checks.append(_check("Plataforma", True, f"{platform.system()} {platform.machine()}"))
    home_ok = DEFAULT_HOME.exists()
    checks.append(_check("SOMER Home", home_ok, str(DEFAULT_HOME)))

    # Subdirectorios
    for subdir in ("sessions", "credentials", "memory", "logs"):
        sub_path = DEFAULT_HOME / subdir
        checks.append(_check(f"  {subdir}/", sub_path.exists(), str(sub_path)))

    return checks


def _check_config() -> List[CheckResult]:
    """Checks de configuración: archivo, validez, modelo por defecto."""
    from shared.constants import DEFAULT_CONFIG_PATH

    checks = []
    config_ok = DEFAULT_CONFIG_PATH.exists()
    checks.append(_check("Config file", config_ok, str(DEFAULT_CONFIG_PATH)))

    if config_ok:
        try:
            from config.loader import load_config
            config = load_config()
            checks.append(_check("Config parseable", True, f"v{config.version}"))
            checks.append(_check("Modelo default", bool(config.default_model), config.default_model))
            checks.append(_check("Modelo rápido", bool(config.fast_model), config.fast_model))
        except Exception as exc:
            checks.append(_check("Config parseable", False, str(exc)[:80]))

    return checks


def _check_providers() -> List[CheckResult]:
    """Checks de providers: API keys, conectividad."""
    checks = []

    provider_keys = [
        ("ANTHROPIC_API_KEY", "Anthropic"),
        ("OPENAI_API_KEY", "OpenAI"),
        ("GOOGLE_API_KEY", "Google"),
        ("DEEPSEEK_API_KEY", "DeepSeek"),
        ("GROQ_API_KEY", "Groq"),
        ("XAI_API_KEY", "xAI"),
        ("OPENROUTER_API_KEY", "OpenRouter"),
        ("MISTRAL_API_KEY", "Mistral"),
        ("TOGETHER_API_KEY", "Together"),
        ("PERPLEXITY_API_KEY", "Perplexity"),
    ]

    found_any = False
    for env_var, provider in provider_keys:
        has_key = bool(os.environ.get(env_var))
        if has_key:
            found_any = True
        checks.append(_check(f"API Key: {provider}", has_key, env_var))

    # Ollama local
    try:
        import httpx
        resp = httpx.get("http://127.0.0.1:11434/api/tags", timeout=2)
        ollama_ok = resp.status_code == 200
    except Exception:
        ollama_ok = False
    checks.append(_check("Ollama (local)", ollama_ok, "http://127.0.0.1:11434"))

    if not found_any and not ollama_ok:
        checks.append(_check("Al menos un provider", False, "Configura al menos un provider LLM"))

    return checks


def _check_channels() -> List[CheckResult]:
    """Checks de canales: tokens, configuración."""
    checks = []

    channel_tokens = [
        ("TELEGRAM_BOT_TOKEN", "Telegram"),
        ("SLACK_BOT_TOKEN", "Slack"),
        ("DISCORD_BOT_TOKEN", "Discord"),
        ("WHATSAPP_API_TOKEN", "WhatsApp"),
        ("MATRIX_ACCESS_TOKEN", "Matrix"),
    ]

    for env_var, channel in channel_tokens:
        has_token = bool(os.environ.get(env_var))
        checks.append(_check(f"Token: {channel}", has_token, env_var))

    return checks


def _check_gateway() -> List[CheckResult]:
    """Checks de gateway: conectividad, estado."""
    from shared.constants import GATEWAY_HOST, GATEWAY_PORT

    checks = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            gw_ok = s.connect_ex((GATEWAY_HOST, GATEWAY_PORT)) == 0
    except Exception:
        gw_ok = False
    checks.append(_check("Gateway", gw_ok, f"ws://{GATEWAY_HOST}:{GATEWAY_PORT}"))

    return checks


def _check_memory() -> List[CheckResult]:
    """Checks de memoria: backend SQLite, índices."""
    from shared.constants import DEFAULT_MEMORY_DIR

    checks = []
    mem_dir_ok = DEFAULT_MEMORY_DIR.exists()
    checks.append(_check("Memory dir", mem_dir_ok, str(DEFAULT_MEMORY_DIR)))

    if mem_dir_ok:
        db_files = list(DEFAULT_MEMORY_DIR.glob("*.db"))
        checks.append(_check("Memory DB", len(db_files) > 0, f"{len(db_files)} archivo(s)"))

    return checks


def _check_skills() -> List[CheckResult]:
    """Checks de skills: carga, validación."""
    checks = []
    try:
        from skills.loader import discover_skills
        skills = discover_skills(["skills"])
        checks.append(_check("Skills cargados", len(skills) > 0, f"{len(skills)} encontrados"))
    except Exception as exc:
        checks.append(_check("Skills cargados", False, str(exc)[:60]))

    return checks


def _check_dependencies() -> List[CheckResult]:
    """Checks de dependencias Python."""
    checks = []
    deps = [
        ("pydantic", "Pydantic"),
        ("httpx", "httpx"),
        ("websockets", "websockets"),
        ("rich", "Rich"),
        ("typer", "Typer"),
    ]

    # Opcionales
    optional_deps = [
        ("cryptography", "cryptography"),
        ("json5", "json5"),
    ]

    for pkg, name in deps:
        try:
            __import__(pkg)
            checks.append(_check(f"Dep: {name}", True, "instalado"))
        except ImportError:
            checks.append(_check(f"Dep: {name}", False, "no instalado"))

    for pkg, name in optional_deps:
        try:
            __import__(pkg)
            checks.append(_check(f"Opt: {name}", True, "instalado"))
        except ImportError:
            checks.append(_check(f"Opt: {name}", True, "no instalado (opcional)"))

    return checks


def _check_security() -> List[CheckResult]:
    """Checks de seguridad: permisos, credenciales."""
    from shared.constants import DEFAULT_CREDENTIALS_DIR

    checks = []

    if DEFAULT_CREDENTIALS_DIR.exists():
        # Verificar permisos del directorio de credenciales
        mode = oct(DEFAULT_CREDENTIALS_DIR.stat().st_mode)[-3:]
        secure = mode in ("700", "750", "600")
        checks.append(_check("Permisos credentials/", secure, f"mode={mode}"))

        # Verificar que no haya archivos sin encriptar expuestos
        json_files = list(DEFAULT_CREDENTIALS_DIR.glob("*.json"))
        enc_files = list(DEFAULT_CREDENTIALS_DIR.glob("*.enc"))
        has_unenc = len(json_files) > 0 and not all(
            f.name.startswith(".") for f in json_files
        )
        checks.append(_check(
            "Credenciales encriptadas",
            not has_unenc,
            f"{len(enc_files)} enc, {len(json_files)} json",
        ))
    else:
        checks.append(_check("Credentials dir", True, "no existe (sin credenciales)"))

    return checks


# ── Comandos principales ─────────────────────────────────────


@doctor_app.command("check")
def doctor_check(
    category: Optional[str] = typer.Option(
        None, "--category", "-c",
        help="Categoría: system, config, providers, channels, gateway, memory, skills, deps, security",
    ),
    as_json: bool = typer.Option(False, "--json", help="Salida en JSON"),
    fix: bool = typer.Option(False, "--fix", help="Intentar corregir problemas automáticamente"),
) -> None:
    """Ejecuta health check completo.

    Portado de OpenClaw: doctor con categorías, JSON output y auto-fix.
    """
    # Mapeo de categorías
    categories = {
        "system": ("Sistema", _check_system),
        "config": ("Configuración", _check_config),
        "providers": ("Providers LLM", _check_providers),
        "channels": ("Canales", _check_channels),
        "gateway": ("Gateway", _check_gateway),
        "memory": ("Memoria", _check_memory),
        "skills": ("Skills", _check_skills),
        "deps": ("Dependencias", _check_dependencies),
        "security": ("Seguridad", _check_security),
    }

    if category:
        if category not in categories:
            available = ", ".join(categories.keys())
            console.print(f"[red]Categoría '{category}' no válida. Opciones: {available}[/red]")
            raise typer.Exit(1)
        cats_to_run = {category: categories[category]}
    else:
        cats_to_run = categories

    all_checks: List[Dict[str, Any]] = []

    for cat_id, (cat_name, check_fn) in cats_to_run.items():
        results = check_fn()
        for name, ok, detail in results:
            all_checks.append({
                "category": cat_id,
                "category_name": cat_name,
                "name": name,
                "ok": ok,
                "detail": detail,
            })

    # Auto-fix si se solicita
    if fix:
        _auto_fix(all_checks)

    # Output
    if as_json:
        passed = sum(1 for c in all_checks if c["ok"])
        total = len(all_checks)
        result = {
            "passed": passed,
            "total": total,
            "all_ok": passed == total,
            "checks": all_checks,
        }
        console.print(json.dumps(result, indent=2))
        return

    # Tabla agrupada por categoría
    table = Table(title="SOMER Doctor")
    table.add_column("Check", style="cyan", width=28)
    table.add_column("Status", width=6)
    table.add_column("Detalle", style="dim")

    current_cat = ""
    for check in all_checks:
        cat_name = check["category_name"]
        if cat_name != current_cat:
            if current_cat:
                table.add_row("", "", "")  # Separador
            table.add_row(f"[bold]{cat_name}[/bold]", "", "")
            current_cat = cat_name
        icon = _check_icon(check["ok"])
        table.add_row(f"  {check['name']}", icon, check["detail"])

    console.print(table)

    # Resumen
    passed = sum(1 for c in all_checks if c["ok"])
    total = len(all_checks)
    if passed == total:
        console.print(f"\n[green]Todo OK ({passed}/{total})[/green]")
    else:
        failed = total - passed
        console.print(f"\n[yellow]{passed}/{total} checks pasaron — {failed} problema(s)[/yellow]")
        console.print("[dim]Ejecuta 'somer doctor check --fix' para intentar corregir.[/dim]")


@doctor_app.command("env")
def doctor_env() -> None:
    """Muestra un resumen del entorno de ejecución.

    Portado de OpenClaw: doctor-platform-notes.ts.
    """
    from shared.constants import DEFAULT_HOME, VERSION

    table = Table(title="Entorno SOMER")
    table.add_column("Variable", style="cyan")
    table.add_column("Valor", style="green")

    table.add_row("SOMER Version", VERSION)
    table.add_row("Python", f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
    table.add_row("Platform", f"{platform.system()} {platform.release()}")
    table.add_row("Architecture", platform.machine())
    table.add_row("SOMER_HOME", str(os.environ.get("SOMER_HOME", DEFAULT_HOME)))
    table.add_row("Virtual Env", os.environ.get("VIRTUAL_ENV", "N/A"))
    table.add_row("CI", str(os.environ.get("CI", "no")))

    # Variables SOMER relevantes
    for env_var in sorted(k for k in os.environ if k.startswith("SOMER_")):
        val = os.environ[env_var]
        display = val[:40] + "..." if len(val) > 40 else val
        table.add_row(env_var, display)

    console.print(table)


@doctor_app.command("providers")
def doctor_providers() -> None:
    """Check detallado de providers LLM.

    Portado de OpenClaw: doctor-gateway-services.ts provider checks.
    """
    checks = _check_providers()

    table = Table(title="Providers LLM")
    table.add_column("Provider", style="cyan", width=25)
    table.add_column("Status", width=6)
    table.add_column("Detalle", style="dim")

    for name, ok, detail in checks:
        table.add_row(name, _check_icon(ok), detail)

    console.print(table)


def _auto_fix(checks: List[Dict[str, Any]]) -> None:
    """Intenta corregir problemas automáticamente.

    Portado de OpenClaw: doctor --fix con auto-repair.
    """
    from shared.constants import DEFAULT_HOME

    fixed = 0

    for check in checks:
        if check["ok"]:
            continue

        # Fix: crear home directory
        if check["name"] == "SOMER Home":
            from infra.env import ensure_somer_home
            ensure_somer_home()
            check["ok"] = True
            check["detail"] = "creado"
            fixed += 1
            console.print(f"[green]Corregido: {check['name']}[/green]")

        # Fix: crear subdirectorios
        elif check["name"].strip().endswith("/"):
            subdir = check["name"].strip().rstrip("/")
            path = DEFAULT_HOME / subdir
            path.mkdir(parents=True, exist_ok=True)
            check["ok"] = True
            check["detail"] = "creado"
            fixed += 1
            console.print(f"[green]Corregido: {check['name']}[/green]")

        # Fix: crear config
        elif check["name"] == "Config file":
            from config.loader import save_config
            from config.schema import SomerConfig
            save_config(SomerConfig())
            check["ok"] = True
            check["detail"] = "config creada"
            fixed += 1
            console.print(f"[green]Corregido: {check['name']}[/green]")

    if fixed:
        console.print(f"\n[green]{fixed} problema(s) corregido(s)[/green]")
    else:
        console.print("\n[dim]No se pudo corregir ningún problema automáticamente[/dim]")
