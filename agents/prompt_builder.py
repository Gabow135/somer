"""System Prompt Builder — construye prompt multi-sección para el agente.

Portado de OpenClaw: system-prompt.ts, buildEmbeddedSystemPrompt, workspace.ts.

Ensambla un system prompt completo con:
- Personalidad (SOUL.md)
- Identidad (IDENTITY.md)
- Usuario (USER.md)
- Herramientas (TOOLS.md)
- Arranque (BOOT.md)
- Skills disponibles
- Contexto de memoria
- Servicios/credenciales activos
- Fecha, hora, timezone
- Capacidades del canal
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from shared.types import SkillMeta

logger = logging.getLogger(__name__)


# ── Constantes de archivos de workspace (portado de OpenClaw) ────────
DEFAULT_WORKSPACE_DIR = Path.home() / ".somer" / "workspace"
DEFAULT_SOUL_FILENAME = "SOUL.md"
DEFAULT_IDENTITY_FILENAME = "IDENTITY.md"
DEFAULT_USER_FILENAME = "USER.md"
DEFAULT_TOOLS_FILENAME = "TOOLS.md"
DEFAULT_BOOT_FILENAME = "BOOT.md"
DEFAULT_MEMORY_FILENAME = "MEMORY.md"

# Tamaño máximo de archivo de bootstrap (2MB)
MAX_WORKSPACE_FILE_BYTES = 2 * 1024 * 1024


@dataclass
class WorkspaceFile:
    """Representa un archivo de workspace cargado.

    Portado de OpenClaw: WorkspaceBootstrapFile.
    """
    name: str
    path: Path
    content: str = ""
    missing: bool = False


@dataclass
class WorkspaceContext:
    """Contexto completo del workspace cargado.

    Portado de OpenClaw: loadWorkspaceBootstrapFiles.
    Contiene todos los archivos de contexto que definen la personalidad,
    identidad, y configuración del agente.
    """
    soul: WorkspaceFile = field(default_factory=lambda: WorkspaceFile(
        name=DEFAULT_SOUL_FILENAME, path=Path(DEFAULT_SOUL_FILENAME), missing=True
    ))
    identity: WorkspaceFile = field(default_factory=lambda: WorkspaceFile(
        name=DEFAULT_IDENTITY_FILENAME, path=Path(DEFAULT_IDENTITY_FILENAME), missing=True
    ))
    user: WorkspaceFile = field(default_factory=lambda: WorkspaceFile(
        name=DEFAULT_USER_FILENAME, path=Path(DEFAULT_USER_FILENAME), missing=True
    ))
    tools: WorkspaceFile = field(default_factory=lambda: WorkspaceFile(
        name=DEFAULT_TOOLS_FILENAME, path=Path(DEFAULT_TOOLS_FILENAME), missing=True
    ))
    boot: WorkspaceFile = field(default_factory=lambda: WorkspaceFile(
        name=DEFAULT_BOOT_FILENAME, path=Path(DEFAULT_BOOT_FILENAME), missing=True
    ))
    memory: WorkspaceFile = field(default_factory=lambda: WorkspaceFile(
        name=DEFAULT_MEMORY_FILENAME, path=Path(DEFAULT_MEMORY_FILENAME), missing=True
    ))

    def loaded_files(self) -> List[WorkspaceFile]:
        """Retorna lista de archivos que fueron cargados exitosamente."""
        return [
            f for f in [self.soul, self.identity, self.user, self.tools, self.boot, self.memory]
            if not f.missing and f.content
        ]

    def has_soul(self) -> bool:
        """Verifica si SOUL.md está presente."""
        return not self.soul.missing and bool(self.soul.content)


def _read_workspace_file(file_path: Path, max_bytes: int = MAX_WORKSPACE_FILE_BYTES) -> str:
    """Lee un archivo de workspace con límite de tamaño.

    Args:
        file_path: Ruta al archivo.
        max_bytes: Tamaño máximo permitido.

    Returns:
        Contenido del archivo o string vacío si no existe/error.
    """
    try:
        if not file_path.exists():
            return ""
        if file_path.stat().st_size > max_bytes:
            logger.warning(
                "Archivo %s excede límite de %d bytes, ignorando",
                file_path, max_bytes
            )
            return ""
        return file_path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.debug("Error leyendo %s: %s", file_path, exc)
        return ""


def load_workspace_context(
    workspace_dir: Optional[Path] = None,
    project_root: Optional[Path] = None,
) -> WorkspaceContext:
    """Carga todos los archivos de contexto del workspace.

    Portado de OpenClaw: loadWorkspaceBootstrapFiles.

    Busca archivos en este orden de prioridad:
    1. Directorio del proyecto actual (si existe)
    2. Workspace global (~/.somer/workspace)

    Args:
        workspace_dir: Directorio de workspace. Default: ~/.somer/workspace
        project_root: Raíz del proyecto actual (para archivos locales).

    Returns:
        WorkspaceContext con todos los archivos cargados.
    """
    workspace = workspace_dir or DEFAULT_WORKSPACE_DIR
    ctx = WorkspaceContext()

    # Lista de archivos a cargar con su atributo en WorkspaceContext
    files_to_load = [
        (DEFAULT_SOUL_FILENAME, "soul"),
        (DEFAULT_IDENTITY_FILENAME, "identity"),
        (DEFAULT_USER_FILENAME, "user"),
        (DEFAULT_TOOLS_FILENAME, "tools"),
        (DEFAULT_BOOT_FILENAME, "boot"),
        (DEFAULT_MEMORY_FILENAME, "memory"),
    ]

    for filename, attr in files_to_load:
        content = ""
        resolved_path = Path(filename)

        # 1. Intentar cargar desde proyecto local primero
        if project_root:
            local_path = project_root / filename
            content = _read_workspace_file(local_path)
            if content:
                resolved_path = local_path

        # 2. Si no existe localmente, intentar desde workspace global
        if not content:
            global_path = workspace / filename
            content = _read_workspace_file(global_path)
            if content:
                resolved_path = global_path

        # 3. Si aún no hay contenido, marcar como missing
        file_obj = WorkspaceFile(
            name=filename,
            path=resolved_path,
            content=content,
            missing=not bool(content),
        )
        setattr(ctx, attr, file_obj)

    loaded_count = len(ctx.loaded_files())
    if loaded_count > 0:
        logger.debug(
            "Workspace cargado: %d archivos desde %s",
            loaded_count, workspace
        )

    return ctx


def build_system_prompt(
    *,
    soul: str = "",
    workspace_context: Optional[WorkspaceContext] = None,
    skills: Optional[List[SkillMeta]] = None,
    active_skills: Optional[List[SkillMeta]] = None,
    memory_context: Optional[List[Dict[str, Any]]] = None,
    active_services: Optional[List[str]] = None,
    tool_descriptions: Optional[List[Dict[str, str]]] = None,
    channel_id: str = "",
    user_name: str = "",
    user_timezone: str = "",
    orchestrator_mode: bool = False,
) -> str:
    """Construye el system prompt completo multi-sección.

    Portado de OpenClaw: buildAgentSystemPrompt.

    Args:
        soul: Contenido de SOUL.md (personalidad). Deprecated: usar workspace_context.
        workspace_context: Contexto completo del workspace (SOUL, IDENTITY, USER, etc.)
        skills: Skills habilitados.
        active_skills: Skills con credenciales activas (incluye body completo).
        memory_context: Entradas de memoria relevantes.
        active_services: Servicios con credenciales configuradas.
        tool_descriptions: Lista de tools disponibles [{"name": ..., "description": ...}].
        channel_id: Canal de origen del mensaje.
        user_name: Nombre del usuario.
        user_timezone: Timezone del usuario.

    Returns:
        System prompt ensamblado.
    """
    sections: List[str] = []

    # 1. Línea de identidad base (como OpenClaw)
    sections.append("Eres un asistente personal ejecutándose dentro de SOMER.")

    # 2. Contexto temporal
    time_section = _build_time_section(user_timezone)
    if time_section:
        sections.append(time_section)

    # 3. Identidad del usuario (runtime)
    if user_name or channel_id:
        runtime_identity = _build_runtime_identity_section(user_name, channel_id)
        if runtime_identity:
            sections.append(runtime_identity)

    # 4. Servicios activos (credenciales configuradas)
    if active_services:
        services_section = _build_services_section(active_services)
        if services_section:
            sections.append(services_section)

    # 5. Herramientas disponibles (portado de OpenClaw: ## Tooling)
    if tool_descriptions:
        tools_section = _build_tools_section(tool_descriptions)
        if tools_section:
            sections.append(tools_section)

    # 6. Skills disponibles (con bodies de skills activos)
    if skills:
        skills_section = _build_skills_section(skills, active_skills)
        if skills_section:
            sections.append(skills_section)

    # 7. Memoria relevante (de runtime)
    if memory_context:
        runtime_memory_section = _build_memory_section(memory_context)
        if runtime_memory_section:
            sections.append(runtime_memory_section)

    # 8. Directivas de orquestador (delegación automática)
    if orchestrator_mode:
        sections.append(_build_orchestrator_section())

    # 9. Archivos de contexto del workspace (portado de OpenClaw: Project Context)
    #    Esto inyecta SOUL.md, IDENTITY.md, USER.md, TOOLS.md, BOOT.md
    context_section = _build_project_context_section(
        workspace_context=workspace_context,
        legacy_soul=soul,
    )
    if context_section:
        sections.append(context_section)

    return "\n\n".join(sections)


def _build_orchestrator_section() -> str:
    """Construye la sección de directivas de orquestador.

    Cuando orchestrator_mode está activo, el agente NO escribe código
    directamente — delega a agentes especializados via tools.
    """
    return """# Modo Orquestador — Delegación Obligatoria

**ERES UN ORQUESTADOR. NO ESCRIBES CÓDIGO.**

Tu rol es planificar, coordinar y delegar. NUNCA generes, edites o escribas código tú mismo.
Para TODA tarea que implique programación, usa las tools de delegación:

## Qué DEBES delegar (siempre)
- Crear, modificar o eliminar código fuente → `delegate_coding`
- Revisar código, buscar bugs, analizar calidad → `delegate_review`
- Corregir errores, debugging, fixes → `delegate_debug`
- Generar tests unitarios o de integración → `delegate_test_gen`
- Refactorizar, migrar, optimizar código → `delegate_coding`
- Crear archivos nuevos (scripts, módulos, configs) → `delegate_coding`

## Qué SÍ haces directamente
- Responder preguntas del usuario (conversación)
- Planificar y diseñar soluciones (sin escribir código)
- Usar skills para APIs externas (Trello, Bitbucket, GitHub, etc.)
- Consultar memoria, historial, contexto
- Ejecutar comandos de sistema (git status, ls, etc.) via bash
- Coordinar múltiples delegaciones
- Reportar resultados al usuario

## Cómo delegar bien
1. **Sé específico**: describe exactamente QUÉ hacer, DÓNDE y con qué RESTRICCIONES
2. **Da contexto**: menciona tecnologías, convenciones, archivos relevantes
3. **Verifica resultados**: después de delegar, informa al usuario qué se hizo
4. **Divide tareas grandes**: si la tarea es compleja, divídela en delegaciones más pequeñas
5. **No repitas trabajo**: si ya delegaste algo, no lo hagas de nuevo sin razón

## Ejemplo de flujo
Usuario: "Agrega validación de email al registro"
1. Planificas: necesito modificar el módulo de registro para agregar validación
2. Delegas: `delegate_coding(task="Agregar validación de email en el endpoint de registro...", context="Proyecto Python con Pydantic v2...")`
3. Reportas: "Listo, se agregó validación de email en registration/handler.py con regex RFC 5322"

## PROHIBIDO
- Escribir bloques de código en tus respuestas (a menos que sea para explicar un concepto)
- Usar tools de edición de archivos directamente
- Generar archivos con contenido de código
- "Sugerir" código para que el usuario lo copie — delega la implementación"""


def _build_project_context_section(
    workspace_context: Optional[WorkspaceContext] = None,
    legacy_soul: str = "",
) -> str:
    """Construye la sección de Project Context con archivos del workspace.

    Portado de OpenClaw: Project Context section en buildAgentSystemPrompt.

    Si SOUL.md está presente, incluye instrucción de encarnar su persona.

    Args:
        workspace_context: Contexto del workspace con todos los archivos.
        legacy_soul: Soul legacy (para compatibilidad hacia atrás).

    Returns:
        Sección de Project Context formateada.
    """
    lines: List[str] = []

    # Si tenemos workspace_context, usar sus archivos
    if workspace_context:
        loaded_files = workspace_context.loaded_files()
        if loaded_files:
            lines.append("# Contexto del Proyecto")
            lines.append("")
            lines.append("Los siguientes archivos de contexto han sido cargados:")

            # Instrucción especial si SOUL.md está presente (como OpenClaw)
            if workspace_context.has_soul():
                lines.append(
                    "Si SOUL.md está presente, encarna su persona y tono. "
                    "Evita respuestas rígidas y genéricas; sigue su guía a menos que "
                    "instrucciones de mayor prioridad lo anulen."
                )
            lines.append("")

            # Inyectar cada archivo cargado
            for f in loaded_files:
                lines.append(f"## {f.name}")
                lines.append("")
                lines.append(f.content.strip())
                lines.append("")

    # Fallback: si no hay workspace_context pero sí legacy_soul
    elif legacy_soul:
        lines.append("# Contexto del Proyecto")
        lines.append("")
        lines.append("## SOUL.md")
        lines.append("")
        lines.append(legacy_soul.strip())
        lines.append("")

    return "\n".join(lines) if lines else ""


# ── Secciones individuales ──────────────────────────────────────


def _build_time_section(user_timezone: str = "") -> str:
    """Construye la sección de fecha y hora."""
    now_utc = datetime.now(timezone.utc)
    lines = ["## Contexto temporal"]

    if user_timezone:
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            try:
                from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]
            except ImportError:
                ZoneInfo = None  # type: ignore[assignment,misc]

        if ZoneInfo is not None:
            try:
                tz = ZoneInfo(user_timezone)
                now_local = now_utc.astimezone(tz)
                lines.append(
                    f"Fecha y hora actual: {now_local.strftime('%Y-%m-%d %H:%M')} "
                    f"({user_timezone})"
                )
                return "\n".join(lines)
            except (KeyError, Exception):
                pass

    # Fallback: solo UTC
    lines.append(
        f"Fecha y hora actual: {now_utc.strftime('%Y-%m-%d %H:%M UTC')}"
    )
    if user_timezone:
        lines.append(f"Timezone del usuario: {user_timezone}")
    return "\n".join(lines)


def _build_runtime_identity_section(user_name: str, channel_id: str) -> str:
    """Construye la sección de identidad de runtime del usuario.

    Nota: Esto es información de runtime (sesión actual), distinto de USER.md
    que contiene información persistente del usuario.
    """
    parts = []
    if user_name:
        parts.append(f"Usuario actual: {user_name}")
    if channel_id:
        parts.append(f"Canal: {channel_id}")
    if not parts:
        return ""
    return "## Sesión actual\n" + "\n".join(parts)


def _build_services_section(active_services: List[str]) -> str:
    """Construye la sección de servicios configurados."""
    if not active_services:
        return ""
    lines = ["## Servicios configurados", "Tienes acceso a estos servicios (credenciales activas):"]
    for svc in active_services:
        lines.append(f"- {svc}")
    lines.append("")
    lines.append(
        "Puedes usar estos servicios directamente cuando el usuario lo pida. "
        "No necesitas pedirle la API key de nuevo."
    )
    return "\n".join(lines)


def _build_tools_section(
    tool_descriptions: List[Dict[str, str]],
) -> str:
    """Construye la sección de herramientas disponibles.

    Portado de OpenClaw: ## Tooling section en system prompt.
    Lista las tools que el agente puede invocar directamente.
    """
    if not tool_descriptions:
        return ""
    lines = [
        "## Herramientas disponibles (DEBES usarlas)",
        "Tienes acceso a las siguientes herramientas que puedes invocar directamente. "
        "Estas herramientas se ejecutan automáticamente — tú las invocas y recibes "
        "el resultado:",
        "",
    ]
    for tool in tool_descriptions:
        name = tool.get("name", "")
        desc = tool.get("description", "")
        lines.append(f"- **{name}**: {desc}")
    lines.append("")
    lines.append(
        "REGLAS OBLIGATORIAS:\n"
        "1. Cuando necesites interactuar con una API externa "
        "(Notion, GitHub, etc.), DEBES usar la herramienta `http_request`.\n"
        "2. Cuando un skill tenga herramientas dedicadas (ej: `security_scan`, "
        "`check_headers`), úsalas directamente en vez de `http_request`.\n"
        "3. NUNCA generes bloques de código Python/JavaScript/bash para que el "
        "usuario los ejecute. Tú tienes la capacidad de ejecutar acciones "
        "directamente mediante tus herramientas. Úsalas SIEMPRE."
    )
    return "\n".join(lines)


def _build_skills_section(
    skills: List[SkillMeta],
    active_skills: Optional[List[SkillMeta]] = None,
) -> str:
    """Construye la sección de skills disponibles.

    Args:
        skills: Todos los skills habilitados (se listan como resumen).
        active_skills: Skills con credenciales activas (se incluye body completo).
    """
    if not skills:
        return ""

    active_names = {s.name for s in (active_skills or [])}

    lines = [
        "## Skills disponibles",
        "Tienes acceso a los siguientes skills. Cuando el usuario pida algo "
        "relacionado, usa las herramientas disponibles siguiendo las instrucciones "
        "del skill correspondiente:",
        "",
    ]
    for skill in skills:
        desc = skill.description[:120] if skill.description else ""
        triggers = ", ".join(skill.triggers[:3]) if skill.triggers else ""
        active_marker = " ✓" if skill.name in active_names else ""
        line = f"- **{skill.name}**{active_marker}"
        if desc:
            line += f": {desc}"
        if triggers:
            line += f" (triggers: {triggers})"
        lines.append(line)

    # Incluir body completo de skills con credenciales activas
    if active_skills:
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("## Instrucciones detalladas de skills activos")
        lines.append(
            "REGLAS CRÍTICAS para ejecutar skills:\n"
            "1. Si el skill tiene herramientas dedicadas (ej: `security_scan`, "
            "`check_headers`, `check_ssl`), úsalas directamente.\n"
            "2. Para skills que interactúan con APIs externas, usa `http_request`. "
            "NUNCA generes código Python, JavaScript o de cualquier otro lenguaje.\n"
            "3. Los ejemplos curl a continuación son REFERENCIA de los endpoints. "
            "Tradúcelos a llamadas `http_request` así:\n"
            "   - curl -X POST → method: \"POST\"\n"
            "   - La URL del curl → url: \"https://...\"\n"
            "   - Los -H del curl → headers: {\"Authorization\": \"Bearer $NOTION_API_KEY\", ...}\n"
            "   - El -d del curl → body: {...}\n"
            "4. Las credenciales ya están configuradas como variables de entorno. "
            "Usa $NOMBRE_VARIABLE en los headers (ej: $NOTION_API_KEY).\n"
            "5. Ejecuta la herramienta, espera el resultado, y respóndele al "
            "usuario con la información obtenida en lenguaje natural."
        )
        for skill in active_skills:
            if skill.body:
                lines.append("")
                lines.append(f"### {skill.name}")
                # Truncar bodies muy largos para no explotar el contexto
                body = skill.body.strip()
                if len(body) > 3000:
                    body = body[:3000] + "\n\n...(instrucciones truncadas)"
                lines.append(body)

    return "\n".join(lines)


def _build_memory_section(
    memory_context: List[Dict[str, Any]],
) -> str:
    """Construye la sección de memoria relevante."""
    if not memory_context:
        return ""
    lines = [
        "## Memoria relevante",
        "Información recordada de conversaciones anteriores:",
        "",
    ]
    for entry in memory_context[:10]:  # Limitar a 10 entradas
        content = entry.get("content", "")
        source = entry.get("source", "")
        # Truncar contenido largo
        if len(content) > 300:
            content = content[:300] + "..."
        prefix = f"[{source}] " if source else ""
        lines.append(f"- {prefix}{content}")
    return "\n".join(lines)


# ── Utilidades ──────────────────────────────────────────────────


def load_soul(
    soul_path: Optional[str] = None,
    workspace_dir: Optional[Path] = None,
    project_root: Optional[Path] = None,
) -> str:
    """Carga el archivo SOUL.md.

    Busca en orden:
    1. Ruta explícita (soul_path)
    2. Proyecto local (project_root/SOUL.md)
    3. Workspace global (~/.somer/workspace/SOUL.md o workspace_dir/SOUL.md)
    4. Directorio actual (./SOUL.md) - solo si no se especificaron rutas

    Args:
        soul_path: Ruta explícita al archivo.
        workspace_dir: Directorio de workspace global.
        project_root: Raíz del proyecto actual.

    Returns:
        Contenido del SOUL.md o prompt por defecto.
    """
    # 1. Ruta explícita
    if soul_path:
        try:
            path = Path(soul_path)
            if path.exists():
                return path.read_text(encoding="utf-8")
        except Exception:
            pass

    # 2. Proyecto local
    if project_root:
        try:
            local_path = project_root / DEFAULT_SOUL_FILENAME
            if local_path.exists():
                return local_path.read_text(encoding="utf-8")
        except Exception:
            pass

    # 3. Workspace global (usa workspace_dir si se especifica, sino el default)
    workspace = workspace_dir if workspace_dir is not None else DEFAULT_WORKSPACE_DIR
    try:
        global_path = workspace / DEFAULT_SOUL_FILENAME
        if global_path.exists():
            return global_path.read_text(encoding="utf-8")
    except Exception:
        pass

    # 4. Directorio actual (compatibilidad) - solo si no se especificaron rutas
    #    Si se especificó project_root o workspace_dir, no buscar en cwd
    if project_root is None and workspace_dir is None:
        try:
            current_path = Path(DEFAULT_SOUL_FILENAME)
            if current_path.exists():
                return current_path.read_text(encoding="utf-8")
        except Exception:
            pass

    # Fallback
    return (
        "Eres SOMER, un asistente inteligente. "
        "Responde de forma concisa y útil en español."
    )


def load_workspace(
    workspace_dir: Optional[Path] = None,
    project_root: Optional[Path] = None,
) -> WorkspaceContext:
    """Alias conveniente para load_workspace_context.

    Args:
        workspace_dir: Directorio de workspace. Default: ~/.somer/workspace
        project_root: Raíz del proyecto actual.

    Returns:
        WorkspaceContext con todos los archivos cargados.
    """
    return load_workspace_context(
        workspace_dir=workspace_dir,
        project_root=project_root,
    )


def detect_active_services() -> List[str]:
    """Detecta servicios con credenciales configuradas en el entorno.

    Returns:
        Lista de nombres de servicios activos.
    """
    service_env_map = {
        "NOTION_API_KEY": "Notion",
        "ANTHROPIC_API_KEY": "Anthropic (Claude)",
        "OPENAI_API_KEY": "OpenAI",
        "DEEPSEEK_API_KEY": "DeepSeek",
        "GOOGLE_API_KEY": "Google AI",
        "GROQ_API_KEY": "Groq",
        "XAI_API_KEY": "xAI (Grok)",
        "OPENROUTER_API_KEY": "OpenRouter",
        "MISTRAL_API_KEY": "Mistral",
        "TOGETHER_API_KEY": "Together AI",
        "PERPLEXITY_API_KEY": "Perplexity",
        "HF_TOKEN": "HuggingFace",
        "TELEGRAM_BOT_TOKEN": "Telegram Bot",
        "TAVILY_API_KEY": "Tavily (búsqueda web)",
        "SLACK_BOT_TOKEN": "Slack",
        "DISCORD_BOT_TOKEN": "Discord",
    }
    active = []
    for env_var, display_name in service_env_map.items():
        value = os.environ.get(env_var, "").strip()
        if value:
            active.append(display_name)
    return active
