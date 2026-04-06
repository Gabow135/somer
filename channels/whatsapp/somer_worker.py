"""Worker asyncio para procesar mensajes entrantes de WhatsApp con SOMER 2.0.

Consume la cola global `_incoming_queue` expuesta por `handler.py` y, para
cada mensaje entrante, obtiene (o crea) el `AgentRunner` propio del usuario,
genera una respuesta y la envía de vuelta al remitente via `WhatsAppSender`.

Arquitectura multi-usuario:
    Cada número de WhatsApp tiene su propio AgentRunner con su propio
    SOMER_HOME apuntando al directorio de datos personal del usuario.
    Los perfiles se cargan desde ~/.somer/whatsapp_users.json.

Flujo de ejecución:
    run_worker_loop()
        └─ start_worker()             ← loop infinito consumiendo la cola
              └─ _get_or_create_runner(numero)   ← runner por usuario
              └─ _procesar_mensaje(runner, item)
                    ├─ texto  → runner.run() → WhatsAppSender.send_text()
                    └─ otro   → WhatsAppSender.send_text() con msg informativo

Uso típico (desde server.py o bootstrap):

    import asyncio
    from channels.whatsapp.somer_worker import run_worker_loop

    asyncio.create_task(run_worker_loop())
"""

from __future__ import annotations

import asyncio
import base64
import importlib
import json
import logging
import logging.handlers
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Logger de actividad en /var/log/whatsapp-somer.log ───────────────────────

_activity_logger: Optional[logging.Logger] = None


def _get_activity_logger() -> logging.Logger:
    """Retorna (creando si hace falta) el logger de actividad en disco.

    El archivo /var/log/whatsapp-somer.log registra cada mensaje entrante y
    cada respuesta saliente con el formato:
        [2026-04-01 17:30:00] IN  593995466833 → "Hola, cómo estás?"
        [2026-04-01 17:30:05] OUT 593995466833 ← "Hola! Soy SOMER..."
    """
    global _activity_logger
    if _activity_logger is not None:
        return _activity_logger

    _activity_logger = logging.getLogger("whatsapp.activity")
    _activity_logger.setLevel(logging.INFO)
    _activity_logger.propagate = False

    if not _activity_logger.handlers:
        log_path = "/var/log/whatsapp-somer.log"
        try:
            handler = logging.handlers.RotatingFileHandler(
                log_path,
                maxBytes=10 * 1024 * 1024,  # 10 MB
                backupCount=5,
                encoding="utf-8",
            )
            handler.setFormatter(logging.Formatter("%(message)s"))
            _activity_logger.addHandler(handler)
        except (PermissionError, OSError) as exc:
            logger.warning(
                "No se pudo abrir %s para logs de actividad: %s", log_path, exc
            )
            # Fallback: escribir en el logger principal
            _activity_logger.addHandler(logging.StreamHandler())

    return _activity_logger


def _log_in(numero: str, texto: str) -> None:
    """Registra un mensaje entrante en el log de actividad."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _get_activity_logger().info('[%s] IN  %s → "%s"', ts, numero, texto)


def _log_out(numero: str, texto: str) -> None:
    """Registra una respuesta saliente en el log de actividad."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Truncar respuestas muy largas en el log (primeras 200 chars)
    resumen = texto[:200] + "…" if len(texto) > 200 else texto
    _get_activity_logger().info('[%s] OUT %s ← "%s"', ts, numero, resumen)


# ── Mensaje para tipos de media no soportados ─────────────────────────────────

_MSG_MEDIA_NO_SOPORTADO = (
    "Hola! Por el momento solo puedo procesar mensajes de texto. "
    "Por favor escríbeme tu consulta y te responderé a la brevedad."
)


# ── Historial de conversación por usuario ─────────────────────────────────────


def _get_history_path(phone_number: str, data_dir: Optional[str]) -> Optional[Path]:
    """Retorna la ruta al archivo JSONL de historial para el usuario.

    Args:
        phone_number: Número de teléfono WhatsApp del usuario.
        data_dir:     Directorio base de datos del usuario (SOMER_HOME del usuario).

    Returns:
        Path al archivo JSONL, o None si no hay data_dir configurado.
    """
    if not data_dir:
        return None
    history_dir = Path(data_dir) / "whatsapp_history"
    history_dir.mkdir(parents=True, exist_ok=True)
    return history_dir / f"{phone_number}.jsonl"


def load_history(
    phone_number: str,
    data_dir: Optional[str],
    max_messages: int = 20,
) -> List[Dict[str, Any]]:
    """Carga los últimos N mensajes del historial de conversación del usuario.

    Lee el archivo JSONL de historial y retorna los últimos `max_messages`
    mensajes en orden cronológico (más antiguo primero).

    Args:
        phone_number:  Número de teléfono WhatsApp del usuario.
        data_dir:      Directorio base de datos del usuario.
        max_messages:  Máximo de mensajes a cargar (default: 20).

    Returns:
        Lista de dicts con {role, content, timestamp}, o lista vacía si no
        hay historial o si ocurre cualquier error.
    """
    try:
        history_path = _get_history_path(phone_number, data_dir)
        if not history_path or not history_path.exists():
            return []

        mensajes: List[Dict[str, Any]] = []
        with history_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        mensajes.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

        # Retornar solo los últimos N mensajes
        if len(mensajes) > max_messages:
            mensajes = mensajes[-max_messages:]

        logger.debug(
            "Historial cargado para %s: %d mensaje(s)",
            ("*****" + phone_number[-4:]) if len(phone_number) >= 4 else phone_number,
            len(mensajes),
        )
        return mensajes

    except Exception as exc:
        logger.warning("No se pudo cargar historial para %s: %s", phone_number, exc)
        return []


def save_message(
    phone_number: str,
    data_dir: Optional[str],
    role: str,
    content: str,
) -> None:
    """Guarda un mensaje en el historial JSONL del usuario.

    Appends al archivo JSONL una línea JSON con role, content y timestamp.
    Los errores se capturan y registran sin propagar al caller.

    Args:
        phone_number: Número de teléfono WhatsApp del usuario.
        data_dir:     Directorio base de datos del usuario.
        role:         Rol del mensaje ("user" o "assistant").
        content:      Contenido del mensaje.
    """
    try:
        history_path = _get_history_path(phone_number, data_dir)
        if not history_path:
            return

        entrada = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        }
        with history_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entrada, ensure_ascii=False) + "\n")

    except Exception as exc:
        logger.warning("No se pudo guardar mensaje en historial para %s: %s", phone_number, exc)


# ── Perfiles de usuario ────────────────────────────────────────────────────────

_USERS_FILE = Path.home() / ".somer" / "whatsapp_users.json"
_DEFAULT_PERSONA = (
    "Eres SOMER, el orquestador de inteligencia personal. "
    "Tienes acceso completo a todas las herramientas del sistema: CRM, finanzas, "
    "bookmarks, briefing diario, agenda, research y más. "
    "Responde siempre en español con formato profesional. "
    "Puedes usar *negrita* y _cursiva_ para destacar información importante."
)


def _cargar_perfil_usuario(numero: str) -> dict:
    """Carga el perfil de usuario para un número de WhatsApp.

    Lee ~/.somer/whatsapp_users.json y retorna el perfil correspondiente
    al número dado, o un dict vacío si no existe.

    Args:
        numero: Número de WhatsApp (ej: "593995466833").

    Returns:
        Dict con las claves name, agent_id, data_dir, persona; o {} si no
        se encuentra el número o el archivo no existe.
    """
    try:
        if _USERS_FILE.exists():
            data = json.loads(_USERS_FILE.read_text(encoding="utf-8"))
            return data.get(numero, {})
    except Exception as exc:
        logger.warning("No se pudo cargar whatsapp_users.json: %s", exc)
    return {}


# ── Construcción de runners por usuario ───────────────────────────────────────

_runners: Dict[str, object] = {}


def _create_provider(provider_id: str, settings: object) -> Optional[object]:
    """Crea una instancia de provider según el ID.

    Copia exacta de cli/agent_cmd._create_provider para evitar importación
    circular con el módulo CLI.

    Args:
        provider_id: Identificador del provider (ej: "anthropic", "openai").
        settings:    Objeto de configuración del provider (ProviderConfig).

    Returns:
        Instancia del provider listo para registrar, o None si no es posible
        construirlo (clave faltante, provider desconocido, etc.).
    """
    auth = getattr(settings, "auth", None)
    api_key = None
    if auth:
        api_key = getattr(auth, "api_key", None)
        if not api_key:
            env_var = getattr(auth, "api_key_env", None)
            if env_var:
                api_key = os.environ.get(env_var)

    factories = {
        "anthropic":   ("providers.anthropic",   "AnthropicProvider",   True),
        "openai":      ("providers.openai",       "OpenAIProvider",      True),
        "deepseek":    ("providers.deepseek",     "DeepSeekProvider",    True),
        "google":      ("providers.google",       "GoogleProvider",      True),
        "ollama":      ("providers.ollama",       "OllamaProvider",      False),
        "groq":        ("providers.groq",         "GroqProvider",        True),
        "xai":         ("providers.xai",          "XAIProvider",         True),
        "openrouter":  ("providers.openrouter",   "OpenRouterProvider",  True),
        "mistral":     ("providers.mistral",      "MistralProvider",     True),
        "together":    ("providers.together",     "TogetherProvider",    True),
        "perplexity":  ("providers.perplexity",   "PerplexityProvider",  True),
        "claude-code": ("providers.claude_code",  "ClaudeCodeProvider",  False),
    }

    entry = factories.get(provider_id)
    if not entry:
        return None

    module_path, class_name, needs_key = entry

    if needs_key and not api_key:
        return None

    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)

    if needs_key:
        return cls(api_key=api_key)
    if provider_id == "ollama":
        base_url = getattr(auth, "base_url", None) if auth else None
        return cls(base_url=base_url or "http://127.0.0.1:11434")
    return cls()


def _build_runner() -> object:
    """Construye un AgentRunner completamente inicializado con todas las tools.

    Carga la configuración de SOMER (respetando SOMER_HOME actual), registra
    todos los providers habilitados, crea un ToolRegistry con todas las tools
    del orquestador (CRM, finanzas, bookmarks, briefing, research, etc.) y
    devuelve un runner listo para procesar turnos de conversación.

    Replica el comportamiento de gateway/bootstrap.py _setup_agent_runner()
    para que el canal WhatsApp tenga acceso a las mismas capacidades que el
    Gateway.

    Returns:
        Instancia de AgentRunner lista para usar.

    Raises:
        Exception: Cualquier error durante la carga de config o providers.
    """
    from agents.runner import AgentRunner
    from agents.tools.registry import ToolRegistry
    from config.loader import load_config
    from config.runtime_overrides import apply_env_overrides
    from providers.registry import ProviderRegistry

    config = apply_env_overrides(load_config())
    registry = ProviderRegistry()

    providers_registrados = 0
    for provider_id, settings in config.providers.items():
        if not getattr(settings, "enabled", True):
            continue
        try:
            provider = _create_provider(provider_id, settings)
            if provider:
                registry.register(provider)
                providers_registrados += 1
        except Exception as exc:
            logger.warning(
                "No se pudo registrar provider '%s': %s", provider_id, exc
            )

    logger.info(
        "WhatsApp worker: %d provider(s) registrado(s) — modelo por defecto: %s",
        providers_registrados,
        config.default_model,
    )

    # ── Tool Registry ─────────────────────────────────────────────────────────
    tool_registry = ToolRegistry()

    # Built-in tools (siempre disponibles)
    try:
        from agents.tools.builtins import register_builtins
        register_builtins(tool_registry)
    except Exception as exc:
        logger.warning("Built-in tools no disponibles: %s", exc)

    # Report tools
    try:
        from agents.tools.report_tools import register_report_tools
        from reports.manager import ReportManager
        _report_manager = ReportManager()
        register_report_tools(
            tool_registry,
            channel_plugins=None,
            report_manager=_report_manager,
            base_url="http://127.0.0.1:18789",
        )
    except Exception as exc:
        logger.warning("Report tools no disponibles: %s", exc)

    # Delegation tools (si el modo orquestador está activo)
    try:
        if getattr(getattr(config.agents, "delegation", None), "orchestrator_mode", False):
            from agents.tools.delegation_tools import register_delegation_tools
            register_delegation_tools(tool_registry)
    except Exception as exc:
        logger.warning("Delegation tools no disponibles: %s", exc)

    # SQL tools
    try:
        from agents.tools.sql_tools import register_sql_tools
        register_sql_tools(tool_registry)
    except Exception as exc:
        logger.warning("SQL tools no disponibles: %s", exc)

    # Shell tools
    try:
        from agents.tools.shell_tools import register_shell_tools
        register_shell_tools(tool_registry)
    except Exception as exc:
        logger.warning("Shell tools no disponibles: %s", exc)

    # Code interpreter tools
    try:
        from agents.tools.code_interpreter_tools import register_code_interpreter_tools
        register_code_interpreter_tools(tool_registry)
    except Exception as exc:
        logger.warning("Code interpreter tools no disponibles: %s", exc)

    # Knowledge graph tools (si están habilitados en config)
    try:
        if getattr(getattr(config, "knowledge_graph", None), "enabled", False):
            from agents.tools.knowledge_graph_tools import register_knowledge_graph_tools
            register_knowledge_graph_tools(tool_registry)
    except Exception as exc:
        logger.warning("Knowledge graph tools no disponibles: %s", exc)

    # Agent tools (research, data_analyst, planning, messaging, episodic)
    try:
        from agents.tools.agent_tools import register_agent_tools
        register_agent_tools(tool_registry)
    except Exception as exc:
        logger.warning("Agent tools no disponibles: %s", exc)

    # Cybersecurity tools
    try:
        from cybersecurity.tools.orchestrator_tools import register_orchestrator_tools
        from cybersecurity.tools.scanner_tools import register_scanner_tools
        from cybersecurity.tools.exploit_tools import register_exploit_tools
        from cybersecurity.tools.evidence_tools import register_evidence_tools
        from cybersecurity.tools.osint_tools import register_osint_tools
        from cybersecurity.tools.network_tools import register_network_tools
        from cybersecurity.tools.malware_tools import register_malware_tools
        from cybersecurity.tools.compliance_tools import register_compliance_tools
        register_orchestrator_tools(tool_registry)
        register_scanner_tools(tool_registry)
        register_exploit_tools(tool_registry)
        register_evidence_tools(tool_registry)
        register_osint_tools(tool_registry)
        register_network_tools(tool_registry)
        register_malware_tools(tool_registry)
        register_compliance_tools(tool_registry)
    except Exception as exc:
        logger.warning("Cybersecurity tools no disponibles: %s", exc)

    # Business tools (CRM, finanzas, reuniones)
    try:
        from agents.tools.business_tools import register_business_tools
        register_business_tools(tool_registry)
    except Exception as exc:
        logger.warning("Business tools no disponibles: %s", exc)

    # Personal tools (bookmarks, daily briefing)
    try:
        from agents.tools.personal_tools import register_personal_tools
        register_personal_tools(tool_registry)
    except Exception as exc:
        logger.warning("Personal tools no disponibles: %s", exc)

    # Self-improve tools (auto-mejora, credenciales, restart)
    try:
        from self_improve.tools import register_self_improve_tools
        register_self_improve_tools(tool_registry)
    except Exception as exc:
        logger.warning("Self-improve tools no disponibles: %s", exc)

    logger.info(
        "WhatsApp worker: %d tool(s) registrada(s) en ToolRegistry",
        len(tool_registry.tool_names),
    )

    runner = AgentRunner(
        provider_registry=registry,
        default_model=config.default_model,
        tool_registry=tool_registry,
        timeout_secs=180,  # 3 minutos máximo por request
    )
    return runner


def _build_runner_for_user(data_dir: Optional[str]) -> object:
    """Construye un AgentRunner con el SOMER_HOME apuntando al usuario.

    Modifica temporalmente SOMER_HOME en el entorno para que load_config()
    y los tools internos (CRM, finanzas, etc.) lean del directorio personal
    del usuario. Restaura el valor original al terminar.

    Args:
        data_dir: Ruta absoluta al directorio de datos del usuario, o None
                  para usar el directorio por defecto.

    Returns:
        Instancia de AgentRunner configurada para el usuario.
    """
    old_home = os.environ.get("SOMER_HOME")
    if data_dir:
        os.environ["SOMER_HOME"] = data_dir
        Path(data_dir).mkdir(parents=True, exist_ok=True)

    try:
        return _build_runner()
    finally:
        # Restaurar el entorno al estado anterior
        if old_home is not None:
            os.environ["SOMER_HOME"] = old_home
        elif data_dir and "SOMER_HOME" in os.environ:
            del os.environ["SOMER_HOME"]


async def _get_or_create_runner(numero: str) -> Optional[object]:
    """Obtiene o crea un AgentRunner para el número de WhatsApp dado.

    Los runners se almacenan en el dict módulo-level `_runners` indexados por
    número de teléfono. En la primera llamada para un número, se construye el
    runner con SOMER_HOME apuntando al data_dir del perfil del usuario.

    Args:
        numero: Número de WhatsApp del remitente (ej: "593995466833").

    Returns:
        Instancia de AgentRunner, o None si la construcción falla.
    """
    if numero in _runners:
        return _runners[numero]

    perfil = _cargar_perfil_usuario(numero)
    data_dir = perfil.get("data_dir")
    nombre = perfil.get("name") or numero

    try:
        runner = await asyncio.get_event_loop().run_in_executor(
            None, _build_runner_for_user, data_dir
        )
        _runners[numero] = runner
        numero_log = ("*****" + numero[-4:]) if len(numero) >= 4 else numero
        logger.info(
            "Runner creado para %s (%s, data_dir=%s)",
            numero_log,
            nombre,
            data_dir or "default",
        )
        return runner
    except Exception as exc:
        numero_log = ("*****" + numero[-4:]) if len(numero) >= 4 else numero
        logger.warning(
            "No se pudo crear runner para %s: %s", numero_log, exc
        )
        return None


# ── System prompt ──────────────────────────────────────────────────────────────


def _build_system_prompt(
    from_number: str,
    contact_name: str,
    usuario_sri: Optional[Dict[str, Any]],
) -> str:
    """Construye el system prompt con el perfil y contexto del usuario.

    Usa la persona definida en whatsapp_users.json para el número dado.
    Si el número no está registrado, usa la persona por defecto.
    Agrega contexto SRI si el usuario tiene RUC registrado.

    Args:
        from_number:  Número de WhatsApp del remitente.
        contact_name: Nombre del contacto según WhatsApp.
        usuario_sri:  Dict con {ruc, name, alias, whatsapp_number} o None.

    Returns:
        Cadena de texto con el system prompt listo para pasar al runner.
    """
    perfil = _cargar_perfil_usuario(from_number)
    persona = perfil.get("persona", _DEFAULT_PERSONA)
    nombre = perfil.get("name") or contact_name or from_number

    contexto_extra: list[str] = []

    if usuario_sri:
        ruc = usuario_sri.get("ruc", "")
        if ruc:
            contexto_extra.append(f"El usuario tiene RUC {ruc} registrado en el SRI.")

    contexto_extra.append(
        f"Estás respondiendo a través de WhatsApp. "
        f"El usuario se llama {nombre}. "
        "WhatsApp soporta *negrita*, _cursiva_ y ~tachado~ — úsalos con moderación para mejorar la lectura. "
        "Responde directamente sin saludos genéricos ni frases de relleno. "
        "Sé conciso, claro y profesional. "
        "Cuando uses herramientas, ejecuta la acción primero y presenta el resultado de forma limpia, "
        "sin mostrar tecnicismos internos ni prefijos de sistema al usuario. "
        "Nunca menciones 'TPL', 'orquestador', 'AgentRunner' ni términos técnicos internos. "
        "Responde siempre en español."
    )

    contexto_str = "\n\n" + "\n".join(contexto_extra) if contexto_extra else ""
    return f"{persona}{contexto_str}"


# ── Helper de envío ───────────────────────────────────────────────────────────


async def _send_reply(to_number: str, text: str) -> None:
    """Envía un mensaje de texto al número de WhatsApp indicado via WhatsAppSender.

    Los errores se capturan y registran sin propagar al caller.

    Args:
        to_number: Número de WhatsApp destino (ej: "593987654321").
        text:      Texto del mensaje a enviar.
    """
    try:
        from channels.whatsapp.sender import WhatsAppSender

        sender = WhatsAppSender()
        resultado = await sender.send_text(to_number, text)
        numero_log = ("*****" + to_number[-4:]) if len(to_number) >= 4 else "*****"
        if resultado.get("success"):
            logger.info(
                "Respuesta enviada a %s (HTTP %s)",
                numero_log,
                resultado.get("http_code"),
            )
        else:
            logger.warning("Fallo al enviar respuesta a %s: %s", numero_log, resultado)
    except Exception as exc:
        logger.error("Error enviando respuesta a %s: %s", to_number, exc)


# ── Procesamiento de un mensaje ───────────────────────────────────────────────


async def _procesar_media(
    message_type: str,
    raw: Dict[str, Any],
) -> Optional[str]:
    """Descarga y procesa un mensaje multimedia (image, document, audio).

    Usa WhatsAppClient para descargar el media y luego lo procesa según su tipo:
    - image:    convierte a base64 y construye prompt con descripción
    - document: extrae texto si es PDF, o informa del documento
    - audio:    transcribe con whisper si está disponible, si no informa

    Args:
        message_type: Tipo de mensaje ("image", "document", "audio").
        raw:          Dict crudo del mensaje de Meta con los campos del media.

    Returns:
        Texto procesado para pasar al agente, o None si no se pudo procesar.
    """
    try:
        from channels.whatsapp.client import WhatsAppClient

        client = WhatsAppClient()
        await client.start()

        try:
            if message_type == "image":
                media_id = raw.get("image", {}).get("id", "")
                caption = raw.get("image", {}).get("caption", "")
                if not media_id:
                    return None

                image_bytes = await client.download_media(media_id)
                image_b64 = base64.b64encode(image_bytes).decode("utf-8")
                mime_type = raw.get("image", {}).get("mime_type", "image/jpeg")

                caption_texto = f" Caption del usuario: '{caption}'." if caption else ""
                return (
                    f"[Imagen adjunta por el usuario.{caption_texto} "
                    f"Analiza y describe qué ves en esta imagen, extrae texto si es relevante. "
                    f"Datos de la imagen en base64 ({mime_type}): {image_b64[:100]}... "
                    f"(imagen completa disponible como adjunto)]\n\n"
                    f"[IMAGE_BASE64:{mime_type}:{image_b64}]"
                )

            elif message_type == "document":
                media_id = raw.get("document", {}).get("id", "")
                filename = raw.get("document", {}).get("filename", "documento")
                mime_type = raw.get("document", {}).get("mime_type", "")
                caption = raw.get("document", {}).get("caption", "")
                if not media_id:
                    return None

                doc_bytes = await client.download_media(media_id)

                # Intentar extraer texto si es PDF
                texto_extraido = ""
                if "pdf" in mime_type.lower() or filename.lower().endswith(".pdf"):
                    try:
                        import io
                        try:
                            # Intentar con pypdf primero
                            import pypdf
                            reader = pypdf.PdfReader(io.BytesIO(doc_bytes))
                            partes_pdf = []
                            for page in reader.pages[:10]:  # Máximo 10 páginas
                                partes_pdf.append(page.extract_text() or "")
                            texto_extraido = "\n".join(partes_pdf).strip()
                        except ImportError:
                            pass

                        if not texto_extraido:
                            # Fallback con pdfminer
                            try:
                                from pdfminer.high_level import extract_text as pdfminer_extract
                                texto_extraido = pdfminer_extract(io.BytesIO(doc_bytes))
                            except ImportError:
                                pass
                    except Exception as exc_pdf:
                        logger.warning("No se pudo extraer texto del PDF %s: %s", filename, exc_pdf)

                caption_texto = f" Caption: '{caption}'." if caption else ""
                if texto_extraido:
                    # Limitar a primeros 4000 caracteres para no exceder contexto
                    texto_truncado = texto_extraido[:4000]
                    if len(texto_extraido) > 4000:
                        texto_truncado += "\n... [documento truncado]"
                    return (
                        f"[Documento adjunto: {filename}.{caption_texto} "
                        f"Contenido extraído:\n{texto_truncado}]"
                    )
                else:
                    return (
                        f"[Documento adjunto: {filename}.{caption_texto} "
                        f"No se pudo extraer el texto del documento. "
                        f"El usuario envió un archivo de tipo {mime_type}.]"
                    )

            elif message_type == "audio":
                media_id = raw.get("audio", {}).get("id", "")
                if not media_id:
                    return None

                audio_bytes = await client.download_media(media_id)

                # Determinar extensión según MIME type
                mime_type = raw.get("audio", {}).get("mime_type", "audio/ogg")
                ext = ".ogg"
                if "mp4" in mime_type or "m4a" in mime_type:
                    ext = ".m4a"
                elif "mpeg" in mime_type or "mp3" in mime_type:
                    ext = ".mp3"
                elif "wav" in mime_type:
                    ext = ".wav"
                elif "opus" in mime_type:
                    ext = ".opus"

                # Transcribir usando MediaPipeline (mismo pipeline que Telegram)
                import tempfile
                import os as _os
                from pathlib import Path as _Path

                tmp_fd, tmp_str = tempfile.mkstemp(suffix=ext, prefix="somer_wa_voice_")
                tmp_path = _Path(tmp_str)
                _os.close(tmp_fd)
                tmp_path.write_bytes(audio_bytes)

                try:
                    from media.pipeline import MediaPipeline

                    pipeline = MediaPipeline()
                    media_file = pipeline.process(str(tmp_path))
                    transcripcion = await pipeline.transcribe(media_file)

                    if transcripcion and not transcripcion.startswith("[Transcripci\u00f3n no disponible"):
                        return f"[Audio transcrito: {transcripcion}]"
                except Exception as exc_whisper:
                    logger.warning("Error transcribiendo audio: %s", exc_whisper)
                finally:
                    if tmp_path.exists():
                        try:
                            tmp_path.unlink()
                        except Exception:
                            pass

                # Transcripción no disponible: informar al agente
                return (
                    "[El usuario envió un audio. No se pudo transcribir automáticamente. "
                    "Informa al usuario que por el momento no puedo procesar mensajes de voz "
                    "y pídele que escriba su mensaje en texto.]"
                )

        finally:
            await client.stop()

    except Exception as exc:
        logger.error("Error procesando media tipo=%s: %s", message_type, exc)
        return None


async def _procesar_mensaje(runner: object, item: Dict[str, Any]) -> None:
    """Procesa un único mensaje de la cola usando el orquestador SOMER (AgentRunner).

    Para mensajes de texto: construye el system prompt con contexto del usuario,
    invoca runner.run() con un session_id derivado del número de teléfono y envía
    la respuesta via WhatsAppSender.

    Para mensajes multimedia (image, document, audio): descarga y procesa el media,
    construye un mensaje enriquecido y lo pasa al agente.

    Persiste el historial de conversación en JSONL por usuario.

    Si runner no está disponible (inicialización fallida), cae al CLI de SOMER como
    respaldo: /var/www/somer/venv/bin/python3 entry.py agent run "MENSAJE"

    Args:
        runner: Instancia de AgentRunner del usuario (puede ser None si falló).
        item:   Dict de la cola con claves: from_number, text, message_type,
                contact_name, phone_number_id, usuario_sri, message_id, timestamp.
    """
    from_number: str = item.get("from_number", "")
    text: str = item.get("text", "").strip()
    message_type: str = item.get("message_type", "text")
    contact_name: str = item.get("contact_name", "") or from_number
    usuario_sri: Optional[Dict[str, Any]] = item.get("usuario_sri")
    raw: Dict[str, Any] = item.get("raw", {})

    numero_log = ("*****" + from_number[-4:]) if len(from_number) >= 4 else "*****"

    # Cargar perfil del usuario para data_dir
    perfil = _cargar_perfil_usuario(from_number)
    data_dir = perfil.get("data_dir")
    nombre_display = contact_name or from_number
    nombre_usuario = perfil.get("name") or nombre_display

    # ── Manejo de multimedia ───────────────────────────────────────────────────
    if message_type in ("image", "document", "audio"):
        logger.info(
            "Procesando media tipo=%s de %s", message_type, numero_log
        )
        contenido_media = await _procesar_media(message_type, raw)

        if contenido_media is None:
            # Error al procesar el media
            tipo_nombre = {"image": "imagen", "document": "documento", "audio": "audio"}.get(
                message_type, message_type
            )
            await _send_reply(
                from_number,
                f"Recibí tu {tipo_nombre} pero tuve un problema al procesarlo. "
                f"¿Puedes intentarlo de nuevo?",
            )
            return

        # Usar el contenido procesado como mensaje para el agente
        mensaje_orquestador = contenido_media
        texto_historial_user = f"[{message_type}: {text or 'sin caption'}]"
        _log_in(from_number, texto_historial_user)
        save_message(from_number, data_dir, "user", texto_historial_user)

    elif message_type == "text":
        if not text:
            return
        # Registrar mensaje entrante
        _log_in(from_number, text)
        save_message(from_number, data_dir, "user", text)
        mensaje_orquestador = text

    else:
        # Otros tipos no soportados (sticker, location, contacts, etc.)
        await _send_reply(from_number, _MSG_MEDIA_NO_SOPORTADO)
        return

    try:
        respuesta: Optional[str] = None

        if runner is not None:
            # ── Ruta principal: AgentRunner completo con todos los skills/tools ──
            system_prompt = _build_system_prompt(from_number, contact_name, usuario_sri)
            # session_id estable por número para mantener contexto entre mensajes
            session_id = f"whatsapp-{from_number}"

            try:
                turn = await asyncio.wait_for(
                    runner.run(
                        session_id=session_id,
                        user_message=mensaje_orquestador,
                        system_prompt=system_prompt,
                    ),
                    timeout=120,
                )
                # Extraer texto de la respuesta del AgentTurn
                if turn and hasattr(turn, "messages") and turn.messages:
                    partes = []
                    for msg in turn.messages:
                        contenido = getattr(msg, "content", None)
                        if contenido:
                            if isinstance(contenido, str):
                                partes.append(contenido)
                            elif isinstance(contenido, list):
                                for bloque in contenido:
                                    if isinstance(bloque, str):
                                        partes.append(bloque)
                                    elif hasattr(bloque, "text"):
                                        partes.append(bloque.text)
                    respuesta = "\n".join(p for p in partes if p).strip() or None
                elif turn and hasattr(turn, "output"):
                    respuesta = str(turn.output).strip() or None

                if not respuesta:
                    logger.warning(
                        "AgentRunner devolvió turno vacío para %s — usando CLI de respaldo",
                        numero_log,
                    )
            except asyncio.TimeoutError:
                logger.warning(
                    "AgentRunner timeout (120s) para %s — usando CLI de respaldo",
                    numero_log,
                )
            except Exception as exc:
                logger.error(
                    "AgentRunner error para %s: %s — usando CLI de respaldo",
                    numero_log,
                    exc,
                )

        if respuesta is None:
            # ── Ruta de respaldo: CLI de SOMER via subprocess ─────────────────
            python_bin = "/var/www/somer/venv/bin/python3"
            env_path = "/root/.somer/.env"
            # Para el CLI de respaldo solo usamos texto (no media en base64)
            msg_cli = text if message_type == "text" else (
                f"[{message_type} recibido: {text or 'sin caption'}]"
            )
            script = (
                f"set -a; [ -f {env_path} ] && . {env_path}; set +a; "
                f"cd /var/www/somer && {python_bin} entry.py agent run "
                f"{__import__('shlex').quote(msg_cli)}"
            )

            proc = await asyncio.create_subprocess_shell(
                script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=120
                )
            except asyncio.TimeoutError:
                proc.kill()
                await _send_reply(
                    from_number,
                    "Lo siento, tuve un problema procesando tu mensaje. Por favor intenta de nuevo.",
                )
                return

            if proc.returncode == 0 and stdout:
                respuesta = stdout.decode("utf-8").strip() or None

            if not respuesta:
                err = (
                    stderr.decode("utf-8", errors="replace")[:300]
                    if stderr
                    else "sin detalle"
                )
                logger.error(
                    "CLI SOMER error (rc=%s) para %s: %s",
                    proc.returncode,
                    numero_log,
                    err,
                )
                await _send_reply(
                    from_number,
                    "Lo siento, tuve un problema procesando tu mensaje. Por favor intenta de nuevo.",
                )
                return

        # Enviar respuesta, registrar en log de actividad y guardar en historial
        await _send_reply(from_number, respuesta)
        _log_out(from_number, respuesta)
        save_message(from_number, data_dir, "assistant", respuesta)

    except asyncio.TimeoutError:
        logger.error("Timeout global procesando mensaje de %s", numero_log)
        await _send_reply(
            from_number,
            "Lo siento, tuve un problema procesando tu mensaje. Por favor intenta de nuevo.",
        )
    except Exception as exc:
        logger.error("Error procesando mensaje de %s: %s", numero_log, exc)
        await _send_reply(
            from_number,
            "Lo siento, tuve un problema procesando tu mensaje. Por favor intenta de nuevo.",
        )


# ── Worker loop ───────────────────────────────────────────────────────────────


async def start_worker() -> None:
    """Consume indefinidamente la cola de mensajes entrantes de WhatsApp.

    Para cada mensaje obtiene (o crea bajo demanda) el runner específico del
    usuario, luego delega en `_procesar_mensaje`. Los runners se crean la
    primera vez que se recibe un mensaje del usuario y se reutilizan para
    mensajes posteriores del mismo número.

    Las excepciones en `_procesar_mensaje` son capturadas internamente; este
    loop solo captura las excepciones inesperadas del propio bucle para
    evitar que el worker muera silenciosamente.
    """
    from channels.whatsapp.handler import get_incoming_queue

    queue = get_incoming_queue()
    logger.info("WhatsApp SOMER worker multi-usuario iniciado — esperando mensajes...")

    while True:
        try:
            item: Dict[str, Any] = await queue.get()
        except asyncio.CancelledError:
            logger.info("WhatsApp SOMER worker cancelado — deteniendo")
            break
        except Exception as exc:
            logger.error("Error inesperado en queue.get(): %s", exc)
            await asyncio.sleep(1)
            continue

        try:
            from_number = item.get("from_number", "")
            runner = await _get_or_create_runner(from_number)
            await _procesar_mensaje(runner, item)
        except Exception as exc:
            logger.error("Error no capturado en _procesar_mensaje: %s", exc)
        finally:
            queue.task_done()


async def run_worker_loop() -> None:
    """Punto de entrada principal del worker multi-usuario.

    A diferencia de la versión anterior, NO pre-construye un runner global.
    Los runners se crean bajo demanda en `_get_or_create_runner()` cuando
    llega el primer mensaje de cada usuario.

    Reinicia el worker automáticamente si ocurre un error fatal, con una
    pausa de 10 segundos entre intentos.

    Uso típico desde server.py o cualquier punto de arranque del sistema:

        asyncio.create_task(run_worker_loop())
    """
    logger.info("Iniciando worker multi-usuario WhatsApp.")
    while True:
        try:
            await start_worker()
        except asyncio.CancelledError:
            logger.info("run_worker_loop cancelado — saliendo")
            break
        except Exception as exc:
            logger.error(
                "Error fatal en start_worker: %s — reiniciando en 10s", exc
            )
            await asyncio.sleep(10)
