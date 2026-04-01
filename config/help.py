"""Sistema de ayuda y documentación de configuración SOMER 2.0.

Portado de OpenClaw: schema.help.ts, schema.labels.ts.
Proporciona descripciones, etiquetas y documentación inline
para cada campo de configuración.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


class ConfigHelpEntry:
    """Entrada de ayuda para un campo de configuración.

    Portado de OpenClaw: schema.help.ts.
    """

    def __init__(
        self,
        path: str,
        label: str,
        help_text: str = "",
        advanced: bool = False,
        sensitive: bool = False,
        placeholder: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ):
        self.path = path
        self.label = label
        self.help_text = help_text
        self.advanced = advanced
        self.sensitive = sensitive
        self.placeholder = placeholder
        self.tags = tags or []


# ── Registro de ayuda ────────────────────────────────────────

_HELP_ENTRIES: Dict[str, ConfigHelpEntry] = {}


def _register(*entries: ConfigHelpEntry) -> None:
    for entry in entries:
        _HELP_ENTRIES[entry.path] = entry


# ════════════════════════════════════════════════════════════════
# Definiciones de ayuda por sección
# ════════════════════════════════════════════════════════════════

_register(
    # ── Root ──────────────────────────────────────────────────
    ConfigHelpEntry(
        "version", "Versión",
        "Versión del esquema de configuración.",
    ),
    ConfigHelpEntry(
        "default_model", "Modelo por defecto",
        "ID del modelo LLM principal. Se usa para el agente por defecto "
        "si no se especifica otro.",
        placeholder="claude-sonnet-4-5-20250929",
    ),
    ConfigHelpEntry(
        "fast_model", "Modelo rápido",
        "Modelo ligero para tareas de baja latencia (compactación, resúmenes).",
        placeholder="claude-haiku-4-5-20251001",
    ),

    # ── Gateway ──────────────────────────────────────────────
    ConfigHelpEntry(
        "gateway", "Gateway",
        "Configuración del servidor WebSocket JSON-RPC 2.0.",
    ),
    ConfigHelpEntry(
        "gateway.host", "Host",
        "Dirección IP de escucha.",
        placeholder="127.0.0.1",
    ),
    ConfigHelpEntry(
        "gateway.port", "Puerto",
        "Puerto WebSocket del gateway.",
        placeholder="18789",
    ),
    ConfigHelpEntry(
        "gateway.bind", "Modo de binding",
        "Política de bind: loopback (local), lan (todas las interfaces), "
        "auto (loopback con fallback), custom.",
    ),
    ConfigHelpEntry(
        "gateway.tls", "TLS",
        "Configuración de TLS para conexiones seguras al gateway.",
        advanced=True,
    ),
    ConfigHelpEntry(
        "gateway.auth", "Autenticación",
        "Modo de autenticación para conexiones al gateway.",
    ),
    ConfigHelpEntry(
        "gateway.auth.token", "Token",
        "Token compartido para autenticación (modo token).",
        sensitive=True,
    ),
    ConfigHelpEntry(
        "gateway.auth.password", "Password",
        "Password compartido para autenticación (modo password).",
        sensitive=True,
    ),

    # ── Providers ────────────────────────────────────────────
    ConfigHelpEntry(
        "providers", "Providers",
        "Configuración de providers LLM (Anthropic, OpenAI, etc.).",
    ),
    ConfigHelpEntry(
        "providers.*", "Provider",
        "Configuración de un provider LLM individual.",
    ),
    ConfigHelpEntry(
        "providers.*.auth.api_key_env", "Variable de API Key",
        "Nombre de la variable de entorno que contiene la API key.",
        sensitive=True,
    ),
    ConfigHelpEntry(
        "providers.*.auth.api_key", "API Key directa",
        "API key literal. Solo para testing, nunca en producción.",
        sensitive=True,
        advanced=True,
    ),

    # ── Channels ─────────────────────────────────────────────
    ConfigHelpEntry(
        "channels", "Canales",
        "Configuración de canales de comunicación.",
    ),
    ConfigHelpEntry(
        "channels.defaults", "Defaults de canales",
        "Configuración por defecto aplicada a todos los canales.",
    ),
    ConfigHelpEntry(
        "channels.entries", "Canales configurados",
        "Canales individuales con su configuración.",
    ),

    # ── Sessions ─────────────────────────────────────────────
    ConfigHelpEntry(
        "sessions", "Sesiones",
        "Configuración del sistema de sesiones.",
    ),
    ConfigHelpEntry(
        "sessions.idle_timeout_secs", "Timeout inactivo",
        "Segundos de inactividad antes de cerrar una sesión.",
        placeholder="3600",
    ),
    ConfigHelpEntry(
        "sessions.max_turns", "Máximo de turnos",
        "Número máximo de turnos por sesión.",
        placeholder="200",
    ),
    ConfigHelpEntry(
        "sessions.dm_scope", "Alcance DM",
        "Cómo se agrupan las sesiones de mensajes directos: "
        "main (una sola), per-peer (por contacto), etc.",
    ),

    # ── Memory ───────────────────────────────────────────────
    ConfigHelpEntry(
        "memory", "Memoria",
        "Configuración del sistema de memoria a largo plazo.",
    ),
    ConfigHelpEntry(
        "memory.backend", "Backend",
        "Motor de almacenamiento: sqlite o builtin.",
    ),

    # ── Agents ───────────────────────────────────────────────
    ConfigHelpEntry(
        "agents", "Agentes",
        "Configuración de agentes y sus defaults.",
    ),
    ConfigHelpEntry(
        "agents.default", "Agente por defecto",
        "ID del agente que maneja mensajes sin binding específico.",
        placeholder="main",
    ),
    ConfigHelpEntry(
        "agents.list", "Lista de agentes",
        "Definiciones de agentes individuales.",
    ),

    # ── Hooks ────────────────────────────────────────────────
    ConfigHelpEntry(
        "hooks", "Hooks",
        "Sistema de hooks para webhooks entrantes y eventos internos.",
    ),
    ConfigHelpEntry(
        "hooks.enabled", "Habilitado",
        "Activar/desactivar el sistema de hooks.",
    ),
    ConfigHelpEntry(
        "hooks.token", "Token de webhook",
        "Token de autenticación para hooks entrantes.",
        sensitive=True,
    ),

    # ── Skills ───────────────────────────────────────────────
    ConfigHelpEntry(
        "skills", "Skills",
        "Configuración del sistema de skills (SKILL.md).",
    ),
    ConfigHelpEntry(
        "skills.dirs", "Directorios",
        "Directorios donde buscar skills.",
    ),

    # ── Plugins ──────────────────────────────────────────────
    ConfigHelpEntry(
        "plugins", "Plugins",
        "Configuración del sistema de plugins.",
    ),

    # ── Cron ─────────────────────────────────────────────────
    ConfigHelpEntry(
        "cron", "Cron",
        "Scheduler de tareas programadas.",
    ),
    ConfigHelpEntry(
        "cron.enabled", "Habilitado",
        "Activar/desactivar el scheduler cron.",
    ),

    # ── TTS ──────────────────────────────────────────────────
    ConfigHelpEntry(
        "tts", "Text-to-Speech",
        "Configuración de síntesis de voz.",
    ),

    # ── Web Search ───────────────────────────────────────────
    ConfigHelpEntry(
        "web_search", "Búsqueda web",
        "Configuración de búsqueda web (Tavily, Brave, DuckDuckGo).",
    ),

    # ── Security ─────────────────────────────────────────────
    ConfigHelpEntry(
        "security", "Seguridad",
        "Configuración de seguridad y auditoría.",
    ),

    # ── Logging ──────────────────────────────────────────────
    ConfigHelpEntry(
        "logging", "Logging",
        "Configuración de registro de eventos.",
    ),
    ConfigHelpEntry(
        "logging.level", "Nivel",
        "Nivel de logging: silent, fatal, error, warn, info, debug, trace.",
    ),

    # ── Heartbeat ────────────────────────────────────────────
    ConfigHelpEntry(
        "heartbeat", "Heartbeat",
        "Turnos LLM periódicos y alertas automáticas.",
    ),

    # ── MCP ──────────────────────────────────────────────────
    ConfigHelpEntry(
        "mcp", "MCP",
        "Model Context Protocol: servidores de herramientas externas.",
        advanced=True,
    ),

    # ── Bindings ─────────────────────────────────────────────
    ConfigHelpEntry(
        "bindings", "Bindings",
        "Vinculaciones agente ↔ ruta para routing de mensajes.",
    ),
)


# ════════════════════════════════════════════════════════════════
# API pública
# ════════════════════════════════════════════════════════════════

def get_help(path: str) -> Optional[ConfigHelpEntry]:
    """Obtiene la entrada de ayuda para un path de configuración.

    Soporta wildcards: ``providers.anthropic`` matchea ``providers.*``.

    Args:
        path: Ruta en notación de puntos (e.g. "gateway.port").

    Returns:
        ConfigHelpEntry si existe, None si no.
    """
    # Match exacto
    entry = _HELP_ENTRIES.get(path)
    if entry:
        return entry

    # Match con wildcards
    parts = path.split(".")
    for i in range(len(parts)):
        wildcard_path = ".".join(parts[:i] + ["*"] + parts[i + 1:])
        entry = _HELP_ENTRIES.get(wildcard_path)
        if entry:
            return entry

    return None


def get_help_for_section(section: str) -> List[ConfigHelpEntry]:
    """Obtiene todas las entradas de ayuda para una sección.

    Args:
        section: Prefijo de sección (e.g. "gateway", "providers").

    Returns:
        Lista de entradas de ayuda que empiezan con el prefijo.
    """
    prefix = section + "."
    result = []
    for path, entry in _HELP_ENTRIES.items():
        if path == section or path.startswith(prefix):
            result.append(entry)
    return result


def list_sections() -> List[str]:
    """Lista las secciones principales de configuración.

    Returns:
        Lista de nombres de sección (top-level keys).
    """
    sections = set()
    for path in _HELP_ENTRIES:
        top = path.split(".")[0]
        sections.add(top)
    return sorted(sections)


def format_help(path: str) -> str:
    """Formatea la ayuda de un campo para mostrar en CLI.

    Args:
        path: Ruta en notación de puntos.

    Returns:
        String formateado con la documentación.
    """
    entry = get_help(path)
    if not entry:
        return f"No hay ayuda disponible para '{path}'."

    lines = [f"  {entry.label}"]
    if entry.help_text:
        lines.append(f"  {entry.help_text}")
    if entry.placeholder:
        lines.append(f"  Default: {entry.placeholder}")
    if entry.sensitive:
        lines.append("  (Sensible — no mostrar en logs)")
    if entry.advanced:
        lines.append("  (Avanzado)")
    return "\n".join(lines)


def generate_help_table() -> List[Tuple[str, str, str]]:
    """Genera una tabla de ayuda con todos los campos.

    Returns:
        Lista de tuplas (path, label, description).
    """
    result = []
    for path in sorted(_HELP_ENTRIES.keys()):
        entry = _HELP_ENTRIES[path]
        result.append((path, entry.label, entry.help_text))
    return result
