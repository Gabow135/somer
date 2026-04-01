"""Cron — sistema de tareas programadas para SOMER.

Portado desde OpenClaw ``src/cron/``.
Provee scheduler con soporte de timezone, jitter, overlap prevention,
retry con backoff exponencial, alertas de fallo, concurrencia controlada,
ejecución aislada de agentes e historial persistente.
"""

from __future__ import annotations

from cron.isolated_runner import (
    IsolatedCronRunner,
    IsolatedRunConfig,
    IsolatedRunResult,
)
from cron.parser import (
    describe_cron,
    is_top_of_hour_cron,
    matches_cron,
    next_cron_datetime,
    parse_absolute_time,
    parse_cron_expression,
    prev_cron_datetime,
)
from cron.run_log import (
    CronRunLogEntry,
    append_run_log,
    read_run_log,
    read_run_log_all,
    resolve_run_log_path,
)
from cron.scheduler import (
    CronAction,
    CronFailureAlertConfig,
    CronJob,
    CronJobState,
    CronRetryConfig,
    CronRunStatus,
    CronScheduleKind,
    CronScheduler,
)

__all__ = [
    # Scheduler
    "CronScheduler",
    "CronJob",
    "CronJobState",
    "CronAction",
    "CronRunStatus",
    "CronScheduleKind",
    "CronRetryConfig",
    "CronFailureAlertConfig",
    # Parser
    "parse_cron_expression",
    "matches_cron",
    "next_cron_datetime",
    "prev_cron_datetime",
    "parse_absolute_time",
    "is_top_of_hour_cron",
    "describe_cron",
    # Isolated runner
    "IsolatedCronRunner",
    "IsolatedRunConfig",
    "IsolatedRunResult",
    # Run log
    "CronRunLogEntry",
    "append_run_log",
    "read_run_log",
    "read_run_log_all",
    "resolve_run_log_path",
]
