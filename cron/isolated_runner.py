"""Runner aislado para jobs cron — ejecuta agentes en aislamiento.

Portado desde OpenClaw ``isolated-agent/run.ts``.
Permite ejecutar un AgentRunner en una sesión aislada para cada job cron,
con su propio contexto, timeout y manejo de resultados.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, List, Optional

from shared.errors import AgentTimeoutError, CronError, CronJobTimeoutError

logger = logging.getLogger(__name__)


@dataclass
class IsolatedRunResult:
    """Resultado de una ejecución aislada de agente.

    Portado de ``RunCronAgentTurnResult`` en OpenClaw.
    """

    status: str = "ok"                          # "ok" | "error" | "skipped"
    error: Optional[str] = None
    summary: Optional[str] = None
    output_text: Optional[str] = None
    session_id: Optional[str] = None
    session_key: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    duration_secs: float = 0.0
    usage: Optional[Dict[str, int]] = None      # input_tokens, output_tokens, etc.
    delivered: Optional[bool] = None
    delivery_attempted: Optional[bool] = None


# Type alias para la función de ejecución de agente
IsolatedAgentFn = Callable[
    [str, str, Optional[str]],
    Coroutine[Any, Any, IsolatedRunResult],
]


@dataclass
class IsolatedRunConfig:
    """Configuración para una ejecución aislada.

    Portado de los parámetros de ``runCronIsolatedAgentTurn`` en OpenClaw.
    """

    job_id: str = ""
    job_name: str = ""
    message: str = ""
    agent_id: Optional[str] = None
    session_key: Optional[str] = None
    model_override: Optional[str] = None
    timeout_secs: float = 600.0
    light_context: bool = False
    force_new_session: bool = True


class IsolatedCronRunner:
    """Ejecuta agentes en aislamiento para jobs cron.

    Portado de ``isolated-agent/run.ts`` en OpenClaw.
    Cada ejecución crea una sesión aislada con su propio contexto,
    opcionalmente con modelo override y timeout configurable.

    Uso::

        runner = IsolatedCronRunner(agent_fn=my_agent_fn)
        result = await runner.run(IsolatedRunConfig(
            job_id="abc123",
            message="Generar reporte diario",
            timeout_secs=300,
        ))
    """

    def __init__(
        self,
        agent_fn: Optional[IsolatedAgentFn] = None,
        default_model: Optional[str] = None,
        default_timeout_secs: float = 600.0,
    ) -> None:
        """Inicializa el runner aislado.

        Args:
            agent_fn: Función que ejecuta el agente. Recibe (message, session_key, model)
                      y retorna IsolatedRunResult.
            default_model: Modelo por defecto si no se especifica en el job.
            default_timeout_secs: Timeout por defecto en segundos.
        """
        self._agent_fn = agent_fn
        self._default_model = default_model
        self._default_timeout = default_timeout_secs
        self._active_runs: Dict[str, float] = {}  # job_id -> started_at

    @property
    def active_runs(self) -> Dict[str, float]:
        """Runs activos actualmente (job_id -> timestamp de inicio)."""
        return dict(self._active_runs)

    async def run(
        self,
        config: IsolatedRunConfig,
        *,
        abort_event: Optional[asyncio.Event] = None,
    ) -> IsolatedRunResult:
        """Ejecuta un agente en aislamiento para un job cron.

        Args:
            config: Configuración de la ejecución.
            abort_event: Evento para abortar la ejecución.

        Returns:
            Resultado de la ejecución aislada.
        """
        if self._agent_fn is None:
            return IsolatedRunResult(
                status="error",
                error="No se configuró función de agente para ejecución aislada",
            )

        started_at = time.time()
        self._active_runs[config.job_id] = started_at

        session_key = config.session_key or f"cron:{config.job_id}"
        model = config.model_override or self._default_model
        timeout = config.timeout_secs or self._default_timeout

        # Construir prompt con contexto de cron
        prompt = self._build_prompt(config)

        try:
            result = await asyncio.wait_for(
                self._agent_fn(prompt, session_key, model),
                timeout=timeout,
            )
            result.duration_secs = time.time() - started_at
            result.session_key = session_key
            return result

        except asyncio.TimeoutError:
            duration = time.time() - started_at
            error_msg = (
                f"Job cron '{config.job_name or config.job_id}' "
                f"excedió timeout de {timeout}s"
            )
            logger.warning(error_msg)
            return IsolatedRunResult(
                status="error",
                error=error_msg,
                session_key=session_key,
                duration_secs=duration,
            )

        except asyncio.CancelledError:
            duration = time.time() - started_at
            return IsolatedRunResult(
                status="error",
                error="Ejecución cancelada",
                session_key=session_key,
                duration_secs=duration,
            )

        except Exception as exc:
            duration = time.time() - started_at
            error_msg = str(exc)
            logger.exception(
                "Error en ejecución aislada del job '%s'", config.job_id
            )
            return IsolatedRunResult(
                status="error",
                error=error_msg,
                session_key=session_key,
                duration_secs=duration,
            )

        finally:
            self._active_runs.pop(config.job_id, None)

    def _build_prompt(self, config: IsolatedRunConfig) -> str:
        """Construye el prompt para la ejecución aislada.

        Portado de la lógica de prompt en OpenClaw ``run.ts``.
        """
        parts: List[str] = []

        # Header con contexto de cron
        header = f"[cron:{config.job_id}"
        if config.job_name:
            header += f" {config.job_name}"
        header += "]"

        parts.append(header)
        parts.append(config.message)

        return " ".join(parts).strip()

    async def run_with_retry(
        self,
        config: IsolatedRunConfig,
        *,
        max_retries: int = 3,
        backoff_secs: Optional[List[float]] = None,
        retry_on_transient: bool = True,
    ) -> IsolatedRunResult:
        """Ejecuta con lógica de reintentos para errores transitorios.

        Args:
            config: Configuración de la ejecución.
            max_retries: Número máximo de reintentos.
            backoff_secs: Schedule de backoff en segundos.
            retry_on_transient: Si solo reintentar errores transitorios.

        Returns:
            Resultado de la ejecución (último intento).
        """
        from cron.scheduler import _is_transient_error

        schedule = backoff_secs or [5.0, 15.0, 30.0]
        last_result: Optional[IsolatedRunResult] = None

        for attempt in range(max_retries + 1):
            result = await self.run(config)
            last_result = result

            if result.status != "error":
                return result

            if attempt >= max_retries:
                break

            # Verificar si el error es transitorio
            if retry_on_transient and not _is_transient_error(result.error or ""):
                logger.info(
                    "Error permanente en job '%s', sin reintentos: %s",
                    config.job_id, result.error,
                )
                break

            # Backoff
            delay = schedule[min(attempt, len(schedule) - 1)]
            logger.info(
                "Reintentando job '%s' en %.1fs (intento %d/%d): %s",
                config.job_id, delay, attempt + 1, max_retries, result.error,
            )
            await asyncio.sleep(delay)

        return last_result or IsolatedRunResult(
            status="error",
            error="Se agotaron los reintentos",
        )
