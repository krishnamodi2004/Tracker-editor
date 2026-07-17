"""Studio Console API — tasks, ledger (income + expenses) and team attendance.

All routes here require the admin session cookie. Money is integer paise.
"""
import calendar
import os
import secrets
import uuid
from datetime import datetime, date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from database import get_db
from auth import require_admin, check_password, make_session_token, COOKIE_NAME, SESSION_DAYS
from categories import categorize

router = APIRouter(prefix="/api/console")
protected = APIRouter(prefix="/api/console", dependencies=[Depends(require_admin)])

PRESENT_THRESHOLD_MIN = int(os.environ.get("PRESENT_THRESHOLD_MIN", "60"))

TASK_STATUSES = {"todo", "in_progress", "review", "delivered"}
TASK_PRIORITIES = {"low", "medium", "high", "urgent"}
EXPENSE_CATEGORIES = {"software", "salaries", "equipment", "rent", "marketing", "misc"}
INCOME_STATUSES = {"draft", "sent", "paid"}
RECURRING = {"weekly", "monthly", "yearly"}


# ---------- auth ----------

class LoginBody(BaseModel):
    password: str


@router.post("/login")
def login(body: LoginBody, response: Response):
    if not check_password(body.password):
        raise HTTPException(401, "Wrong password")
    response.set_cookie(
        COOKIE_NAME,
        make_session_token(),
        max_age=SESSION_DAYS * 86400,
        httponly=True,
        samesite="lax",
    )
    return {"ok": True}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


# ---------- clients & projects ----------

class ClientBody(BaseModel):
    name: str
    contact: str = ""


class ProjectBody(BaseModel):
    client_id: int
    name: str
    platform: str = ""


@protected.get("/clients")
def list_clients():
    db = get_db()
    clients = [dict(r) for r in db.execute("SELECT * FROM clients ORDER BY name").fetchall()]
    projects = [dict(r) for r in db.execute("SELECT * FROM projects WHERE active = 1 ORDER BY name").fetchall()]
    db.close()
    for c in clients:
        c["projects"] = [p for p in projects if p["client_id"] == c["id"]]
    return clients


@protected.post("/clients")
def create_client(body: ClientBody):
    if not body.name.strip():
        raise HTTPException(400, "Client name is required")
    db = get_db()
    cur = db.execute(
        "INSERT INTO clients (name, contact, created_at) VALUES (?, ?, ?)",
        (body.name.strip(), body.contact.strip(), datetime.utcnow().isoformat()),
    )
    db.commit()
    db.close()
    return {"id": cur.lastrowid}


@protected.delete("/clients/{client_id}")
def delete_client(client_id: int):
    db = get_db()
    has_income = db.execute("SELECT COUNT(*) AS n FROM income WHERE client_id = ?", (client_id,)).fetchone()["n"]
    if has_income:
        db.close()
        raise HTTPException(400, "This client has income entries — delete those first")
    db.execute(
        "DELETE FROM tasks WHERE project_id IN (SELECT id FROM projects WHERE client_id = ?)",
        (client_id,),
    )
    db.execute("DELETE FROM projects WHERE client_id = ?", (client_id,))
    db.execute("DELETE FROM clients WHERE id = ?", (client_id,))
    db.commit()
    db.close()
    return {"ok": True}


@protected.post("/projects")
def create_project(body: ProjectBody):
    if not body.name.strip():
        raise HTTPException(400, "Project name is required")
    db = get_db()
    cur = db.execute(
        "INSERT INTO projects (client_id, name, platform, active, created_at) VALUES (?, ?, ?, 1, ?)",
        (body.client_id, body.name.strip(), body.platform.strip(), datetime.utcnow().isoformat()),
    )
    db.commit()
    db.close()
    return {"id": cur.lastrowid}


@protected.delete("/projects/{project_id}")
def delete_project(project_id: int):
    db = get_db()
    db.execute("DELETE FROM tasks WHERE project_id = ?", (project_id,))
    db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    db.commit()
    db.close()
    return {"ok": True}


# ---------- tasks ----------

class TaskBody(BaseModel):
    project_id: int
    title: str
    description: str = ""
    assignee_id: str | None = None
    status: str = "todo"
    priority: str = "medium"
    due_date: str | None = None
    asset_link: str = ""


class TaskPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    project_id: int | None = None
    assignee_id: str | None = None
    status: str | None = None
    priority: str | None = None
    due_date: str | None = None
    asset_link: str | None = None


def _task_rows(db, where="", params=()):
    return db.execute(
        f"""SELECT t.*, p.name AS project_name, p.platform, c.id AS client_id, c.name AS client_name,
                   e.name AS assignee_name
            FROM tasks t
            JOIN projects p ON p.id = t.project_id
            JOIN clients c ON c.id = p.client_id
            LEFT JOIN editors e ON e.id = t.assignee_id
            {where}
            ORDER BY c.name, t.due_date IS NULL, t.due_date""",
        params,
    ).fetchall()


def _with_overdue(rows):
    today = date.today().isoformat()
    out = []
    for r in rows:
        t = dict(r)
        t["overdue"] = bool(t["due_date"] and t["due_date"] < today and t["status"] != "delivered")
        out.append(t)
    return out


@protected.get("/tasks")
def list_tasks():
    db = get_db()
    rows = _task_rows(db)
    db.close()
    return _with_overdue(rows)


@protected.post("/tasks")
def create_task(body: TaskBody):
    if not body.title.strip():
        raise HTTPException(400, "Task title is required")
    if body.status not in TASK_STATUSES or body.priority not in TASK_PRIORITIES:
        raise HTTPException(400, "Invalid status or priority")
    db = get_db()
    cur = db.execute(
        """INSERT INTO tasks (project_id, title, description, assignee_id, status, priority,
           due_date, asset_link, created_at, delivered_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            body.project_id, body.title.strip(), body.description, body.assignee_id or None,
            body.status, body.priority, body.due_date or None, body.asset_link.strip(),
            datetime.utcnow().isoformat(),
            datetime.utcnow().isoformat() if body.status == "delivered" else None,
        ),
    )
    db.commit()
    db.close()
    return {"id": cur.lastrowid}


@protected.patch("/tasks/{task_id}")
def update_task(task_id: int, body: TaskPatch):
    fields = body.model_dump(exclude_unset=True)
    if "status" in fields and fields["status"] not in TASK_STATUSES:
        raise HTTPException(400, "Invalid status")
    if "priority" in fields and fields["priority"] not in TASK_PRIORITIES:
        raise HTTPException(400, "Invalid priority")
    if not fields:
        return {"ok": True}
    if fields.get("status") == "delivered":
        fields["delivered_at"] = datetime.utcnow().isoformat()
    elif "status" in fields:
        fields["delivered_at"] = None
    db = get_db()
    sets = ", ".join(f"{k} = ?" for k in fields)
    db.execute(f"UPDATE tasks SET {sets} WHERE id = ?", (*fields.values(), task_id))
    db.commit()
    db.close()
    return {"ok": True}


@protected.delete("/tasks/{task_id}")
def delete_task(task_id: int):
    db = get_db()
    db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    db.commit()
    db.close()
    return {"ok": True}


# ---------- ledger: expenses & income ----------

class ExpenseBody(BaseModel):
    date: str
    category: str
    payee: str
    amount_paise: int
    notes: str = ""
    recurring: str | None = None


class ExpensePatch(BaseModel):
    date: str | None = None
    category: str | None = None
    payee: str | None = None
    amount_paise: int | None = None
    notes: str | None = None


class IncomeBody(BaseModel):
    client_id: int
    description: str = ""
    amount_paise: int
    invoice_date: str
    due_date: str | None = None
    status: str = "draft"


class IncomePatch(BaseModel):
    description: str | None = None
    amount_paise: int | None = None
    invoice_date: str | None = None
    due_date: str | None = None
    status: str | None = None


def _next_date(d: date, freq: str) -> date:
    if freq == "weekly":
        return d + timedelta(days=7)
    if freq == "monthly":
        year, month = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
        return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))
    year = d.year + 1
    return date(year, d.month, min(d.day, calendar.monthrange(year, d.month)[1]))


def materialize_recurring(db):
    """Create this period's copy of every recurring expense series, catching up
    any missed periods since the server last looked."""
    today = date.today()
    series = db.execute(
        """SELECT series_id, MAX(date) AS last_date FROM expenses
           WHERE recurring IS NOT NULL AND series_id IS NOT NULL GROUP BY series_id"""
    ).fetchall()
    for s in series:
        template = db.execute(
            "SELECT * FROM expenses WHERE series_id = ? AND recurring IS NOT NULL ORDER BY date DESC LIMIT 1",
            (s["series_id"],),
        ).fetchone()
        if not template:
            continue
        nxt = _next_date(date.fromisoformat(s["last_date"]), template["recurring"])
        while nxt <= today:
            db.execute(
                """INSERT INTO expenses (date, category, payee, amount_paise, notes, recurring, series_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    nxt.isoformat(), template["category"], template["payee"], template["amount_paise"],
                    template["notes"], template["recurring"], s["series_id"], datetime.utcnow().isoformat(),
                ),
            )
            nxt = _next_date(nxt, template["recurring"])
    db.commit()


def _month_bounds(month: str):
    y, m = int(month[:4]), int(month[5:7])
    start = date(y, m, 1)
    end = date(y, m, calendar.monthrange(y, m)[1])
    return start.isoformat(), end.isoformat()


@protected.get("/ledger")
def get_ledger(month: str | None = None):
    if month is None:
        month = date.today().strftime("%Y-%m")
    start, end = _month_bounds(month)
    today = date.today().isoformat()

    db = get_db()
    materialize_recurring(db)

    expenses = [dict(r) for r in db.execute(
        "SELECT * FROM expenses WHERE date BETWEEN ? AND ? ORDER BY date DESC, id DESC", (start, end)
    ).fetchall()]

    income = []
    for r in db.execute(
        """SELECT i.*, c.name AS client_name FROM income i JOIN clients c ON c.id = i.client_id
           WHERE i.invoice_date BETWEEN ? AND ? ORDER BY i.invoice_date DESC, i.id DESC""",
        (start, end),
    ).fetchall():
        row = dict(r)
        row["overdue"] = bool(row["status"] == "sent" and row["due_date"] and row["due_date"] < today)
        income.append(row)

    # six-month series ending at the requested month, for the chart
    y, m = int(month[:4]), int(month[5:7])
    months = []
    for _ in range(6):
        months.append(f"{y:04d}-{m:02d}")
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    months.reverse()

    series = []
    for mo in months:
        s, e = _month_bounds(mo)
        inc = db.execute(
            "SELECT COALESCE(SUM(amount_paise),0) AS v FROM income WHERE invoice_date BETWEEN ? AND ?", (s, e)
        ).fetchone()["v"]
        exp = db.execute(
            "SELECT COALESCE(SUM(amount_paise),0) AS v FROM expenses WHERE date BETWEEN ? AND ?", (s, e)
        ).fetchone()["v"]
        series.append({"month": mo, "income": inc, "expenses": exp})

    pending = db.execute(
        "SELECT COALESCE(SUM(amount_paise),0) AS v FROM income WHERE status = 'sent'"
    ).fetchone()["v"]
    db.close()

    month_income = sum(i["amount_paise"] for i in income)
    month_expenses = sum(e["amount_paise"] for e in expenses)
    return {
        "month": month,
        "expenses": expenses,
        "income": income,
        "summary": {
            "income": month_income,
            "expenses": month_expenses,
            "net": month_income - month_expenses,
            "pending_invoices": pending,
        },
        "series": series,
    }


@protected.post("/expenses")
def create_expense(body: ExpenseBody):
    if body.category not in EXPENSE_CATEGORIES:
        raise HTTPException(400, "Invalid category")
    if body.recurring is not None and body.recurring not in RECURRING:
        raise HTTPException(400, "Invalid recurring value")
    if body.amount_paise <= 0:
        raise HTTPException(400, "Amount must be positive")
    db = get_db()
    cur = db.execute(
        """INSERT INTO expenses (date, category, payee, amount_paise, notes, recurring, series_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?, NULL, ?)""",
        (body.date, body.category, body.payee.strip(), body.amount_paise, body.notes,
         body.recurring, datetime.utcnow().isoformat()),
    )
    if body.recurring:
        db.execute("UPDATE expenses SET series_id = ? WHERE id = ?", (cur.lastrowid, cur.lastrowid))
    db.commit()
    db.close()
    return {"id": cur.lastrowid}


@protected.patch("/expenses/{expense_id}")
def update_expense(expense_id: int, body: ExpensePatch):
    fields = body.model_dump(exclude_unset=True)
    if "category" in fields and fields["category"] not in EXPENSE_CATEGORIES:
        raise HTTPException(400, "Invalid category")
    if not fields:
        return {"ok": True}
    db = get_db()
    sets = ", ".join(f"{k} = ?" for k in fields)
    db.execute(f"UPDATE expenses SET {sets} WHERE id = ?", (*fields.values(), expense_id))
    db.commit()
    db.close()
    return {"ok": True}


@protected.post("/expenses/{expense_id}/stop-recurring")
def stop_recurring(expense_id: int):
    db = get_db()
    row = db.execute("SELECT series_id FROM expenses WHERE id = ?", (expense_id,)).fetchone()
    if not row or row["series_id"] is None:
        db.close()
        raise HTTPException(404, "Not a recurring expense")
    db.execute("UPDATE expenses SET recurring = NULL WHERE series_id = ?", (row["series_id"],))
    db.commit()
    db.close()
    return {"ok": True}


@protected.delete("/expenses/{expense_id}")
def delete_expense(expense_id: int):
    db = get_db()
    db.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
    db.commit()
    db.close()
    return {"ok": True}


@protected.post("/income")
def create_income(body: IncomeBody):
    if body.status not in INCOME_STATUSES:
        raise HTTPException(400, "Invalid status")
    if body.amount_paise <= 0:
        raise HTTPException(400, "Amount must be positive")
    db = get_db()
    cur = db.execute(
        """INSERT INTO income (client_id, description, amount_paise, invoice_date, due_date, status, paid_date, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (body.client_id, body.description, body.amount_paise, body.invoice_date,
         body.due_date or None, body.status,
         date.today().isoformat() if body.status == "paid" else None,
         datetime.utcnow().isoformat()),
    )
    db.commit()
    db.close()
    return {"id": cur.lastrowid}


@protected.patch("/income/{income_id}")
def update_income(income_id: int, body: IncomePatch):
    fields = body.model_dump(exclude_unset=True)
    if "status" in fields:
        if fields["status"] not in INCOME_STATUSES:
            raise HTTPException(400, "Invalid status")
        fields["paid_date"] = date.today().isoformat() if fields["status"] == "paid" else None
    if not fields:
        return {"ok": True}
    db = get_db()
    sets = ", ".join(f"{k} = ?" for k in fields)
    db.execute(f"UPDATE income SET {sets} WHERE id = ?", (*fields.values(), income_id))
    db.commit()
    db.close()
    return {"ok": True}


@protected.delete("/income/{income_id}")
def delete_income(income_id: int):
    db = get_db()
    db.execute("DELETE FROM income WHERE id = ?", (income_id,))
    db.commit()
    db.close()
    return {"ok": True}


# ---------- team & attendance ----------

class EditorBody(BaseModel):
    name: str


def _day_stats(db, day: str):
    """Per-editor activity rollup for one date (ISO)."""
    rows = db.execute(
        """SELECT editor_id,
                  MIN(start_time) AS first_seen,
                  MAX(start_time) AS last_seen,
                  SUM(CASE WHEN is_idle = 0 THEN duration_seconds ELSE 0 END) AS active_seconds,
                  SUM(CASE WHEN is_idle = 1 THEN duration_seconds ELSE 0 END) AS idle_seconds
           FROM activity_logs WHERE start_time LIKE ? GROUP BY editor_id""",
        (f"{day}%",),
    ).fetchall()
    return {r["editor_id"]: dict(r) for r in rows}


@protected.get("/team")
def get_team(days: int = 14):
    days = max(1, min(days, 60))
    today = date.today()
    db = get_db()

    cutoff = (datetime.utcnow() - timedelta(minutes=2)).isoformat()
    db.execute("UPDATE editors SET status = 'offline' WHERE last_seen < ?", (cutoff,))
    db.commit()

    editors = [dict(r) for r in db.execute("SELECT * FROM editors ORDER BY name").fetchall()]
    today_stats = _day_stats(db, today.isoformat())

    # presence grid: active seconds per editor per day for the trailing window
    since = (today - timedelta(days=days - 1)).isoformat()
    grid_rows = db.execute(
        """SELECT editor_id, substr(start_time, 1, 10) AS day,
                  SUM(CASE WHEN is_idle = 0 THEN duration_seconds ELSE 0 END) AS active_seconds
           FROM activity_logs WHERE substr(start_time, 1, 10) >= ? GROUP BY editor_id, day""",
        (since,),
    ).fetchall()
    db.close()

    grid = {}
    for r in grid_rows:
        grid.setdefault(r["editor_id"], {})[r["day"]] = r["active_seconds"]

    day_list = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    threshold = PRESENT_THRESHOLD_MIN * 60

    out = []
    for e in editors:
        stats = today_stats.get(e["id"], {})
        active = stats.get("active_seconds") or 0
        out.append({
            **e,
            "first_seen": stats.get("first_seen"),
            "last_seen_activity": stats.get("last_seen"),
            "active_seconds": active,
            "idle_seconds": stats.get("idle_seconds") or 0,
            "present": active >= threshold,
            "history": [
                {"date": d, "present": (grid.get(e["id"], {}).get(d, 0)) >= threshold}
                for d in day_list
            ],
        })
    return {"editors": out, "threshold_minutes": PRESENT_THRESHOLD_MIN, "days": day_list}


@protected.post("/editors")
def create_editor(body: EditorBody):
    if not body.name.strip():
        raise HTTPException(400, "Name is required")
    editor_id = str(uuid.uuid4())[:8]
    db = get_db()
    db.execute(
        "INSERT INTO editors (id, name, last_seen, status) VALUES (?, ?, NULL, 'offline')",
        (editor_id, body.name.strip()),
    )
    db.commit()
    db.close()
    return {"id": editor_id}


@protected.delete("/editors/{editor_id}")
def delete_editor(editor_id: str):
    db = get_db()
    db.execute("UPDATE tasks SET assignee_id = NULL WHERE assignee_id = ?", (editor_id,))
    db.execute("DELETE FROM editors WHERE id = ?", (editor_id,))
    db.commit()
    db.close()
    return {"ok": True}


# ---------- invites ----------

class InviteBody(BaseModel):
    name: str | None = None        # create a new editor + invite together
    editor_id: str | None = None   # invite an existing editor who has none yet


@protected.get("/invites")
def list_invites():
    db = get_db()
    rows = db.execute(
        """SELECT i.*, e.name AS editor_name FROM invites i
           JOIN editors e ON e.id = i.editor_id ORDER BY i.created_at DESC"""
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


@protected.post("/invites")
def create_invite(body: InviteBody):
    if not body.name and not body.editor_id:
        raise HTTPException(400, "Provide either name or editor_id")
    if body.name and body.editor_id:
        raise HTTPException(400, "Provide only one of name or editor_id")

    db = get_db()
    now = datetime.utcnow().isoformat()

    if body.name:
        if not body.name.strip():
            db.close()
            raise HTTPException(400, "Name is required")
        editor_id = str(uuid.uuid4())[:8]
        db.execute(
            "INSERT INTO editors (id, name, last_seen, status) VALUES (?, ?, NULL, 'offline')",
            (editor_id, body.name.strip()),
        )
    else:
        editor_id = body.editor_id
        row = db.execute("SELECT id FROM editors WHERE id = ?", (editor_id,)).fetchone()
        if not row:
            db.close()
            raise HTTPException(404, "Editor not found")

    token = secrets.token_hex(32)
    db.execute(
        "INSERT INTO invites (token, editor_id, status, created_at) VALUES (?, ?, 'pending', ?)",
        (token, editor_id, now),
    )
    db.commit()
    db.close()
    return {"editor_id": editor_id, "token": token, "download_path": f"/download/{token}"}


@protected.post("/invites/{token}/revoke")
def revoke_invite(token: str):
    db = get_db()
    row = db.execute("SELECT token FROM invites WHERE token = ?", (token,)).fetchone()
    if not row:
        db.close()
        raise HTTPException(404, "Invite not found")
    db.execute("UPDATE invites SET status = 'revoked' WHERE token = ?", (token,))
    db.commit()
    db.close()
    return {"ok": True}


# ---------- productivity (dashboard-only breakdown, no client changes) ----------

@protected.get("/productivity")
def get_productivity(days: int = 14, editor_id: str | None = None):
    days = max(1, min(days, 90))
    since = (date.today() - timedelta(days=days - 1)).isoformat()

    db = get_db()
    where = "WHERE substr(start_time, 1, 10) >= ? AND is_idle = 0"
    params = [since]
    if editor_id:
        where += " AND editor_id = ?"
        params.append(editor_id)

    rows = db.execute(
        f"""SELECT editor_id, app_name, SUM(duration_seconds) AS seconds
            FROM activity_logs {where} GROUP BY editor_id, app_name""",
        params,
    ).fetchall()
    names = {r["id"]: r["name"] for r in db.execute("SELECT id, name FROM editors").fetchall()}
    db.close()

    per_editor: dict[str, dict[str, int]] = {}
    totals: dict[str, int] = {}
    for r in rows:
        cat = categorize(r["app_name"])
        per_editor.setdefault(r["editor_id"], {}).setdefault(cat, 0)
        per_editor[r["editor_id"]][cat] += r["seconds"]
        totals[cat] = totals.get(cat, 0) + r["seconds"]

    return {
        "days": days,
        "totals": totals,
        "by_editor": [
            {"editor_id": eid, "name": names.get(eid, eid), "categories": cats}
            for eid, cats in per_editor.items()
        ],
    }


# ---------- overview ----------

@protected.get("/overview")
def get_overview():
    today = date.today()
    db = get_db()
    materialize_recurring(db)

    editors = db.execute("SELECT id FROM editors").fetchall()
    today_stats = _day_stats(db, today.isoformat())
    threshold = PRESENT_THRESHOLD_MIN * 60
    present = sum(
        1 for e in editors if (today_stats.get(e["id"], {}).get("active_seconds") or 0) >= threshold
    )

    status_counts = {
        r["status"]: r["n"]
        for r in db.execute("SELECT status, COUNT(*) AS n FROM tasks GROUP BY status").fetchall()
    }
    overdue_rows = _with_overdue(_task_rows(db, "WHERE t.status != 'delivered'"))
    attention = [t for t in overdue_rows if t["overdue"] or t["priority"] == "urgent"]

    start, end = _month_bounds(today.strftime("%Y-%m"))
    month_income = db.execute(
        "SELECT COALESCE(SUM(amount_paise),0) AS v FROM income WHERE invoice_date BETWEEN ? AND ?", (start, end)
    ).fetchone()["v"]
    month_expenses = db.execute(
        "SELECT COALESCE(SUM(amount_paise),0) AS v FROM expenses WHERE date BETWEEN ? AND ?", (start, end)
    ).fetchone()["v"]
    pending = db.execute(
        "SELECT COALESCE(SUM(amount_paise),0) AS v FROM income WHERE status = 'sent'"
    ).fetchone()["v"]
    db.close()

    return {
        "present": present,
        "team_size": len(editors),
        "tasks": {
            "todo": status_counts.get("todo", 0),
            "in_progress": status_counts.get("in_progress", 0),
            "review": status_counts.get("review", 0),
            "delivered": status_counts.get("delivered", 0),
            "overdue": sum(1 for t in overdue_rows if t["overdue"]),
        },
        "attention": attention[:8],
        "money": {
            "income": month_income,
            "expenses": month_expenses,
            "net": month_income - month_expenses,
            "pending_invoices": pending,
        },
    }
