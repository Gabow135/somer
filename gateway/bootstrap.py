"""Bootstrap del gateway — inicializa providers, canales y agent runner.

Este módulo conecta todo el pipeline:
  Config → Providers → Skills → Memory → Agent Runner → Channels → Message Routing

Portado de OpenClaw: server-startup.ts, server-channels.ts, attempt.ts.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid as _uuid
from typing import Any, Dict, List, Optional

from rich.console import Console

from agents.tools.user_context import set_current_user_id
from channels.plugin import ChannelPlugin
from channels.registry import ChannelRegistry
from config.loader import load_config
from config.runtime_overrides import apply_env_overrides
from config.schema import SomerConfig
from gateway.server import GatewayServer
from providers.base import BaseProvider
from providers.registry import ProviderRegistry
from shared.types import IncomingMessage, OutgoingMessage, ResponseType

logger = logging.getLogger(__name__)
console = Console()


class GatewayBootstrap:
    """Orquesta el arranque completo del gateway con canales y agente.

    Flujo:
    1. Carga config
    2. Inicializa providers LLM
    3. Carga skills
    4. Inicializa memoria
    5. Crea agent runner
    6. Inicializa y arranca canales
    7. Conecta routing: canal → contexto → agente → respuesta → canal
    8. Inicia gateway WebSocket
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 18789,
        config: Optional[SomerConfig] = None,
    ):
        self.host = host
        self.port = port
        self._config = config
        self._gateway: Optional[GatewayServer] = None
        self._provider_registry = ProviderRegistry()
        self._channel_registry = ChannelRegistry()
        self._runner: Any = None  # AgentRunner, lazy
        self._credential_interceptor: Any = None
        self._heartbeat: Any = None
        self._cron_scheduler: Any = None  # CronScheduler, lazy
        self._skill_registry: Any = None  # SkillRegistry, lazy
        self._memory_manager: Any = None  # MemoryManager, lazy
        self._persistence: Any = None  # SessionPersistence, lazy
        self._workspace_context: Any = None  # WorkspaceContext, cached
        self._episodic_memory: Any = None  # EpisodicMemory, lazy
        self._message_bus: Any = None  # AgentMessageBus, lazy
        self._planning_engine: Any = None  # PlanningEngine, lazy
        self._alert_manager: Any = None  # ProactiveAlertManager, lazy
        self._task_manager: Any = None  # AsyncTaskManager, lazy

        # Debounce: agrupa mensajes rápidos del mismo usuario
        self._debounce_buffers: Dict[str, List[IncomingMessage]] = {}
        self._debounce_timers: Dict[str, asyncio.TimerHandle] = {}
        self._debounce_locks: Dict[str, asyncio.Lock] = {}
        self._processing_sessions: Dict[str, bool] = {}

        # Concurrencia: semáforos por usuario para procesar múltiples mensajes
        self._user_semaphores: Dict[str, asyncio.Semaphore] = {}
        self._active_tasks: Dict[str, List[asyncio.Task]] = {}  # type: ignore[type-arg]

    async def start(self) -> None:
        """Arranca todo el sistema."""
        # 0. Cargar ~/.somer/.env (API keys, tokens guardados por onboard)
        from infra.env import load_somer_env
        loaded = load_somer_env()
        if loaded:
            console.print(f"[dim]Cargadas {len(loaded)} variables desde ~/.somer/.env[/dim]")

        # 1. Config
        if not self._config:
            self._config = apply_env_overrides(load_config())
        console.print(f"[dim]Config cargada: {len(self._config.providers)} providers, "
                      f"{len(self._config.channels.entries)} canales[/dim]")

        # 2. Providers
        await self._setup_providers()

        # 3. Skills
        self._setup_skills()

        # 4. Memoria
        self._setup_memory()

        # 5. Persistencia de sesiones
        from sessions.persistence import SessionPersistence
        self._persistence = SessionPersistence()
        console.print("  [green]✓[/green] Persistencia de sesiones")

        # 6. Agent runner
        self._setup_agent_runner()

        # 6. Channels
        await self._setup_channels()

        # 7. Gateway WebSocket
        await self._setup_gateway()

        # 8. Arrancar canales
        started = await self._start_channels()
        console.print(f"[green]{started} canal(es) iniciado(s)[/green]")

        # 9. Cron scheduler
        await self._setup_cron()

        # 10. Heartbeat runner
        await self._setup_heartbeat()

        # 11. Cargar workspace context (SOUL.md, IDENTITY.md, USER.md, etc.)
        self._setup_workspace_context()

        # 12. Message bus inter-agente
        self._setup_message_bus()

        # 13. Planning engine
        self._setup_planning_engine()

        # 14. Proactive alerts
        await self._setup_proactive_alerts()

        # 15. Task queue
        await self._setup_task_queue()

    async def stop(self) -> None:
        """Detiene todo."""
        console.print("[yellow]Deteniendo servicios...[/yellow]")
        if self._task_manager:
            await self._task_manager.stop()
        if self._alert_manager:
            await self._alert_manager.stop()
        if self._heartbeat:
            await self._heartbeat.stop()
        if self._cron_scheduler:
            await self._cron_scheduler.stop()
        await self._channel_registry.stop_all()
        if self._gateway:
            await self._gateway.stop()
        if self._episodic_memory:
            self._episodic_memory.close()
        console.print("[yellow]Gateway detenido[/yellow]")

    # ── Providers ─────────────────────────────────────────────────

    async def _setup_providers(self) -> None:
        """Inicializa providers desde config."""
        assert self._config is not None
        count = 0

        for provider_id, settings in self._config.providers.items():
            if not settings.enabled:
                continue

            provider = self._create_provider(provider_id, settings)
            if provider:
                # Ollama necesita discovery async antes de registrar
                if hasattr(provider, "discover_models"):
                    await provider.discover_models()
                self._provider_registry.register(provider)
                count += 1
                console.print(f"  [green]✓[/green] Provider: {provider_id}")

        if count == 0:
            console.print("[yellow]  No hay providers configurados. "
                          "Ejecuta: somer onboard[/yellow]")

    def _create_provider(
        self, provider_id: str, settings: Any
    ) -> Optional[BaseProvider]:
        """Crea una instancia de provider según el ID."""
        api_key = self._resolve_api_key(settings.auth)

        try:
            if provider_id == "anthropic":
                from providers.anthropic import AnthropicProvider
                return AnthropicProvider(api_key=api_key)
            elif provider_id == "openai":
                from providers.openai import OpenAIProvider
                return OpenAIProvider(api_key=api_key)
            elif provider_id == "deepseek":
                from providers.deepseek import DeepSeekProvider
                return DeepSeekProvider(api_key=api_key)
            elif provider_id == "google":
                from providers.google import GoogleProvider
                return GoogleProvider(api_key=api_key)
            elif provider_id == "ollama":
                from providers.ollama import OllamaProvider
                base_url = settings.auth.base_url or "http://127.0.0.1:11434"
                p = OllamaProvider(base_url=base_url)
                return p
            elif provider_id == "groq":
                from providers.groq import GroqProvider
                return GroqProvider(api_key=api_key)
            elif provider_id == "xai":
                from providers.xai import XAIProvider
                return XAIProvider(api_key=api_key)
            elif provider_id == "openrouter":
                from providers.openrouter import OpenRouterProvider
                return OpenRouterProvider(api_key=api_key)
            elif provider_id == "mistral":
                from providers.mistral import MistralProvider
                return MistralProvider(api_key=api_key)
            elif provider_id == "together":
                from providers.together import TogetherProvider
                return TogetherProvider(api_key=api_key)
            elif provider_id == "perplexity":
                from providers.perplexity import PerplexityProvider
                return PerplexityProvider(api_key=api_key)
            elif provider_id == "claude-code":
                from providers.claude_code import ClaudeCodeProvider
                return ClaudeCodeProvider()
            else:
                logger.warning("Provider desconocido: %s", provider_id)
                return None
        except Exception as exc:
            logger.warning("Error creando provider %s: %s", provider_id, exc)
            return None

    @staticmethod
    def _resolve_api_key(auth: Any) -> Optional[str]:
        """Resuelve API key desde env var o valor directo."""
        if auth.api_key:
            return auth.api_key
        if auth.api_key_env:
            return os.environ.get(auth.api_key_env)
        return None

    # ── Agent Runner ──────────────────────────────────────────────

    def _setup_agent_runner(self) -> None:
        """Crea el agent runner con tools built-in."""
        assert self._config is not None
        from agents.runner import AgentRunner
        from agents.tools.builtins import register_builtins
        from agents.tools.registry import ToolRegistry

        # Crear registry y registrar tools built-in
        tool_registry = ToolRegistry()
        register_builtins(tool_registry)

        # Registrar report tools
        from agents.tools.report_tools import register_report_tools
        from reports.manager import ReportManager

        self._report_manager = ReportManager()
        register_report_tools(
            tool_registry,
            channel_plugins=self._channel_registry,
            report_manager=self._report_manager,
            base_url=f"http://{self.host}:{self.port}",
        )

        # Registrar delegation tools (orquestador → claude-code)
        if self._config.agents.delegation.orchestrator_mode:
            from agents.tools.delegation_tools import register_delegation_tools
            register_delegation_tools(tool_registry)

        # Registrar SQL tools
        from agents.tools.sql_tools import register_sql_tools
        register_sql_tools(tool_registry)

        # Registrar shell tools
        from agents.tools.shell_tools import register_shell_tools
        register_shell_tools(tool_registry)

        # Registrar code interpreter
        from agents.tools.code_interpreter_tools import register_code_interpreter_tools
        register_code_interpreter_tools(tool_registry)

        # Registrar knowledge graph tools
        if self._config.knowledge_graph.enabled:
            from agents.tools.knowledge_graph_tools import register_knowledge_graph_tools
            register_knowledge_graph_tools(tool_registry)

        # Registrar agent tools (research, data_analyst, planning, messaging, episodic)
        from agents.tools.agent_tools import register_agent_tools
        register_agent_tools(tool_registry)

        # Registrar cybersecurity tools (pentesting, scanners, exploits, evidence, OSINT, network, malware, compliance)
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

        # Registrar business tools (CRM, finance, meetings)
        try:
            from agents.tools.business_tools import register_business_tools
            register_business_tools(tool_registry)
        except Exception as exc:
            logger.warning("Business tools no disponibles: %s", exc)

        # Registrar personal tools (bookmarks, daily briefing)
        try:
            from agents.tools.personal_tools import register_personal_tools
            register_personal_tools(tool_registry)
        except Exception as exc:
            logger.warning("Personal tools no disponibles: %s", exc)

        # Registrar self-improve tools (auto-mejora, credenciales, restart)
        try:
            from self_improve.tools import register_self_improve_tools
            register_self_improve_tools(tool_registry)
        except Exception as exc:
            logger.warning("Self-improve tools no disponibles: %s", exc)

        self._runner = AgentRunner(
            provider_registry=self._provider_registry,
            default_model=self._config.default_model,
            tool_registry=tool_registry,
            timeout_secs=0,  # Sin timeout — el agente trabaja hasta terminar
        )

        # Cadena de fallback configurada
        self._fallback_models: list = [
            (pair[0], pair[1])
            for pair in self._config.fallback_models
            if len(pair) >= 2
        ] or None

        fb_label = ""
        if self._fallback_models:
            fb_label = f", fallback: {' → '.join(f'{p}/{m}' for p, m in self._fallback_models)}"
        console.print(
            f"  [green]✓[/green] Agent runner "
            f"(modelo: {self._config.default_model}{fb_label}, "
            f"tools: {len(tool_registry.tool_names)})"
        )

    # ── Channels ──────────────────────────────────────────────────

    async def _setup_channels(self) -> None:
        """Inicializa canales desde config."""
        assert self._config is not None

        for channel_id, ch_config in self._config.channels.entries.items():
            if not ch_config.enabled:
                continue

            plugin = self._create_channel_plugin(channel_id)
            if not plugin:
                continue

            try:
                # Inyectar políticas de acceso al config del plugin
                plugin_config = dict(ch_config.config)
                if ch_config.dm_policy:
                    plugin_config["dm_policy"] = ch_config.dm_policy
                if ch_config.allow_from is not None:
                    plugin_config["allow_from"] = ch_config.allow_from

                await plugin.setup(plugin_config)
                # Registrar el callback de routing
                plugin.on_message(self._handle_incoming_message)
                self._channel_registry.register(plugin)
                console.print(f"  [green]✓[/green] Canal: {channel_id}")
            except Exception as exc:
                console.print(f"  [red]✗[/red] Canal {channel_id}: {exc}")

    def _create_channel_plugin(self, channel_id: str) -> Optional[ChannelPlugin]:
        """Crea instancia de un channel plugin."""
        try:
            if channel_id == "telegram":
                from channels.telegram.plugin import TelegramPlugin
                return TelegramPlugin()
            elif channel_id == "discord":
                from channels.discord.plugin import DiscordPlugin
                return DiscordPlugin()
            elif channel_id == "slack":
                from channels.slack.plugin import SlackPlugin
                return SlackPlugin()
            elif channel_id == "webchat":
                from channels.webchat.plugin import WebChatPlugin
                return WebChatPlugin()
            elif channel_id == "whatsapp":
                from channels.whatsapp.plugin import WhatsAppPlugin
                return WhatsAppPlugin()
            else:
                logger.warning("Canal no soportado para gateway: %s", channel_id)
                return None
        except Exception as exc:
            logger.warning("Error creando canal %s: %s", channel_id, exc)
            return None

    async def _start_channels(self) -> int:
        """Arranca todos los canales registrados."""
        started = 0
        for plugin in self._channel_registry.list_plugins():
            try:
                await plugin.start()
                started += 1
                logger.info("Canal %s iniciado", plugin.id)
            except Exception as exc:
                console.print(f"  [red]Error iniciando {plugin.id}: {exc}[/red]")
                logger.exception("Error iniciando canal %s", plugin.id)
        return started

    # ── Skills ────────────────────────────────────────────────────

    def _setup_skills(self) -> None:
        """Carga skills desde los directorios configurados."""
        try:
            from skills.loader import discover_skills, load_skill_file
            from skills.registry import SkillRegistry

            self._skill_registry = SkillRegistry()

            # Directorios de skills: bundled + config
            skill_dirs = ["skills"]
            if self._config and hasattr(self._config, "skills"):
                extra = getattr(self._config.skills, "dirs", [])
                if extra:
                    skill_dirs.extend(extra)

            paths = discover_skills(skill_dirs)
            loaded = 0
            for path in paths:
                try:
                    meta = load_skill_file(path)
                    self._skill_registry.register(meta)
                    loaded += 1
                except Exception as exc:
                    logger.debug("Error cargando skill %s: %s", path, exc)

            console.print(f"  [green]✓[/green] Skills: {loaded} cargados")
        except Exception as exc:
            logger.warning("Error inicializando skills: %s", exc)

    # ── Memoria ──────────────────────────────────────────────────

    def _setup_memory(self) -> None:
        """Inicializa el memory manager y la memoria episódica."""
        try:
            from memory.manager import MemoryManager
            self._memory_manager = MemoryManager()
            console.print("  [green]✓[/green] Memoria híbrida")
        except Exception as exc:
            logger.warning("Error inicializando memoria: %s", exc)

        # Memoria episódica
        if self._config and self._config.episodic_memory.enabled:
            try:
                from memory.episodic import EpisodicMemory
                db_path = self._config.episodic_memory.database_path
                self._episodic_memory = EpisodicMemory(
                    db_path=db_path,
                ) if db_path else EpisodicMemory()
                console.print("  [green]✓[/green] Memoria episódica")
            except Exception as exc:
                logger.warning("Error inicializando memoria episódica: %s", exc)

    async def _query_memory(self, query: str) -> List[Dict[str, Any]]:
        """Busca en memoria entradas relevantes para el query."""
        if not self._memory_manager:
            return []
        try:
            results = await self._memory_manager.search(query, limit=5)
            return [
                {
                    "content": entry.content,
                    "source": entry.source.value if hasattr(entry.source, "value") else str(entry.source),
                }
                for entry in results
            ]
        except Exception as exc:
            logger.warning("Error consultando memoria: %s", exc)
            return []

    # ── Cron Scheduler ──────────────────────────────────────────────

    async def _setup_cron(self) -> None:
        """Inicializa y arranca el cron scheduler si está habilitado."""
        assert self._config is not None
        if not self._config.cron.enabled:
            return

        from cron.scheduler import CronScheduler

        self._cron_scheduler = CronScheduler(
            max_concurrent_jobs=self._config.cron.max_concurrent_runs,
        )
        await self._cron_scheduler.start()
        console.print(
            f"  [green]\u2713[/green] Cron scheduler "
            f"(max_concurrent={self._config.cron.max_concurrent_runs})"
        )

    @property
    def cron_scheduler(self) -> Any:
        """Acceso público al scheduler para registrar jobs externos."""
        return self._cron_scheduler

    # ── Heartbeat ──────────────────────────────────────────────────

    async def _setup_heartbeat(self) -> None:
        """Inicializa y arranca el heartbeat runner si está habilitado."""
        assert self._config is not None
        if not self._config.heartbeat.enabled:
            return

        from infra.heartbeat import HeartbeatRunner

        self._heartbeat = HeartbeatRunner(
            runner=self._runner,
            channel_registry=self._channel_registry,
            config=self._config,
        )
        self._heartbeat.set_system_prompt(self._build_full_prompt())
        await self._heartbeat.start()
        console.print(
            f"  [green]✓[/green] Heartbeat (cada {self._config.heartbeat.every}s "
            f"→ {self._config.heartbeat.target})"
        )

    # ── Message Bus ──────────────────────────────────────────────────

    def _setup_message_bus(self) -> None:
        """Inicializa el bus de mensajes inter-agente."""
        from agents.messaging import AgentMessageBus, set_message_bus
        self._message_bus = AgentMessageBus()
        set_message_bus(self._message_bus)
        console.print("  [green]✓[/green] Message bus inter-agente")

    # ── Planning Engine ──────────────────────────────────────────────

    def _setup_planning_engine(self) -> None:
        """Inicializa el planning engine."""
        assert self._config is not None
        if not self._config.planning.enabled:
            return

        from agents.planning import PlanningEngine
        self._planning_engine = PlanningEngine(
            max_concurrent_steps=self._config.planning.max_concurrent_steps,
        )
        console.print("  [green]✓[/green] Planning engine")

    # ── Proactive Alerts ─────────────────────────────────────────────

    async def _setup_proactive_alerts(self) -> None:
        """Inicializa el sistema de alertas proactivas si está habilitado."""
        assert self._config is not None
        if not self._config.proactive_alerts.enabled:
            return

        from agents.proactive_alerts import ProactiveAlertManager

        # Función de notificación por canal
        async def _notify(alert: Any, channel_id: str) -> bool:
            plugin = self._channel_registry.get(channel_id)
            if not plugin:
                return False
            targets = self._config.proactive_alerts.default_notify_channels
            target_chat = ""
            if self._config.heartbeat.target_chat_id:
                target_chat = self._config.heartbeat.target_chat_id
            if target_chat:
                await plugin.send_message(target_chat, alert.format_notification())
                return True
            return False

        self._alert_manager = ProactiveAlertManager(notify_func=_notify)

        # Registrar monitor de disco built-in
        disk_monitor = ProactiveAlertManager.create_disk_monitor()
        self._alert_manager.add_monitor(disk_monitor)

        await self._alert_manager.start()
        console.print(
            f"  [green]✓[/green] Proactive alerts "
            f"({len(self._config.proactive_alerts.rules)} reglas)"
        )

    # ── Task Queue ─────────────────────────────────────────────────

    async def _setup_task_queue(self) -> None:
        """Inicializa el task queue con workers y handlers built-in."""
        try:
            from tasks.manager import AsyncTaskManager
            from tasks.handlers import TaskHandlers
            from tasks.tools import register_task_tools

            self._task_manager = AsyncTaskManager("redis://localhost:6379")

            # Registrar handlers built-in
            if self._runner:
                tool_reg = getattr(self._runner, "_tool_registry", None)
                handlers = TaskHandlers(self._runner, tool_reg)
                self._task_manager.register_handler("agent_run", handlers.handle_agent_run)
                self._task_manager.register_handler("tool_call", handlers.handle_tool_call)
                self._task_manager.register_handler("custom", handlers.handle_custom)

                # Registrar tools en el registry del agente
                if tool_reg:
                    register_task_tools(tool_reg, self._task_manager)

            # Callback de finalización: notificar al usuario por su canal
            async def _on_task_complete(task: Any, result: str = None, error: str = None) -> None:
                channel_id = getattr(task, "channel", "")
                user_id = getattr(task, "user_id", "")
                if not channel_id or not user_id:
                    return
                plugin = self._channel_registry.get(channel_id)
                if not plugin:
                    return
                title = getattr(task, "title", "Tarea")
                if error:
                    msg = "Task '{}' failed: {}".format(title, error)
                else:
                    # Truncate long results
                    display = result if result and len(result) < 500 else (result[:497] + "..." if result else "No result")
                    msg = "Task '{}' completed:\n{}".format(title, display)
                try:
                    await plugin.send_message(user_id, msg)
                except Exception as exc:
                    logger.warning("Error notificando tarea completada: %s", exc)

            self._task_manager.set_completion_callback(_on_task_complete)

            # Arrancar workers (2 por defecto)
            await self._task_manager.start(num_workers=2)
            console.print("  [green]\u2713[/green] Task queue (2 workers)")
        except Exception as exc:
            logger.warning("Task queue no disponible: %s", exc)

    # ── Credential Interceptor ─────────────────────────────────────

    def _ensure_interceptor(self) -> Any:
        """Inicializa el interceptor de credenciales (lazy)."""
        if self._credential_interceptor is None:
            from agents.credential_interceptor import CredentialInterceptor
            self._credential_interceptor = CredentialInterceptor()
        return self._credential_interceptor

    # ── Message Routing ───────────────────────────────────────────

    def _get_debounce_ms(self) -> int:
        """Retorna el debounce en ms desde la config (default 1500ms)."""
        if self._config:
            val = self._config.messages.queue.debounce_ms
            # Si el usuario dejó 0, usar un default razonable para chat
            return val if val > 0 else 1500
        return 1500

    def _get_user_semaphore(self, session_key: str) -> asyncio.Semaphore:
        """Obtiene o crea un semáforo de concurrencia para el usuario."""
        if session_key not in self._user_semaphores:
            max_concurrent = 5
            try:
                if self._config and self._config.messages:
                    max_concurrent = self._config.messages.queue.max_concurrent_per_user
            except Exception:
                pass
            self._user_semaphores[session_key] = asyncio.Semaphore(max_concurrent)
        return self._user_semaphores[session_key]

    async def _handle_incoming_message(self, message: IncomingMessage) -> None:
        """Callback: recibe mensaje y lo despacha concurrentemente.

        Cada mensaje se procesa de forma independiente como una tarea
        asyncio separada, permitiendo que múltiples mensajes del mismo
        usuario se procesen en paralelo (limitado por semáforo).

        Un debounce corto (configurable) agrupa mensajes que llegan
        en ráfaga (<1.5s) como antes. Mensajes separados por más tiempo
        se procesan concurrentemente.
        """
        chat_id = message.metadata.get("chat_id", message.channel_user_id)
        channel_id = message.channel.value
        session_key = f"{channel_id}_{chat_id}"
        msg_id = message.metadata.get("message_id")

        logger.info(
            "Mensaje de %s/%s (msg_id=%s): %s",
            channel_id, chat_id, msg_id,
            message.content[:80],
        )

        # Inicializar lock para debounce de esta sesión si no existe
        if session_key not in self._debounce_locks:
            self._debounce_locks[session_key] = asyncio.Lock()

        # Agregar al buffer de debounce
        if session_key not in self._debounce_buffers:
            self._debounce_buffers[session_key] = []
        self._debounce_buffers[session_key].append(message)

        # Cancelar timer anterior si existe (debounce de ráfaga)
        old_timer = self._debounce_timers.pop(session_key, None)
        if old_timer is not None:
            old_timer.cancel()

        # Programar flush tras debounce — siempre, sin importar si hay
        # mensajes en proceso (ahora son concurrentes)
        debounce_secs = self._get_debounce_ms() / 1000.0
        loop = asyncio.get_running_loop()
        self._debounce_timers[session_key] = loop.call_later(
            debounce_secs,
            lambda sk=session_key: asyncio.ensure_future(
                self._flush_debounce(sk)
            ),
        )

    async def _flush_debounce(self, session_key: str) -> None:
        """Vacía el buffer de debounce y lanza procesamiento concurrente."""
        self._debounce_timers.pop(session_key, None)

        async with self._debounce_locks[session_key]:
            messages = self._debounce_buffers.pop(session_key, [])
            if not messages:
                return

        # Lanzar como tarea concurrente con control de semáforo
        task = asyncio.create_task(
            self._process_concurrent(session_key, messages)
        )

        # Registrar tarea activa para cleanup
        if session_key not in self._active_tasks:
            self._active_tasks[session_key] = []
        self._active_tasks[session_key].append(task)

        # Limpiar tareas completadas
        self._active_tasks[session_key] = [
            t for t in self._active_tasks[session_key] if not t.done()
        ]

    async def _process_concurrent(
        self, session_key: str, messages: List[IncomingMessage]
    ) -> None:
        """Procesa mensajes bajo el semáforo de concurrencia del usuario."""
        sem = self._get_user_semaphore(session_key)
        async with sem:
            await self._process_session_messages(session_key, messages)

    async def _process_session_messages(
        self,
        session_key: str,
        messages: List[IncomingMessage],
    ) -> None:
        """Procesa uno o más mensajes agrupados de una sesión.

        Pipeline completo (portado de OpenClaw attempt.ts):
        1. Credential interceptor (antes del LLM)
        2. Concatenar mensajes si hay varios (solo los del mismo debounce batch)
        3. Cargar historial de conversación (JSONL) — snapshot al momento
        4. Consultar memoria relevante
        5. Construir system prompt
        6. Ejecutar agente con session_id único por tarea concurrente
        7. Persistir turno en la sesión principal
        8. Enviar respuesta al canal con reply_to_message_id
        """
        if not messages:
            return

        first = messages[0]
        set_current_user_id(first.channel_user_id)
        chat_id = first.metadata.get("chat_id", first.channel_user_id)
        channel_id = first.channel.value
        username = first.metadata.get("username", "")
        # message_id del primer mensaje para reply_to
        reply_to_msg_id = first.metadata.get("message_id")

        if not self._runner:
            logger.error("Agent runner no disponible")
            try:
                plugin = self._channel_registry.get(channel_id)
                if plugin:
                    await plugin.send_message(
                        chat_id, "Error interno: el agente no está disponible.",
                        reply_to_message_id=reply_to_msg_id,
                    )
            except Exception:
                pass
            return

        # Concatenar contenido de múltiples mensajes (debounce batch)
        if len(messages) == 1:
            combined_content = messages[0].content
        else:
            combined_content = "\n".join(m.content for m in messages)
            logger.info(
                "Agrupados %d mensajes de %s/%s en un solo turno",
                len(messages), channel_id, chat_id,
            )

        # 1. Interceptor de credenciales (antes del LLM)
        try:
            interceptor = self._ensure_interceptor()
            result = await interceptor.intercept(combined_content)
            if result.intercepted:
                plugin = self._channel_registry.get(channel_id)
                if plugin:
                    await plugin.send_message(
                        chat_id, result.response,
                        reply_to_message_id=reply_to_msg_id,
                    )
                    logger.info(
                        "Credencial interceptada (%s) para %s/%s",
                        result.service_id, channel_id, chat_id,
                    )
                return
        except Exception as exc:
            logger.warning("Error en credential interceptor: %s", exc)

        # Typing continuo: enviar "escribiendo..." cada 4s durante todo el procesamiento
        typing_stop = asyncio.Event()

        async def _keep_typing() -> None:
            while not typing_stop.is_set():
                try:
                    p = self._channel_registry.get(channel_id)
                    if p:
                        await p.send_typing(chat_id)
                except Exception:
                    pass
                try:
                    await asyncio.wait_for(typing_stop.wait(), timeout=4.0)
                except asyncio.TimeoutError:
                    pass

        typing_task = asyncio.create_task(_keep_typing())

        try:
            # 2. Cargar historial de conversación desde disco (snapshot)
            history_context = self._load_session_history(session_key)
            logger.info(
                "[MSG] Historial cargado para %s: %d mensajes",
                session_key, len(history_context),
            )
            # Log de tool calls/errores en el historial
            for i, hmsg in enumerate(history_context):
                role = hmsg.get("role", "?")
                if hmsg.get("tool_calls"):
                    tc_names = [tc.get("name", "?") for tc in hmsg["tool_calls"]]
                    logger.info("[MSG] Historial[%d] %s: tool_calls=%s", i, role, tc_names)
                elif role == "tool":
                    logger.info(
                        "[MSG] Historial[%d] tool: id=%s, content=%s",
                        i, hmsg.get("tool_call_id", "?"), hmsg.get("content", "")[:100],
                    )

            # 3. Consultar memoria relevante para el query
            memory_context = await self._query_memory(combined_content)

            # 4. Construir system prompt completo
            system_prompt = self._build_full_prompt(
                channel_id=channel_id,
                user_name=username,
                memory_context=memory_context,
            )
            logger.info(
                "[MSG] System prompt: %d chars, memory_items=%d",
                len(system_prompt),
                len(memory_context) if memory_context else 0,
            )

            # 5. Ejecutar agente — usar session_id con sufijo único para
            #    aislar ejecuciones concurrentes y evitar conflictos de contexto
            run_id = f"{session_key}__run_{_uuid.uuid4().hex[:8]}"
            logger.info(
                "[MSG] Ejecutando agente para %s/%s (run=%s): '%s'",
                channel_id, chat_id, run_id, combined_content[:100],
            )
            turn = await self._runner.run(
                session_id=run_id,
                user_message=combined_content,
                system_prompt=system_prompt,
                extra_context=history_context if history_context else None,
                fallback_models=self._fallback_models,
            )
            logger.info(
                "[MSG] Turno completado (run=%s): %d mensajes, %d tokens",
                run_id, len(turn.messages), turn.token_count,
            )

            # 6. Persistir todos los mensajes del turno en la sesión principal
            self._persist_turn(session_key, turn)

            # 7. Extraer respuesta (última del asistente)
            response_text = ""
            for msg in reversed(turn.messages):
                if msg.role.value == "assistant" and msg.content:
                    response_text = msg.content
                    break

            logger.info("[MSG] Respuesta raw (%d chars): %s", len(response_text), response_text[:200])

            # Limpiar tags de razonamiento interno (<think>...</think>)
            # Separar por bloques <think>...</think> y recoger solo el texto visible;
            # eliminar duplicados consecutivos (modelo repite texto entre bloques)
            segments = re.split(r"<think>.*?</think>\s*", response_text, flags=re.DOTALL)
            clean_segments: list = []
            for seg in segments:
                seg = seg.strip()
                # DeepSeek omite <think> de apertura: descartar todo antes de </think>
                if "</think>" in seg:
                    seg = seg.rsplit("</think>", 1)[-1].strip()
                if seg and (not clean_segments or seg != clean_segments[-1]):
                    clean_segments.append(seg)
            response_text = "\n\n".join(clean_segments).strip()

            # Deduplicar texto repetido (DeepSeek a veces genera el mismo texto 2 veces)
            response_text = self._deduplicate_response(response_text)

            if not response_text:
                response_text = "No pude generar una respuesta."

            logger.info("[MSG] Respuesta limpia (%d chars): %s", len(response_text), response_text[:200])

            # 8. Enviar respuesta de vuelta al canal (con reply_to)
            plugin = self._channel_registry.get(channel_id)
            if plugin:
                await plugin.send_message(
                    chat_id, response_text,
                    reply_to_message_id=reply_to_msg_id,
                )
                logger.info(
                    "Respuesta enviada a %s/%s (reply_to=%s)",
                    channel_id, chat_id, reply_to_msg_id,
                )

                # 8b. Auto-delivery: enviar archivos generados por tools
                report_files = self._extract_report_files(turn)
                for file_info in report_files:
                    try:
                        sent = await plugin.send_file(
                            target=chat_id,
                            file_path=file_info["file_path"],
                            filename=file_info.get("filename"),
                            caption=file_info.get("caption"),
                        )
                        if sent:
                            logger.info(
                                "Archivo enviado a %s/%s: %s",
                                channel_id, chat_id, file_info.get("filename"),
                            )
                    except Exception as file_exc:
                        logger.warning(
                            "Error enviando archivo a %s/%s: %s",
                            channel_id, chat_id, file_exc,
                        )
            else:
                logger.error("Canal %s no encontrado para responder", channel_id)

        except Exception as exc:
            logger.exception(
                "Error procesando mensaje de %s/%s (msg_id=%s)",
                channel_id, chat_id, reply_to_msg_id,
            )
            try:
                plugin = self._channel_registry.get(channel_id)
                if plugin:
                    await plugin.send_message(
                        chat_id,
                        f"Error procesando tu mensaje: {exc}",
                        reply_to_message_id=reply_to_msg_id,
                    )
            except Exception:
                pass
        finally:
            typing_stop.set()
            typing_task.cancel()
            try:
                await typing_task
            except asyncio.CancelledError:
                pass

    # ── Session History ───────────────────────────────────────────

    def _load_session_history(
        self, session_id: str
    ) -> List[Dict[str, Any]]:
        """Carga historial de conversación reciente desde disco.

        Solo carga los últimos turnos conversacionales (user + assistant text).
        NO incluye tool_calls ni tool_results en el historial — las tools
        se ejecutan fresh en cada turno. Esto evita:
        - Contexto contaminado con errores de tools anteriores
        - Error 400 de la API por tool_calls sin tool results
        - Sobrecarga de tokens por tool results enormes
        """
        if not self._persistence:
            return []

        try:
            messages = self._persistence.load_messages(session_id)
            if not messages:
                return []

            max_turns = 6
            max_chars = 8000

            history: List[Dict[str, Any]] = []
            char_count = 0
            turn_count = 0

            for msg in reversed(messages):
                role = msg.role.value

                # Solo user y assistant (sin tool interactions)
                if role not in ("user", "assistant"):
                    continue

                content = msg.content or ""
                if not content.strip():
                    continue

                if role == "user":
                    turn_count += 1
                    if turn_count > max_turns:
                        break

                char_count += len(content)
                if char_count > max_chars and turn_count > 1:
                    break

                # Solo texto plano — NO incluir tool_calls
                history.append({"role": role, "content": content})

            history.reverse()

            logger.info(
                "[HISTORY] Sesión %s: %d originales → %d en contexto (%d chars)",
                session_id, len(messages), len(history), char_count,
            )
            return history
        except Exception as exc:
            logger.warning("Error cargando historial de %s: %s", session_id, exc)
            return []

    def _persist_turn(self, session_id: str, turn: Any) -> None:
        """Persiste los mensajes de un turno a disco.

        Portado de OpenClaw: emitSessionTranscriptUpdate.
        """
        if not self._persistence:
            return

        try:
            for msg in turn.messages:
                self._persistence.save_message(session_id, msg)
            logger.debug(
                "Persistidos %d mensajes para sesión %s",
                len(turn.messages), session_id,
            )
        except Exception as exc:
            logger.warning("Error persistiendo turno de %s: %s", session_id, exc)

    # ── Workspace Context ─────────────────────────────────────────

    def _setup_workspace_context(self) -> None:
        """Carga el contexto del workspace (SOUL.md, IDENTITY.md, USER.md, etc.).

        Portado de OpenClaw: loadWorkspaceBootstrapFiles.
        """
        from pathlib import Path
        from agents.prompt_builder import load_workspace_context

        # Buscar archivos en:
        # 1. Directorio actual del proyecto
        # 2. Workspace global ~/.somer/workspace
        project_root = Path.cwd()
        workspace_dir = Path.home() / ".somer" / "workspace"

        self._workspace_context = load_workspace_context(
            workspace_dir=workspace_dir,
            project_root=project_root,
        )

        # Log de archivos cargados
        loaded = self._workspace_context.loaded_files()
        if loaded:
            file_names = ", ".join(f.name for f in loaded)
            console.print(f"  [green]✓[/green] Workspace: {file_names}")
        else:
            console.print("  [yellow]○[/yellow] Workspace: sin archivos de contexto")

    @staticmethod
    def _deduplicate_response(text: str) -> str:
        """Detecta y elimina texto duplicado consecutivo en la respuesta.

        DeepSeek a veces genera el mismo bloque de texto dos veces seguidas.
        Ejemplo: "Texto A.  Texto A." → "Texto A."
        """
        text = text.strip()
        if not text or len(text) < 40:
            return text

        # Buscar un separador donde first_half == second_half
        for sep in ("  ", "\n\n", "\n"):
            parts = text.split(sep)
            if len(parts) >= 2:
                # Intentar unir las primeras N partes y comparar con el resto
                for i in range(1, len(parts)):
                    first = sep.join(parts[:i]).strip()
                    second = sep.join(parts[i:]).strip()
                    if first and second and first == second and len(first) > 20:
                        return first

        return text

    def _build_full_prompt(
        self,
        *,
        channel_id: str = "",
        user_name: str = "",
        memory_context: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Construye el system prompt completo con todas las secciones.

        Portado de OpenClaw: buildEmbeddedSystemPrompt.
        Incluye:
        - Archivos de workspace (SOUL.md, IDENTITY.md, USER.md, TOOLS.md, BOOT.md)
        - Body completo de skills cuyas credenciales están activas
        - Tools disponibles
        - Servicios configurados
        """
        from agents.prompt_builder import build_system_prompt, detect_active_services

        # Skills habilitados
        skills: List[Any] = []
        active_skills: List[Any] = []
        if self._skill_registry:
            try:
                skills = self._skill_registry.list_enabled()
                # Filtrar skills activos:
                # - Sin credenciales requeridas → siempre activo
                # - Con credenciales → activo solo si están en entorno
                for skill in skills:
                    if not skill.body:
                        continue
                    if not skill.required_credentials:
                        # Skill sin credenciales requeridas: siempre activo
                        active_skills.append(skill)
                    else:
                        creds_ok = all(
                            os.environ.get(cred, "").strip()
                            for cred in skill.required_credentials
                        )
                        if creds_ok:
                            active_skills.append(skill)
            except Exception:
                pass

        # Tool descriptions para la sección ## Tooling del prompt
        tool_descriptions: List[Dict[str, str]] = []
        if self._runner and hasattr(self._runner, "tool_registry"):
            registry = self._runner.tool_registry
            if registry:
                for tool in registry.list_tools():
                    tool_descriptions.append({
                        "name": tool.name,
                        "description": tool.description,
                    })

        # Timezone del usuario desde config
        user_tz = ""
        if self._config:
            user_tz = getattr(self._config, "timezone", "") or ""

        # Modo orquestador: delega código a agentes especializados
        orch_mode = False
        if self._config:
            orch_mode = self._config.agents.delegation.orchestrator_mode

        return build_system_prompt(
            workspace_context=self._workspace_context,
            skills=skills,
            active_skills=active_skills,
            memory_context=memory_context,
            active_services=detect_active_services(),
            tool_descriptions=tool_descriptions if tool_descriptions else None,
            channel_id=channel_id,
            user_name=user_name,
            user_timezone=user_tz,
            orchestrator_mode=orch_mode,
        )

    # ── Gateway WebSocket ─────────────────────────────────────────

    async def _setup_gateway(self) -> None:
        """Inicializa el gateway WebSocket con métodos extendidos."""
        from gateway.methods import BUILTIN_METHODS

        self._gateway = GatewayServer(host=self.host, port=self.port)

        # Métodos built-in
        for name, handler in BUILTIN_METHODS.items():
            self._gateway.register_method(name, handler)

        # Métodos adicionales del bootstrap
        self._gateway.register_method("status", self._rpc_status)
        self._gateway.register_method("channels.list", self._rpc_channels_list)
        self._gateway.register_method("providers.list", self._rpc_providers_list)
        self._gateway.register_method("send", self._rpc_send_message)
        self._gateway.register_method("agent.run", self._rpc_agent_run)

        # Métodos cron
        self._gateway.register_method("cron.list", self._rpc_cron_list)
        self._gateway.register_method("cron.status", self._rpc_cron_status)
        self._gateway.register_method("cron.run", self._rpc_cron_run)

        # Métodos de nuevos sistemas
        self._gateway.register_method("messaging.status", self._rpc_messaging_status)
        self._gateway.register_method("alerts.status", self._rpc_alerts_status)
        self._gateway.register_method("planning.status", self._rpc_planning_status)

        # Conectar report manager para descargas HTTP
        if hasattr(self, '_report_manager') and self._report_manager:
            self._gateway.set_report_manager(self._report_manager)

        await self._gateway.start()
        console.print(f"[green]Gateway activo en ws://{self.host}:{self.port}[/green]")

    async def _rpc_status(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """RPC: estado completo del sistema."""
        return {
            "gateway": self._gateway.status() if self._gateway else {},
            "providers": self._provider_registry.provider_count,
            "channels": {
                "total": self._channel_registry.plugin_count,
                "running": len(self._channel_registry.list_running()),
            },
            "models": self._provider_registry.model_count,
        }

    async def _rpc_channels_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """RPC: lista de canales."""
        return {
            "channels": [
                {
                    "id": p.id,
                    "name": p.meta.name,
                    "running": p.is_running,
                }
                for p in self._channel_registry.list_plugins()
            ]
        }

    async def _rpc_providers_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """RPC: lista de providers."""
        return {
            "providers": [
                {
                    "id": p.provider_id,
                    "models": len(p.list_models()),
                    "available": p.auth.is_available,
                }
                for p in self._provider_registry.list_providers()
            ]
        }

    async def _rpc_send_message(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """RPC: enviar mensaje a un canal."""
        channel_id = params.get("channel", "")
        target = params.get("target", "")
        content = params.get("content", "")

        plugin = self._channel_registry.get(channel_id)
        if not plugin:
            return {"error": f"Canal no encontrado: {channel_id}"}

        await plugin.send_message(target, content)
        return {"sent": True}

    async def _rpc_agent_run(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """RPC: ejecuta el agente y opcionalmente entrega por canal."""
        message = params.get("message", "")
        if not message:
            return {"error": "Falta 'message'"}

        channel_id = params.get("channel")
        chat_id = params.get("chat_id", "")
        model = params.get("model")

        # Resolver chat_id por defecto del heartbeat config
        if channel_id and not chat_id:
            if self._config and self._config.heartbeat.target_chat_id:
                chat_id = self._config.heartbeat.target_chat_id

        if channel_id and not chat_id:
            return {"error": "Falta 'chat_id' y no hay target_chat_id en heartbeat config"}

        # Construir system prompt con contexto
        memory_context = await self._query_memory(message)
        system_prompt = self._build_full_prompt(
            channel_id=channel_id,
            memory_context=memory_context,
        )

        # Ejecutar agente
        session_key = f"rpc_agent_{_uuid.uuid4().hex[:8]}"
        try:
            turn = await self._runner.run(
                session_id=session_key,
                user_message=message,
                model=model,
                system_prompt=system_prompt,
                fallback_models=self._fallback_models,
            )
        except Exception as exc:
            return {"error": f"Error ejecutando agente: {exc}"}

        # Extraer respuesta
        response_text = ""
        for msg in reversed(turn.messages):
            if msg.role.value == "assistant" and msg.content:
                response_text = msg.content
                break

        # Limpiar tags <think>
        segments = re.split(r"<think>.*?</think>\s*", response_text, flags=re.DOTALL)
        clean_segments: list = []
        for seg in segments:
            seg = seg.strip()
            if "</think>" in seg:
                seg = seg.rsplit("</think>", 1)[-1].strip()
            if seg and (not clean_segments or seg != clean_segments[-1]):
                clean_segments.append(seg)
        response_text = "\n\n".join(clean_segments).strip()
        response_text = self._deduplicate_response(response_text)

        if not response_text:
            response_text = "No pude generar una respuesta."

        # Entregar por canal si se especificó
        delivered = False
        if channel_id:
            plugin = self._channel_registry.get(channel_id)
            if plugin:
                await plugin.send_message(chat_id, response_text)
                delivered = True

                # Auto-delivery de archivos
                report_files = self._extract_report_files(turn)
                for file_info in report_files:
                    try:
                        await plugin.send_file(
                            target=chat_id,
                            file_path=file_info["file_path"],
                            filename=file_info.get("filename"),
                            caption=file_info.get("caption"),
                        )
                    except Exception as exc:
                        logger.warning("Error enviando archivo: %s", exc)

        return {
            "response": response_text,
            "delivered": delivered,
            "channel": channel_id,
            "session_id": session_key,
            "token_count": turn.token_count,
        }

    # ── RPC: Cron ──────────────────────────────────────────────────

    async def _rpc_cron_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """RPC: lista de jobs cron."""
        if not self._cron_scheduler:
            return {"jobs": [], "enabled": False}
        jobs = self._cron_scheduler.list_jobs()
        return {
            "enabled": True,
            "jobs": [
                {
                    "id": j.id,
                    "name": j.name,
                    "expression": j.expression,
                    "enabled": j.enabled,
                    "next_run_at": j.state.next_run_at,
                    "last_run_at": j.state.last_run_at,
                    "last_status": j.state.last_run_status.value if j.state.last_run_status else None,
                    "consecutive_errors": j.state.consecutive_errors,
                }
                for j in jobs
            ],
        }

    async def _rpc_cron_status(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """RPC: estado del scheduler cron."""
        if not self._cron_scheduler:
            return {"running": False, "enabled": False}
        status = self._cron_scheduler.status()
        hb_summary = None
        if self._heartbeat:
            hb_summary = self._heartbeat.get_summary()
        return {
            "enabled": True,
            "scheduler": status,
            "heartbeat": hb_summary,
        }

    async def _rpc_cron_run(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """RPC: ejecuta un job cron inmediatamente."""
        if not self._cron_scheduler:
            return {"status": "error", "message": "Cron scheduler no disponible"}
        job_id = params.get("job_id")
        if not job_id:
            return {"status": "error", "message": "Falta job_id"}
        force = params.get("force", False)
        try:
            result = await self._cron_scheduler.run_now(job_id, force=force)
            return {"status": result.value, "job_id": job_id}
        except KeyError:
            return {"status": "error", "message": f"Job '{job_id}' no encontrado"}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    # ── RPC: Nuevos sistemas ──────────────────────────────────────

    async def _rpc_messaging_status(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """RPC: estado del message bus inter-agente."""
        if not self._message_bus:
            return {"enabled": False}
        return {"enabled": True, **self._message_bus.status()}

    async def _rpc_alerts_status(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """RPC: estado del sistema de alertas proactivas."""
        if not self._alert_manager:
            return {"enabled": False}
        return {"enabled": True, **self._alert_manager.status()}

    async def _rpc_planning_status(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """RPC: estado del planning engine."""
        if not self._planning_engine:
            return {"enabled": False}
        return {"enabled": True, **self._planning_engine.status_summary()}

    # ── Report file extraction ────────────────────────────────────

    @staticmethod
    def _extract_report_files(turn: Any) -> List[Dict[str, Any]]:
        """Extrae archivos de reportes generados durante el turno.

        Escanea los tool_results buscando resultados de generate_report
        con file_path válidos para auto-delivery por el orquestador.
        """
        import json as _json
        from pathlib import Path

        files: List[Dict[str, Any]] = []
        for msg in turn.messages:
            if not hasattr(msg, "tool_results") or not msg.tool_results:
                continue
            for tr in msg.tool_results:
                if tr.is_error:
                    continue
                try:
                    data = _json.loads(tr.content)
                except (ValueError, TypeError):
                    continue
                fp = data.get("file_path", "")
                if fp and Path(fp).exists():
                    files.append({
                        "file_path": fp,
                        "filename": data.get("filename", Path(fp).name),
                        "caption": None,
                    })
        return files
