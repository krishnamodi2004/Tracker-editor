import sqlite3
import os
import json
from datetime import datetime

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

        CREATE INDEX IF NOT EXISTS idx_activity_editor ON activity_logs(editor_id);
        CREATE INDEX IF NOT EXISTS idx_activity_time ON activity_logs(start_time);
        CREATE INDEX IF NOT EXISTS idx_screenshots_editor ON screenshots(editor_id);
    """)
    conn.commit()
    conn.close()
