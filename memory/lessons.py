"""Memoria de lecciones aprendidas (errores y workarounds).

Registra errores encontrados y sus soluciones para que el agente
no repita los mismos errores. Antes de ejecutar una accion, el
agente puede consultar si hay lecciones relevantes.

Almacenamiento: SQLite

Python 3.9+ — ``from __future__ import annotations``.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────

_DEFAULT_DB_PATH = os.path.expanduser("~/.somer/memory/lessons.db")
_MAX_SEARCH_RESULTS = 20

# ── Schema SQL ───────────────────────────────────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS lessons (
    id INTEGER PRIMARY KEY,
    lesson_id TEXT UNIQUE NOT NULL,
    context TEXT NOT NULL,
    error TEXT NOT NULL,
    solution TEXT NOT NULL,
    tags TEXT DEFAULT '[]',
    tool_name TEXT DEFAULT '',
    severity TEXT DEFAULT 'warning',
    hit_count INTEGER DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_lessons_tags ON lessons(tags);
CREATE INDEX IF NOT EXISTS idx_lessons_tool ON lessons(tool_name);
"""


# ── LessonsMemory ────────────────────────────────────────────


class LessonsMemory:
    """Almacen de lecciones aprendidas (errores y workarounds).

    Uso:
        lessons = LessonsMemory()

        # Guardar leccion
        lid = lessons.save_lesson(
            context="Intentando deploy a produccion",
            error="Puerto 80 ya en uso",
            solution="Usar puerto 8080 o matar proceso existente",
            tags=["deploy", "networking"],
            tool_name="shell",
        )

        # Buscar lecciones
        results = lessons.recall_lessons(query="deploy produccion")

        # Verificar antes de actuar
        warnings = lessons.check_before_action("shell", context="deploy")
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path or _DEFAULT_DB_PATH
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(_SCHEMA_SQL)
        return self._conn

    def close(self) -> None:
        """Cierra la conexion a la base de datos."""
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── Save ──────────────────────────────────────────────

    def save_lesson(
        self,
        context: str,
        error: str,
        solution: str,
        tags: Optional[List[str]] = None,
        tool_name: str = "",
        severity: str = "warning",
    ) -> str:
        """Guarda una leccion aprendida.

        Args:
            context: Que se estaba intentando hacer.
            error: Que salio mal.
            solution: Que funciono o workaround encontrado.
            tags: Etiquetas para clasificacion.
            tool_name: Tool que fallo (si aplica).
            severity: Nivel de severidad (info, warning, error).

        Returns:
            lesson_id generado.
        """
        conn = self._get_conn()
        now = time.time()
        lesson_id = uuid.uuid4().hex[:12]
        tags_json = json.dumps(tags or [], ensure_ascii=False)

        conn.execute(
            "INSERT INTO lessons "
            "(lesson_id, context, error, solution, tags, tool_name, "
            "severity, hit_count, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
            (lesson_id, context, error, solution, tags_json,
             tool_name, severity, now, now),
        )
        conn.commit()
        logger.debug("Leccion guardada: %s — %s", lesson_id, error[:80])
        return lesson_id

    # ── Recall ────────────────────────────────────────────

    def recall_lessons(
        self,
        query: str = "",
        tool_name: str = "",
        tags: Optional[List[str]] = None,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """Busca lecciones por texto, tool o tags.

        Ordena por relevancia (hit_count + recencia).

        Args:
            query: Texto libre para buscar en context, error, solution.
            tool_name: Filtrar por tool especifica.
            tags: Filtrar por tags.
            limit: Maximo de resultados.

        Returns:
            Lista de lecciones como diccionarios.
        """
        conn = self._get_conn()
        conditions: List[str] = []
        params: List[Any] = []

        if query:
            conditions.append(
                "(context LIKE ? OR error LIKE ? OR solution LIKE ?)"
            )
            q = f"%{query}%"
            params.extend([q, q, q])

        if tool_name:
            conditions.append("tool_name = ?")
            params.append(tool_name)

        if tags:
            for tag in tags:
                conditions.append("tags LIKE ?")
                params.append(f'%"{tag}"%')

        where = " AND ".join(conditions) if conditions else "1=1"
        limit = min(limit, _MAX_SEARCH_RESULTS)

        rows = conn.execute(
            f"""
            SELECT * FROM lessons
            WHERE {where}
            ORDER BY
                hit_count DESC,
                updated_at DESC
            LIMIT ?
            """,
            params + [limit],
        ).fetchall()

        results: List[Dict[str, Any]] = []
        for row in rows:
            results.append(self._row_to_dict(row))

        # Incrementar hit_count de las lecciones encontradas
        if results:
            now = time.time()
            for lesson in results:
                conn.execute(
                    "UPDATE lessons SET hit_count = hit_count + 1, updated_at = ? "
                    "WHERE lesson_id = ?",
                    (now, lesson["lesson_id"]),
                )
            conn.commit()

        return results

    # ── Check before action ───────────────────────────────

    def check_before_action(
        self,
        tool_name: str,
        context: str = "",
    ) -> List[Dict[str, Any]]:
        """Verifica si hay lecciones relevantes antes de ejecutar una accion.

        Busca lecciones asociadas a la tool y opcionalmente al contexto.
        No incrementa hit_count (es solo un check).

        Args:
            tool_name: Nombre de la tool a ejecutar.
            context: Descripcion opcional de lo que se va a hacer.

        Returns:
            Lista de advertencias/lecciones relevantes.
        """
        conn = self._get_conn()
        conditions: List[str] = ["tool_name = ?"]
        params: List[Any] = [tool_name]

        if context:
            conditions.append(
                "(context LIKE ? OR error LIKE ?)"
            )
            q = f"%{context}%"
            params.extend([q, q])

        where = " AND ".join(conditions)

        rows = conn.execute(
            f"""
            SELECT * FROM lessons
            WHERE {where}
            ORDER BY severity DESC, hit_count DESC, updated_at DESC
            LIMIT 5
            """,
            params,
        ).fetchall()

        return [self._row_to_dict(row) for row in rows]

    # ── Stats ─────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        """Estadisticas de la memoria de lecciones."""
        conn = self._get_conn()
        total = conn.execute("SELECT COUNT(*) FROM lessons").fetchone()[0]
        by_severity = conn.execute(
            "SELECT severity, COUNT(*) as cnt FROM lessons GROUP BY severity"
        ).fetchall()
        by_tool = conn.execute(
            "SELECT tool_name, COUNT(*) as cnt FROM lessons "
            "WHERE tool_name != '' GROUP BY tool_name ORDER BY cnt DESC LIMIT 10"
        ).fetchall()
        most_hit = conn.execute(
            "SELECT lesson_id, context, hit_count FROM lessons "
            "ORDER BY hit_count DESC LIMIT 5"
        ).fetchall()

        return {
            "total_lessons": total,
            "by_severity": {r[0]: r[1] for r in by_severity},
            "by_tool": {r[0]: r[1] for r in by_tool},
            "most_recalled": [
                {"id": r[0], "context": r[1][:80], "hits": r[2]}
                for r in most_hit
            ],
        }

    # ── Delete ────────────────────────────────────────────

    def delete_lesson(self, lesson_id: str) -> bool:
        """Elimina una leccion por su ID."""
        conn = self._get_conn()
        cursor = conn.execute(
            "DELETE FROM lessons WHERE lesson_id = ?", (lesson_id,)
        )
        conn.commit()
        return cursor.rowcount > 0

    # ── Helpers ───────────────────────────────────────────

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        """Convierte una fila de SQLite a diccionario."""
        return {
            "lesson_id": row["lesson_id"],
            "context": row["context"],
            "error": row["error"],
            "solution": row["solution"],
            "tags": json.loads(row["tags"]),
            "tool_name": row["tool_name"],
            "severity": row["severity"],
            "hit_count": row["hit_count"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
