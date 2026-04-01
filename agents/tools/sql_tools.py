"""Tool de consultas SQL para agentes.

Permite ejecutar queries SELECT contra bases de datos SQLite, PostgreSQL
y MySQL directamente desde la conversación del agente.

Seguridad:
- Solo permite SELECT (read-only por defecto)
- Timeout configurable
- Límite de filas en respuesta
- Sanitización básica contra inyección

Python 3.9+ — ``from __future__ import annotations``.
"""

from __future__ import annotations

import json
import logging
import os
import re
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

_MAX_ROWS = 500
_MAX_CELL_LENGTH = 1000
_DEFAULT_TIMEOUT = 30
_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(DROP|DELETE|UPDATE|INSERT|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|EXEC)\b",
    re.IGNORECASE,
)


# ── Helpers ──────────────────────────────────────────────────


def _validate_query(query: str, *, allow_write: bool = False) -> Optional[str]:
    """Valida que el query sea seguro para ejecución.

    Returns:
        None si es válido, mensaje de error si no.
    """
    stripped = query.strip().rstrip(";")
    if not stripped:
        return "Query vacío."

    if not allow_write and _FORBIDDEN_KEYWORDS.search(stripped):
        return (
            "Solo se permiten queries SELECT en modo lectura. "
            "Para operaciones de escritura, usa allow_write=true."
        )

    return None


def _format_results(
    columns: List[str],
    rows: List[Tuple[Any, ...]],
    *,
    max_rows: int = _MAX_ROWS,
    format_type: str = "table",
) -> str:
    """Formatea resultados de query."""
    truncated = len(rows) > max_rows
    rows = rows[:max_rows]

    if format_type == "json":
        data = []
        for row in rows:
            record: Dict[str, Any] = {}
            for i, col in enumerate(columns):
                val = row[i] if i < len(row) else None
                if isinstance(val, str) and len(val) > _MAX_CELL_LENGTH:
                    val = val[:_MAX_CELL_LENGTH] + "..."
                record[col] = val
            data.append(record)

        result: Dict[str, Any] = {
            "columns": columns,
            "rows": data,
            "row_count": len(data),
        }
        if truncated:
            result["truncated"] = True
            result["note"] = f"Resultados truncados a {max_rows} filas."
        return json.dumps(result, ensure_ascii=False, default=str)

    # Formato tabla markdown
    if not columns:
        return "Query ejecutado sin resultados."

    lines: List[str] = []
    lines.append("| " + " | ".join(columns) + " |")
    lines.append("| " + " | ".join("---" for _ in columns) + " |")

    for row in rows:
        cells: List[str] = []
        for i, col in enumerate(columns):
            val = str(row[i]) if i < len(row) else ""
            if len(val) > _MAX_CELL_LENGTH:
                val = val[:_MAX_CELL_LENGTH] + "..."
            val = val.replace("|", "\\|").replace("\n", " ")
            cells.append(val)
        lines.append("| " + " | ".join(cells) + " |")

    if truncated:
        lines.append(f"\n*Resultados truncados a {max_rows} filas.*")

    return "\n".join(lines)


async def _execute_sqlite(
    db_path: str,
    query: str,
    *,
    params: Optional[List[Any]] = None,
    timeout: float = _DEFAULT_TIMEOUT,
    max_rows: int = _MAX_ROWS,
    format_type: str = "table",
) -> str:
    """Ejecuta query contra SQLite."""
    import asyncio

    if not os.path.exists(db_path):
        return json.dumps({"error": f"Base de datos no encontrada: {db_path}"})

    def _run() -> str:
        conn = sqlite3.connect(db_path, timeout=timeout)
        conn.row_factory = None
        try:
            cursor = conn.execute(query, params or [])
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = cursor.fetchmany(max_rows + 1)
            return _format_results(columns, rows, max_rows=max_rows, format_type=format_type)
        finally:
            conn.close()

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _run)


async def _execute_postgres(
    dsn: str,
    query: str,
    *,
    params: Optional[List[Any]] = None,
    max_rows: int = _MAX_ROWS,
    format_type: str = "table",
) -> str:
    """Ejecuta query contra PostgreSQL usando asyncpg."""
    try:
        import asyncpg
    except ImportError:
        return json.dumps({
            "error": "asyncpg no instalado. Instala con: pip install asyncpg"
        })

    conn = await asyncpg.connect(dsn)
    try:
        stmt = await conn.prepare(query)
        columns = [attr.name for attr in stmt.get_attributes()]
        records = await stmt.fetch(*params or [], timeout=_DEFAULT_TIMEOUT)
        rows = [tuple(r.values()) for r in records]
        return _format_results(columns, rows, max_rows=max_rows, format_type=format_type)
    finally:
        await conn.close()


async def _execute_mysql(
    dsn: str,
    query: str,
    *,
    params: Optional[List[Any]] = None,
    max_rows: int = _MAX_ROWS,
    format_type: str = "table",
) -> str:
    """Ejecuta query contra MySQL usando aiomysql."""
    try:
        import aiomysql
        import urllib.parse
    except ImportError:
        return json.dumps({
            "error": "aiomysql no instalado. Instala con: pip install aiomysql"
        })

    parsed = urllib.parse.urlparse(dsn)
    conn = await aiomysql.connect(
        host=parsed.hostname or "localhost",
        port=parsed.port or 3306,
        user=parsed.username or "root",
        password=parsed.password or "",
        db=parsed.path.lstrip("/"),
    )
    try:
        async with conn.cursor() as cur:
            await cur.execute(query, params or [])
            columns = [desc[0] for desc in cur.description] if cur.description else []
            rows = await cur.fetchmany(max_rows + 1)
            return _format_results(columns, rows, max_rows=max_rows, format_type=format_type)
    finally:
        conn.close()


# ── Handler principal ────────────────────────────────────────


async def _sql_query_handler(args: Dict[str, Any]) -> str:
    """Ejecuta un query SQL contra una base de datos."""
    query = args.get("query", "").strip()
    if not query:
        return json.dumps({"error": "query es requerido."})

    db_type = args.get("database_type", "sqlite")
    connection = args.get("connection", "")
    allow_write = args.get("allow_write", False)
    max_rows = min(args.get("max_rows", _MAX_ROWS), _MAX_ROWS)
    format_type = args.get("format", "table")

    # Validar query
    error = _validate_query(query, allow_write=allow_write)
    if error:
        return json.dumps({"error": error})

    start = time.monotonic()

    try:
        if db_type == "sqlite":
            db_path = connection or os.path.expanduser("~/.somer/memory/memory.db")
            result = await _execute_sqlite(
                db_path, query, max_rows=max_rows, format_type=format_type,
            )
        elif db_type == "postgres":
            if not connection:
                return json.dumps({"error": "connection (DSN) es requerido para PostgreSQL."})
            result = await _execute_postgres(
                connection, query, max_rows=max_rows, format_type=format_type,
            )
        elif db_type == "mysql":
            if not connection:
                return json.dumps({"error": "connection (DSN) es requerido para MySQL."})
            result = await _execute_mysql(
                connection, query, max_rows=max_rows, format_type=format_type,
            )
        else:
            return json.dumps({"error": f"database_type no soportado: {db_type}. Usa sqlite, postgres o mysql."})

        duration = time.monotonic() - start
        logger.info("SQL query ejecutado en %.1fms (%s)", duration * 1000, db_type)
        return result

    except Exception as exc:
        duration = time.monotonic() - start
        logger.error("SQL query error después de %.1fms: %s", duration * 1000, exc)
        return json.dumps({"error": f"Error ejecutando query: {str(exc)[:500]}"})


async def _sql_schema_handler(args: Dict[str, Any]) -> str:
    """Muestra el schema de una base de datos."""
    db_type = args.get("database_type", "sqlite")
    connection = args.get("connection", "")
    table = args.get("table", "")

    if db_type == "sqlite":
        db_path = connection or os.path.expanduser("~/.somer/memory/memory.db")
        if table:
            query = f"PRAGMA table_info('{table}')"
        else:
            query = "SELECT name, type FROM sqlite_master WHERE type IN ('table','view') ORDER BY name"
        return await _execute_sqlite(db_path, query, format_type="table")

    elif db_type == "postgres":
        if not connection:
            return json.dumps({"error": "connection (DSN) requerido."})
        if table:
            query = (
                "SELECT column_name, data_type, is_nullable, column_default "
                f"FROM information_schema.columns WHERE table_name = '{table}' "
                "ORDER BY ordinal_position"
            )
        else:
            query = (
                "SELECT table_name, table_type FROM information_schema.tables "
                "WHERE table_schema = 'public' ORDER BY table_name"
            )
        return await _execute_postgres(connection, query, format_type="table")

    elif db_type == "mysql":
        if not connection:
            return json.dumps({"error": "connection (DSN) requerido."})
        if table:
            query = f"DESCRIBE `{table}`"
        else:
            query = "SHOW TABLES"
        return await _execute_mysql(connection, query, format_type="table")

    return json.dumps({"error": f"database_type no soportado: {db_type}"})


# ── Registro ─────────────────────────────────────────────────


def register_sql_tools(registry: ToolRegistry) -> None:
    """Registra las tools de SQL en el registry."""

    registry.register(ToolDefinition(
        id="sql_query",
        name="sql_query",
        description=(
            "Ejecuta queries SQL contra bases de datos SQLite, PostgreSQL o MySQL. "
            "Usar para: consultar datos, analizar tablas, buscar registros, "
            "generar estadísticas desde la base de datos. "
            "Por defecto solo permite SELECT (lectura). "
            "Soporta la base de datos de memoria de SOMER como default."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Query SQL a ejecutar. Por defecto solo SELECT.",
                },
                "database_type": {
                    "type": "string",
                    "enum": ["sqlite", "postgres", "mysql"],
                    "description": "Tipo de base de datos (default: sqlite).",
                },
                "connection": {
                    "type": "string",
                    "description": (
                        "Conexión: ruta para SQLite, DSN para Postgres/MySQL. "
                        "Default: base de datos de memoria de SOMER."
                    ),
                },
                "max_rows": {
                    "type": "integer",
                    "description": "Máximo de filas a retornar (default: 500, max: 500).",
                },
                "format": {
                    "type": "string",
                    "enum": ["table", "json"],
                    "description": "Formato de salida: table (markdown) o json.",
                },
                "allow_write": {
                    "type": "boolean",
                    "description": "Permitir operaciones de escritura (default: false). ¡Usar con precaución!",
                },
            },
            "required": ["query"],
        },
        handler=_sql_query_handler,
        section=ToolSection.RUNTIME,
        profiles=[ToolProfile.CODING, ToolProfile.FULL],
        timeout_secs=60.0,
        requires_approval=False,
        dangerous=False,
    ))

    registry.register(ToolDefinition(
        id="sql_schema",
        name="sql_schema",
        description=(
            "Muestra el schema de una base de datos: tablas, columnas, tipos. "
            "Usar antes de sql_query para entender la estructura de datos."
        ),
        parameters={
            "type": "object",
            "properties": {
                "database_type": {
                    "type": "string",
                    "enum": ["sqlite", "postgres", "mysql"],
                    "description": "Tipo de base de datos (default: sqlite).",
                },
                "connection": {
                    "type": "string",
                    "description": "Conexión a la base de datos.",
                },
                "table": {
                    "type": "string",
                    "description": "Nombre de tabla (opcional — sin tabla lista todas).",
                },
            },
        },
        handler=_sql_schema_handler,
        section=ToolSection.RUNTIME,
        profiles=[ToolProfile.CODING, ToolProfile.FULL],
        timeout_secs=30.0,
    ))

    logger.info("SQL tools registradas: 2 tools")
