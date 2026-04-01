"""Memoria episódica para agentes.

Almacena secuencias de acciones exitosas (episodios) que el agente
puede recordar y replicar en situaciones similares.

A diferencia de la memoria semántica (hechos), la episódica recuerda
CÓMO se hicieron las cosas: qué tools se usaron, en qué orden,
con qué parámetros, y qué resultado obtuvieron.

Almacenamiento: SQLite

Python 3.9+ — ``from __future__ import annotations``.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Constantes ────────────────────────────────────────────────

_DEFAULT_DB_PATH = os.path.expanduser("~/.somer/memory/episodic.db")
_MAX_EPISODES = 1000
_MAX_STEPS_PER_EPISODE = 50
_DEFAULT_DECAY_DAYS = 90
_MAX_SEARCH_RESULTS = 20


# ── Schema SQL ───────────────────────────────────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    trigger_pattern TEXT DEFAULT '',
    outcome TEXT NOT NULL DEFAULT 'success',
    tags TEXT DEFAULT '[]',
    success_score REAL DEFAULT 1.0,
    use_count INTEGER DEFAULT 0,
    last_used_at REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS episode_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id TEXT NOT NULL REFERENCES episodes(episode_id),
    step_index INTEGER NOT NULL,
    action_type TEXT NOT NULL,
    action_name TEXT NOT NULL,
    action_args TEXT DEFAULT '{}',
    result_summary TEXT DEFAULT '',
    duration_secs REAL DEFAULT 0.0,
    success INTEGER DEFAULT 1,
    notes TEXT DEFAULT '',
    UNIQUE(episode_id, step_index)
);

CREATE INDEX IF NOT EXISTS idx_episodes_trigger ON episodes(trigger_pattern);
CREATE INDEX IF NOT EXISTS idx_episodes_tags ON episodes(tags);
CREATE INDEX IF NOT EXISTS idx_episodes_outcome ON episodes(outcome);
CREATE INDEX IF NOT EXISTS idx_episodes_score ON episodes(success_score);
CREATE INDEX IF NOT EXISTS idx_episode_steps_eid ON episode_steps(episode_id);
"""


# ── Tipos ────────────────────────────────────────────────────


class EpisodeOutcome(str, Enum):
    """Resultado de un episodio."""
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILURE = "failure"


@dataclass
class EpisodeStep:
    """Paso individual de un episodio."""
    step_index: int = 0
    action_type: str = ""         # tool, shell, code, api, manual
    action_name: str = ""         # Nombre de la tool/comando
    action_args: Dict[str, Any] = field(default_factory=dict)
    result_summary: str = ""      # Resumen del resultado
    duration_secs: float = 0.0
    success: bool = True
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step": self.step_index,
            "type": self.action_type,
            "action": self.action_name,
            "args": self.action_args,
            "result": self.result_summary,
            "duration": self.duration_secs,
            "success": self.success,
            "notes": self.notes,
        }


@dataclass
class Episode:
    """Episodio completo: secuencia de acciones con contexto."""
    episode_id: str = ""
    title: str = ""
    description: str = ""
    trigger_pattern: str = ""     # Patrón que activó este episodio
    steps: List[EpisodeStep] = field(default_factory=list)
    outcome: EpisodeOutcome = EpisodeOutcome.SUCCESS
    tags: List[str] = field(default_factory=list)
    success_score: float = 1.0    # 0.0-1.0, decae con el tiempo
    use_count: int = 0
    last_used_at: Optional[float] = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.episode_id,
            "title": self.title,
            "description": self.description,
            "trigger": self.trigger_pattern,
            "outcome": self.outcome.value,
            "tags": self.tags,
            "score": self.success_score,
            "uses": self.use_count,
            "steps": [s.to_dict() for s in self.steps],
            "created_at": self.created_at,
        }

    def to_replay_instructions(self) -> str:
        """Genera instrucciones para replicar este episodio."""
        lines = [
            f"## Episodio: {self.title}",
            f"*{self.description}*",
            f"Éxito: {self.success_score:.0%} | Usos: {self.use_count}",
            "",
            "### Pasos:",
        ]
        for step in self.steps:
            status = "✅" if step.success else "❌"
            lines.append(f"{step.step_index}. {status} `{step.action_name}` ({step.action_type})")
            if step.action_args:
                args_str = json.dumps(step.action_args, ensure_ascii=False)
                if len(args_str) > 200:
                    args_str = args_str[:200] + "..."
                lines.append(f"   Args: {args_str}")
            if step.notes:
                lines.append(f"   Nota: {step.notes}")

        return "\n".join(lines)


# ── EpisodicMemory Store ─────────────────────────────────────


class EpisodicMemory:
    """Almacén de memoria episódica.

    Uso:
        memory = EpisodicMemory()

        # Grabar episodio
        episode = Episode(
            title="Deploy a producción",
            trigger_pattern="deploy*prod*",
            steps=[...],
        )
        memory.save_episode(episode)

        # Buscar episodios similares
        episodes = memory.recall("deploy producción")

        # Usar episodio (incrementa contador)
        memory.mark_used(episode.episode_id)
    """

    def __init__(self, db_path: str = _DEFAULT_DB_PATH) -> None:
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(_SCHEMA_SQL)
        return self._conn

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── Save ───────────────────────────────────────────────

    def save_episode(self, episode: Episode) -> str:
        """Guarda un episodio nuevo o actualiza uno existente."""
        conn = self._get_conn()
        now = time.time()

        if not episode.episode_id:
            import uuid
            episode.episode_id = uuid.uuid4().hex[:12]

        tags_json = json.dumps(episode.tags, ensure_ascii=False)

        try:
            conn.execute(
                "INSERT INTO episodes "
                "(episode_id, title, description, trigger_pattern, outcome, tags, "
                "success_score, use_count, last_used_at, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    episode.episode_id, episode.title, episode.description,
                    episode.trigger_pattern, episode.outcome.value, tags_json,
                    episode.success_score, episode.use_count,
                    episode.last_used_at, episode.created_at, now,
                ),
            )
        except sqlite3.IntegrityError:
            conn.execute(
                "UPDATE episodes SET title=?, description=?, trigger_pattern=?, "
                "outcome=?, tags=?, success_score=?, updated_at=? "
                "WHERE episode_id=?",
                (
                    episode.title, episode.description, episode.trigger_pattern,
                    episode.outcome.value, tags_json, episode.success_score,
                    now, episode.episode_id,
                ),
            )
            # Limpiar pasos viejos
            conn.execute("DELETE FROM episode_steps WHERE episode_id=?", (episode.episode_id,))

        # Guardar pasos
        for step in episode.steps[:_MAX_STEPS_PER_EPISODE]:
            conn.execute(
                "INSERT INTO episode_steps "
                "(episode_id, step_index, action_type, action_name, action_args, "
                "result_summary, duration_secs, success, notes) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    episode.episode_id, step.step_index, step.action_type,
                    step.action_name, json.dumps(step.action_args, ensure_ascii=False),
                    step.result_summary, step.duration_secs,
                    1 if step.success else 0, step.notes,
                ),
            )

        conn.commit()
        logger.debug("Episodio guardado: %s (%s)", episode.episode_id, episode.title)
        return episode.episode_id

    # ── Recall ─────────────────────────────────────────────

    def recall(
        self,
        query: str = "",
        *,
        tags: Optional[List[str]] = None,
        outcome: Optional[EpisodeOutcome] = None,
        min_score: float = 0.3,
        limit: int = _MAX_SEARCH_RESULTS,
    ) -> List[Episode]:
        """Busca episodios similares.

        Busca por: trigger_pattern, title, description, tags.
        Ordena por: relevancia * success_score * recency.
        """
        conn = self._get_conn()
        conditions: List[str] = []
        params: List[Any] = []

        if query:
            conditions.append(
                "(title LIKE ? OR description LIKE ? OR trigger_pattern LIKE ?)"
            )
            q = f"%{query}%"
            params.extend([q, q, q])

        if tags:
            for tag in tags:
                conditions.append("tags LIKE ?")
                params.append(f'%"{tag}"%')

        if outcome:
            conditions.append("outcome = ?")
            params.append(outcome.value)

        conditions.append("success_score >= ?")
        params.append(min_score)

        where = " AND ".join(conditions) if conditions else "1=1"

        rows = conn.execute(
            f"""
            SELECT * FROM episodes
            WHERE {where}
            ORDER BY
                success_score * (1.0 + use_count * 0.1) DESC,
                updated_at DESC
            LIMIT ?
            """,
            params + [limit],
        ).fetchall()

        episodes: List[Episode] = []
        for row in rows:
            episode = Episode(
                episode_id=row["episode_id"],
                title=row["title"],
                description=row["description"],
                trigger_pattern=row["trigger_pattern"],
                outcome=EpisodeOutcome(row["outcome"]),
                tags=json.loads(row["tags"]),
                success_score=row["success_score"],
                use_count=row["use_count"],
                last_used_at=row["last_used_at"],
                created_at=row["created_at"],
            )

            # Cargar pasos
            step_rows = conn.execute(
                "SELECT * FROM episode_steps WHERE episode_id=? ORDER BY step_index",
                (episode.episode_id,),
            ).fetchall()

            for sr in step_rows:
                episode.steps.append(EpisodeStep(
                    step_index=sr["step_index"],
                    action_type=sr["action_type"],
                    action_name=sr["action_name"],
                    action_args=json.loads(sr["action_args"]),
                    result_summary=sr["result_summary"],
                    duration_secs=sr["duration_secs"],
                    success=bool(sr["success"]),
                    notes=sr["notes"],
                ))

            episodes.append(episode)

        return episodes

    # ── Update ─────────────────────────────────────────────

    def mark_used(self, episode_id: str) -> None:
        """Marca un episodio como usado (incrementa contador)."""
        conn = self._get_conn()
        now = time.time()
        conn.execute(
            "UPDATE episodes SET use_count = use_count + 1, last_used_at = ?, updated_at = ? "
            "WHERE episode_id = ?",
            (now, now, episode_id),
        )
        conn.commit()

    def update_score(self, episode_id: str, score: float) -> None:
        """Actualiza el score de éxito de un episodio."""
        conn = self._get_conn()
        conn.execute(
            "UPDATE episodes SET success_score = ?, updated_at = ? WHERE episode_id = ?",
            (max(0.0, min(1.0, score)), time.time(), episode_id),
        )
        conn.commit()

    def delete_episode(self, episode_id: str) -> bool:
        """Elimina un episodio y sus pasos."""
        conn = self._get_conn()
        conn.execute("DELETE FROM episode_steps WHERE episode_id=?", (episode_id,))
        cursor = conn.execute("DELETE FROM episodes WHERE episode_id=?", (episode_id,))
        conn.commit()
        return cursor.rowcount > 0

    # ── Decay ──────────────────────────────────────────────

    def apply_temporal_decay(self, decay_days: int = _DEFAULT_DECAY_DAYS) -> int:
        """Aplica decay temporal a episodios viejos no usados.

        Reduce el score de episodios que no se han usado recientemente.
        """
        conn = self._get_conn()
        now = time.time()
        cutoff = now - (decay_days * 86400)

        # Reducir score de episodios viejos
        cursor = conn.execute(
            "UPDATE episodes SET success_score = success_score * 0.9, updated_at = ? "
            "WHERE updated_at < ? AND success_score > 0.1",
            (now, cutoff),
        )
        affected = cursor.rowcount
        conn.commit()

        if affected:
            logger.debug("Decay aplicado a %d episodios", affected)

        # Eliminar episodios con score muy bajo
        conn.execute(
            "DELETE FROM episode_steps WHERE episode_id IN "
            "(SELECT episode_id FROM episodes WHERE success_score < 0.05)",
        )
        conn.execute("DELETE FROM episodes WHERE success_score < 0.05")
        conn.commit()

        return affected

    # ── Stats ──────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        """Estadísticas de la memoria episódica."""
        conn = self._get_conn()
        total = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
        by_outcome = conn.execute(
            "SELECT outcome, COUNT(*) as cnt FROM episodes GROUP BY outcome"
        ).fetchall()
        avg_score = conn.execute(
            "SELECT AVG(success_score) FROM episodes"
        ).fetchone()[0] or 0.0
        total_steps = conn.execute("SELECT COUNT(*) FROM episode_steps").fetchone()[0]
        most_used = conn.execute(
            "SELECT episode_id, title, use_count FROM episodes "
            "ORDER BY use_count DESC LIMIT 5"
        ).fetchall()

        return {
            "total_episodes": total,
            "total_steps": total_steps,
            "avg_score": round(avg_score, 3),
            "by_outcome": {r[0]: r[1] for r in by_outcome},
            "most_used": [
                {"id": r[0], "title": r[1], "uses": r[2]}
                for r in most_used
            ],
        }


# ── Recording helper ─────────────────────────────────────────


class EpisodeRecorder:
    """Helper para grabar episodios durante la ejecución.

    Uso:
        recorder = EpisodeRecorder(memory, "Deploy feature X")
        recorder.add_step("shell", "git push", {"branch": "main"}, "Pushed OK")
        recorder.add_step("tool", "delegate_coding", {...}, "Tests pass")
        recorder.finish(outcome=EpisodeOutcome.SUCCESS)
    """

    def __init__(
        self,
        memory: EpisodicMemory,
        title: str,
        *,
        description: str = "",
        trigger_pattern: str = "",
        tags: Optional[List[str]] = None,
    ) -> None:
        self._memory = memory
        self._episode = Episode(
            title=title,
            description=description,
            trigger_pattern=trigger_pattern,
            tags=tags or [],
        )
        self._step_counter = 0
        self._start_time = time.time()

    def add_step(
        self,
        action_type: str,
        action_name: str,
        args: Optional[Dict[str, Any]] = None,
        result: str = "",
        *,
        success: bool = True,
        duration: float = 0.0,
        notes: str = "",
    ) -> None:
        """Añade un paso al episodio en grabación."""
        self._step_counter += 1
        self._episode.steps.append(EpisodeStep(
            step_index=self._step_counter,
            action_type=action_type,
            action_name=action_name,
            action_args=args or {},
            result_summary=result[:500],
            duration_secs=duration,
            success=success,
            notes=notes,
        ))

    def finish(
        self,
        outcome: EpisodeOutcome = EpisodeOutcome.SUCCESS,
        score: Optional[float] = None,
    ) -> str:
        """Finaliza la grabación y guarda el episodio.

        Returns:
            ID del episodio guardado.
        """
        self._episode.outcome = outcome

        if score is not None:
            self._episode.success_score = score
        else:
            # Calcular score automáticamente
            if not self._episode.steps:
                self._episode.success_score = 0.5
            else:
                successes = sum(1 for s in self._episode.steps if s.success)
                self._episode.success_score = successes / len(self._episode.steps)

        return self._memory.save_episode(self._episode)
