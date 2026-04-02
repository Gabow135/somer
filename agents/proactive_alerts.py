"""Sistema de alertas proactivas para agentes.

Monitorea servicios, canales y condiciones definidas, y genera
alertas automáticas sin que el usuario pregunte.

Implementa:
- Monitors: chequeos periódicos de condiciones
- Alert rules: reglas de cuando alertar
- Channels: entrega por canal (Telegram, Slack, etc.)
- Deduplication: suprime alertas repetidas
- Escalation: escalamiento si no se atiende

Python 3.9+ — ``from __future__ import annotations``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ── Constantes ────────────────────────────────────────────────

DEFAULT_CHECK_INTERVAL = 300     # 5 minutos
DEFAULT_DEDUP_WINDOW = 3600      # 1 hora
MAX_MONITORS = 50
MAX_ALERT_HISTORY = 500


# ── Tipos ────────────────────────────────────────────────────


class AlertSeverity(str, Enum):
    """Severidad de una alerta."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class MonitorStatus(str, Enum):
    """Estado de un monitor."""
    OK = "ok"
    DEGRADED = "degraded"
    DOWN = "down"
    UNKNOWN = "unknown"


class AlertState(str, Enum):
    """Estado de una alerta."""
    FIRING = "firing"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    SILENCED = "silenced"


@dataclass
class MonitorCheck:
    """Resultado de un chequeo de monitor."""
    status: MonitorStatus = MonitorStatus.UNKNOWN
    message: str = ""
    metrics: Dict[str, Any] = field(default_factory=dict)
    checked_at: float = field(default_factory=time.time)


@dataclass
class AlertRule:
    """Regla que define cuándo generar una alerta."""
    id: str = ""
    name: str = ""
    description: str = ""
    monitor_id: str = ""
    condition: str = ""           # Condición para alertar
    severity: AlertSeverity = AlertSeverity.WARNING
    enabled: bool = True
    check_interval_secs: int = DEFAULT_CHECK_INTERVAL
    dedup_window_secs: int = DEFAULT_DEDUP_WINDOW
    notify_channels: List[str] = field(default_factory=list)  # IDs de canales
    labels: Dict[str, str] = field(default_factory=dict)
    # Escalamiento
    escalate_after_secs: int = 0     # 0 = no escalar
    escalate_to: List[str] = field(default_factory=list)


@dataclass
class Alert:
    """Alerta generada."""
    id: str = ""
    rule_id: str = ""
    rule_name: str = ""
    severity: AlertSeverity = AlertSeverity.WARNING
    state: AlertState = AlertState.FIRING
    title: str = ""
    message: str = ""
    metrics: Dict[str, Any] = field(default_factory=dict)
    labels: Dict[str, str] = field(default_factory=dict)
    fingerprint: str = ""         # Para deduplicación
    fired_at: float = field(default_factory=time.time)
    acknowledged_at: Optional[float] = None
    resolved_at: Optional[float] = None
    notified_channels: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "rule": self.rule_name,
            "severity": self.severity.value,
            "state": self.state.value,
            "title": self.title,
            "message": self.message,
            "metrics": self.metrics,
            "labels": self.labels,
            "fired_at": self.fired_at,
            "acknowledged_at": self.acknowledged_at,
            "resolved_at": self.resolved_at,
        }

    def format_notification(self) -> str:
        """Formatea la alerta para enviar por canal."""
        icons = {
            AlertSeverity.INFO: "ℹ️",
            AlertSeverity.WARNING: "⚠️",
            AlertSeverity.ERROR: "🔴",
            AlertSeverity.CRITICAL: "🚨",
        }
        icon = icons.get(self.severity, "⚠️")
        lines = [
            f"{icon} **{self.severity.value.upper()}**: {self.title}",
            self.message,
        ]
        if self.metrics:
            metrics_str = ", ".join(f"{k}: {v}" for k, v in self.metrics.items())
            lines.append(f"📊 {metrics_str}")
        return "\n".join(lines)

    def send_whatsapp_alert(self, phone: str, razonsocial: str = "SOMER") -> dict:
        """Envía esta alerta por WhatsApp al número indicado.

        Usa WhatsAppNotifier para despachar el mensaje formateado de la alerta
        a través del template 'dtirols' de la WhatsApp Business Cloud API.

        Args:
            phone:       Número destino en formato internacional sin + (ej: '593987654321').
            razonsocial: Nombre del remitente para el header del template.

        Returns:
            dict con {success, http_code, whatsapp_number} o {success, error}.
        """
        try:
            from channels.whatsapp.notifier import WhatsAppNotifier
            notifier = WhatsAppNotifier()
            mensaje = f"[{self.severity.value.upper()}] {self.title}: {self.message}"
            return notifier.notify_user(
                whatsapp_number=phone,
                message=mensaje,
                razonsocial=razonsocial,
            )
        except Exception as exc:
            logger.error("Error enviando alerta WhatsApp a %s: %s", phone, exc)
            return {"success": False, "error": str(exc)}


# Tipo para función de chequeo de monitor
MonitorCheckFunc = Callable[[], Awaitable[MonitorCheck]]
# Tipo para función de notificación
NotifyFunc = Callable[[Alert, str], Awaitable[bool]]  # (alert, channel_id) -> success


# ── Monitor ──────────────────────────────────────────────────


@dataclass
class Monitor:
    """Monitor que ejecuta chequeos periódicos."""
    id: str = ""
    name: str = ""
    description: str = ""
    check_func: Optional[MonitorCheckFunc] = None
    interval_secs: int = DEFAULT_CHECK_INTERVAL
    enabled: bool = True
    last_check: Optional[MonitorCheck] = None
    consecutive_failures: int = 0
    labels: Dict[str, str] = field(default_factory=dict)


# ── ProactiveAlertManager ────────────────────────────────────


class ProactiveAlertManager:
    """Gestor de alertas proactivas.

    Uso:
        manager = ProactiveAlertManager(notify_func=send_to_channel)

        # Registrar monitor
        manager.add_monitor(Monitor(
            id="api_health",
            name="API Health Check",
            check_func=check_api_health,
            interval_secs=60,
        ))

        # Registrar regla
        manager.add_rule(AlertRule(
            id="api_down",
            name="API Down",
            monitor_id="api_health",
            condition="status == down",
            severity=AlertSeverity.CRITICAL,
            notify_channels=["telegram"],
        ))

        # Iniciar monitoreo
        await manager.start()
    """

    def __init__(
        self,
        *,
        notify_func: Optional[NotifyFunc] = None,
        llm_func: Optional[Callable[[str], Awaitable[str]]] = None,
    ) -> None:
        self._monitors: Dict[str, Monitor] = {}
        self._rules: Dict[str, AlertRule] = {}
        self._active_alerts: Dict[str, Alert] = {}      # Por fingerprint
        self._alert_history: List[Alert] = []
        self._notify_func = notify_func
        self._llm = llm_func
        self._running = False
        self._tasks: List[asyncio.Task[None]] = []
        self._dedup_cache: Dict[str, float] = {}  # fingerprint → last_fired_at

    # ── Configuration ──────────────────────────────────────

    def add_monitor(self, monitor: Monitor) -> None:
        """Registra un monitor."""
        if len(self._monitors) >= MAX_MONITORS:
            logger.warning("Máximo de monitors alcanzado (%d)", MAX_MONITORS)
            return
        self._monitors[monitor.id] = monitor
        logger.info("Monitor registrado: %s (%s)", monitor.id, monitor.name)

    def remove_monitor(self, monitor_id: str) -> bool:
        return self._monitors.pop(monitor_id, None) is not None

    def add_rule(self, rule: AlertRule) -> None:
        """Registra una regla de alerta."""
        self._rules[rule.id] = rule
        logger.info("Regla registrada: %s → monitor %s", rule.id, rule.monitor_id)

    def remove_rule(self, rule_id: str) -> bool:
        return self._rules.pop(rule_id, None) is not None

    # ── Lifecycle ──────────────────────────────────────────

    async def start(self) -> None:
        """Inicia el loop de monitoreo."""
        if self._running:
            return

        self._running = True
        logger.info("ProactiveAlertManager iniciado con %d monitors", len(self._monitors))

        for monitor_id, monitor in self._monitors.items():
            if monitor.enabled:
                task = asyncio.create_task(
                    self._monitor_loop(monitor),
                    name=f"monitor-{monitor_id}",
                )
                self._tasks.append(task)

    async def stop(self) -> None:
        """Detiene el monitoreo."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("ProactiveAlertManager detenido")

    async def _monitor_loop(self, monitor: Monitor) -> None:
        """Loop de chequeo para un monitor individual."""
        while self._running:
            try:
                await self._run_check(monitor)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Error en monitor %s: %s", monitor.id, exc)
                monitor.consecutive_failures += 1

            await asyncio.sleep(monitor.interval_secs)

    async def _run_check(self, monitor: Monitor) -> None:
        """Ejecuta un chequeo y evalúa reglas."""
        if not monitor.check_func:
            return

        try:
            check = await asyncio.wait_for(
                monitor.check_func(),
                timeout=30.0,
            )
            monitor.last_check = check

            if check.status == MonitorStatus.OK:
                monitor.consecutive_failures = 0
                # Resolver alertas activas de este monitor
                await self._auto_resolve(monitor.id)
            else:
                monitor.consecutive_failures += 1

        except asyncio.TimeoutError:
            check = MonitorCheck(
                status=MonitorStatus.UNKNOWN,
                message="Check timeout",
            )
            monitor.last_check = check
            monitor.consecutive_failures += 1

        # Evaluar reglas para este monitor
        for rule in self._rules.values():
            if rule.monitor_id != monitor.id or not rule.enabled:
                continue
            await self._evaluate_rule(rule, monitor, check)

    # ── Rule evaluation ────────────────────────────────────

    async def _evaluate_rule(
        self,
        rule: AlertRule,
        monitor: Monitor,
        check: MonitorCheck,
    ) -> None:
        """Evalúa una regla contra un resultado de chequeo."""
        should_fire = self._check_condition(rule.condition, check, monitor)

        if should_fire:
            await self._fire_alert(rule, monitor, check)
        else:
            # Resolver si la alerta estaba activa
            fingerprint = self._make_fingerprint(rule.id, monitor.id)
            if fingerprint in self._active_alerts:
                await self._resolve_alert(fingerprint)

    def _check_condition(
        self,
        condition: str,
        check: MonitorCheck,
        monitor: Monitor,
    ) -> bool:
        """Evalúa una condición simple contra el check."""
        # Condiciones soportadas:
        # "status == down", "status != ok", "consecutive_failures > 3"
        # "metric.X > Y", "metric.X < Y"
        try:
            condition = condition.strip()

            if "status" in condition:
                parts = condition.split()
                if len(parts) >= 3:
                    op = parts[1]
                    value = parts[2]
                    if op == "==":
                        return check.status.value == value
                    elif op == "!=":
                        return check.status.value != value

            if "consecutive_failures" in condition:
                parts = condition.split()
                if len(parts) >= 3:
                    op = parts[1]
                    threshold = int(parts[2])
                    if op == ">":
                        return monitor.consecutive_failures > threshold
                    elif op == ">=":
                        return monitor.consecutive_failures >= threshold

            if "metric." in condition:
                # metric.cpu_usage > 90
                parts = condition.split()
                if len(parts) >= 3:
                    metric_name = parts[0].replace("metric.", "")
                    op = parts[1]
                    threshold = float(parts[2])
                    value = check.metrics.get(metric_name, 0)
                    if op == ">":
                        return float(value) > threshold
                    elif op == "<":
                        return float(value) < threshold
                    elif op == ">=":
                        return float(value) >= threshold

        except Exception as exc:
            logger.warning("Error evaluando condición '%s': %s", condition, exc)

        return False

    # ── Alert firing ───────────────────────────────────────

    async def _fire_alert(
        self,
        rule: AlertRule,
        monitor: Monitor,
        check: MonitorCheck,
    ) -> None:
        """Genera y envía una alerta."""
        fingerprint = self._make_fingerprint(rule.id, monitor.id)

        # Deduplicación
        if fingerprint in self._dedup_cache:
            last_fired = self._dedup_cache[fingerprint]
            if time.time() - last_fired < rule.dedup_window_secs:
                return

        import uuid
        alert = Alert(
            id=uuid.uuid4().hex[:10],
            rule_id=rule.id,
            rule_name=rule.name,
            severity=rule.severity,
            state=AlertState.FIRING,
            title=f"{monitor.name}: {check.status.value}",
            message=check.message or f"Monitor {monitor.name} reporta estado {check.status.value}",
            metrics=check.metrics,
            labels={**monitor.labels, **rule.labels},
            fingerprint=fingerprint,
        )

        self._active_alerts[fingerprint] = alert
        self._dedup_cache[fingerprint] = time.time()

        # Guardar en historial
        self._alert_history.append(alert)
        if len(self._alert_history) > MAX_ALERT_HISTORY:
            self._alert_history = self._alert_history[-MAX_ALERT_HISTORY:]

        # Notificar
        if self._notify_func and rule.notify_channels:
            for channel in rule.notify_channels:
                try:
                    await self._notify_func(alert, channel)
                    alert.notified_channels.append(channel)
                except Exception as exc:
                    logger.error("Error notificando por %s: %s", channel, exc)

        logger.info(
            "Alerta disparada: [%s] %s — %s",
            alert.severity.value, alert.title, alert.message[:100],
        )

    async def _resolve_alert(self, fingerprint: str) -> None:
        """Resuelve una alerta activa."""
        alert = self._active_alerts.pop(fingerprint, None)
        if alert:
            alert.state = AlertState.RESOLVED
            alert.resolved_at = time.time()
            logger.info("Alerta resuelta: %s", alert.title)

    async def _auto_resolve(self, monitor_id: str) -> None:
        """Auto-resuelve alertas de un monitor que vuelve a OK."""
        to_resolve: List[str] = []
        for fp, alert in self._active_alerts.items():
            if monitor_id in fp:
                to_resolve.append(fp)
        for fp in to_resolve:
            await self._resolve_alert(fp)

    @staticmethod
    def _make_fingerprint(rule_id: str, monitor_id: str) -> str:
        raw = f"{rule_id}:{monitor_id}"
        return hashlib.md5(raw.encode()).hexdigest()[:12]

    # ── Manual operations ──────────────────────────────────

    async def acknowledge_alert(self, alert_id: str) -> bool:
        """Marca una alerta como reconocida."""
        for alert in self._active_alerts.values():
            if alert.id == alert_id:
                alert.state = AlertState.ACKNOWLEDGED
                alert.acknowledged_at = time.time()
                return True
        return False

    async def silence_rule(self, rule_id: str, duration_secs: int = 3600) -> bool:
        """Silencia una regla temporalmente."""
        rule = self._rules.get(rule_id)
        if rule:
            rule.enabled = False
            # Re-habilitar después
            asyncio.get_event_loop().call_later(
                duration_secs,
                lambda: setattr(rule, "enabled", True),
            )
            return True
        return False

    async def test_monitor(self, monitor_id: str) -> Optional[MonitorCheck]:
        """Ejecuta un chequeo manual de un monitor."""
        monitor = self._monitors.get(monitor_id)
        if monitor and monitor.check_func:
            check = await monitor.check_func()
            monitor.last_check = check
            return check
        return None

    # ── Built-in monitors ──────────────────────────────────

    @staticmethod
    def create_http_monitor(
        monitor_id: str,
        url: str,
        *,
        name: str = "",
        expected_status: int = 200,
        timeout: float = 10.0,
    ) -> Monitor:
        """Crea un monitor HTTP predefinido."""
        import aiohttp

        async def _check() -> MonitorCheck:
            start = time.time()
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                        duration = time.time() - start
                        if resp.status == expected_status:
                            return MonitorCheck(
                                status=MonitorStatus.OK,
                                message=f"HTTP {resp.status} en {duration:.1f}s",
                                metrics={"status_code": resp.status, "response_time_ms": round(duration * 1000)},
                            )
                        return MonitorCheck(
                            status=MonitorStatus.DEGRADED,
                            message=f"HTTP {resp.status} (esperado {expected_status})",
                            metrics={"status_code": resp.status, "response_time_ms": round(duration * 1000)},
                        )
            except Exception as exc:
                return MonitorCheck(
                    status=MonitorStatus.DOWN,
                    message=f"Error: {str(exc)[:200]}",
                    metrics={"response_time_ms": round((time.time() - start) * 1000)},
                )

        return Monitor(
            id=monitor_id,
            name=name or f"HTTP: {url}",
            check_func=_check,
        )

    @staticmethod
    def create_disk_monitor(
        monitor_id: str = "disk_space",
        threshold_pct: float = 90.0,
        path: str = "/",
    ) -> Monitor:
        """Crea un monitor de espacio en disco."""
        import shutil

        async def _check() -> MonitorCheck:
            usage = shutil.disk_usage(path)
            pct = (usage.used / usage.total) * 100
            free_gb = usage.free / (1024 ** 3)

            if pct >= threshold_pct:
                return MonitorCheck(
                    status=MonitorStatus.DEGRADED,
                    message=f"Disco {pct:.1f}% usado ({free_gb:.1f}GB libre)",
                    metrics={"usage_pct": round(pct, 1), "free_gb": round(free_gb, 1)},
                )
            return MonitorCheck(
                status=MonitorStatus.OK,
                message=f"Disco OK: {pct:.1f}% usado ({free_gb:.1f}GB libre)",
                metrics={"usage_pct": round(pct, 1), "free_gb": round(free_gb, 1)},
            )

        return Monitor(
            id=monitor_id,
            name=f"Disk Space ({path})",
            check_func=_check,
        )

    @staticmethod
    def create_process_monitor(
        monitor_id: str,
        process_name: str,
        *,
        name: str = "",
    ) -> Monitor:
        """Crea un monitor de proceso del sistema."""

        async def _check() -> MonitorCheck:
            import subprocess
            try:
                result = subprocess.run(
                    ["pgrep", "-f", process_name],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0:
                    pids = result.stdout.strip().split("\n")
                    return MonitorCheck(
                        status=MonitorStatus.OK,
                        message=f"{process_name}: {len(pids)} proceso(s) activo(s)",
                        metrics={"pid_count": len(pids)},
                    )
                return MonitorCheck(
                    status=MonitorStatus.DOWN,
                    message=f"{process_name}: no encontrado",
                    metrics={"pid_count": 0},
                )
            except Exception as exc:
                return MonitorCheck(
                    status=MonitorStatus.UNKNOWN,
                    message=f"Error verificando {process_name}: {exc}",
                )

        return Monitor(
            id=monitor_id,
            name=name or f"Process: {process_name}",
            check_func=_check,
        )

    # ── WhatsApp ────────────────────────────────────────────

    async def send_whatsapp_alert(self, phone: str, message: str, razonsocial: str = "SOMER") -> dict:
        """Envía un mensaje de alerta directo por WhatsApp.

        Método de conveniencia para despachar notificaciones al canal WhatsApp
        sin necesidad de crear un objeto Alert completo. Útil cuando el canal
        configurado en AlertRule es 'whatsapp'.

        Args:
            phone:       Número destino en formato internacional sin + (ej: '593987654321').
            message:     Texto del mensaje de alerta.
            razonsocial: Nombre del remitente para el header del template.

        Returns:
            dict con {success, http_code, whatsapp_number} o {success, error}.
        """
        try:
            from channels.whatsapp.notifier import WhatsAppNotifier
            notifier = WhatsAppNotifier()
            resultado = notifier.notify_user(
                whatsapp_number=phone,
                message=message,
                razonsocial=razonsocial,
            )
            if resultado.get("success"):
                logger.info("Alerta WhatsApp enviada a %s", phone)
            else:
                logger.warning(
                    "Fallo al enviar alerta WhatsApp a %s: %s",
                    phone, resultado.get("error", "error desconocido"),
                )
            return resultado
        except Exception as exc:
            logger.error("Error inesperado en send_whatsapp_alert a %s: %s", phone, exc)
            return {"success": False, "error": str(exc)}

    # ── Status ─────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        """Estado del sistema de alertas."""
        return {
            "running": self._running,
            "monitors": {
                mid: {
                    "name": m.name,
                    "enabled": m.enabled,
                    "status": m.last_check.status.value if m.last_check else "unknown",
                    "failures": m.consecutive_failures,
                }
                for mid, m in self._monitors.items()
            },
            "rules": len(self._rules),
            "active_alerts": [a.to_dict() for a in self._active_alerts.values()],
            "alert_history_count": len(self._alert_history),
        }
