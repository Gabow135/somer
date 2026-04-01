"""Backend SQLite para memoria persistente.

Portado y extendido desde OpenClaw: memory-schema.ts, internal.ts, manager-sync-ops.ts.
Soporta ciclo de vida completo, categorías, tags, importancia, archival,
batch operations y export/import.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from shared.constants import (
    DEFAULT_MEMORY_DIR,
    MEMORY_BATCH_SIZE,
)
from shared.types import (
    MemoryCategory,
    MemoryEntry,
    MemorySource,
    MemoryStats,
    MemoryStatus,
)

logger = logging.getLogger(__name__)


def _content_hash(content: str) -> str:
    """Genera un hash SHA-256 del contenido."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class SQLiteMemoryBackend:
    """Backend de memoria usando SQLite.

    Almacena entries con texto, metadata, categorías, tags e importancia.
    Los embeddings se almacenan como JSON (o con sqlite-vec si disponible).

    Portado de OpenClaw: memory-schema.ts + manager-sync-ops.ts.
    """

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or str(DEFAULT_MEMORY_DIR / "memory.db")
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._has_vec = False
        self._init_db()

    def _init_db(self) -> None:
        """Inicializa la base de datos y migra el esquema si es necesario."""
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        # Timeout para evitar SQLITE_BUSY en acceso concurrente
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_entries (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                content_hash TEXT,
                embedding TEXT,
                metadata TEXT DEFAULT '{}',
                session_id TEXT,
                category TEXT DEFAULT 'knowledge',
                tags TEXT DEFAULT '[]',
                source TEXT DEFAULT 'memory',
                importance REAL DEFAULT 0.5,
                status TEXT DEFAULT 'active',
                version INTEGER DEFAULT 1,
                parent_id TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                accessed_at REAL NOT NULL,
                archived_at REAL,
                access_count INTEGER DEFAULT 0
            )
        """)
        # Tabla de metadata del índice (portado de OpenClaw: meta table)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        self._conn.commit()

        # Migrar esquema legacy ANTES de crear índices sobre columnas nuevas
        self._migrate_schema()

        # Crear índices (ahora todas las columnas existen)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memory_session
            ON memory_entries(session_id)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memory_created
            ON memory_entries(created_at DESC)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memory_status
            ON memory_entries(status)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memory_category
            ON memory_entries(category)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memory_importance
            ON memory_entries(importance DESC)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memory_content_hash
            ON memory_entries(content_hash)
        """)
        self._conn.commit()

        # Intentar cargar sqlite-vec
        try:
            self._conn.enable_load_extension(True)
            self._has_vec = False
        except Exception:
            self._has_vec = False

    def _migrate_schema(self) -> None:
        """Migra el esquema de versiones anteriores añadiendo columnas faltantes.

        Portado de OpenClaw: ensureMemoryIndexSchema que maneja
        migraciones incrementales del esquema.
        """
        assert self._conn is not None
        existing = set()
        for row in self._conn.execute("PRAGMA table_info(memory_entries)"):
            existing.add(row[1])  # column name

        migrations: List[Tuple[str, str, str]] = [
            ("content_hash", "TEXT", "NULL"),
            ("category", "TEXT", "'knowledge'"),
            ("tags", "TEXT", "'[]'"),
            ("source", "TEXT", "'memory'"),
            ("importance", "REAL", "0.5"),
            ("status", "TEXT", "'active'"),
            ("version", "INTEGER", "1"),
            ("parent_id", "TEXT", "NULL"),
            ("updated_at", "REAL", "0"),
            ("archived_at", "REAL", "NULL"),
        ]

        for col_name, col_type, default in migrations:
            if col_name not in existing:
                try:
                    self._conn.execute(
                        f"ALTER TABLE memory_entries ADD COLUMN {col_name} "
                        f"{col_type} DEFAULT {default}"
                    )
                    logger.info("Migrada columna %s a memory_entries", col_name)
                except sqlite3.OperationalError:
                    pass

        # Rellenar updated_at donde falta
        if "updated_at" not in existing:
            self._conn.execute(
                "UPDATE memory_entries SET updated_at = created_at WHERE updated_at = 0"
            )

        self._conn.commit()

    # ── CRUD básico ──────────────────────────────────────────────

    def store(self, entry: MemoryEntry) -> str:
        """Almacena una entrada de memoria."""
        assert self._conn is not None
        embedding_json = json.dumps(entry.embedding) if entry.embedding else None
        metadata_json = json.dumps(entry.metadata, ensure_ascii=False)
        tags_json = json.dumps(entry.tags, ensure_ascii=False)
        c_hash = entry.content_hash or _content_hash(entry.content)
        self._conn.execute(
            """INSERT OR REPLACE INTO memory_entries
               (id, content, content_hash, embedding, metadata, session_id,
                category, tags, source, importance, status, version, parent_id,
                created_at, updated_at, accessed_at, archived_at, access_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.id,
                entry.content,
                c_hash,
                embedding_json,
                metadata_json,
                entry.session_id,
                entry.category.value if isinstance(entry.category, MemoryCategory) else entry.category,
                tags_json,
                entry.source.value if isinstance(entry.source, MemorySource) else entry.source,
                entry.importance,
                entry.status.value if isinstance(entry.status, MemoryStatus) else entry.status,
                entry.version,
                entry.parent_id,
                entry.created_at,
                entry.updated_at,
                entry.accessed_at,
                entry.archived_at,
                entry.access_count,
            ),
        )
        self._conn.commit()
        return entry.id

    def get(self, entry_id: str) -> Optional[MemoryEntry]:
        """Recupera una entrada por ID y actualiza el contador de acceso."""
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT * FROM memory_entries WHERE id = ?", (entry_id,)
        ).fetchone()
        if not row:
            return None
        # Actualizar acceso
        now = time.time()
        self._conn.execute(
            "UPDATE memory_entries SET accessed_at = ?, access_count = access_count + 1 WHERE id = ?",
            (now, entry_id),
        )
        self._conn.commit()
        return self._row_to_entry(row)

    def get_without_access_update(self, entry_id: str) -> Optional[MemoryEntry]:
        """Recupera una entrada por ID sin actualizar el contador de acceso."""
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT * FROM memory_entries WHERE id = ?", (entry_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_entry(row)

    def update(self, entry: MemoryEntry) -> bool:
        """Actualiza una entrada existente.

        Portado de OpenClaw: operación de actualización incremental con
        versionado automático.
        """
        assert self._conn is not None
        existing = self.get_without_access_update(entry.id)
        if not existing:
            return False

        now = time.time()
        c_hash = _content_hash(entry.content)
        embedding_json = json.dumps(entry.embedding) if entry.embedding else None
        metadata_json = json.dumps(entry.metadata, ensure_ascii=False)
        tags_json = json.dumps(entry.tags, ensure_ascii=False)
        new_version = existing.version + 1

        self._conn.execute(
            """UPDATE memory_entries SET
                content = ?, content_hash = ?, embedding = ?,
                metadata = ?, category = ?, tags = ?, source = ?,
                importance = ?, status = ?, version = ?,
                updated_at = ?, accessed_at = ?
               WHERE id = ?""",
            (
                entry.content,
                c_hash,
                embedding_json,
                metadata_json,
                entry.category.value if isinstance(entry.category, MemoryCategory) else entry.category,
                tags_json,
                entry.source.value if isinstance(entry.source, MemorySource) else entry.source,
                entry.importance,
                entry.status.value if isinstance(entry.status, MemoryStatus) else entry.status,
                new_version,
                now,
                now,
                entry.id,
            ),
        )
        self._conn.commit()
        return True

    def delete(self, entry_id: str) -> bool:
        """Elimina una entrada permanentemente."""
        assert self._conn is not None
        cursor = self._conn.execute(
            "DELETE FROM memory_entries WHERE id = ?", (entry_id,)
        )
        self._conn.commit()
        return cursor.rowcount > 0

    # ── Archival (portado de OpenClaw) ───────────────────────────

    def archive(self, entry_id: str) -> bool:
        """Archiva una entrada (soft delete).

        Portado de OpenClaw: ciclo de vida de archival de memoria.
        """
        assert self._conn is not None
        now = time.time()
        cursor = self._conn.execute(
            """UPDATE memory_entries
               SET status = 'archived', archived_at = ?, updated_at = ?
               WHERE id = ? AND status = 'active'""",
            (now, now, entry_id),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def unarchive(self, entry_id: str) -> bool:
        """Restaura una entrada archivada."""
        assert self._conn is not None
        now = time.time()
        cursor = self._conn.execute(
            """UPDATE memory_entries
               SET status = 'active', archived_at = NULL, updated_at = ?
               WHERE id = ? AND status = 'archived'""",
            (now, entry_id),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def archive_old_entries(self, max_age_days: float) -> int:
        """Archiva entradas que superan la edad máxima.

        Portado de OpenClaw: lógica de retención temporal de archivos
        de sesión con retentionMs.

        Returns:
            Número de entradas archivadas.
        """
        assert self._conn is not None
        cutoff = time.time() - (max_age_days * 86400)
        now = time.time()
        cursor = self._conn.execute(
            """UPDATE memory_entries
               SET status = 'archived', archived_at = ?, updated_at = ?
               WHERE status = 'active' AND accessed_at < ?""",
            (now, now, cutoff),
        )
        self._conn.commit()
        count = cursor.rowcount
        if count > 0:
            logger.info("Archivadas %d entradas con más de %.0f días", count, max_age_days)
        return count

    # ── Búsqueda ─────────────────────────────────────────────────

    def search_by_text(
        self, query: str, limit: int = 10, include_archived: bool = False
    ) -> List[MemoryEntry]:
        """Búsqueda simple por texto (LIKE)."""
        assert self._conn is not None
        status_filter = "" if include_archived else "AND status = 'active'"
        rows = self._conn.execute(
            f"""SELECT * FROM memory_entries
               WHERE content LIKE ? {status_filter}
               ORDER BY accessed_at DESC
               LIMIT ?""",
            (f"%{query}%", limit),
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def search_recent(
        self, limit: int = 10, session_id: Optional[str] = None,
        include_archived: bool = False,
    ) -> List[MemoryEntry]:
        """Recupera las entradas más recientes."""
        assert self._conn is not None
        status_filter = "" if include_archived else "AND status = 'active'"
        if session_id:
            rows = self._conn.execute(
                f"""SELECT * FROM memory_entries
                   WHERE session_id = ? {status_filter}
                   ORDER BY created_at DESC LIMIT ?""",
                (session_id, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                f"""SELECT * FROM memory_entries
                    WHERE 1=1 {status_filter}
                    ORDER BY created_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def search_by_category(
        self, category: str, limit: int = 50, include_archived: bool = False
    ) -> List[MemoryEntry]:
        """Busca entradas por categoría."""
        assert self._conn is not None
        status_filter = "" if include_archived else "AND status = 'active'"
        rows = self._conn.execute(
            f"""SELECT * FROM memory_entries
               WHERE category = ? {status_filter}
               ORDER BY importance DESC, created_at DESC
               LIMIT ?""",
            (category, limit),
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def search_by_tags(
        self, tags: List[str], limit: int = 50, include_archived: bool = False
    ) -> List[MemoryEntry]:
        """Busca entradas que contengan alguno de los tags dados."""
        assert self._conn is not None
        status_filter = "" if include_archived else "AND status = 'active'"
        conditions = " OR ".join(
            "tags LIKE ?" for _ in tags
        )
        params: List[Any] = [f'%"{tag}"%' for tag in tags]
        params.append(limit)
        rows = self._conn.execute(
            f"""SELECT * FROM memory_entries
               WHERE ({conditions}) {status_filter}
               ORDER BY importance DESC, created_at DESC
               LIMIT ?""",
            params,
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def search_by_importance(
        self, min_importance: float = 0.0, limit: int = 50
    ) -> List[MemoryEntry]:
        """Busca entradas con importancia mínima."""
        assert self._conn is not None
        rows = self._conn.execute(
            """SELECT * FROM memory_entries
               WHERE importance >= ? AND status = 'active'
               ORDER BY importance DESC, created_at DESC
               LIMIT ?""",
            (min_importance, limit),
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def find_duplicates(self, content_hash: str) -> List[MemoryEntry]:
        """Encuentra entradas con el mismo hash de contenido.

        Portado de OpenClaw: deduplicación por hash en manager-sync-ops.ts.
        """
        assert self._conn is not None
        rows = self._conn.execute(
            """SELECT * FROM memory_entries
               WHERE content_hash = ? AND status = 'active'
               ORDER BY created_at ASC""",
            (content_hash,),
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    # ── Batch operations (portado de OpenClaw) ───────────────────

    def store_batch(self, entries: List[MemoryEntry]) -> List[str]:
        """Almacena un lote de entradas en una sola transacción.

        Portado de OpenClaw: operaciones batch con transacciones
        atómicas en manager-sync-ops.ts.

        Returns:
            Lista de IDs creados.
        """
        assert self._conn is not None
        ids: List[str] = []
        self._conn.execute("BEGIN")
        try:
            for entry in entries:
                embedding_json = json.dumps(entry.embedding) if entry.embedding else None
                metadata_json = json.dumps(entry.metadata, ensure_ascii=False)
                tags_json = json.dumps(entry.tags, ensure_ascii=False)
                c_hash = entry.content_hash or _content_hash(entry.content)
                self._conn.execute(
                    """INSERT OR REPLACE INTO memory_entries
                       (id, content, content_hash, embedding, metadata, session_id,
                        category, tags, source, importance, status, version, parent_id,
                        created_at, updated_at, accessed_at, archived_at, access_count)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        entry.id,
                        entry.content,
                        c_hash,
                        embedding_json,
                        metadata_json,
                        entry.session_id,
                        entry.category.value if isinstance(entry.category, MemoryCategory) else entry.category,
                        tags_json,
                        entry.source.value if isinstance(entry.source, MemorySource) else entry.source,
                        entry.importance,
                        entry.status.value if isinstance(entry.status, MemoryStatus) else entry.status,
                        entry.version,
                        entry.parent_id,
                        entry.created_at,
                        entry.updated_at,
                        entry.accessed_at,
                        entry.archived_at,
                        entry.access_count,
                    ),
                )
                ids.append(entry.id)
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        return ids

    def delete_batch(self, entry_ids: List[str]) -> int:
        """Elimina un lote de entradas.

        Returns:
            Número de entradas eliminadas.
        """
        assert self._conn is not None
        if not entry_ids:
            return 0
        placeholders = ",".join("?" for _ in entry_ids)
        cursor = self._conn.execute(
            f"DELETE FROM memory_entries WHERE id IN ({placeholders})",
            entry_ids,
        )
        self._conn.commit()
        return cursor.rowcount

    def update_importance_batch(
        self, updates: List[Tuple[str, float]]
    ) -> int:
        """Actualiza la importancia de un lote de entradas.

        Args:
            updates: Lista de (entry_id, nueva_importancia).

        Returns:
            Número de entradas actualizadas.
        """
        assert self._conn is not None
        now = time.time()
        count = 0
        self._conn.execute("BEGIN")
        try:
            for entry_id, importance in updates:
                cursor = self._conn.execute(
                    "UPDATE memory_entries SET importance = ?, updated_at = ? WHERE id = ?",
                    (max(0.0, min(1.0, importance)), now, entry_id),
                )
                count += cursor.rowcount
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        return count

    # ── Conteo y estadísticas ────────────────────────────────────

    def count(self, include_archived: bool = False) -> int:
        """Número total de entradas."""
        assert self._conn is not None
        if include_archived:
            row = self._conn.execute("SELECT COUNT(*) FROM memory_entries").fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM memory_entries WHERE status = 'active'"
            ).fetchone()
        return row[0] if row else 0

    def stats(self) -> MemoryStats:
        """Genera estadísticas del sistema de memoria.

        Portado de OpenClaw: readCounts() en qmd-manager.ts y
        status() en manager.ts.
        """
        assert self._conn is not None
        total = self._conn.execute(
            "SELECT COUNT(*) FROM memory_entries"
        ).fetchone()[0]
        active = self._conn.execute(
            "SELECT COUNT(*) FROM memory_entries WHERE status = 'active'"
        ).fetchone()[0]
        archived = self._conn.execute(
            "SELECT COUNT(*) FROM memory_entries WHERE status = 'archived'"
        ).fetchone()[0]

        # Por categoría
        by_category: Dict[str, int] = {}
        for row in self._conn.execute(
            "SELECT category, COUNT(*) as c FROM memory_entries WHERE status = 'active' GROUP BY category"
        ):
            by_category[row[0]] = row[1]

        # Por source
        by_source: Dict[str, int] = {}
        for row in self._conn.execute(
            "SELECT source, COUNT(*) as c FROM memory_entries WHERE status = 'active' GROUP BY source"
        ):
            by_source[row[0]] = row[1]

        # Promedio de importancia
        avg_row = self._conn.execute(
            "SELECT AVG(importance) FROM memory_entries WHERE status = 'active'"
        ).fetchone()
        avg_importance = avg_row[0] if avg_row[0] is not None else 0.0

        # Timestamps extremos
        oldest_row = self._conn.execute(
            "SELECT MIN(created_at) FROM memory_entries WHERE status = 'active'"
        ).fetchone()
        newest_row = self._conn.execute(
            "SELECT MAX(created_at) FROM memory_entries WHERE status = 'active'"
        ).fetchone()

        return MemoryStats(
            total_entries=total,
            active_entries=active,
            archived_entries=archived,
            total_by_category=by_category,
            total_by_source=by_source,
            avg_importance=avg_importance,
            oldest_entry_at=oldest_row[0] if oldest_row else None,
            newest_entry_at=newest_row[0] if newest_row else None,
        )

    # ── Export / Import (portado de OpenClaw) ────────────────────

    def export_entries(
        self,
        include_archived: bool = False,
        max_entries: int = 50000,
    ) -> List[Dict[str, Any]]:
        """Exporta entradas como lista de diccionarios para backup.

        Portado de OpenClaw: exportación de sesiones y memoria para
        persistencia y backup.
        """
        assert self._conn is not None
        status_filter = "" if include_archived else "WHERE status = 'active'"
        rows = self._conn.execute(
            f"""SELECT * FROM memory_entries
                {status_filter}
                ORDER BY created_at ASC
                LIMIT ?""",
            (max_entries,),
        ).fetchall()
        result = []
        for row in rows:
            entry = self._row_to_entry(row)
            data = entry.model_dump(exclude={"embedding", "score"})
            # Serializar enums como strings
            data["category"] = data["category"].value if hasattr(data["category"], "value") else data["category"]
            data["source"] = data["source"].value if hasattr(data["source"], "value") else data["source"]
            data["status"] = data["status"].value if hasattr(data["status"], "value") else data["status"]
            result.append(data)
        return result

    def import_entries(self, data: List[Dict[str, Any]]) -> int:
        """Importa entradas desde una lista de diccionarios.

        Portado de OpenClaw: importación con deduplicación.

        Returns:
            Número de entradas importadas.
        """
        assert self._conn is not None
        count = 0
        entries: List[MemoryEntry] = []
        for item in data:
            try:
                # Si no hay ID o es vacío, se genera uno nuevo automáticamente
                raw_id = item.get("id", "")
                entry_kwargs: Dict[str, Any] = {"content": item["content"]}
                if raw_id:
                    entry_kwargs["id"] = raw_id
                entry = MemoryEntry(
                    **entry_kwargs,
                    metadata=item.get("metadata", {}),
                    session_id=item.get("session_id"),
                    category=item.get("category", "knowledge"),
                    tags=item.get("tags", []),
                    source=MemorySource.IMPORT,
                    importance=item.get("importance", 0.5),
                    status=item.get("status", "active"),
                    version=item.get("version", 1),
                    parent_id=item.get("parent_id"),
                    created_at=item.get("created_at", time.time()),
                    updated_at=item.get("updated_at", time.time()),
                    accessed_at=item.get("accessed_at", time.time()),
                    archived_at=item.get("archived_at"),
                    access_count=item.get("access_count", 0),
                )
                entries.append(entry)
            except (KeyError, ValueError) as exc:
                logger.warning("Entrada de importación inválida: %s", exc)
                continue

        if entries:
            batch_size = MEMORY_BATCH_SIZE
            for i in range(0, len(entries), batch_size):
                batch = entries[i:i + batch_size]
                ids = self.store_batch(batch)
                count += len(ids)

        logger.info("Importadas %d entradas de memoria", count)
        return count

    # ── Meta key-value store ─────────────────────────────────────

    def get_meta(self, key: str) -> Optional[str]:
        """Lee un valor de metadata del índice."""
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT value FROM memory_meta WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        """Escribe un valor de metadata del índice."""
        assert self._conn is not None
        self._conn.execute(
            """INSERT INTO memory_meta (key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            (key, value),
        )
        self._conn.commit()

    # ── Utilidades ───────────────────────────────────────────────

    def get_all_active(self, limit: int = 10000) -> List[MemoryEntry]:
        """Recupera todas las entradas activas."""
        assert self._conn is not None
        rows = self._conn.execute(
            """SELECT * FROM memory_entries
               WHERE status = 'active'
               ORDER BY created_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def close(self) -> None:
        """Cierra la conexión."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def _row_to_entry(self, row: sqlite3.Row) -> MemoryEntry:
        """Convierte una fila SQLite a MemoryEntry."""
        embedding = json.loads(row["embedding"]) if row["embedding"] else None
        metadata = json.loads(row["metadata"]) if row["metadata"] else {}

        # Tags: puede ser JSON o valor legacy vacío
        tags_raw = row["tags"] if "tags" in row.keys() else "[]"
        try:
            tags = json.loads(tags_raw) if tags_raw else []
        except (json.JSONDecodeError, TypeError):
            tags = []

        # Campos con defaults para retrocompatibilidad
        category = row["category"] if "category" in row.keys() else "knowledge"
        source = row["source"] if "source" in row.keys() else "memory"
        importance = row["importance"] if "importance" in row.keys() else 0.5
        status = row["status"] if "status" in row.keys() else "active"
        version = row["version"] if "version" in row.keys() else 1
        parent_id = row["parent_id"] if "parent_id" in row.keys() else None
        content_hash = row["content_hash"] if "content_hash" in row.keys() else None
        updated_at = row["updated_at"] if "updated_at" in row.keys() else row["created_at"]
        archived_at = row["archived_at"] if "archived_at" in row.keys() else None

        return MemoryEntry(
            id=row["id"],
            content=row["content"],
            content_hash=content_hash,
            embedding=embedding,
            metadata=metadata,
            session_id=row["session_id"],
            category=category,
            tags=tags,
            source=source,
            importance=importance,
            status=status,
            version=version,
            parent_id=parent_id,
            created_at=row["created_at"],
            updated_at=updated_at,
            accessed_at=row["accessed_at"],
            archived_at=archived_at,
            access_count=row["access_count"],
        )
