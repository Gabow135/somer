"""Run log persistente para jobs cron — historial de ejecución en JSONL.

Portado desde OpenClaw ``run-log.ts``.
Almacena entradas de ejecución en archivos JSONL con rotación automática.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from shared.errors import CronError

logger = logging.getLogger(__name__)

# ── Constantes ──────────────────────────────────────────────
DEFAULT_MAX_BYTES = 2_000_000       # 2 MB
DEFAULT_KEEP_LINES = 2_000


# ── Tipos ───────────────────────────────────────────────────
class CronRunLogEntry:
    """Entrada de log de ejecución de un job cron.

    Portada de ``CronRunLogEntry`` en OpenClaw ``run-log.ts``.
    """

    __slots__ = (
        "ts", "job_id", "action", "status", "error", "summary",
        "duration_secs", "next_run_at", "model", "provider", "usage",
        "session_id", "session_key",
    )

    def __init__(
        self,
        ts: float,
        job_id: str,
        action: str = "finished",
        status: Optional[str] = None,
        error: Optional[str] = None,
        summary: Optional[str] = None,
        duration_secs: Optional[float] = None,
        next_run_at: Optional[float] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        usage: Optional[Dict[str, int]] = None,
        session_id: Optional[str] = None,
        session_key: Optional[str] = None,
    ):
        self.ts = ts
        self.job_id = job_id
        self.action = action
        self.status = status
        self.error = error
        self.summary = summary
        self.duration_secs = duration_secs
        self.next_run_at = next_run_at
        self.model = model
        self.provider = provider
        self.usage = usage
        self.session_id = session_id
        self.session_key = session_key

    def to_dict(self) -> Dict[str, Any]:
        """Serializa la entrada a diccionario."""
        d: Dict[str, Any] = {
            "ts": self.ts,
            "jobId": self.job_id,
            "action": self.action,
        }
        if self.status is not None:
            d["status"] = self.status
        if self.error is not None:
            d["error"] = self.error
        if self.summary is not None:
            d["summary"] = self.summary
        if self.duration_secs is not None:
            d["durationSecs"] = self.duration_secs
        if self.next_run_at is not None:
            d["nextRunAt"] = self.next_run_at
        if self.model is not None:
            d["model"] = self.model
        if self.provider is not None:
            d["provider"] = self.provider
        if self.usage is not None:
            d["usage"] = self.usage
        if self.session_id is not None:
            d["sessionId"] = self.session_id
        if self.session_key is not None:
            d["sessionKey"] = self.session_key
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Optional[CronRunLogEntry]:
        """Deserializa una entrada desde diccionario. Retorna None si inválida."""
        try:
            ts = data.get("ts")
            job_id = data.get("jobId", data.get("job_id"))
            action = data.get("action")
            if not isinstance(ts, (int, float)) or not isinstance(job_id, str):
                return None
            if action != "finished":
                return None
            return cls(
                ts=float(ts),
                job_id=job_id,
                action="finished",
                status=data.get("status"),
                error=data.get("error"),
                summary=data.get("summary"),
                duration_secs=data.get("durationSecs", data.get("duration_secs")),
                next_run_at=data.get("nextRunAt", data.get("next_run_at")),
                model=data.get("model"),
                provider=data.get("provider"),
                usage=data.get("usage"),
                session_id=data.get("sessionId", data.get("session_id")),
                session_key=data.get("sessionKey", data.get("session_key")),
            )
        except Exception:
            return None


def resolve_run_log_path(store_path: str, job_id: str) -> str:
    """Resuelve la ruta del archivo de log para un job.

    Portado de ``resolveCronRunLogPath`` en OpenClaw ``run-log.ts``.

    Args:
        store_path: Ruta base del store de cron.
        job_id: ID del job.

    Returns:
        Ruta absoluta al archivo JSONL.
    """
    safe_id = job_id.strip()
    if not safe_id or "/" in safe_id or "\\" in safe_id or "\0" in safe_id:
        raise CronError(f"ID de job inválido para run log: {job_id}")
    base = Path(store_path).resolve()
    runs_dir = base.parent / "runs"
    resolved = (runs_dir / f"{safe_id}.jsonl").resolve()
    if not str(resolved).startswith(str(runs_dir)):
        raise CronError(f"ID de job inválido para run log: {job_id}")
    return str(resolved)


def append_run_log(
    file_path: str,
    entry: CronRunLogEntry,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    keep_lines: int = DEFAULT_KEEP_LINES,
) -> None:
    """Agrega una entrada al log de ejecución con rotación automática.

    Portado de ``appendCronRunLog`` en OpenClaw ``run-log.ts``.

    Args:
        file_path: Ruta al archivo JSONL.
        entry: Entrada a agregar.
        max_bytes: Tamaño máximo antes de rotar.
        keep_lines: Líneas a mantener tras rotación.
    """
    path = Path(file_path)

    # Crear directorio si no existe
    path.parent.mkdir(parents=True, exist_ok=True)

    # Agregar entrada
    line = json.dumps(entry.to_dict(), ensure_ascii=False) + "\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)

    # Rotar si excede tamaño máximo
    try:
        _prune_if_needed(str(path), max_bytes, keep_lines)
    except Exception:
        logger.warning("Error al rotar run log %s", file_path)


def _prune_if_needed(file_path: str, max_bytes: int, keep_lines: int) -> None:
    """Rota el archivo de log si excede el tamaño máximo.

    Portado de ``pruneIfNeeded`` en OpenClaw ``run-log.ts``.
    """
    try:
        stat = os.stat(file_path)
        if stat.st_size <= max_bytes:
            return
    except OSError:
        return

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
        kept = lines[max(0, len(lines) - keep_lines):]
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("\n".join(kept) + "\n")
    except Exception:
        logger.warning("Error al rotar run log %s", file_path)


def read_run_log(
    file_path: str,
    *,
    job_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    sort_desc: bool = True,
) -> List[CronRunLogEntry]:
    """Lee entradas del log de ejecución con filtros.

    Portado de ``readCronRunLogEntriesPage`` en OpenClaw ``run-log.ts``.

    Args:
        file_path: Ruta al archivo JSONL.
        job_id: Filtrar por job ID.
        status: Filtrar por estado (ok, error, skipped).
        limit: Cantidad máxima de entradas.
        offset: Offset para paginación.
        sort_desc: Si True, más recientes primero.

    Returns:
        Lista de entradas del log.
    """
    path = Path(file_path)
    if not path.exists():
        return []

    entries: List[CronRunLogEntry] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    entry = CronRunLogEntry.from_dict(data)
                    if entry is None:
                        continue
                    if job_id and entry.job_id != job_id:
                        continue
                    if status and entry.status != status:
                        continue
                    entries.append(entry)
                except (json.JSONDecodeError, KeyError):
                    continue
    except OSError:
        return []

    # Ordenar
    entries.sort(key=lambda e: e.ts, reverse=sort_desc)

    # Paginar (limit=0 devuelve todas)
    if limit <= 0:
        return entries
    limit = min(200, limit)
    offset = max(0, min(len(entries), offset))
    return entries[offset:offset + limit]


def read_run_log_all(
    store_path: str,
    *,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    sort_desc: bool = True,
) -> List[CronRunLogEntry]:
    """Lee entradas de todos los logs de ejecución.

    Portado de ``readCronRunLogEntriesPageAll`` en OpenClaw ``run-log.ts``.

    Args:
        store_path: Ruta base del store de cron.
        status: Filtrar por estado.
        limit: Cantidad máxima de entradas.
        offset: Offset para paginación.
        sort_desc: Si True, más recientes primero.

    Returns:
        Lista combinada de entradas de todos los jobs.
    """
    base = Path(store_path).resolve()
    runs_dir = base.parent / "runs"
    if not runs_dir.exists():
        return []

    all_entries: List[CronRunLogEntry] = []
    for jsonl_file in runs_dir.glob("*.jsonl"):
        entries = read_run_log(
            str(jsonl_file), status=status, limit=0, offset=0, sort_desc=False
        )
        all_entries.extend(entries)

    # Ordenar y paginar
    all_entries.sort(key=lambda e: e.ts, reverse=sort_desc)
    limit = max(1, min(200, limit))
    offset = max(0, min(len(all_entries), offset))
    return all_entries[offset:offset + limit]
