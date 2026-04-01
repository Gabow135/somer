"""Tool de Knowledge Graph para agentes.

Construye y consulta grafos de conocimiento en memoria y SQLite
para representar relaciones entre entidades del contexto del usuario.

Almacena tripletas (sujeto, predicado, objeto) con metadata
y permite queries semánticas sobre el grafo.

Python 3.9+ — ``from __future__ import annotations``.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

from agents.tools.registry import (
    ToolDefinition,
    ToolProfile,
    ToolRegistry,
    ToolSection,
)

logger = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────

_DEFAULT_DB_PATH = os.path.expanduser("~/.somer/memory/knowledge_graph.db")
_MAX_RESULTS = 100

# ── Schema SQL ───────────────────────────────────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS kg_entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    entity_type TEXT NOT NULL DEFAULT 'thing',
    properties TEXT DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS kg_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id INTEGER NOT NULL REFERENCES kg_entities(id),
    predicate TEXT NOT NULL,
    object_id INTEGER NOT NULL REFERENCES kg_entities(id),
    weight REAL DEFAULT 1.0,
    properties TEXT DEFAULT '{}',
    source TEXT DEFAULT '',
    created_at REAL NOT NULL,
    UNIQUE(subject_id, predicate, object_id)
);

CREATE INDEX IF NOT EXISTS idx_kg_entities_name ON kg_entities(name);
CREATE INDEX IF NOT EXISTS idx_kg_entities_type ON kg_entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_kg_relations_subject ON kg_relations(subject_id);
CREATE INDEX IF NOT EXISTS idx_kg_relations_object ON kg_relations(object_id);
CREATE INDEX IF NOT EXISTS idx_kg_relations_predicate ON kg_relations(predicate);
"""


# ── KnowledgeGraphStore ─────────────────────────────────────


class KnowledgeGraphStore:
    """Almacén de Knowledge Graph basado en SQLite."""

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

    # ── Entidades ──────────────────────────────────────────

    def add_entity(
        self,
        name: str,
        entity_type: str = "thing",
        properties: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Añade o actualiza una entidad. Retorna su ID."""
        conn = self._get_conn()
        now = time.time()
        props_json = json.dumps(properties or {}, ensure_ascii=False)

        try:
            conn.execute(
                "INSERT INTO kg_entities (name, entity_type, properties, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (name, entity_type, props_json, now, now),
            )
        except sqlite3.IntegrityError:
            conn.execute(
                "UPDATE kg_entities SET entity_type = ?, properties = ?, updated_at = ? "
                "WHERE name = ?",
                (entity_type, props_json, now, name),
            )
        conn.commit()

        row = conn.execute("SELECT id FROM kg_entities WHERE name = ?", (name,)).fetchone()
        return row["id"]

    def get_entity(self, name: str) -> Optional[Dict[str, Any]]:
        """Obtiene una entidad por nombre."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM kg_entities WHERE name = ?", (name,)
        ).fetchone()
        if row:
            return {
                "id": row["id"],
                "name": row["name"],
                "type": row["entity_type"],
                "properties": json.loads(row["properties"]),
            }
        return None

    def search_entities(
        self,
        query: str = "",
        entity_type: str = "",
        limit: int = _MAX_RESULTS,
    ) -> List[Dict[str, Any]]:
        """Busca entidades por nombre y/o tipo."""
        conn = self._get_conn()
        conditions: List[str] = []
        params: List[Any] = []

        if query:
            conditions.append("name LIKE ?")
            params.append(f"%{query}%")
        if entity_type:
            conditions.append("entity_type = ?")
            params.append(entity_type)

        where = " AND ".join(conditions) if conditions else "1=1"
        rows = conn.execute(
            f"SELECT * FROM kg_entities WHERE {where} ORDER BY updated_at DESC LIMIT ?",
            params + [limit],
        ).fetchall()

        return [
            {
                "id": r["id"],
                "name": r["name"],
                "type": r["entity_type"],
                "properties": json.loads(r["properties"]),
            }
            for r in rows
        ]

    # ── Relaciones ─────────────────────────────────────────

    def add_relation(
        self,
        subject: str,
        predicate: str,
        obj: str,
        *,
        weight: float = 1.0,
        properties: Optional[Dict[str, Any]] = None,
        source: str = "",
    ) -> bool:
        """Añade una relación (crea entidades si no existen)."""
        subject_id = self.add_entity(subject)
        object_id = self.add_entity(obj)

        conn = self._get_conn()
        now = time.time()
        props_json = json.dumps(properties or {}, ensure_ascii=False)

        try:
            conn.execute(
                "INSERT INTO kg_relations "
                "(subject_id, predicate, object_id, weight, properties, source, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (subject_id, predicate, object_id, weight, props_json, source, now),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            # Relación ya existe, actualizar peso
            conn.execute(
                "UPDATE kg_relations SET weight = ?, properties = ?, source = ? "
                "WHERE subject_id = ? AND predicate = ? AND object_id = ?",
                (weight, props_json, source, subject_id, predicate, object_id),
            )
            conn.commit()
            return False

    def query_relations(
        self,
        subject: str = "",
        predicate: str = "",
        obj: str = "",
        limit: int = _MAX_RESULTS,
    ) -> List[Dict[str, Any]]:
        """Consulta relaciones con filtros opcionales."""
        conn = self._get_conn()
        conditions: List[str] = []
        params: List[Any] = []

        if subject:
            conditions.append("s.name LIKE ?")
            params.append(f"%{subject}%")
        if predicate:
            conditions.append("r.predicate LIKE ?")
            params.append(f"%{predicate}%")
        if obj:
            conditions.append("o.name LIKE ?")
            params.append(f"%{obj}%")

        where = " AND ".join(conditions) if conditions else "1=1"

        rows = conn.execute(
            f"""
            SELECT s.name as subject, r.predicate, o.name as object,
                   r.weight, r.properties, r.source
            FROM kg_relations r
            JOIN kg_entities s ON r.subject_id = s.id
            JOIN kg_entities o ON r.object_id = o.id
            WHERE {where}
            ORDER BY r.weight DESC, r.created_at DESC
            LIMIT ?
            """,
            params + [limit],
        ).fetchall()

        return [
            {
                "subject": r["subject"],
                "predicate": r["predicate"],
                "object": r["object"],
                "weight": r["weight"],
                "properties": json.loads(r["properties"]),
                "source": r["source"],
            }
            for r in rows
        ]

    def get_neighbors(
        self,
        entity_name: str,
        *,
        direction: str = "both",
        predicate: str = "",
        depth: int = 1,
        limit: int = _MAX_RESULTS,
    ) -> List[Dict[str, Any]]:
        """Obtiene vecinos de una entidad (traversal del grafo)."""
        conn = self._get_conn()
        entity = self.get_entity(entity_name)
        if not entity:
            return []

        results: List[Dict[str, Any]] = []
        visited: set = {entity["id"]}

        def _traverse(entity_id: int, current_depth: int) -> None:
            if current_depth > depth or len(results) >= limit:
                return

            conditions = []
            params: List[Any] = []

            if direction in ("out", "both"):
                cond = "r.subject_id = ?"
                if predicate:
                    cond += " AND r.predicate LIKE ?"
                conditions.append(
                    f"SELECT o.id, o.name, o.entity_type, r.predicate, 'out' as dir, r.weight "
                    f"FROM kg_relations r JOIN kg_entities o ON r.object_id = o.id "
                    f"WHERE {cond}"
                )
                params.append(entity_id)
                if predicate:
                    params.append(f"%{predicate}%")

            if direction in ("in", "both"):
                cond = "r.object_id = ?"
                if predicate:
                    cond += " AND r.predicate LIKE ?"
                conditions.append(
                    f"SELECT s.id, s.name, s.entity_type, r.predicate, 'in' as dir, r.weight "
                    f"FROM kg_relations r JOIN kg_entities s ON r.subject_id = s.id "
                    f"WHERE {cond}"
                )
                params.append(entity_id)
                if predicate:
                    params.append(f"%{predicate}%")

            if not conditions:
                return

            query = " UNION ALL ".join(conditions) + " ORDER BY weight DESC"
            rows = conn.execute(query, params).fetchall()

            for row in rows:
                if len(results) >= limit:
                    break
                neighbor_id = row[0]
                if neighbor_id in visited:
                    continue
                visited.add(neighbor_id)

                results.append({
                    "entity": row[1],
                    "type": row[2],
                    "relation": row[3],
                    "direction": row[4],
                    "weight": row[5],
                    "depth": current_depth,
                })

                if current_depth < depth:
                    _traverse(neighbor_id, current_depth + 1)

        _traverse(entity["id"], 1)
        return results

    def stats(self) -> Dict[str, Any]:
        """Estadísticas del grafo."""
        conn = self._get_conn()
        entities = conn.execute("SELECT COUNT(*) FROM kg_entities").fetchone()[0]
        relations = conn.execute("SELECT COUNT(*) FROM kg_relations").fetchone()[0]
        types = conn.execute(
            "SELECT entity_type, COUNT(*) as cnt FROM kg_entities "
            "GROUP BY entity_type ORDER BY cnt DESC"
        ).fetchall()
        predicates = conn.execute(
            "SELECT predicate, COUNT(*) as cnt FROM kg_relations "
            "GROUP BY predicate ORDER BY cnt DESC LIMIT 20"
        ).fetchall()

        return {
            "entities": entities,
            "relations": relations,
            "entity_types": {r[0]: r[1] for r in types},
            "top_predicates": {r[0]: r[1] for r in predicates},
        }


# ── Singleton ────────────────────────────────────────────────

_store: Optional[KnowledgeGraphStore] = None


def _get_store() -> KnowledgeGraphStore:
    global _store
    if _store is None:
        _store = KnowledgeGraphStore()
    return _store


# ── Handlers ─────────────────────────────────────────────────


async def _kg_add_handler(args: Dict[str, Any]) -> str:
    """Añade entidades y relaciones al knowledge graph."""
    store = _get_store()
    entities = args.get("entities", [])
    relations = args.get("relations", [])

    added_entities = 0
    added_relations = 0

    for ent in entities:
        name = ent.get("name", "")
        if name:
            store.add_entity(
                name,
                entity_type=ent.get("type", "thing"),
                properties=ent.get("properties"),
            )
            added_entities += 1

    for rel in relations:
        subject = rel.get("subject", "")
        predicate = rel.get("predicate", "")
        obj = rel.get("object", "")
        if subject and predicate and obj:
            store.add_relation(
                subject,
                predicate,
                obj,
                weight=rel.get("weight", 1.0),
                properties=rel.get("properties"),
                source=rel.get("source", ""),
            )
            added_relations += 1

    return json.dumps({
        "status": "success",
        "entities_added": added_entities,
        "relations_added": added_relations,
    })


async def _kg_query_handler(args: Dict[str, Any]) -> str:
    """Consulta el knowledge graph."""
    store = _get_store()
    query_type = args.get("query_type", "relations")

    if query_type == "entity":
        name = args.get("entity", "")
        if not name:
            return json.dumps({"error": "entity es requerido."})
        entity = store.get_entity(name)
        if entity:
            return json.dumps({"entity": entity})
        return json.dumps({"error": f"Entidad no encontrada: {name}"})

    elif query_type == "search":
        results = store.search_entities(
            query=args.get("query", ""),
            entity_type=args.get("entity_type", ""),
            limit=args.get("limit", 50),
        )
        return json.dumps({"entities": results, "count": len(results)})

    elif query_type == "relations":
        results = store.query_relations(
            subject=args.get("subject", ""),
            predicate=args.get("predicate", ""),
            obj=args.get("object", ""),
            limit=args.get("limit", 50),
        )
        return json.dumps({"relations": results, "count": len(results)})

    elif query_type == "neighbors":
        entity = args.get("entity", "")
        if not entity:
            return json.dumps({"error": "entity es requerido."})
        results = store.get_neighbors(
            entity,
            direction=args.get("direction", "both"),
            predicate=args.get("predicate", ""),
            depth=min(args.get("depth", 1), 3),
            limit=args.get("limit", 50),
        )
        return json.dumps({
            "entity": entity,
            "neighbors": results,
            "count": len(results),
        })

    elif query_type == "stats":
        return json.dumps(store.stats())

    return json.dumps({"error": f"query_type no válido: {query_type}"})


async def _kg_delete_handler(args: Dict[str, Any]) -> str:
    """Elimina entidades o relaciones del knowledge graph."""
    store = _get_store()
    conn = store._get_conn()

    entity = args.get("entity", "")
    subject = args.get("subject", "")
    predicate = args.get("predicate", "")
    obj = args.get("object", "")
    deleted = 0

    if entity:
        ent = store.get_entity(entity)
        if ent:
            conn.execute("DELETE FROM kg_relations WHERE subject_id = ? OR object_id = ?",
                         (ent["id"], ent["id"]))
            conn.execute("DELETE FROM kg_entities WHERE id = ?", (ent["id"],))
            conn.commit()
            deleted += 1

    if subject and predicate and obj:
        s = store.get_entity(subject)
        o = store.get_entity(obj)
        if s and o:
            conn.execute(
                "DELETE FROM kg_relations WHERE subject_id = ? AND predicate = ? AND object_id = ?",
                (s["id"], predicate, o["id"]),
            )
            conn.commit()
            deleted += 1

    return json.dumps({"status": "success", "deleted": deleted})


# ── Registro ─────────────────────────────────────────────────


def register_knowledge_graph_tools(registry: ToolRegistry) -> None:
    """Registra las tools de knowledge graph en el registry."""

    registry.register(ToolDefinition(
        id="kg_add",
        name="kg_add",
        description=(
            "Añade entidades y relaciones al knowledge graph. "
            "Usar para: registrar hechos, relaciones entre personas/proyectos/conceptos, "
            "construir un modelo mental del contexto del usuario. "
            "Las entidades se crean automáticamente al añadir relaciones."
        ),
        parameters={
            "type": "object",
            "properties": {
                "entities": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Nombre de la entidad."},
                            "type": {
                                "type": "string",
                                "description": "Tipo: person, project, technology, concept, organization, location, etc.",
                            },
                            "properties": {
                                "type": "object",
                                "description": "Propiedades adicionales de la entidad.",
                            },
                        },
                        "required": ["name"],
                    },
                    "description": "Entidades a añadir al grafo.",
                },
                "relations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "subject": {"type": "string", "description": "Entidad sujeto."},
                            "predicate": {
                                "type": "string",
                                "description": "Relación: uses, manages, depends_on, created_by, part_of, etc.",
                            },
                            "object": {"type": "string", "description": "Entidad objeto."},
                            "weight": {"type": "number", "description": "Peso/importancia (default: 1.0)."},
                            "source": {"type": "string", "description": "Fuente de la información."},
                        },
                        "required": ["subject", "predicate", "object"],
                    },
                    "description": "Relaciones (tripletas) a añadir.",
                },
            },
        },
        handler=_kg_add_handler,
        section=ToolSection.MEMORY,
        profiles=[ToolProfile.FULL],
        timeout_secs=30.0,
    ))

    registry.register(ToolDefinition(
        id="kg_query",
        name="kg_query",
        description=(
            "Consulta el knowledge graph para obtener entidades, relaciones y vecinos. "
            "Usar para: buscar relaciones entre conceptos, explorar conexiones, "
            "entender el contexto del usuario, encontrar entidades relacionadas."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query_type": {
                    "type": "string",
                    "enum": ["entity", "search", "relations", "neighbors", "stats"],
                    "description": (
                        "Tipo de consulta: entity (por nombre), search (buscar), "
                        "relations (tripletas), neighbors (vecinos), stats (estadísticas)."
                    ),
                },
                "entity": {"type": "string", "description": "Nombre de entidad (para entity/neighbors)."},
                "query": {"type": "string", "description": "Texto de búsqueda (para search)."},
                "entity_type": {"type": "string", "description": "Filtrar por tipo de entidad."},
                "subject": {"type": "string", "description": "Filtrar relaciones por sujeto."},
                "predicate": {"type": "string", "description": "Filtrar relaciones por predicado."},
                "object": {"type": "string", "description": "Filtrar relaciones por objeto."},
                "direction": {
                    "type": "string",
                    "enum": ["in", "out", "both"],
                    "description": "Dirección para neighbors (default: both).",
                },
                "depth": {"type": "integer", "description": "Profundidad de traversal (default: 1, max: 3)."},
                "limit": {"type": "integer", "description": "Máximo de resultados (default: 50)."},
            },
            "required": ["query_type"],
        },
        handler=_kg_query_handler,
        section=ToolSection.MEMORY,
        profiles=[ToolProfile.FULL],
        timeout_secs=30.0,
    ))

    registry.register(ToolDefinition(
        id="kg_delete",
        name="kg_delete",
        description=(
            "Elimina entidades o relaciones del knowledge graph. "
            "Eliminar una entidad también elimina todas sus relaciones."
        ),
        parameters={
            "type": "object",
            "properties": {
                "entity": {"type": "string", "description": "Entidad a eliminar (y todas sus relaciones)."},
                "subject": {"type": "string", "description": "Sujeto de la relación a eliminar."},
                "predicate": {"type": "string", "description": "Predicado de la relación a eliminar."},
                "object": {"type": "string", "description": "Objeto de la relación a eliminar."},
            },
        },
        handler=_kg_delete_handler,
        section=ToolSection.MEMORY,
        profiles=[ToolProfile.FULL],
        timeout_secs=15.0,
    ))

    logger.info("Knowledge graph tools registradas: 3 tools")
