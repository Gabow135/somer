"""Tools personales — daily briefing, bookmark manager."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict

from agents.tools.registry import ToolDefinition, ToolRegistry, ToolSection
from agents.tools.user_context import get_current_user_id

logger = logging.getLogger(__name__)

_MAX_RESPONSE = 8000
_SOMER_DIR = os.path.expanduser("~/.somer")


def _truncate(text: str, max_len: int = _MAX_RESPONSE) -> str:
    if len(text) > max_len:
        return text[:max_len] + "\n...(truncado)"
    return text


# ── Database ─────────────────────────────────────────────────


def _get_bookmarks_db() -> sqlite3.Connection:
    os.makedirs(_SOMER_DIR, exist_ok=True)
    db_path = os.path.join(_SOMER_DIR, "bookmarks.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS bookmarks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT NOT NULL UNIQUE,
        title TEXT,
        description TEXT,
        category TEXT DEFAULT 'other',
        tags TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    try:
        conn.execute("ALTER TABLE bookmarks ADD COLUMN user_id TEXT DEFAULT 'default'")
        conn.commit()
    except Exception:
        pass
    conn.execute("UPDATE bookmarks SET user_id = 'default' WHERE user_id IS NULL")
    conn.commit()
    # Verificar si el UNIQUE constraint es simple (solo url) y reconstruir con UNIQUE(url, user_id)
    idxs = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='bookmarks' AND name LIKE 'sqlite_autoindex%'"
    ).fetchall()
    needs_rebuild = len(idxs) > 0
    if needs_rebuild:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bookmarks_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                title TEXT,
                description TEXT,
                category TEXT DEFAULT 'other',
                tags TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                user_id TEXT DEFAULT 'default',
                UNIQUE(url, user_id)
            )
        """)
        conn.execute("INSERT OR IGNORE INTO bookmarks_new SELECT *, COALESCE(user_id, 'default') as user_id FROM bookmarks")
        conn.execute("DROP TABLE bookmarks")
        conn.execute("ALTER TABLE bookmarks_new RENAME TO bookmarks")
        conn.commit()
    return conn


# ── Bookmark Handlers ────────────────────────────────────────


async def _bookmark_save_handler(args: Dict[str, Any]) -> str:
    """Guardar bookmark."""
    url = args.get("url", "").strip()
    if not url:
        return "Error: url es requerido"

    title = args.get("title", "")
    description = args.get("description", "")

    # Auto-fetch metadata si no se proporciona título
    if not title:
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10), ssl=False) as resp:
                    if resp.status == 200:
                        html = await resp.text()
                        import re
                        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
                        if title_match:
                            title = title_match.group(1).strip()[:200]
                        desc_match = re.search(r'<meta[^>]*name=["\']description["\'][^>]*content=["\']([^"\']*)', html, re.I)
                        if desc_match and not description:
                            description = desc_match.group(1).strip()[:500]
        except Exception:
            pass

    uid = get_current_user_id()
    conn = _get_bookmarks_db()
    try:
        # Upsert
        existing = conn.execute("SELECT id FROM bookmarks WHERE url = ? AND user_id = ?", (url, uid)).fetchone()
        if existing:
            conn.execute(
                "UPDATE bookmarks SET title = ?, description = ?, category = ?, tags = ?, notes = ? WHERE id = ? AND user_id = ?",
                (title or "", description or "", args.get("category", "other"),
                 args.get("tags", ""), args.get("notes", ""), existing["id"], uid),
            )
            action = "updated"
        else:
            conn.execute(
                "INSERT INTO bookmarks (url, title, description, category, tags, notes, user_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (url, title or url, description or "", args.get("category", "other"),
                 args.get("tags", ""), args.get("notes", ""), uid),
            )
            action = "saved"
        conn.commit()

        bm = dict(conn.execute("SELECT * FROM bookmarks WHERE url = ? AND user_id = ?", (url, uid)).fetchone())
        bm["action"] = action
        return json.dumps(bm, indent=2, ensure_ascii=False, default=str)
    finally:
        conn.close()


async def _bookmark_search_handler(args: Dict[str, Any]) -> str:
    """Búsqueda en bookmarks."""
    query = args.get("query", "").strip()
    if not query:
        return "Error: query es requerido"

    uid = get_current_user_id()
    conn = _get_bookmarks_db()
    try:
        rows = conn.execute(
            "SELECT * FROM bookmarks WHERE (title LIKE ? OR description LIKE ? OR tags LIKE ? OR url LIKE ? OR notes LIKE ?) "
            "AND user_id = ? ORDER BY created_at DESC LIMIT 20",
            (f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%", uid),
        ).fetchall()

        # También buscar en memoria vectorial de SOMER si está disponible
        results = [dict(r) for r in rows]
        return json.dumps({"results": results, "count": len(results)}, indent=2, ensure_ascii=False, default=str)
    finally:
        conn.close()


async def _bookmark_list_handler(args: Dict[str, Any]) -> str:
    """Listar bookmarks."""
    category = args.get("category", "")
    tag = args.get("tag", "")
    limit = args.get("limit", 20)

    uid = get_current_user_id()
    conn = _get_bookmarks_db()
    try:
        if category:
            rows = conn.execute(
                "SELECT * FROM bookmarks WHERE category = ? AND user_id = ? ORDER BY created_at DESC LIMIT ?", (category, uid, limit)
            ).fetchall()
        elif tag:
            rows = conn.execute(
                "SELECT * FROM bookmarks WHERE tags LIKE ? AND user_id = ? ORDER BY created_at DESC LIMIT ?", (f"%{tag}%", uid, limit)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM bookmarks WHERE user_id = ? ORDER BY created_at DESC LIMIT ?", (uid, limit)).fetchall()

        return json.dumps({"bookmarks": [dict(r) for r in rows], "count": len(rows)}, indent=2, ensure_ascii=False, default=str)
    finally:
        conn.close()


async def _bookmark_delete_handler(args: Dict[str, Any]) -> str:
    """Eliminar bookmark."""
    url = args.get("url", "").strip()
    bookmark_id = args.get("id")

    uid = get_current_user_id()
    conn = _get_bookmarks_db()
    try:
        if url:
            conn.execute("DELETE FROM bookmarks WHERE url = ? AND user_id = ?", (url, uid))
        elif bookmark_id:
            conn.execute("DELETE FROM bookmarks WHERE id = ? AND user_id = ?", (bookmark_id, uid))
        else:
            return "Error: url o id es requerido"
        conn.commit()
        return json.dumps({"deleted": True})
    finally:
        conn.close()


async def _bookmark_export_handler(args: Dict[str, Any]) -> str:
    """Exportar bookmarks."""
    fmt = args.get("format", "markdown")

    uid = get_current_user_id()
    conn = _get_bookmarks_db()
    try:
        rows = conn.execute("SELECT * FROM bookmarks WHERE user_id = ? ORDER BY category, created_at DESC", (uid,)).fetchall()
        bookmarks = [dict(r) for r in rows]

        if fmt == "json":
            return json.dumps({"bookmarks": bookmarks, "total": len(bookmarks)}, indent=2, ensure_ascii=False, default=str)
        elif fmt == "html":
            html = '<!DOCTYPE NETSCAPE-Bookmark-file-1>\n<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">\n<TITLE>Bookmarks</TITLE>\n<DL><p>\n'
            current_cat = ""
            for bm in bookmarks:
                if bm["category"] != current_cat:
                    if current_cat:
                        html += "</DL><p>\n"
                    current_cat = bm["category"]
                    html += f'<DT><H3>{current_cat}</H3>\n<DL><p>\n'
                html += f'<DT><A HREF="{bm["url"]}">{bm["title"]}</A>\n'
            html += "</DL><p>\n</DL><p>"
            return json.dumps({"format": "html", "content": html, "total": len(bookmarks)})
        else:  # markdown
            md = "# Bookmarks\n\n"
            current_cat = ""
            for bm in bookmarks:
                if bm["category"] != current_cat:
                    current_cat = bm["category"]
                    md += f"\n## {current_cat}\n\n"
                md += f"- [{bm['title']}]({bm['url']})"
                if bm["tags"]:
                    md += f" — {bm['tags']}"
                md += "\n"
            return json.dumps({"format": "markdown", "content": md, "total": len(bookmarks)})
    finally:
        conn.close()


# ── Daily Briefing Handler ───────────────────────────────────


async def _briefing_generate_handler(args: Dict[str, Any]) -> str:
    """Genera briefing diario consolidado."""
    sections = args.get("sections", ["crm", "finance", "meetings", "bookmarks"])

    briefing: Dict[str, Any] = {
        "date": date.today().isoformat(),
        "generated_at": datetime.now().isoformat(),
        "sections": {},
    }

    today_str = date.today().isoformat()

    # CRM: seguimientos del día
    if "crm" in sections:
        try:
            from agents.tools.business_tools import _crm_list_followups_handler, _crm_dashboard_handler
            followups_result = await _crm_list_followups_handler({"period": "today"})
            dashboard_result = await _crm_dashboard_handler({})
            briefing["sections"]["crm"] = {
                "followups": json.loads(followups_result),
                "dashboard": json.loads(dashboard_result),
            }
        except Exception as exc:
            briefing["sections"]["crm"] = {"error": str(exc)}

    # Finanzas: balance
    if "finance" in sections:
        try:
            from agents.tools.business_tools import _finance_get_summary_handler
            summary = await _finance_get_summary_handler({"period": "month"})
            briefing["sections"]["finance"] = json.loads(summary)
        except Exception as exc:
            briefing["sections"]["finance"] = {"error": str(exc)}

    # Reuniones: action items pendientes
    if "meetings" in sections:
        try:
            from agents.tools.business_tools import _meeting_list_actions_handler
            actions = await _meeting_list_actions_handler({})
            briefing["sections"]["meeting_actions"] = json.loads(actions)
        except Exception as exc:
            briefing["sections"]["meeting_actions"] = {"error": str(exc)}

    # Bookmarks recientes
    if "bookmarks" in sections:
        try:
            bookmarks = await _bookmark_list_handler({"limit": 5})
            briefing["sections"]["recent_bookmarks"] = json.loads(bookmarks)
        except Exception as exc:
            briefing["sections"]["recent_bookmarks"] = {"error": str(exc)}

    # SRI: obligaciones tributarias — todos los RUCs registrados
    if "sri" in sections or True:  # siempre intentar; se omite si no hay nada próximo o falla
        try:
            from agents.tools.sri_credentials import list_all_credentials
            all_creds = list_all_credentials()
            if all_creds:
                # Hay RUCs registrados en la BD multi-usuario
                sri_raw = await _sri_check_all_users_handler({})
                sri_data = json.loads(sri_raw)
                briefing["sections"]["sri"] = sri_data
            else:
                # Fallback: usar credenciales del env (comportamiento legacy)
                sri_result = await _sri_check_handler({})
                if sri_result.get("success") and sri_result.get("total", 0) > 0:
                    briefing["sections"]["sri"] = sri_result
        except Exception as exc:
            logger.debug("SRI briefing section omitida: %s", exc)
            # Silencioso: no romper el briefing

    # Nota para el agente: puede enriquecer con weather, calendar, servers
    briefing["enrichment_note"] = (
        "El agente puede enriquecer este briefing llamando también a: "
        "weather (clima), google-calendar (eventos), net_full_check (servidores), "
        "apple-reminders (recordatorios)."
    )

    return _truncate(json.dumps(briefing, indent=2, ensure_ascii=False), 12000)


# ── SRI Handler ──────────────────────────────────────────────

_SRI_SCRIPT = Path(__file__).parent.parent.parent / "skills" / "sri-obligations" / "scripts" / "sri_check.py"


def _run_sri_script(ruc: str, password: str, timeout: int = 120) -> dict:
    """Ejecuta el script Playwright de SRI con credenciales explícitas.

    Usa subprocess para aislar la ejecución; pasa RUC y password como
    argumentos CLI para evitar contaminar el env global.
    """
    script_path = str(_SRI_SCRIPT)
    if not Path(script_path).exists():
        return {"success": False, "error": f"Script no encontrado: {script_path}", "obligaciones": [], "total": 0}

    # Heredar el entorno actual pero no sobrescribir si ya están puestos
    env = os.environ.copy()

    try:
        proc = subprocess.run(
            [sys.executable, script_path, "--ruc", ruc, "--password", password, "--json"],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        stdout = proc.stdout.strip()
        if not stdout:
            return {
                "success": False,
                "error": proc.stderr.strip() or "Sin output del script SRI",
                "obligaciones": [],
                "total": 0,
            }
        return json.loads(stdout)
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Timeout consultando SRI ({timeout}s)", "obligaciones": [], "total": 0}
    except json.JSONDecodeError as exc:
        return {"success": False, "error": f"Output no es JSON válido: {exc}", "obligaciones": [], "total": 0}
    except Exception as exc:
        return {"success": False, "error": str(exc), "obligaciones": [], "total": 0}


async def _sri_check_handler(args: Dict[str, Any]) -> dict:
    """Revisa obligaciones tributarias pendientes en el SRI Ecuador (credenciales del env)."""
    script_path = str(_SRI_SCRIPT)
    if not Path(script_path).exists():
        return {"success": False, "error": f"Script no encontrado: {script_path}", "obligaciones": [], "total": 0}

    try:
        proc = subprocess.run(
            [sys.executable, script_path, "--json"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        stdout = proc.stdout.strip()
        if not stdout:
            return {
                "success": False,
                "error": proc.stderr.strip() or "Sin output del script SRI",
                "obligaciones": [],
                "total": 0,
            }
        result = json.loads(stdout)
        return result
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Timeout consultando SRI (120s)", "obligaciones": [], "total": 0}
    except json.JSONDecodeError as exc:
        return {"success": False, "error": f"Output no es JSON válido: {exc}", "obligaciones": [], "total": 0}
    except Exception as exc:
        return {"success": False, "error": str(exc), "obligaciones": [], "total": 0}


async def _sri_check_tool_handler(args: Dict[str, Any]) -> str:
    """Handler de tool que devuelve JSON string para el registry."""
    result = await _sri_check_handler(args)
    return json.dumps(result, indent=2, ensure_ascii=False)


# ── SRI Multi-usuario handlers ────────────────────────────────


async def _sri_save_credentials_handler(args: Dict[str, Any]) -> str:
    """Guarda credenciales SRI para un RUC en la base de datos cifrada."""
    from agents.tools.sri_credentials import save_credentials

    ruc = str(args.get("ruc", "")).strip()
    password = str(args.get("password", "")).strip()
    alias = args.get("alias", "")
    name = args.get("name", "")

    owner_user_id = get_current_user_id()
    result = save_credentials(
        ruc=ruc,
        password=password,
        alias=alias or None,
        owner_user_id=owner_user_id,
        name=name or None,
    )
    return json.dumps(result, indent=2, ensure_ascii=False)


async def _sri_check_user_handler(args: Dict[str, Any]) -> str:
    """Revisa obligaciones SRI para un RUC o nombre de contribuyente guardado en la BD."""
    from agents.tools.sri_credentials import get_credentials
    from datetime import date

    ruc_or_name = str(args.get("ruc_or_name", "") or args.get("ruc", "")).strip()
    if not ruc_or_name:
        return json.dumps({"success": False, "error": "ruc_or_name es requerido"})

    user_id = get_current_user_id()
    creds = get_credentials(ruc_or_name, user_id=user_id)
    if not creds:
        # Segundo intento sin filtrar por user_id (compatibilidad con registros legacy)
        creds = get_credentials(ruc_or_name)
    if not creds:
        return json.dumps({
            "success": False,
            "error": f"No hay credenciales guardadas para '{ruc_or_name}'. "
                     "Usa sri_save_credentials para registrarlo primero.",
        })

    ruc = creds["ruc"]
    loop = __import__("asyncio").get_event_loop()
    result = await loop.run_in_executor(None, _run_sri_script, ruc, creds["password"])

    today = date.today().strftime("%d/%b/%Y")
    display_name = creds.get("name") or creds.get("alias") or ruc

    if not result.get("success"):
        formatted = (
            f"ACCIÓN — SRI Ecuador | {display_name} | Error | {today}\n\n"
            f"RESULTADO\n"
            f"  Estado:     Error\n"
            f"  RUC:        {ruc}\n"
            f"  Detalle:    {result.get('error', 'Error desconocido')}\n\n"
            "---\nEjecutado por: SOMER SRI Multi-usuario"
        )
    else:
        obligaciones = result.get("obligaciones", [])
        descripciones = result.get("descripciones", [])
        total = result.get("total", 0)
        lines = [
            f"ACCIÓN — SRI Ecuador | {display_name} | Obligaciones | {today}",
            "",
            "RESULTADO",
            f"  Estado:     Completado",
            f"  RUC:        {ruc}",
        ]
        if creds.get("name"):
            lines.append(f"  Nombre:     {creds['name']}")
        if creds.get("alias"):
            lines.append(f"  Alias:      {creds['alias']}")
        lines.extend([
            f"  Total:      {total} obligaciones encontradas",
            "",
        ])
        if obligaciones:
            lines.append("OBLIGACIONES")
            for i, obl in enumerate(obligaciones, 1):
                desc = descripciones[i - 1] if i - 1 < len(descripciones) else ""
                if desc:
                    lines.extend([f"  {i:2}. {obl}", f"      └─ {desc}"])
                else:
                    lines.append(f"  {i:2}. {obl}")
            lines.append("")
        else:
            lines.extend(["  [OK] Sin obligaciones pendientes encontradas", ""])
        lines.extend(["---", f"Fuente: SRI Ecuador | srienlinea.sri.gob.ec | {result.get('timestamp', '')[:10]}"])
        formatted = "\n".join(lines)

    return json.dumps({
        "success": result.get("success"),
        "ruc": ruc,
        "name": creds.get("name"),
        "alias": creds.get("alias"),
        "formatted": formatted,
        "raw": result,
    }, indent=2, ensure_ascii=False)


async def _sri_check_all_users_handler(args: Dict[str, Any]) -> str:
    """Revisa obligaciones SRI para todos los RUCs registrados en paralelo."""
    import asyncio as _asyncio
    from agents.tools.sri_credentials import list_all_credentials, get_credentials
    from datetime import date

    all_creds_meta = list_all_credentials()
    if not all_creds_meta:
        return json.dumps({
            "success": False,
            "error": "No hay RUCs registrados. Usa sri_save_credentials para añadir credenciales.",
            "results": [],
        }, indent=2, ensure_ascii=False)

    today = date.today().strftime("%d/%b/%Y")
    loop = _asyncio.get_event_loop()

    async def _check_one(meta: dict) -> dict:
        ruc = meta["ruc"]
        creds = get_credentials(ruc)
        if not creds:
            return {
                "ruc": ruc,
                "name": meta.get("name"),
                "alias": meta.get("alias"),
                "success": False,
                "error": "Credenciales no disponibles",
            }
        result = await loop.run_in_executor(None, _run_sri_script, ruc, creds["password"])
        return {
            "ruc": ruc,
            "name": meta.get("name"),
            "alias": meta.get("alias"),
            "success": result.get("success"),
            "total": result.get("total", 0),
            "obligaciones": result.get("obligaciones", []),
            "descripciones": result.get("descripciones", []),
            "error": result.get("error") if not result.get("success") else None,
            "timestamp": result.get("timestamp"),
        }

    tasks = [_check_one(m) for m in all_creds_meta]
    results = await _asyncio.gather(*tasks, return_exceptions=False)

    # Construir reporte consolidado en formato TPL-ACTION
    lines = [
        f"ACCIÓN — SRI Ecuador | Reporte Consolidado | {today}",
        "",
        f"RESUMEN: {len(results)} RUCs consultados",
        "",
    ]

    success_count = sum(1 for r in results if r.get("success"))
    error_count = len(results) - success_count
    lines.extend([
        f"  Exitosos:   {success_count}",
        f"  Con error:  {error_count}",
        "",
    ])

    for r in results:
        display = r.get("name") or r.get("alias") or r["ruc"]
        if not r.get("success"):
            lines.extend([
                f"── {display} ({r['ruc']}) ──────────────",
                f"  Estado:  ERROR — {r.get('error', 'desconocido')}",
                "",
            ])
        else:
            total = r.get("total", 0)
            obligaciones = r.get("obligaciones", [])
            descripciones = r.get("descripciones", [])
            ruc_line = f"── {display} ({r['ruc']}) ──────────────"
            lines.extend([ruc_line, f"  Estado:  OK — {total} obligaciones", ""])
            if obligaciones:
                for i, obl in enumerate(obligaciones, 1):
                    desc = descripciones[i - 1] if i - 1 < len(descripciones) else ""
                    if desc:
                        lines.extend([f"  {i:2}. {obl}", f"      └─ {desc}"])
                    else:
                        lines.append(f"  {i:2}. {obl}")
                lines.append("")
            else:
                lines.extend(["  [OK] Sin obligaciones pendientes", ""])

    lines.extend(["---", f"Fuente: SRI Ecuador | srienlinea.sri.gob.ec"])
    formatted = "\n".join(lines)

    return json.dumps({
        "success": True,
        "total_rucs": len(results),
        "success_count": success_count,
        "error_count": error_count,
        "formatted": formatted,
        "results": results,
    }, indent=2, ensure_ascii=False)


# ── Registro ─────────────────────────────────────────────────


def register_personal_tools(registry: ToolRegistry) -> None:
    """Registra las tools personales."""

    # ── Bookmarks ──
    registry.register(ToolDefinition(
        id="bookmark_save", name="bookmark_save",
        description="Guardar un link/URL como bookmark con título, categoría y tags.",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL a guardar"},
                "title": {"type": "string"}, "description": {"type": "string"},
                "category": {"type": "string", "enum": ["dev", "security", "devops", "ai", "design", "business", "learning", "tools", "news", "personal", "other"]},
                "tags": {"type": "string", "description": "Tags separados por coma"},
                "notes": {"type": "string"},
            },
            "required": ["url"],
        },
        handler=_bookmark_save_handler, section=ToolSection.PERSONAL, timeout_secs=15,
    ))

    registry.register(ToolDefinition(
        id="bookmark_search", name="bookmark_search",
        description="Buscar en bookmarks guardados por concepto, keyword o tag.",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        handler=_bookmark_search_handler, section=ToolSection.PERSONAL, timeout_secs=10,
    ))

    registry.register(ToolDefinition(
        id="bookmark_list", name="bookmark_list",
        description="Listar bookmarks por categoría, tag o recientes.",
        parameters={
            "type": "object",
            "properties": {
                "category": {"type": "string"}, "tag": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
            },
        },
        handler=_bookmark_list_handler, section=ToolSection.PERSONAL, timeout_secs=10,
    ))

    registry.register(ToolDefinition(
        id="bookmark_delete", name="bookmark_delete",
        description="Eliminar un bookmark por URL o ID.",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string"}, "id": {"type": "integer"},
            },
        },
        handler=_bookmark_delete_handler, section=ToolSection.PERSONAL, timeout_secs=10,
    ))

    registry.register(ToolDefinition(
        id="bookmark_export", name="bookmark_export",
        description="Exportar bookmarks a Markdown, HTML (navegador) o JSON.",
        parameters={
            "type": "object",
            "properties": {
                "format": {"type": "string", "enum": ["markdown", "html", "json"]},
            },
        },
        handler=_bookmark_export_handler, section=ToolSection.PERSONAL, timeout_secs=10,
    ))

    # ── SRI Obligaciones ──
    registry.register(ToolDefinition(
        id="sri_check_obligations", name="sri_check_obligations",
        description=(
            "Revisa obligaciones tributarias pendientes en el SRI Ecuador. "
            "Usa Playwright para hacer login y extraer las obligaciones del portal. "
            "Requiere SRI_RUC y SRI_PASSWORD configurados en ~/.somer/.env."
        ),
        parameters={"type": "object", "properties": {}},
        handler=_sri_check_tool_handler, section=ToolSection.PERSONAL, timeout_secs=130,
    ))

    # ── SRI Multi-usuario ──
    registry.register(ToolDefinition(
        id="sri_save_credentials", name="sri_save_credentials",
        description=(
            "Guarda credenciales del portal SRI Ecuador (RUC + password) en la base de datos "
            "local cifrada. Permite registrar múltiples contribuyentes para consultas automáticas. "
            "El password se cifra con Fernet antes de guardar."
        ),
        parameters={
            "type": "object",
            "properties": {
                "ruc": {"type": "string", "description": "RUC del contribuyente (13 dígitos)"},
                "password": {"type": "string", "description": "Password del portal SRI"},
                "name": {"type": "string", "description": "Razón social o nombre completo del contribuyente (opcional, ej: 'Empresa XYZ S.A.')"},
                "alias": {"type": "string", "description": "Nombre amigable interno (opcional, ej: 'empresa_principal')"},
            },
            "required": ["ruc", "password"],
        },
        handler=_sri_save_credentials_handler, section=ToolSection.PERSONAL, timeout_secs=15,
    ))

    registry.register(ToolDefinition(
        id="sri_check_user", name="sri_check_user",
        description=(
            "Revisa obligaciones tributarias en el SRI Ecuador para un RUC o nombre de contribuyente "
            "previamente registrado con sri_save_credentials. "
            "Acepta RUC exacto (13 dígitos) o nombre/razón social parcial. "
            "Usa las credenciales guardadas en la base de datos local cifrada."
        ),
        parameters={
            "type": "object",
            "properties": {
                "ruc_or_name": {
                    "type": "string",
                    "description": "RUC del contribuyente (13 dígitos) o nombre/razón social parcial para buscarlo",
                },
            },
            "required": ["ruc_or_name"],
        },
        handler=_sri_check_user_handler, section=ToolSection.PERSONAL, timeout_secs=130,
    ))

    registry.register(ToolDefinition(
        id="sri_check_all_users", name="sri_check_all_users",
        description=(
            "Revisa obligaciones tributarias SRI Ecuador para TODOS los RUCs registrados "
            "en la base de datos local. Ejecuta las consultas en paralelo y genera un "
            "reporte consolidado. Usa esta tool en el briefing diario para mostrar "
            "las obligaciones de todos los contribuyentes registrados."
        ),
        parameters={"type": "object", "properties": {}},
        handler=_sri_check_all_users_handler, section=ToolSection.PERSONAL, timeout_secs=300,
    ))

    # ── Daily Briefing ──
    registry.register(ToolDefinition(
        id="briefing_generate", name="briefing_generate",
        description=(
            "Genera briefing diario consolidado: seguimientos CRM, balance financiero, "
            "action items de reuniones, bookmarks recientes. "
            "USA ESTA HERRAMIENTA cuando el usuario pida su briefing, resumen del día, "
            "o 'qué tengo para hoy'."
        ),
        parameters={
            "type": "object",
            "properties": {
                "sections": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["crm", "finance", "meetings", "bookmarks", "weather", "calendar", "servers"]},
                    "description": "Secciones a incluir (default: todas)",
                },
            },
        },
        handler=_briefing_generate_handler, section=ToolSection.PERSONAL, timeout_secs=30,
    ))
