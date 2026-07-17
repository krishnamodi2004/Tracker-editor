import sqlite3
import os
import json
from datetime import datetime, date, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "tracker.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS editors (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            last_seen TEXT,
            status TEXT DEFAULT 'offline'
        );

        CREATE TABLE IF NOT EXISTS activity_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            editor_id TEXT NOT NULL,
            app_name TEXT NOT NULL,
            window_title TEXT,
            start_time TEXT NOT NULL,
            duration_seconds INTEGER DEFAULT 0,
            is_idle INTEGER DEFAULT 0,
            FOREIGN KEY (editor_id) REFERENCES editors(id)
        );

        CREATE TABLE IF NOT EXISTS screenshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            editor_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            filename TEXT NOT NULL,
            FOREIGN KEY (editor_id) REFERENCES editors(id)
        );

        -- Invite tokens bind a pre-created editor row to a not-yet-installed tracker
        -- instance. The token itself is the long-lived bearer credential the tracker
        -- uses forever after activation -- there is no separate secret-rotation table.
        -- To revoke, flip status to 'revoked' and issue a fresh invite for the same
        -- editor_id; require_editor() only accepts status='activated'.
        CREATE TABLE IF NOT EXISTS invites (
            token TEXT PRIMARY KEY,
            editor_id TEXT NOT NULL,
            status TEXT DEFAULT 'pending',     -- pending | downloaded | activated | revoked
            created_at TEXT NOT NULL,
            downloaded_at TEXT,
            activated_at TEXT,
            FOREIGN KEY (editor_id) REFERENCES editors(id)
        );

        CREATE INDEX IF NOT EXISTS idx_activity_editor ON activity_logs(editor_id);
        CREATE INDEX IF NOT EXISTS idx_activity_time ON activity_logs(start_time);
        CREATE INDEX IF NOT EXISTS idx_screenshots_editor ON screenshots(editor_id);
        CREATE INDEX IF NOT EXISTS idx_invites_editor ON invites(editor_id);
        CREATE INDEX IF NOT EXISTS idx_invites_status ON invites(status);

        -- Studio Console tables --

        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            contact TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            platform TEXT DEFAULT '',
            active INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            FOREIGN KEY (client_id) REFERENCES clients(id)
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            assignee_id TEXT,
            status TEXT DEFAULT 'todo',        -- todo | in_progress | review | delivered
            priority TEXT DEFAULT 'medium',    -- low | medium | high | urgent
            due_date TEXT,
            asset_link TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            delivered_at TEXT,
            FOREIGN KEY (project_id) REFERENCES projects(id),
            FOREIGN KEY (assignee_id) REFERENCES editors(id)
        );

        -- amounts stored as integer paise (Rs 1 = 100) to avoid float drift
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            category TEXT NOT NULL,            -- software | salaries | equipment | rent | marketing | misc
            payee TEXT NOT NULL,
            amount_paise INTEGER NOT NULL,
            notes TEXT DEFAULT '',
            recurring TEXT,                    -- NULL | weekly | monthly | yearly
            series_id INTEGER,                 -- groups auto-generated recurring entries
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS income (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER NOT NULL,
            description TEXT DEFAULT '',
            amount_paise INTEGER NOT NULL,
            invoice_date TEXT NOT NULL,
            due_date TEXT,
            status TEXT DEFAULT 'draft',       -- draft | sent | paid
            paid_date TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (client_id) REFERENCES clients(id)
        );

        CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);
        CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
        CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(date);
        CREATE INDEX IF NOT EXISTS idx_income_date ON income(invoice_date);
    """)
    conn.commit()
    conn.close()
    seed_console_data()


def seed_console_data():
    """Seed starter clients, editors, projects, tasks and ledger entries.

    Runs only when the clients table is empty, so real data is never touched.
    """
    conn = get_db()
    if conn.execute("SELECT COUNT(*) AS n FROM clients").fetchone()["n"] > 0:
        conn.close()
        return

    now = datetime.utcnow().isoformat()
    today = date.today()

    def d(days):
        return (today + timedelta(days=days)).isoformat()

    clients = [
        ("Northwind Fitness", "priyanka@northwindfit.in"),
        ("Kavi & Co.", "kavi@kaviandco.com"),
        ("Bloom Beauty", "hello@bloombeauty.in"),
    ]
    client_ids = []
    for name, contact in clients:
        cur = conn.execute(
            "INSERT INTO clients (name, contact, created_at) VALUES (?, ?, ?)",
            (name, contact, now),
        )
        client_ids.append(cur.lastrowid)

    if conn.execute("SELECT COUNT(*) AS n FROM editors").fetchone()["n"] == 0:
        for eid, name in [("seed-adit", "Aditi"), ("seed-rahl", "Rahul"), ("seed-priy", "Priya")]:
            conn.execute(
                "INSERT INTO editors (id, name, last_seen, status) VALUES (?, ?, NULL, 'offline')",
                (eid, name),
            )

    editor_ids = [r["id"] for r in conn.execute("SELECT id FROM editors ORDER BY name").fetchall()]

    projects = [
        (client_ids[0], "Monthly Reels", "Instagram"),
        (client_ids[0], "YouTube Series", "YouTube"),
        (client_ids[1], "Ad Campaign Q3", "Meta Ads"),
        (client_ids[2], "Product Launch Videos", "Instagram"),
    ]
    project_ids = []
    for cid, name, platform in projects:
        cur = conn.execute(
            "INSERT INTO projects (client_id, name, platform, active, created_at) VALUES (?, ?, ?, 1, ?)",
            (cid, name, platform, now),
        )
        project_ids.append(cur.lastrowid)

    def editor(i):
        return editor_ids[i % len(editor_ids)] if editor_ids else None

    tasks = [
        (project_ids[0], "Rough cut — Reel 14", editor(0), "in_progress", "high", d(2)),
        (project_ids[0], "Colour grade — Reel 13", editor(1), "review", "medium", d(1)),
        (project_ids[1], "Add captions — Episode 22", editor(1), "in_progress", "medium", d(3)),
        (project_ids[1], "Thumbnail options — Episode 22", editor(2), "todo", "low", d(5)),
        (project_ids[2], "Colour grade — Ad v2", editor(0), "in_progress", "urgent", d(-1)),
        (project_ids[2], "Cutdowns 15s / 30s — Ad v2", editor(2), "todo", "high", d(4)),
        (project_ids[3], "Teaser edit — Launch film", editor(0), "todo", "medium", d(7)),
        (project_ids[3], "Deliver final — Brand intro", editor(1), "delivered", "medium", d(-3)),
    ]
    for pid, title, aid, status, priority, due in tasks:
        conn.execute(
            """INSERT INTO tasks (project_id, title, assignee_id, status, priority, due_date,
               asset_link, created_at, delivered_at) VALUES (?, ?, ?, ?, ?, ?, '', ?, ?)""",
            (pid, title, aid, status, priority, due, now, now if status == "delivered" else None),
        )

    month_start = today.replace(day=1).isoformat()
    expenses = [
        (month_start, "software", "Adobe Creative Cloud", 4_600_00, "Team plan", "monthly"),
        (month_start, "software", "Frame.io", 1_250_00, "", "monthly"),
        (month_start, "salaries", "Editor salaries", 80_000_00, "Aditi + Rahul + Priya", "monthly"),
        (d(-10), "equipment", "SSD — Samsung T7 2TB", 14_500_00, "Footage drive", None),
        (d(-4), "marketing", "Instagram ads", 3_000_00, "Agency promo", None),
    ]
    for edate, cat, payee, amount, notes, recurring in expenses:
        cur = conn.execute(
            """INSERT INTO expenses (date, category, payee, amount_paise, notes, recurring, series_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, NULL, ?)""",
            (edate, cat, payee, amount, notes, recurring, now),
        )
        if recurring:
            conn.execute("UPDATE expenses SET series_id = ? WHERE id = ?", (cur.lastrowid, cur.lastrowid))

    income_rows = [
        (client_ids[0], "Monthly retainer — June", 45_000_00, d(-32), d(-17), "paid", d(-20)),
        (client_ids[0], "Monthly retainer — July", 45_000_00, d(-1), d(14), "sent", None),
        (client_ids[1], "Ad campaign — first batch", 28_000_00, d(-6), d(-2), "sent", None),
        (client_ids[2], "Launch videos — advance", 20_000_00, d(-12), d(-5), "paid", d(-5)),
    ]
    for cid, desc, amount, inv, due, status, paid in income_rows:
        conn.execute(
            """INSERT INTO income (client_id, description, amount_paise, invoice_date, due_date, status, paid_date, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (cid, desc, amount, inv, due, status, paid, now),
        )

    conn.commit()
    conn.close()
