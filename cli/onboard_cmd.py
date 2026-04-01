"""Comando: somer onboard — setup wizard interactivo.

Portado de OpenClaw: wizard/setup.ts, onboard-helpers.ts.
Guía al usuario por la configuración completa de SOMER 2.0.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional, Tuple

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

console = Console()

# ── Paleta (inspirada en OpenClaw lobster palette) ────────────────
ACCENT = "cyan"
SUCCESS = "green"
WARN = "yellow"
ERROR = "red"
MUTED = "dim"

# ── Definiciones de providers ─────────────────────────────────────
PROVIDER_DEFS: List[Dict[str, Any]] = [
    {
        "id": "anthropic", "name": "Anthropic (Claude)",
        "env": "ANTHROPIC_API_KEY", "default": True,
        "hint": "Recomendado — Claude Sonnet/Opus",
    },
    {
        "id": "openai", "name": "OpenAI (GPT)",
        "env": "OPENAI_API_KEY", "default": False,
        "hint": "GPT-4o, o3-mini",
    },
    {
        "id": "deepseek", "name": "DeepSeek",
        "env": "DEEPSEEK_API_KEY", "default": False,
        "hint": "DeepSeek V3, R1",
    },
    {
        "id": "google", "name": "Google (Gemini)",
        "env": "GOOGLE_API_KEY", "default": False,
        "hint": "Gemini Pro/Flash",
    },
    {
        "id": "groq", "name": "Groq",
        "env": "GROQ_API_KEY", "default": False,
        "hint": "Ultra-rápido, Llama/Mixtral",
    },
    {
        "id": "openrouter", "name": "OpenRouter",
        "env": "OPENROUTER_API_KEY", "default": False,
        "hint": "Acceso a 100+ modelos",
    },
    {
        "id": "xai", "name": "xAI (Grok)",
        "env": "XAI_API_KEY", "default": False,
        "hint": "Grok 3",
    },
    {
        "id": "mistral", "name": "Mistral",
        "env": "MISTRAL_API_KEY", "default": False,
        "hint": "Mistral Large/Medium",
    },
    {
        "id": "together", "name": "Together AI",
        "env": "TOGETHER_API_KEY", "default": False,
        "hint": "Open-source models",
    },
    {
        "id": "perplexity", "name": "Perplexity",
        "env": "PERPLEXITY_API_KEY", "default": False,
        "hint": "Búsqueda + LLM",
    },
]

# ── Definiciones de canales ───────────────────────────────────────
CHANNEL_DEFS: List[Dict[str, Any]] = [
    {
        "id": "telegram", "name": "Telegram",
        "env": "TELEGRAM_BOT_TOKEN", "plugin": "channels.telegram",
        "hint": "Bot de Telegram (@BotFather)",
    },
    {
        "id": "discord", "name": "Discord",
        "env": "DISCORD_BOT_TOKEN", "plugin": "channels.discord",
        "hint": "Bot de Discord",
    },
    {
        "id": "slack", "name": "Slack",
        "env": "SLACK_BOT_TOKEN", "plugin": "channels.slack",
        "hint": "Slack Bot (Bolt)",
    },
    {
        "id": "whatsapp", "name": "WhatsApp",
        "env": "WHATSAPP_API_TOKEN", "plugin": "channels.whatsapp",
        "hint": "WhatsApp Business API",
    },
    {
        "id": "matrix", "name": "Matrix",
        "env": "MATRIX_ACCESS_TOKEN", "plugin": "channels.matrix",
        "hint": "Matrix/Element",
    },
    {
        "id": "webchat", "name": "WebChat",
        "env": None, "plugin": "channels.webchat",
        "hint": "Chat embebido en web (sin token)",
    },
]


def _header() -> None:
    """Muestra el encabezado del wizard."""
    from shared.constants import VERSION

    art = Text()
    art.append("  ____   ___  __  __ _____ ____  \n", style=f"bold {ACCENT}")
    art.append(" / ___| / _ \\|  \\/  | ____|  _ \\ \n", style=f"bold {ACCENT}")
    art.append(" \\___ \\| | | | |\\/| |  _| | |_) |\n", style=f"bold {ACCENT}")
    art.append("  ___) | |_| | |  | | |___|  _ < \n", style=f"bold {ACCENT}")
    art.append(" |____/ \\___/|_|  |_|_____|_| \\_\\\n", style=f"bold {ACCENT}")

    console.print(Panel(
        art,
        title=f"[bold {ACCENT}]SOMER {VERSION} — Setup Wizard[/bold {ACCENT}]",
        border_style=ACCENT,
        padding=(1, 2),
    ))
    console.print()


def _detect_env_keys() -> Dict[str, str]:
    """Detecta API keys ya configuradas en el entorno."""
    found = {}
    all_envs = [p["env"] for p in PROVIDER_DEFS if p.get("env")]
    all_envs += [c["env"] for c in CHANNEL_DEFS if c.get("env")]
    for env_var in all_envs:
        val = os.environ.get(env_var, "")
        if val:
            found[env_var] = val[:8] + "..." if len(val) > 8 else val
    return found


def _detect_ollama() -> bool:
    """Detecta si Ollama está corriendo localmente."""
    try:
        import httpx
        resp = httpx.get("http://127.0.0.1:11434/api/tags", timeout=2)
        return resp.status_code == 200
    except Exception:
        return False


def _show_detected(env_keys: Dict[str, str], ollama_running: bool) -> None:
    """Muestra lo que se detectó automáticamente."""
    if not env_keys and not ollama_running:
        console.print(f"[{MUTED}]No se detectaron API keys ni Ollama local.[/{MUTED}]")
        console.print()
        return

    table = Table(title="Detectado automáticamente", border_style=MUTED)
    table.add_column("Recurso", style=ACCENT)
    table.add_column("Estado", style=SUCCESS)
    table.add_column("Detalle", style=MUTED)

    for env_var, preview in env_keys.items():
        table.add_row(env_var, "Encontrada", preview)

    if ollama_running:
        table.add_row("Ollama (local)", "Corriendo", "http://127.0.0.1:11434")

    console.print(table)
    console.print()


def _check_existing_config() -> "Optional[Any]":
    """Revisa si ya existe configuración."""
    from shared.constants import DEFAULT_CONFIG_PATH
    if DEFAULT_CONFIG_PATH.exists():
        from config.loader import load_config
        try:
            return load_config()
        except Exception:
            return None
    return None


def _show_existing_config(config: Any) -> None:
    """Muestra resumen de configuración existente."""
    console.print(f"[{WARN}]Ya existe una configuración:[/{WARN}]")
    table = Table(border_style=MUTED, show_header=False)
    table.add_column("Key", style=ACCENT, width=20)
    table.add_column("Value", style="white")
    table.add_row("Modelo default", config.default_model)
    table.add_row("Providers", ", ".join(config.providers.keys()) or "ninguno")
    table.add_row("Canales", ", ".join(config.channels.entries.keys()) or "ninguno")
    table.add_row("Memoria", "activada" if config.memory.enabled else "desactivada")
    console.print(table)
    console.print()


def _setup_providers(
    env_keys: Dict[str, str],
    ollama_running: bool,
    existing: "Optional[Any]" = None,
) -> Dict[str, Any]:
    """Configura providers LLM."""
    from config.schema import ProviderAuthConfig, ProviderSettings
    from infra.env import save_env_var

    # Providers previamente configurados
    prev_providers = existing.providers if existing else {}

    console.print(f"\n[bold {ACCENT}]Paso 1/4 — Providers LLM[/bold {ACCENT}]")
    console.print(f"[{MUTED}]Selecciona qué providers de IA quieres usar.[/{MUTED}]")
    console.print(f"[{MUTED}]Los que ya tienen API key se activan automáticamente.[/{MUTED}]\n")

    providers: Dict[str, ProviderSettings] = {}

    for pdef in PROVIDER_DEFS:
        env_var = pdef["env"]
        has_key = env_var in env_keys
        was_enabled = pdef["id"] in prev_providers and getattr(
            prev_providers[pdef["id"]], "enabled", False
        )
        auto_label = f" [{SUCCESS}](key detectada)[/{SUCCESS}]" if has_key else ""
        if was_enabled and not has_key:
            auto_label = f" [{SUCCESS}](configurado)[/{SUCCESS}]"

        if has_key:
            # Auto-activar y persistir en .env
            save_env_var(env_var, os.environ[env_var])
            console.print(f"  [{SUCCESS}]>[/{SUCCESS}] {pdef['name']}{auto_label} — {pdef['hint']}")
            providers[pdef["id"]] = ProviderSettings(
                enabled=True,
                auth=ProviderAuthConfig(api_key_env=env_var),
            )
        elif was_enabled:
            # Ya estaba configurado — mantener sin preguntar
            console.print(f"  [{SUCCESS}]>[/{SUCCESS}] {pdef['name']}{auto_label} — {pdef['hint']}")
            providers[pdef["id"]] = prev_providers[pdef["id"]]
        else:
            activate = Confirm.ask(
                f"  {pdef['name']} — {pdef['hint']}",
                default=pdef.get("default", False),
            )
            if activate:
                key = Prompt.ask(
                    f"    {env_var}",
                    password=True,
                    default="",
                )
                if key:
                    # Guardar en ~/.somer/.env (persiste entre sesiones)
                    save_env_var(env_var, key)
                    providers[pdef["id"]] = ProviderSettings(
                        enabled=True,
                        auth=ProviderAuthConfig(api_key_env=env_var),
                    )
                    console.print(f"    [{SUCCESS}]Guardado en ~/.somer/.env[/{SUCCESS}]")
                else:
                    console.print(f"    [{MUTED}]Omitido (sin key)[/{MUTED}]")

    # Ollama (especial: sin API key)
    ollama_was_enabled = "ollama" in prev_providers and getattr(
        prev_providers["ollama"], "enabled", False
    )
    if ollama_running or ollama_was_enabled:
        prev_url = "http://127.0.0.1:11434"
        if ollama_was_enabled:
            prev_auth = getattr(prev_providers["ollama"], "auth", None)
            if prev_auth and getattr(prev_auth, "base_url", None):
                prev_url = prev_auth.base_url
        label = f"[{SUCCESS}](detectado)[/{SUCCESS}]" if ollama_running else f"[{SUCCESS}](configurado)[/{SUCCESS}]"
        console.print(f"\n  [{SUCCESS}]>[/{SUCCESS}] Ollama (local) {label}")
        providers["ollama"] = ProviderSettings(
            enabled=True,
            auth=ProviderAuthConfig(base_url=prev_url),
        )
    else:
        if Confirm.ask("  Ollama (local) — Modelos locales sin API key", default=False):
            url = Prompt.ask("    URL de Ollama", default="http://127.0.0.1:11434")
            providers["ollama"] = ProviderSettings(
                enabled=True,
                auth=ProviderAuthConfig(base_url=url),
            )

    if not providers:
        console.print(f"\n[{WARN}]No configuraste ningún provider. SOMER necesita al menos uno.[/{WARN}]")
        console.print(f"[{MUTED}]Puedes agregar providers después con: somer config show[/{MUTED}]")

    return providers


def _setup_model(
    providers: Dict[str, Any],
    existing: "Optional[Any]" = None,
) -> Tuple[str, str, List[List[str]]]:
    """Selecciona modelos por defecto y cadena de fallback."""
    console.print(f"\n[bold {ACCENT}]Paso 2/4 — Modelo por defecto[/bold {ACCENT}]")

    # Modelos sugeridos por provider
    suggestions = {
        "anthropic": ("claude-sonnet-4-5-20250929", "claude-haiku-4-5-20251001"),
        "openai": ("gpt-4o", "gpt-4o-mini"),
        "deepseek": ("deepseek-chat", "deepseek-chat"),
        "google": ("gemini-2.5-pro", "gemini-2.5-flash"),
        "groq": ("llama-3.3-70b-versatile", "llama-3.3-70b-versatile"),
        "openrouter": ("anthropic/claude-sonnet-4-5-20250929", "anthropic/claude-haiku-4-5-20251001"),
        "ollama": ("llama3.1:8b", "llama3.1:8b"),
    }

    # Usar valores guardados si existen, sino sugerir por provider
    if existing:
        default_model = existing.default_model
        fast_model = existing.fast_model
    else:
        default_model = "claude-sonnet-4-5-20250929"
        fast_model = "claude-haiku-4-5-20251001"
        for pid in ["anthropic", "openai", "deepseek", "google", "groq", "openrouter", "ollama"]:
            if pid in providers:
                default_model, fast_model = suggestions.get(pid, (default_model, fast_model))
                break

    console.print(f"[{MUTED}]El modelo principal se usa para tareas complejas.[/{MUTED}]")
    console.print(f"[{MUTED}]El modelo rápido para tareas simples y clasificación.[/{MUTED}]\n")

    default_model = Prompt.ask(
        "  Modelo principal",
        default=default_model,
    )
    fast_model = Prompt.ask(
        "  Modelo rápido",
        default=fast_model,
    )

    # ── Cadena de fallback ──────────────────────────────────
    prev_fallback: List[List[str]] = existing.fallback_models if existing else []
    prev_fallback_str = ", ".join(f"{f[0]}:{f[1]}" for f in prev_fallback if len(f) >= 2)

    console.print(f"\n[{MUTED}]Si el modelo principal falla (quota, billing, rate-limit),[/{MUTED}]")
    console.print(f"[{MUTED}]SOMER intentará automáticamente los modelos de fallback en orden.[/{MUTED}]")
    if prev_fallback_str:
        console.print(f"[{MUTED}]Actual: {prev_fallback_str}[/{MUTED}]")

    fallback_input = Prompt.ask(
        "  Fallback models (provider:modelo, ...)",
        default=prev_fallback_str,
    ).strip()

    fallback_models: List[List[str]] = []
    if fallback_input:
        for entry in fallback_input.split(","):
            entry = entry.strip()
            if ":" in entry:
                parts = entry.split(":", 1)
                fallback_models.append([parts[0].strip(), parts[1].strip()])
            else:
                console.print(f"  [{WARN}]Formato inválido '{entry}' — usar provider:modelo[/{WARN}]")

    return default_model, fast_model, fallback_models


def _ask_dm_policy(channel_name: str) -> Optional[str]:
    """Pregunta al usuario qué política de DM quiere para un canal."""
    console.print(f"\n    [{ACCENT}]Política de acceso DM para {channel_name}:[/{ACCENT}]")
    console.print(f"    [{MUTED}]1. pairing  — El usuario recibe un código que el admin aprueba (recomendado)[/{MUTED}]")
    console.print(f"    [{MUTED}]2. allowlist — Solo IDs explícitamente autorizados[/{MUTED}]")
    console.print(f"    [{MUTED}]3. open     — Cualquiera puede escribir al bot[/{MUTED}]")
    console.print(f"    [{MUTED}]4. disabled — No acepta DMs[/{MUTED}]")

    choice = Prompt.ask(
        f"    Política DM",
        choices=["pairing", "allowlist", "open", "disabled"],
        default="pairing",
    )
    return choice


def _setup_channels(
    env_keys: Dict[str, str],
    existing: "Optional[Any]" = None,
) -> Dict[str, Any]:
    """Configura canales de comunicación."""
    from config.schema import ChannelConfig
    from infra.env import save_env_var

    prev_channels = existing.channels.entries if existing else {}

    console.print(f"\n[bold {ACCENT}]Paso 3/4 — Canales[/bold {ACCENT}]")
    console.print(f"[{MUTED}]Selecciona por dónde quieres hablar con SOMER.[/{MUTED}]")
    console.print(f"[{MUTED}]Puedes agregar más después con: somer config show[/{MUTED}]\n")

    # Canales que soportan DM y por tanto necesitan dm_policy
    DM_CHANNELS = {"telegram", "discord", "slack", "whatsapp", "matrix"}

    channels: Dict[str, ChannelConfig] = {}

    for cdef in CHANNEL_DEFS:
        env_var = cdef.get("env")
        has_token = env_var in env_keys if env_var else False
        was_enabled = cdef["id"] in prev_channels and getattr(
            prev_channels[cdef["id"]], "enabled", False
        )

        if has_token:
            auto_label = f" [{SUCCESS}](token detectado)[/{SUCCESS}]"
            # Persistir en .env
            if env_var:
                save_env_var(env_var, os.environ[env_var])
            console.print(f"  [{SUCCESS}]>[/{SUCCESS}] {cdef['name']}{auto_label}")

            # Preguntar dm_policy para canales con DM
            dm_policy = None
            if cdef["id"] in DM_CHANNELS:
                dm_policy = _ask_dm_policy(cdef["name"])

            channels[cdef["id"]] = ChannelConfig(
                enabled=True,
                plugin=cdef["plugin"],
                dm_policy=dm_policy,
                config={"token_env": env_var} if env_var else {},
            )
        elif was_enabled:
            # Ya estaba configurado — mantener
            auto_label = f" [{SUCCESS}](configurado)[/{SUCCESS}]"
            console.print(f"  [{SUCCESS}]>[/{SUCCESS}] {cdef['name']}{auto_label}")
            channels[cdef["id"]] = prev_channels[cdef["id"]]
        else:
            activate = Confirm.ask(
                f"  {cdef['name']} — {cdef['hint']}",
                default=False,
            )
            if activate:
                if env_var:
                    token = Prompt.ask(f"    {env_var}", password=True, default="")
                    if token:
                        # Guardar en ~/.somer/.env (persiste entre sesiones)
                        save_env_var(env_var, token)

                        # Preguntar dm_policy para canales con DM
                        dm_policy = None
                        if cdef["id"] in DM_CHANNELS:
                            dm_policy = _ask_dm_policy(cdef["name"])

                        channels[cdef["id"]] = ChannelConfig(
                            enabled=True,
                            plugin=cdef["plugin"],
                            dm_policy=dm_policy,
                            config={"token_env": env_var},
                        )
                        console.print(f"    [{SUCCESS}]Guardado en ~/.somer/.env[/{SUCCESS}]")
                    else:
                        console.print(f"    [{MUTED}]Omitido (sin token)[/{MUTED}]")
                else:
                    # Canal sin token (ej: webchat)
                    channels[cdef["id"]] = ChannelConfig(
                        enabled=True,
                        plugin=cdef["plugin"],
                    )
                    console.print(f"    [{SUCCESS}]Activado[/{SUCCESS}]")

    return channels


def _setup_extras(
    channels: Dict[str, Any],
    existing: "Optional[Any]" = None,
) -> Dict[str, Any]:
    """Configuraciones adicionales."""
    console.print(f"\n[bold {ACCENT}]Paso 4/5 — Opciones adicionales[/bold {ACCENT}]\n")

    extras: Dict[str, Any] = {}

    prev_memory = existing.memory.enabled if existing else True
    prev_port = existing.gateway.port if existing else 18789

    extras["memory_enabled"] = Confirm.ask(
        "  Activar sistema de memoria (recuerda conversaciones)",
        default=prev_memory,
    )

    extras["gateway_port"] = int(Prompt.ask(
        "  Puerto del gateway WebSocket",
        default=str(prev_port),
    ))

    return extras


def _setup_heartbeat(
    channels: Dict[str, Any],
    existing: "Optional[Any]" = None,
) -> Dict[str, Any]:
    """Configura heartbeat y cron."""
    console.print(f"\n[bold {ACCENT}]Paso 5/5 — Heartbeat y tareas programadas[/bold {ACCENT}]")
    console.print(f"[{MUTED}]El heartbeat monitorea el sistema periódicamente y te avisa si algo falla.[/{MUTED}]\n")

    prev_hb = existing.heartbeat if existing else None
    prev_cron = existing.cron if existing else None

    hb: Dict[str, Any] = {}

    hb["heartbeat_enabled"] = Confirm.ask(
        "  Activar heartbeat (monitoreo periódico)",
        default=prev_hb.enabled if prev_hb else bool(channels),
    )

    if hb["heartbeat_enabled"]:
        # Seleccionar canal destino
        if channels:
            channel_names = list(channels.keys())
            prev_target = prev_hb.target if prev_hb and prev_hb.target in channel_names else channel_names[0]
            hb["heartbeat_target"] = Prompt.ask(
                "  Canal para alertas del heartbeat",
                choices=channel_names,
                default=prev_target,
            )
            prev_chat_id = prev_hb.target_chat_id if prev_hb else ""
            hb["heartbeat_chat_id"] = Prompt.ask(
                "  Chat ID / Channel ID destino",
                default=prev_chat_id or "",
            )
        else:
            console.print(f"  [{WARN}]Sin canales configurados — heartbeat no podra enviar alertas.[/{WARN}]")
            hb["heartbeat_target"] = "none"
            hb["heartbeat_chat_id"] = ""

        prev_every = str(prev_hb.every) if prev_hb else "1800"
        hb["heartbeat_every"] = int(Prompt.ask(
            "  Intervalo en segundos",
            default=prev_every,
        ))

    hb["cron_enabled"] = Confirm.ask(
        "  Activar cron scheduler (tareas programadas)",
        default=prev_cron.enabled if prev_cron else hb.get("heartbeat_enabled", False),
    )

    return hb


def _show_summary(
    providers: Dict[str, Any],
    channels: Dict[str, Any],
    default_model: str,
    fast_model: str,
    extras: Dict[str, Any],
    hb_config: Dict[str, Any],
    fallback_models: Optional[List[List[str]]] = None,
) -> None:
    """Muestra resumen antes de guardar."""
    console.print(f"\n[bold {ACCENT}]Resumen de configuración[/bold {ACCENT}]\n")

    table = Table(border_style=ACCENT, show_header=False, padding=(0, 2))
    table.add_column("", style=ACCENT, width=22)
    table.add_column("", style="white")

    table.add_row("Modelo principal", default_model)
    table.add_row("Modelo rápido", fast_model)
    if fallback_models:
        fb_str = " → ".join(f"{f[0]}:{f[1]}" for f in fallback_models if len(f) >= 2)
        table.add_row("Fallback", fb_str)
    table.add_row(
        "Providers",
        ", ".join(providers.keys()) if providers else f"[{WARN}]ninguno[/{WARN}]",
    )
    table.add_row(
        "Canales",
        ", ".join(channels.keys()) if channels else f"[{MUTED}]ninguno[/{MUTED}]",
    )
    table.add_row("Memoria", "activada" if extras.get("memory_enabled") else "desactivada")
    table.add_row("Gateway", f"ws://127.0.0.1:{extras.get('gateway_port', 18789)}")

    if hb_config.get("heartbeat_enabled"):
        target = hb_config.get("heartbeat_target", "none")
        every = hb_config.get("heartbeat_every", 1800)
        table.add_row("Heartbeat", f"cada {every}s -> {target}")
    else:
        table.add_row("Heartbeat", "desactivado")

    table.add_row("Cron scheduler", "activado" if hb_config.get("cron_enabled") else "desactivado")

    console.print(table)
    console.print()


def _verify_env_file() -> None:
    """Verifica y muestra las variables guardadas en ~/.somer/.env."""
    from infra.env import get_env_file_path

    env_path = get_env_file_path()
    if not env_path.exists():
        console.print(f"  [{WARN}]~/.somer/.env no existe[/{WARN}]")
        return

    saved_vars = []
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.partition("=")[0].strip()
        saved_vars.append(key)

    if saved_vars:
        table = Table(
            title="Variables guardadas en ~/.somer/.env",
            border_style=SUCCESS,
            show_header=True,
        )
        table.add_column("Variable", style=ACCENT)
        table.add_column("Estado", style=SUCCESS)
        for var in saved_vars:
            # Verificar que realmente está en el entorno
            in_env = bool(os.environ.get(var))
            status = "OK (cargada)" if in_env else f"[{WARN}]En archivo, no en entorno[/{WARN}]"
            table.add_row(var, status)
        console.print(table)
    else:
        console.print(f"  [{WARN}]~/.somer/.env está vacío[/{WARN}]")

    console.print()


def _install_system_deps() -> None:
    """Instala dependencias del sistema necesarias para SOMER."""
    import subprocess

    console.print(f"\n[bold {ACCENT}]Dependencias del sistema[/bold {ACCENT}]\n")

    deps_to_install: list = []

    # ── Playwright (browser automation, screenshots, PoCs de seguridad) ──
    try:
        import playwright  # noqa: F401
        console.print(f"  [{SUCCESS}]OK[/{SUCCESS}]  Playwright instalado")
        # Verificar si chromium está instalado
        try:
            result = subprocess.run(
                [sys.executable, "-m", "playwright", "install", "--dry-run", "chromium"],
                capture_output=True, text=True, timeout=10,
            )
            # Si dry-run falla, probablemente no está instalado el browser
            if result.returncode != 0:
                deps_to_install.append("playwright-chromium")
            else:
                console.print(f"  [{SUCCESS}]OK[/{SUCCESS}]  Chromium browser")
        except Exception:
            deps_to_install.append("playwright-chromium")
    except ImportError:
        deps_to_install.append("playwright")

    # ── Instalar lo que falte ──
    if not deps_to_install:
        console.print(f"  [{SUCCESS}]Todo instalado[/{SUCCESS}]")
        return

    console.print()
    install_items = ", ".join(deps_to_install)
    if not Confirm.ask(
        f"Instalar dependencias faltantes ({install_items})", default=True,
    ):
        console.print(f"  [{MUTED}]Saltado. Puedes instalar después con:[/{MUTED}]")
        console.print(f"  [{MUTED}]  pip install playwright && playwright install chromium[/{MUTED}]")
        return

    for dep in deps_to_install:
        try:
            if dep == "playwright":
                console.print(f"  Instalando playwright...", end=" ")
                subprocess.run(
                    [sys.executable, "-m", "pip", "install", "playwright"],
                    capture_output=True, check=True, timeout=120,
                )
                console.print(f"[{SUCCESS}]OK[/{SUCCESS}]")
                # Instalar chromium también
                dep = "playwright-chromium"

            if dep == "playwright-chromium":
                console.print(f"  Instalando Chromium browser...", end=" ")
                subprocess.run(
                    [sys.executable, "-m", "playwright", "install", "chromium"],
                    capture_output=True, check=True, timeout=300,
                )
                console.print(f"[{SUCCESS}]OK[/{SUCCESS}]")

        except subprocess.CalledProcessError as exc:
            console.print(f"[{WARN}]Error[/{WARN}]")
            console.print(f"  [{MUTED}]{str(exc)[:200]}[/{MUTED}]")
        except subprocess.TimeoutExpired:
            console.print(f"[{WARN}]Timeout[/{WARN}]")

    console.print()


def _run_doctor_check() -> None:
    """Ejecuta un health check rápido."""
    from shared.constants import DEFAULT_CONFIG_PATH, DEFAULT_HOME

    console.print(f"\n[bold {ACCENT}]Verificación rápida[/bold {ACCENT}]\n")

    # Primero mostrar variables guardadas
    _verify_env_file()

    checks = [
        ("Home directory", DEFAULT_HOME.exists()),
        ("Config guardada", DEFAULT_CONFIG_PATH.exists()),
        ("Python >= 3.9", sys.version_info >= (3, 9)),
    ]

    # Verificar providers con key
    for pdef in PROVIDER_DEFS:
        if os.environ.get(pdef["env"]):
            checks.append((f"API Key: {pdef['name']}", True))

    # Verificar Ollama
    checks.append(("Ollama local", _detect_ollama()))

    # Skills
    try:
        from skills.loader import discover_skills
        skills = discover_skills(["skills"])
        checks.append((f"Skills ({len(skills)})", len(skills) > 0))
    except Exception:
        checks.append(("Skills", False))

    for name, ok in checks:
        icon = f"[{SUCCESS}]OK[/{SUCCESS}]" if ok else f"[{MUTED}]--[/{MUTED}]"
        console.print(f"  {icon}  {name}")

    console.print()


def onboard() -> None:
    """Wizard de setup interactivo para SOMER 2.0."""
    from config.loader import save_config
    from config.schema import (
        ChannelConfig,
        ChannelsConfig,
        GatewayConfig,
        MemoryConfig,
        ProviderAuthConfig,
        ProviderSettings,
        SomerConfig,
    )
    from infra.env import ensure_somer_home
    from shared.constants import DEFAULT_CONFIG_PATH

    # ── Header ────────────────────────────────────────────────
    _header()

    # ── Crear home ────────────────────────────────────────────
    home = ensure_somer_home()

    # ── Cargar .env existente ─────────────────────────────────
    from infra.env import load_somer_env, save_env_var
    load_somer_env()
    console.print(f"[{MUTED}]Home: {home}[/{MUTED}]")

    # ── Auto-detectar y persistir SOMER_PROJECT_ROOT ──────────
    project_root = os.environ.get("SOMER_PROJECT_ROOT")
    if project_root:
        save_env_var("SOMER_PROJECT_ROOT", project_root)
        console.print(f"[{MUTED}]Proyecto: {project_root}[/{MUTED}]")

    # ── Detectar estado actual ────────────────────────────────
    env_keys = _detect_env_keys()
    ollama_running = _detect_ollama()
    _show_detected(env_keys, ollama_running)

    # ── Config existente ──────────────────────────────────────
    existing = _check_existing_config()
    if existing:
        _show_existing_config(existing)
        action = Prompt.ask(
            "Acción",
            choices=["actualizar", "resetear", "cancelar"],
            default="actualizar",
        )
        if action == "cancelar":
            console.print(f"[{MUTED}]Setup cancelado.[/{MUTED}]")
            raise typer.Exit()
        elif action == "resetear":
            console.print(f"[{WARN}]Reseteando configuración...[/{WARN}]")
            existing = None

    # ── Configurar providers ──────────────────────────────────
    providers = _setup_providers(env_keys, ollama_running, existing)

    # ── Seleccionar modelos ───────────────────────────────────
    default_model, fast_model, fallback_models = _setup_model(providers, existing)

    # ── Configurar canales ────────────────────────────────────
    channels = _setup_channels(env_keys, existing)

    # ── Extras ────────────────────────────────────────────────
    extras = _setup_extras(channels, existing)

    # ── Heartbeat y Cron ─────────────────────────────────────
    hb_config = _setup_heartbeat(channels, existing)

    # ── Resumen ───────────────────────────────────────────────
    _show_summary(providers, channels, default_model, fast_model, extras, hb_config, fallback_models)

    if not Confirm.ask("Guardar esta configuración", default=True):
        console.print(f"[{MUTED}]Setup cancelado.[/{MUTED}]")
        raise typer.Exit()

    # ── Construir y guardar config ────────────────────────────
    from config.schema import CronConfig, HeartbeatConfig

    heartbeat = HeartbeatConfig(
        enabled=hb_config.get("heartbeat_enabled", False),
        every=hb_config.get("heartbeat_every", 1800),
        target=hb_config.get("heartbeat_target", "none"),
        target_chat_id=hb_config.get("heartbeat_chat_id", ""),
    )

    cron = CronConfig(
        enabled=hb_config.get("cron_enabled", False),
    )

    config = SomerConfig(
        default_model=default_model,
        fast_model=fast_model,
        fallback_models=fallback_models,
        providers=providers,
        channels=ChannelsConfig(entries=channels),
        gateway=GatewayConfig(port=extras.get("gateway_port", 18789)),
        memory=MemoryConfig(enabled=extras.get("memory_enabled", True)),
        heartbeat=heartbeat,
        cron=cron,
    )

    saved_path = save_config(config)
    console.print(f"\n[bold {SUCCESS}]Configuración guardada en {saved_path}[/bold {SUCCESS}]")

    # ── Dependencias del sistema ──────────────────────────────
    _install_system_deps()

    # ── Verificación ──────────────────────────────────────────
    _run_doctor_check()

    # ── Próximos pasos ────────────────────────────────────────
    console.print(Panel(
        f"[bold]Próximos pasos:[/bold]\n\n"
        f"  1. Verifica tu setup:  [bold {ACCENT}]somer doctor check[/bold {ACCENT}]\n"
        f"  2. Inicia el gateway:  [bold {ACCENT}]somer gateway start[/bold {ACCENT}]\n"
        f"  3. Habla con SOMER:    [bold {ACCENT}]somer agent run \"hola\"[/bold {ACCENT}]\n"
        f"  4. Ver config:         [bold {ACCENT}]somer config show[/bold {ACCENT}]",
        title=f"[bold {SUCCESS}]Setup completo[/bold {SUCCESS}]",
        border_style=SUCCESS,
        padding=(1, 2),
    ))
