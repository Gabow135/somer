"""Tools empresariales — CRM lite, financial tracker, meeting notes."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, date
from typing import Any, Dict, Optional

from agents.tools.registry import ToolDefinition, ToolRegistry, ToolSection
from agents.tools.user_context import get_current_user_id

logger = logging.getLogger(__name__)

_MAX_RESPONSE = 8000
_SOMER_DIR = os.path.expanduser("~/.somer")


def _truncate(text: str, max_len: int = _MAX_RESPONSE) -> str:
    if len(text) > max_len:
        return text[:max_len] + "\n...(truncado)"
    return text


# ── Database helpers ─────────────────────────────────────────


def _get_crm_db() -> sqlite3.Connection:
    """Abre/crea la base CRM."""
    os.makedirs(_SOMER_DIR, exist_ok=True)
    db_path = os.path.join(_SOMER_DIR, "crm.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT,
        phone TEXT,
        company TEXT,
        tags TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        pipeline_stage TEXT DEFAULT 'lead',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS interactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contact_id INTEGER NOT NULL,
        type TEXT NOT NULL,
        content TEXT NOT NULL,
        date TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (contact_id) REFERENCES contacts(id)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS followups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contact_id INTEGER,
        description TEXT NOT NULL,
        due_date TEXT NOT NULL,
        priority TEXT DEFAULT 'normal',
        completed INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    # Migración multi-usuario: agregar user_id si no existe
    for table in ("contacts", "followups", "interactions"):
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN user_id TEXT DEFAULT 'default'")
            conn.commit()
        except Exception:
            pass  # columna ya existe
        conn.execute(f"UPDATE {table} SET user_id = 'default' WHERE user_id IS NULL")
    conn.commit()
    return conn


def _get_finance_db() -> sqlite3.Connection:
    """Abre/crea la base de finanzas."""
    os.makedirs(_SOMER_DIR, exist_ok=True)
    db_path = os.path.join(_SOMER_DIR, "finance.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT NOT NULL CHECK(type IN ('expense', 'income')),
        amount REAL NOT NULL,
        currency TEXT DEFAULT 'USD',
        category TEXT DEFAULT 'otros',
        description TEXT,
        source TEXT,
        payment_method TEXT,
        date TEXT DEFAULT CURRENT_TIMESTAMP,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS debts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        person TEXT NOT NULL,
        amount REAL NOT NULL,
        currency TEXT DEFAULT 'USD',
        concept TEXT,
        direction TEXT NOT NULL CHECK(direction IN ('me_deben', 'debo')),
        settled INTEGER DEFAULT 0,
        date TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS budgets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT NOT NULL,
        monthly_limit REAL NOT NULL,
        currency TEXT DEFAULT 'USD',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    for table in ("transactions", "debts", "budgets"):
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN user_id TEXT DEFAULT 'default'")
            conn.commit()
        except Exception:
            pass
        conn.execute(f"UPDATE {table} SET user_id = 'default' WHERE user_id IS NULL")
    conn.commit()
    return conn


def _get_meetings_db() -> sqlite3.Connection:
    """Abre/crea la base de reuniones."""
    os.makedirs(_SOMER_DIR, exist_ok=True)
    db_path = os.path.join(_SOMER_DIR, "meetings.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS meetings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        attendees TEXT,
        topics TEXT,
        agreements TEXT,
        action_items TEXT,
        raw_notes TEXT,
        date TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS action_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        meeting_id INTEGER,
        assignee TEXT,
        description TEXT NOT NULL,
        due_date TEXT,
        completed INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (meeting_id) REFERENCES meetings(id)
    )""")
    conn.commit()
    try:
        conn.execute("ALTER TABLE meetings ADD COLUMN user_id TEXT DEFAULT 'default'")
        conn.commit()
    except Exception:
        pass
    conn.execute("UPDATE meetings SET user_id = 'default' WHERE user_id IS NULL")
    conn.commit()
    try:
        conn.execute("ALTER TABLE action_items ADD COLUMN user_id TEXT DEFAULT 'default'")
        conn.commit()
    except Exception:
        pass
    conn.execute("UPDATE action_items SET user_id = 'default' WHERE user_id IS NULL")
    conn.commit()
    return conn


# ── CRM Handlers ─────────────────────────────────────────────


async def _crm_add_contact_handler(args: Dict[str, Any]) -> str:
    """Crear/actualizar contacto."""
    name = args.get("name", "").strip()
    if not name:
        return "Error: name es requerido"

    uid = get_current_user_id()
    conn = _get_crm_db()
    try:
        # Check if exists
        existing = conn.execute("SELECT id FROM contacts WHERE name = ? AND user_id = ?", (name, uid)).fetchone()
        if existing:
            updates = []
            values = []
            for field in ("email", "phone", "company", "tags", "notes", "pipeline_stage"):
                if args.get(field):
                    updates.append(f"{field} = ?")
                    values.append(args[field])
            if updates:
                updates.append("updated_at = ?")
                values.append(datetime.now().isoformat())
                values.append(existing["id"])
                conn.execute(f"UPDATE contacts SET {', '.join(updates)} WHERE id = ? AND user_id = '{uid}'", values)
                conn.commit()
            contact = dict(conn.execute("SELECT * FROM contacts WHERE id = ? AND user_id = ?", (existing["id"], uid)).fetchone())
            contact["action"] = "updated"
        else:
            conn.execute(
                "INSERT INTO contacts (name, email, phone, company, tags, notes, pipeline_stage, user_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (name, args.get("email", ""), args.get("phone", ""), args.get("company", ""),
                 args.get("tags", ""), args.get("notes", ""), args.get("pipeline_stage", "lead"), uid),
            )
            conn.commit()
            cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            contact = dict(conn.execute("SELECT * FROM contacts WHERE id = ? AND user_id = ?", (cid, uid)).fetchone())
            contact["action"] = "created"

        return json.dumps(contact, indent=2, ensure_ascii=False, default=str)
    finally:
        conn.close()


async def _crm_search_handler(args: Dict[str, Any]) -> str:
    """Buscar contactos."""
    query = args.get("query", "").strip()
    uid = get_current_user_id()
    conn = _get_crm_db()
    try:
        if query:
            rows = conn.execute(
                "SELECT * FROM contacts WHERE (name LIKE ? OR company LIKE ? OR tags LIKE ? OR email LIKE ?) AND user_id = ?",
                (f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%", uid),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM contacts WHERE user_id = ? ORDER BY updated_at DESC LIMIT 20", (uid,)).fetchall()
        contacts = [dict(r) for r in rows]
        return json.dumps({"results": contacts, "count": len(contacts)}, indent=2, ensure_ascii=False, default=str)
    finally:
        conn.close()


async def _crm_add_interaction_handler(args: Dict[str, Any]) -> str:
    """Registrar interacción con contacto."""
    contact_name = args.get("contact_name", "").strip()
    interaction_type = args.get("type", "note")
    content = args.get("content", "").strip()

    if not contact_name or not content:
        return "Error: contact_name y content son requeridos"

    uid = get_current_user_id()
    conn = _get_crm_db()
    try:
        contact = conn.execute("SELECT id, name FROM contacts WHERE name LIKE ? AND user_id = ?", (f"%{contact_name}%", uid)).fetchone()
        if not contact:
            return f"Error: contacto '{contact_name}' no encontrado"

        conn.execute(
            "INSERT INTO interactions (contact_id, type, content, user_id) VALUES (?, ?, ?, ?)",
            (contact["id"], interaction_type, content, uid),
        )
        conn.execute("UPDATE contacts SET updated_at = ? WHERE id = ?", (datetime.now().isoformat(), contact["id"]))
        conn.commit()

        total = conn.execute("SELECT COUNT(*) FROM interactions WHERE contact_id = ? AND user_id = ?", (contact["id"], uid)).fetchone()[0]
        return json.dumps({
            "contact": contact["name"],
            "type": interaction_type,
            "content": content,
            "total_interactions": total,
        }, indent=2, ensure_ascii=False)
    finally:
        conn.close()


async def _crm_get_history_handler(args: Dict[str, Any]) -> str:
    """Historial de interacciones."""
    contact_name = args.get("contact_name", "").strip()
    if not contact_name:
        return "Error: contact_name es requerido"

    uid = get_current_user_id()
    conn = _get_crm_db()
    try:
        contact = conn.execute("SELECT * FROM contacts WHERE name LIKE ? AND user_id = ?", (f"%{contact_name}%", uid)).fetchone()
        if not contact:
            return f"Error: contacto '{contact_name}' no encontrado"

        interactions = conn.execute(
            "SELECT * FROM interactions WHERE contact_id = ? AND user_id = ? ORDER BY date DESC LIMIT 20",
            (contact["id"], uid),
        ).fetchall()

        followups = conn.execute(
            "SELECT * FROM followups WHERE contact_id = ? AND completed = 0 ORDER BY due_date",
            (contact["id"],),
        ).fetchall()

        return json.dumps({
            "contact": dict(contact),
            "interactions": [dict(i) for i in interactions],
            "pending_followups": [dict(f) for f in followups],
        }, indent=2, ensure_ascii=False, default=str)
    finally:
        conn.close()


async def _crm_add_followup_handler(args: Dict[str, Any]) -> str:
    """Programar seguimiento."""
    description = args.get("description", "").strip()
    due_date = args.get("due_date", "")
    contact_name = args.get("contact_name", "")
    priority = args.get("priority", "normal")

    if not description:
        return "Error: description es requerido"

    uid = get_current_user_id()
    conn = _get_crm_db()
    try:
        contact_id = None
        if contact_name:
            contact = conn.execute("SELECT id FROM contacts WHERE name LIKE ? AND user_id = ?", (f"%{contact_name}%", uid)).fetchone()
            if contact:
                contact_id = contact["id"]

        conn.execute(
            "INSERT INTO followups (contact_id, description, due_date, priority, user_id) VALUES (?, ?, ?, ?, ?)",
            (contact_id, description, due_date or date.today().isoformat(), priority, uid),
        )
        conn.commit()
        return json.dumps({"created": True, "description": description, "due_date": due_date, "priority": priority})
    finally:
        conn.close()


async def _crm_list_followups_handler(args: Dict[str, Any]) -> str:
    """Listar seguimientos pendientes."""
    period = args.get("period", "week")
    uid = get_current_user_id()
    conn = _get_crm_db()
    try:
        today = date.today().isoformat()
        if period == "today":
            rows = conn.execute(
                "SELECT f.*, c.name as contact_name FROM followups f LEFT JOIN contacts c ON f.contact_id = c.id "
                "WHERE f.completed = 0 AND f.due_date <= ? AND f.user_id = ? ORDER BY f.due_date", (today, uid)
            ).fetchall()
        elif period == "overdue":
            rows = conn.execute(
                "SELECT f.*, c.name as contact_name FROM followups f LEFT JOIN contacts c ON f.contact_id = c.id "
                "WHERE f.completed = 0 AND f.due_date < ? AND f.user_id = ? ORDER BY f.due_date", (today, uid)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT f.*, c.name as contact_name FROM followups f LEFT JOIN contacts c ON f.contact_id = c.id "
                "WHERE f.completed = 0 AND f.user_id = ? ORDER BY f.due_date LIMIT 30", (uid,)
            ).fetchall()

        followups = [dict(r) for r in rows]
        overdue = [f for f in followups if f.get("due_date", "") < today]
        return json.dumps({
            "followups": followups,
            "total": len(followups),
            "overdue": len(overdue),
        }, indent=2, ensure_ascii=False, default=str)
    finally:
        conn.close()


async def _crm_update_pipeline_handler(args: Dict[str, Any]) -> str:
    """Mover contacto en pipeline."""
    contact_name = args.get("contact_name", "").strip()
    stage = args.get("stage", "").strip()

    valid_stages = ["lead", "contactado", "propuesta", "negociación", "cerrado_ganado", "cerrado_perdido"]
    if stage not in valid_stages:
        return f"Error: stage debe ser uno de: {', '.join(valid_stages)}"

    uid = get_current_user_id()
    conn = _get_crm_db()
    try:
        contact = conn.execute("SELECT * FROM contacts WHERE name LIKE ? AND user_id = ?", (f"%{contact_name}%", uid)).fetchone()
        if not contact:
            return f"Error: contacto '{contact_name}' no encontrado"

        old_stage = contact["pipeline_stage"]
        conn.execute(
            "UPDATE contacts SET pipeline_stage = ?, updated_at = ? WHERE id = ? AND user_id = ?",
            (stage, datetime.now().isoformat(), contact["id"], uid),
        )
        conn.commit()
        return json.dumps({"contact": contact["name"], "old_stage": old_stage, "new_stage": stage})
    finally:
        conn.close()


async def _crm_dashboard_handler(args: Dict[str, Any]) -> str:
    """Dashboard CRM."""
    uid = get_current_user_id()
    conn = _get_crm_db()
    try:
        total = conn.execute("SELECT COUNT(*) FROM contacts WHERE user_id = ?", (uid,)).fetchone()[0]
        pipeline = {}
        for row in conn.execute("SELECT pipeline_stage, COUNT(*) as count FROM contacts WHERE user_id = ? GROUP BY pipeline_stage", (uid,)):
            pipeline[row["pipeline_stage"]] = row["count"]

        today = date.today().isoformat()
        overdue_followups = conn.execute(
            "SELECT COUNT(*) FROM followups WHERE completed = 0 AND due_date < ? AND user_id = ?", (today, uid)
        ).fetchone()[0]
        today_followups = conn.execute(
            "SELECT COUNT(*) FROM followups WHERE completed = 0 AND due_date = ? AND user_id = ?", (today, uid)
        ).fetchone()[0]

        recent = conn.execute(
            "SELECT name, company, pipeline_stage, updated_at FROM contacts WHERE user_id = ? ORDER BY updated_at DESC LIMIT 5",
            (uid,)
        ).fetchall()

        return json.dumps({
            "total_contacts": total,
            "pipeline": pipeline,
            "followups": {"overdue": overdue_followups, "today": today_followups},
            "recent_activity": [dict(r) for r in recent],
        }, indent=2, ensure_ascii=False, default=str)
    finally:
        conn.close()


# ── Finance Handlers ─────────────────────────────────────────


async def _finance_add_expense_handler(args: Dict[str, Any]) -> str:
    """Registrar gasto."""
    amount = args.get("amount")
    if not amount:
        return "Error: amount es requerido"

    uid = get_current_user_id()
    conn = _get_finance_db()
    try:
        conn.execute(
            "INSERT INTO transactions (type, amount, currency, category, description, payment_method, date, user_id) "
            "VALUES ('expense', ?, ?, ?, ?, ?, ?, ?)",
            (float(amount), args.get("currency", "USD"), args.get("category", "otros"),
             args.get("description", ""), args.get("payment_method", ""),
             args.get("date", datetime.now().isoformat()), uid),
        )
        conn.commit()
        return json.dumps({"registered": True, "type": "expense", "amount": float(amount),
                          "category": args.get("category", "otros"), "description": args.get("description", "")})
    finally:
        conn.close()


async def _finance_add_income_handler(args: Dict[str, Any]) -> str:
    """Registrar ingreso."""
    amount = args.get("amount")
    if not amount:
        return "Error: amount es requerido"

    uid = get_current_user_id()
    conn = _get_finance_db()
    try:
        conn.execute(
            "INSERT INTO transactions (type, amount, currency, category, description, source, date, user_id) "
            "VALUES ('income', ?, ?, ?, ?, ?, ?, ?)",
            (float(amount), args.get("currency", "USD"), args.get("category", "otros"),
             args.get("description", ""), args.get("source", ""),
             args.get("date", datetime.now().isoformat()), uid),
        )
        conn.commit()
        return json.dumps({"registered": True, "type": "income", "amount": float(amount),
                          "source": args.get("source", ""), "category": args.get("category", "otros")})
    finally:
        conn.close()


async def _finance_add_debt_handler(args: Dict[str, Any]) -> str:
    """Registrar deuda."""
    person = args.get("person", "").strip()
    amount = args.get("amount")
    direction = args.get("direction", "me_deben")

    if not person or not amount:
        return "Error: person y amount son requeridos"

    uid = get_current_user_id()
    conn = _get_finance_db()
    try:
        conn.execute(
            "INSERT INTO debts (person, amount, currency, concept, direction, user_id) VALUES (?, ?, ?, ?, ?, ?)",
            (person, float(amount), args.get("currency", "USD"), args.get("concept", ""), direction, uid),
        )
        conn.commit()
        return json.dumps({"registered": True, "person": person, "amount": float(amount), "direction": direction})
    finally:
        conn.close()


async def _finance_get_summary_handler(args: Dict[str, Any]) -> str:
    """Resumen financiero por período."""
    period = args.get("period", "month")

    uid = get_current_user_id()
    conn = _get_finance_db()
    try:
        now = datetime.now()
        if period == "day":
            date_filter = now.strftime("%Y-%m-%d")
            where = f"date LIKE '{date_filter}%'"
        elif period == "week":
            from_date = (now.replace(hour=0, minute=0, second=0) - __import__("datetime").timedelta(days=now.weekday())).isoformat()
            where = f"date >= '{from_date}'"
        elif period == "year":
            where = f"date LIKE '{now.year}-%'"
        else:  # month
            where = f"date LIKE '{now.strftime('%Y-%m')}%'"

        income = conn.execute(f"SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE type = 'income' AND user_id = ? AND {where}", (uid,)).fetchone()[0]
        expenses = conn.execute(f"SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE type = 'expense' AND user_id = ? AND {where}", (uid,)).fetchone()[0]

        by_category = conn.execute(
            f"SELECT category, type, SUM(amount) as total FROM transactions WHERE user_id = ? AND {where} GROUP BY category, type ORDER BY total DESC",
            (uid,)
        ).fetchall()

        # Debts summary
        owed_to_me = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM debts WHERE direction = 'me_deben' AND settled = 0 AND user_id = ?", (uid,)).fetchone()[0]
        i_owe = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM debts WHERE direction = 'debo' AND settled = 0 AND user_id = ?", (uid,)).fetchone()[0]

        return json.dumps({
            "period": period,
            "income": round(income, 2),
            "expenses": round(expenses, 2),
            "balance": round(income - expenses, 2),
            "by_category": [{"category": r["category"], "type": r["type"], "total": round(r["total"], 2)} for r in by_category],
            "debts": {"owed_to_me": round(owed_to_me, 2), "i_owe": round(i_owe, 2)},
        }, indent=2, ensure_ascii=False)
    finally:
        conn.close()


async def _finance_by_category_handler(args: Dict[str, Any]) -> str:
    """Desglose por categoría."""
    tx_type = args.get("type", "expense")
    period = args.get("period", "month")

    uid = get_current_user_id()
    conn = _get_finance_db()
    try:
        now = datetime.now()
        where = f"date LIKE '{now.strftime('%Y-%m')}%'" if period == "month" else f"date LIKE '{now.year}-%'"
        rows = conn.execute(
            f"SELECT category, SUM(amount) as total, COUNT(*) as count FROM transactions "
            f"WHERE type = ? AND user_id = ? AND {where} GROUP BY category ORDER BY total DESC",
            (tx_type, uid),
        ).fetchall()
        total = sum(r["total"] for r in rows)
        categories = [{
            "category": r["category"],
            "total": round(r["total"], 2),
            "count": r["count"],
            "percentage": round(r["total"] / total * 100, 1) if total else 0,
        } for r in rows]
        return json.dumps({"type": tx_type, "period": period, "categories": categories, "total": round(total, 2)}, indent=2)
    finally:
        conn.close()


async def _finance_list_debts_handler(args: Dict[str, Any]) -> str:
    """Listar deudas pendientes."""
    uid = get_current_user_id()
    conn = _get_finance_db()
    try:
        rows = conn.execute("SELECT * FROM debts WHERE settled = 0 AND user_id = ? ORDER BY date DESC", (uid,)).fetchall()
        debts = [dict(r) for r in rows]
        me_deben = [d for d in debts if d["direction"] == "me_deben"]
        debo = [d for d in debts if d["direction"] == "debo"]
        return json.dumps({
            "me_deben": me_deben,
            "total_me_deben": round(sum(d["amount"] for d in me_deben), 2),
            "debo": debo,
            "total_debo": round(sum(d["amount"] for d in debo), 2),
        }, indent=2, ensure_ascii=False, default=str)
    finally:
        conn.close()


async def _finance_set_budget_handler(args: Dict[str, Any]) -> str:
    """Definir presupuesto mensual."""
    category = args.get("category", "").strip()
    limit_amount = args.get("monthly_limit")
    if not category or not limit_amount:
        return "Error: category y monthly_limit son requeridos"

    uid = get_current_user_id()
    conn = _get_finance_db()
    try:
        existing = conn.execute("SELECT id FROM budgets WHERE category = ? AND user_id = ?", (category, uid)).fetchone()
        if existing:
            conn.execute("UPDATE budgets SET monthly_limit = ? WHERE id = ? AND user_id = ?", (float(limit_amount), existing["id"], uid))
        else:
            conn.execute("INSERT INTO budgets (category, monthly_limit, user_id) VALUES (?, ?, ?)", (category, float(limit_amount), uid))
        conn.commit()
        return json.dumps({"category": category, "monthly_limit": float(limit_amount), "action": "updated" if existing else "created"})
    finally:
        conn.close()


# ── Meeting Notes Handlers ───────────────────────────────────


async def _meeting_process_handler(args: Dict[str, Any]) -> str:
    """Procesa notas de reunión y extrae estructura."""
    notes = args.get("notes", "").strip()
    title = args.get("title", "")
    if not notes:
        return "Error: notes es requerido"

    # Extraer estructura de las notas usando heurísticas
    lines = notes.split("\n")
    attendees = []
    topics = []
    agreements = []
    action_items = []

    for line in lines:
        line = line.strip()
        lower = line.lower()
        if any(kw in lower for kw in ["asistente", "participante", "reunión con", "con "]) and len(line) < 100:
            attendees.append(line)
        elif any(kw in lower for kw in ["acordamos", "acuerdo", "decidimos", "se aprobó"]):
            agreements.append(line)
        elif any(kw in lower for kw in ["tarea:", "pendiente:", "action:", "todo:", "[ ]", "hacer:"]):
            action_items.append(line)
        elif line and len(line) > 10:
            topics.append(line)

    uid = get_current_user_id()
    conn = _get_meetings_db()
    try:
        conn.execute(
            "INSERT INTO meetings (title, attendees, topics, agreements, action_items, raw_notes, user_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (title or f"Reunión {datetime.now().strftime('%d/%b/%Y')}",
             json.dumps(attendees), json.dumps(topics[:10]),
             json.dumps(agreements), json.dumps(action_items), notes, uid),
        )
        meeting_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Crear action items
        for item in action_items:
            conn.execute(
                "INSERT INTO action_items (meeting_id, description, user_id) VALUES (?, ?, ?)",
                (meeting_id, item, uid),
            )
        conn.commit()

        return json.dumps({
            "meeting_id": meeting_id,
            "title": title,
            "attendees": attendees,
            "topics": topics[:10],
            "agreements": agreements,
            "action_items": action_items,
            "note": "Usa meeting_dispatch_actions para distribuir los action items a Trello/CRM/Calendar",
        }, indent=2, ensure_ascii=False)
    finally:
        conn.close()


async def _meeting_dispatch_handler(args: Dict[str, Any]) -> str:
    """Distribuye action items a otras skills."""
    meeting_id = args.get("meeting_id")
    if not meeting_id:
        return "Error: meeting_id es requerido"

    uid = get_current_user_id()
    conn = _get_meetings_db()
    try:
        meeting = conn.execute("SELECT * FROM meetings WHERE id = ? AND user_id = ?", (meeting_id, uid)).fetchone()
        if not meeting:
            return f"Error: reunión {meeting_id} no encontrada"

        items = conn.execute("SELECT * FROM action_items WHERE meeting_id = ? AND user_id = ?", (meeting_id, uid)).fetchall()

        dispatched = {
            "trello": [],
            "crm": [],
            "calendar": [],
            "finance": [],
        }

        for item in items:
            desc = item["description"].lower()
            # Categorizar automáticamente
            if any(kw in desc for kw in ["llamar", "contactar", "seguimiento", "enviar email"]):
                dispatched["crm"].append(item["description"])
            elif any(kw in desc for kw in ["reunión", "meeting", "agenda"]):
                dispatched["calendar"].append(item["description"])
            elif any(kw in desc for kw in ["pago", "factura", "cobrar", "precio", "$"]):
                dispatched["finance"].append(item["description"])
            else:
                dispatched["trello"].append(item["description"])

        return json.dumps({
            "meeting_id": meeting_id,
            "dispatched": dispatched,
            "note": "Los action items han sido categorizados. "
                    "El agente debe ejecutar las tools correspondientes de cada skill.",
        }, indent=2, ensure_ascii=False)
    finally:
        conn.close()


async def _meeting_list_actions_handler(args: Dict[str, Any]) -> str:
    """Lista action items pendientes."""
    uid = get_current_user_id()
    conn = _get_meetings_db()
    try:
        rows = conn.execute(
            "SELECT a.*, m.title as meeting_title FROM action_items a "
            "JOIN meetings m ON a.meeting_id = m.id "
            "WHERE a.completed = 0 AND m.user_id = ? ORDER BY a.created_at DESC LIMIT 30",
            (uid,)
        ).fetchall()
        items = [dict(r) for r in rows]
        return json.dumps({"pending_actions": items, "total": len(items)}, indent=2, ensure_ascii=False, default=str)
    finally:
        conn.close()


async def _meeting_search_handler(args: Dict[str, Any]) -> str:
    """Busca en minutas."""
    query = args.get("query", "").strip()
    if not query:
        return "Error: query es requerido"

    uid = get_current_user_id()
    conn = _get_meetings_db()
    try:
        rows = conn.execute(
            "SELECT * FROM meetings WHERE (title LIKE ? OR raw_notes LIKE ? OR attendees LIKE ?) AND user_id = ? ORDER BY date DESC LIMIT 10",
            (f"%{query}%", f"%{query}%", f"%{query}%", uid),
        ).fetchall()
        meetings = [dict(r) for r in rows]
        return json.dumps({"results": meetings, "count": len(meetings)}, indent=2, ensure_ascii=False, default=str)
    finally:
        conn.close()


# ── Registro ─────────────────────────────────────────────────


def register_business_tools(registry: ToolRegistry) -> None:
    """Registra todas las tools empresariales."""

    # ── CRM ──
    registry.register(ToolDefinition(
        id="crm_add_contact", name="crm_add_contact",
        description="Crear o actualizar un contacto en el CRM (nombre, email, empresa, tags, pipeline).",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nombre del contacto"},
                "email": {"type": "string"}, "phone": {"type": "string"},
                "company": {"type": "string"}, "tags": {"type": "string", "description": "Tags separados por coma"},
                "notes": {"type": "string"},
                "pipeline_stage": {"type": "string", "enum": ["lead", "contactado", "propuesta", "negociación", "cerrado_ganado", "cerrado_perdido"]},
            },
            "required": ["name"],
        },
        handler=_crm_add_contact_handler, section=ToolSection.BUSINESS, timeout_secs=10,
    ))

    registry.register(ToolDefinition(
        id="crm_search_contacts", name="crm_search_contacts",
        description="Buscar contactos por nombre, empresa, tag o texto libre.",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Búsqueda (nombre, empresa, tag)"}},
        },
        handler=_crm_search_handler, section=ToolSection.BUSINESS, timeout_secs=10,
    ))

    registry.register(ToolDefinition(
        id="crm_add_interaction", name="crm_add_interaction",
        description="Registrar una interacción (reunión, llamada, email, nota) con un contacto.",
        parameters={
            "type": "object",
            "properties": {
                "contact_name": {"type": "string"}, "type": {"type": "string", "enum": ["reunión", "llamada", "email", "nota"]},
                "content": {"type": "string", "description": "Contenido de la interacción"},
            },
            "required": ["contact_name", "content"],
        },
        handler=_crm_add_interaction_handler, section=ToolSection.BUSINESS, timeout_secs=10,
    ))

    registry.register(ToolDefinition(
        id="crm_get_history", name="crm_get_history",
        description="Ver historial de interacciones y seguimientos de un contacto.",
        parameters={
            "type": "object",
            "properties": {"contact_name": {"type": "string"}},
            "required": ["contact_name"],
        },
        handler=_crm_get_history_handler, section=ToolSection.BUSINESS, timeout_secs=10,
    ))

    registry.register(ToolDefinition(
        id="crm_add_followup", name="crm_add_followup",
        description="Programar un seguimiento futuro (ej: 'llamar a Juan el viernes').",
        parameters={
            "type": "object",
            "properties": {
                "description": {"type": "string"}, "due_date": {"type": "string", "description": "Fecha YYYY-MM-DD"},
                "contact_name": {"type": "string"}, "priority": {"type": "string", "enum": ["low", "normal", "high", "urgent"]},
            },
            "required": ["description"],
        },
        handler=_crm_add_followup_handler, section=ToolSection.BUSINESS, timeout_secs=10,
    ))

    registry.register(ToolDefinition(
        id="crm_list_followups", name="crm_list_followups",
        description="Listar seguimientos pendientes (hoy, esta semana, vencidos).",
        parameters={
            "type": "object",
            "properties": {"period": {"type": "string", "enum": ["today", "week", "overdue", "all"]}},
        },
        handler=_crm_list_followups_handler, section=ToolSection.BUSINESS, timeout_secs=10,
    ))

    registry.register(ToolDefinition(
        id="crm_update_pipeline", name="crm_update_pipeline",
        description="Mover contacto en el pipeline de ventas.",
        parameters={
            "type": "object",
            "properties": {
                "contact_name": {"type": "string"},
                "stage": {"type": "string", "enum": ["lead", "contactado", "propuesta", "negociación", "cerrado_ganado", "cerrado_perdido"]},
            },
            "required": ["contact_name", "stage"],
        },
        handler=_crm_update_pipeline_handler, section=ToolSection.BUSINESS, timeout_secs=10,
    ))

    registry.register(ToolDefinition(
        id="crm_dashboard", name="crm_dashboard",
        description="Dashboard CRM: contactos, pipeline, seguimientos pendientes.",
        parameters={"type": "object", "properties": {}},
        handler=_crm_dashboard_handler, section=ToolSection.BUSINESS, timeout_secs=10,
    ))

    # ── Finance ──
    registry.register(ToolDefinition(
        id="finance_add_expense", name="finance_add_expense",
        description="Registrar un gasto (monto, categoría, descripción).",
        parameters={
            "type": "object",
            "properties": {
                "amount": {"type": "number"}, "category": {"type": "string"},
                "description": {"type": "string"}, "currency": {"type": "string", "default": "USD"},
                "payment_method": {"type": "string"}, "date": {"type": "string"},
            },
            "required": ["amount"],
        },
        handler=_finance_add_expense_handler, section=ToolSection.BUSINESS, timeout_secs=10,
    ))

    registry.register(ToolDefinition(
        id="finance_add_income", name="finance_add_income",
        description="Registrar un ingreso (monto, fuente/cliente, categoría).",
        parameters={
            "type": "object",
            "properties": {
                "amount": {"type": "number"}, "source": {"type": "string"},
                "category": {"type": "string"}, "description": {"type": "string"},
                "currency": {"type": "string", "default": "USD"}, "date": {"type": "string"},
            },
            "required": ["amount"],
        },
        handler=_finance_add_income_handler, section=ToolSection.BUSINESS, timeout_secs=10,
    ))

    registry.register(ToolDefinition(
        id="finance_add_debt", name="finance_add_debt",
        description="Registrar deuda (quién debe, monto, dirección: me_deben/debo).",
        parameters={
            "type": "object",
            "properties": {
                "person": {"type": "string"}, "amount": {"type": "number"},
                "concept": {"type": "string"},
                "direction": {"type": "string", "enum": ["me_deben", "debo"]},
                "currency": {"type": "string", "default": "USD"},
            },
            "required": ["person", "amount"],
        },
        handler=_finance_add_debt_handler, section=ToolSection.BUSINESS, timeout_secs=10,
    ))

    registry.register(ToolDefinition(
        id="finance_get_summary", name="finance_get_summary",
        description="Resumen financiero por período (día/semana/mes/año): ingresos, gastos, balance.",
        parameters={
            "type": "object",
            "properties": {"period": {"type": "string", "enum": ["day", "week", "month", "year"]}},
        },
        handler=_finance_get_summary_handler, section=ToolSection.BUSINESS, timeout_secs=10,
    ))

    registry.register(ToolDefinition(
        id="finance_by_category", name="finance_by_category",
        description="Desglose de gastos/ingresos por categoría.",
        parameters={
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["expense", "income"]},
                "period": {"type": "string", "enum": ["month", "year"]},
            },
        },
        handler=_finance_by_category_handler, section=ToolSection.BUSINESS, timeout_secs=10,
    ))

    registry.register(ToolDefinition(
        id="finance_list_debts", name="finance_list_debts",
        description="Listar deudas pendientes (a favor y en contra).",
        parameters={"type": "object", "properties": {}},
        handler=_finance_list_debts_handler, section=ToolSection.BUSINESS, timeout_secs=10,
    ))

    registry.register(ToolDefinition(
        id="finance_set_budget", name="finance_set_budget",
        description="Definir presupuesto mensual por categoría.",
        parameters={
            "type": "object",
            "properties": {
                "category": {"type": "string"}, "monthly_limit": {"type": "number"},
            },
            "required": ["category", "monthly_limit"],
        },
        handler=_finance_set_budget_handler, section=ToolSection.BUSINESS, timeout_secs=10,
    ))

    # ── Meeting Notes ──
    registry.register(ToolDefinition(
        id="meeting_process_notes", name="meeting_process_notes",
        description="Procesa notas de reunión — extrae asistentes, temas, acuerdos y action items.",
        parameters={
            "type": "object",
            "properties": {
                "notes": {"type": "string", "description": "Texto de las notas de reunión"},
                "title": {"type": "string", "description": "Título de la reunión"},
            },
            "required": ["notes"],
        },
        handler=_meeting_process_handler, section=ToolSection.BUSINESS, timeout_secs=10,
    ))

    registry.register(ToolDefinition(
        id="meeting_dispatch_actions", name="meeting_dispatch_actions",
        description="Distribuye action items de una reunión a Trello, CRM, Calendar y Finance.",
        parameters={
            "type": "object",
            "properties": {"meeting_id": {"type": "integer"}},
            "required": ["meeting_id"],
        },
        handler=_meeting_dispatch_handler, section=ToolSection.BUSINESS, timeout_secs=10,
    ))

    registry.register(ToolDefinition(
        id="meeting_list_actions", name="meeting_list_actions",
        description="Lista action items pendientes de todas las reuniones.",
        parameters={"type": "object", "properties": {}},
        handler=_meeting_list_actions_handler, section=ToolSection.BUSINESS, timeout_secs=10,
    ))

    registry.register(ToolDefinition(
        id="meeting_search", name="meeting_search",
        description="Busca en minutas anteriores por participante, tema o fecha.",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        handler=_meeting_search_handler, section=ToolSection.BUSINESS, timeout_secs=10,
    ))
