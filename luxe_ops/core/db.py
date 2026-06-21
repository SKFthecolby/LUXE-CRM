from contextlib import closing
import sqlite3
import pandas as pd

from .config import DB_PATH, DEFAULT_SETTINGS
from .helpers import new_id, now_ts

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS leads (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    name TEXT NOT NULL,
    phone TEXT,
    address TEXT,
    source TEXT,
    desired_frequency TEXT,
    condition TEXT,
    priority_focus TEXT,
    follow_up_date TEXT,
    status TEXT NOT NULL,
    notes TEXT,
    archived INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS clients (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    name TEXT NOT NULL,
    phone TEXT,
    address TEXT,
    frequency TEXT,
    recurring_rate REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    notes TEXT,
    archived INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    client_id TEXT NOT NULL,
    job_date TEXT NOT NULL,
    job_type TEXT NOT NULL,
    hours_estimate REAL NOT NULL DEFAULT 0,
    actual_hours REAL,
    amount REAL,
    status TEXT NOT NULL,
    notes TEXT,
    archived INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(client_id) REFERENCES clients(id)
);

CREATE TABLE IF NOT EXISTS invoices (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    client_id TEXT NOT NULL,
    job_id TEXT,
    due_date TEXT NOT NULL,
    amount REAL NOT NULL,
    status TEXT NOT NULL,
    paid_date TEXT,
    notes TEXT,
    archived INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(client_id) REFERENCES clients(id),
    FOREIGN KEY(job_id) REFERENCES jobs(id)
);

CREATE TABLE IF NOT EXISTS expenses (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    expense_date TEXT NOT NULL,
    category TEXT NOT NULL,
    vendor TEXT,
    amount REAL NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    action_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    risk TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL,
    decided_at TEXT,
    decision_note TEXT
);

CREATE TABLE IF NOT EXISTS alerts (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    level TEXT NOT NULL,
    category TEXT NOT NULL,
    message TEXT NOT NULL,
    resolved INTEGER NOT NULL DEFAULT 0,
    meta TEXT,
    archived INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    category TEXT NOT NULL,
    detail TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quotes (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_id TEXT,
    client_name TEXT NOT NULL,
    phone TEXT,
    address TEXT,
    service_type TEXT NOT NULL,
    bedrooms INTEGER NOT NULL DEFAULT 0,
    bathrooms INTEGER NOT NULL DEFAULT 0,
    living_rooms INTEGER NOT NULL DEFAULT 0,
    additional_rooms INTEGER NOT NULL DEFAULT 0,
    kitchen_size TEXT NOT NULL,
    condition TEXT NOT NULL,
    pets INTEGER NOT NULL DEFAULT 0,
    supplies INTEGER NOT NULL DEFAULT 1,
    pantry_org INTEGER NOT NULL DEFAULT 0,
    low_estimate REAL NOT NULL,
    high_estimate REAL NOT NULL,
    recommended REAL NOT NULL,
    low_hours REAL NOT NULL,
    high_hours REAL NOT NULL,
    final_amount REAL,
    status TEXT NOT NULL,
    notes TEXT,
    archived INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sms_messages (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    client_id TEXT,
    lead_id TEXT,
    phone TEXT NOT NULL,
    direction TEXT NOT NULL,
    message_type TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL,
    external_id TEXT,
    sent_at TEXT,
    error_text TEXT,
    approval_required INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS portal_access (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    client_id TEXT NOT NULL,
    access_code TEXT NOT NULL,
    status TEXT NOT NULL,
    last_used_at TEXT,
    archived INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(client_id) REFERENCES clients(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_clients_active_name
ON clients(name COLLATE NOCASE)
WHERE archived = 0;

CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_active_client_date
ON jobs(client_id, job_date)
WHERE archived = 0;

CREATE UNIQUE INDEX IF NOT EXISTS idx_portal_access_active_client
ON portal_access(client_id)
WHERE archived = 0;

CREATE UNIQUE INDEX IF NOT EXISTS idx_invoices_active_job
ON invoices(job_id)
WHERE archived = 0 AND job_id IS NOT NULL;
"""


class DB:
    def __init__(self, path: str = DB_PATH):
        self.path = path
        self._init()

    def conn(self):
        con = sqlite3.connect(self.path, check_same_thread=False)
        con.row_factory = sqlite3.Row
        return con

    def _init(self):
        with closing(self.conn()) as con:
            con.executescript(SCHEMA)
            for k, v in DEFAULT_SETTINGS.items():
                con.execute(
                    "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                    (k, v),
                )
            con.commit()

    def execute(self, sql, params=()):
        with closing(self.conn()) as con:
            con.execute(sql, params)
            con.commit()

    def fetchone(self, sql, params=()):
        with closing(self.conn()) as con:
            return con.execute(sql, params).fetchone()

    def fetchall(self, sql, params=()):
        with closing(self.conn()) as con:
            return con.execute(sql, params).fetchall()

    def fetch_df(self, sql, params=()):
        with closing(self.conn()) as con:
            return pd.read_sql_query(sql, con, params=params)

    def set_setting(self, key, value):
        self.execute(
            """
            INSERT INTO settings(key, value) VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, str(value)),
        )

    def setting(self, key):
        row = self.fetchone("SELECT value FROM settings WHERE key = ?", (key,))
        return row["value"] if row else DEFAULT_SETTINGS[key]

    def log(self, category, detail):
        self.execute(
            "INSERT INTO audit_log(id, created_at, category, detail) VALUES(?, ?, ?, ?)",
            (new_id(), now_ts(), category, detail),
        )
