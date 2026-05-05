import os
import json
import uuid
import sqlite3
from datetime import datetime, date, timedelta

import pandas as pd
import streamlit as st

DB_PATH = "luxe_ops.db"
DATE_FMT = "%Y-%m-%d"
NOW_FMT = "%Y-%m-%d %H:%M:%S"


# =========================
# CONFIG
# =========================
DEFAULT_SETTINGS = {
    "business_name": "Luxe Home Services",
    "tagline": "A higher standard of clean you can feel",
    "phone": "435-994-5348",
    "deep_clean_base_hours": "3",
    "deep_clean_base_price": "320",
    "deep_clean_overage_hourly": "75",
    "recurring_biweekly_rate": "160",
    "max_jobs_per_day": "2",
    "low_pipeline_threshold_14d": "3",
    "self_care_job_threshold_7d": "6",
    "archive_after_days": "180",
}


# =========================
# DATABASE
# =========================
class DB:
    def __init__(self, path=DB_PATH):
        self.path = path
        self._init()

    def conn(self):
        c = sqlite3.connect(self.path, check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c

    def _init(self):
        with self.conn() as con:
            con.executescript(
                """
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
                """
            )

            for k, v in DEFAULT_SETTINGS.items():
                con.execute(
                    "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                    (k, v),
                )

    def execute(self, sql, params=()):
        with self.conn() as con:
            con.execute(sql, params)
            con.commit()

    def execute_many(self, sql, seq):
        with self.conn() as con:
            con.executemany(sql, seq)
            con.commit()

    def fetchall(self, sql, params=()):
        with self.conn() as con:
            cur = con.execute(sql, params)
            return cur.fetchall()

    def fetchone(self, sql, params=()):
        with self.conn() as con:
            cur = con.execute(sql, params)
            return cur.fetchone()

    def fetch_df(self, sql, params=()):
        with self.conn() as con:
            return pd.read_sql_query(sql, con, params=params)

    def setting(self, key):
        row = self.fetchone("SELECT value FROM settings WHERE key = ?", (key,))
        return row["value"] if row else DEFAULT_SETTINGS.get(key)

    def set_setting(self, key, value):
        self.execute(
            """
            INSERT INTO settings(key, value) VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, str(value)),
        )

    def log(self, category, detail):
        self.execute(
            "INSERT INTO audit_log(id, created_at, category, detail) VALUES(?, ?, ?, ?)",
            (new_id(), now_ts(), category, detail),
        )


# =========================
# HELPERS
# =========================
def new_id():
    return str(uuid.uuid4())[:8]

def now_ts():
    return datetime.now().strftime(NOW_FMT)

def today_str():
    return date.today().strftime(DATE_FMT)

def parse_date(s):
    return datetime.strptime(s, DATE_FMT).date()

def to_csv_download(df, filename, label):
    st.download_button(label, df.to_csv(index=False).encode("utf-8"), file_name=filename, mime="text/csv")

def money(x):
    try:
        return f"${float(x):,.2f}"
    except Exception:
        return "$0.00"


# =========================
# CORE ENGINES
# =========================
class AutomationEngine:
    def __init__(self, db: DB):
        self.db = db

    def push_alert(self, level, category, message, meta=None):
        existing = self.db.fetchone(
            """
            SELECT id FROM alerts
            WHERE category = ? AND message = ? AND resolved = 0 AND archived = 0
            """,
            (category, message),
        )
        if existing:
            return
        self.db.execute(
            """
            INSERT INTO alerts(id, created_at, level, category, message, resolved, meta, archived)
            VALUES(?, ?, ?, ?, ?, 0, ?, 0)
            """,
            (new_id(), now_ts(), level, category, message, json.dumps(meta or {})),
        )

    def create_approval(self, action_type, payload, risk, reason):
        existing = self.db.fetchone(
            """
            SELECT id FROM approvals
            WHERE action_type = ? AND payload = ? AND status = 'pending'
            """,
            (action_type, json.dumps(payload, sort_keys=True)),
        )
        if existing:
            return
        self.db.execute(
            """
            INSERT INTO approvals(id, created_at, action_type, payload, risk, reason, status)
            VALUES(?, ?, ?, ?, ?, ?, 'pending')
            """,
            (new_id(), now_ts(), action_type, json.dumps(payload, sort_keys=True), risk, reason),
        )
        self.db.log("approval_created", f"{action_type}: {reason}")

    def process_approval(self, approval_id, decision, note=""):
        row = self.db.fetchone("SELECT * FROM approvals WHERE id = ?", (approval_id,))
        if not row or row["status"] != "pending":
            return "invalid"

        payload = json.loads(row["payload"])
        if decision == "approve":
            if row["action_type"] == "reschedule_job":
                self.db.execute(
                    "UPDATE jobs SET job_date = ?, status = 'scheduled' WHERE id = ?",
                    (payload["new_date"], payload["job_id"]),
                )
                self.db.log("job_rescheduled", f"{payload['job_id']} -> {payload['new_date']}")
            elif row["action_type"] == "change_client_rate":
                self.db.execute(
                    "UPDATE clients SET recurring_rate = ? WHERE id = ?",
                    (float(payload["new_rate"]), payload["client_id"]),
                )
                self.db.log("rate_changed", f"{payload['client_id']} -> {payload['new_rate']}")
            elif row["action_type"] == "archive_batch":
                self.archive_now()
            status = "approved"
        else:
            status = "rejected"

        self.db.execute(
            """
            UPDATE approvals
            SET status = ?, decided_at = ?, decision_note = ?
            WHERE id = ?
            """,
            (status, now_ts(), note, approval_id),
        )
        return status

    def scan(self):
        self.scan_overdue_leads()
        self.scan_overdue_invoices()
        self.scan_schedule_load()
        self.scan_pipeline_health()
        self.scan_self_care()
        self.auto_archive_soft()
        self.db.log("automation_scan", "full scan complete")

    def scan_overdue_leads(self):
        today = today_str()
        rows = self.db.fetchall(
            """
            SELECT * FROM leads
            WHERE archived = 0
              AND status IN ('new', 'contacted', 'quoted')
              AND follow_up_date IS NOT NULL
              AND follow_up_date < ?
            """,
            (today,),
        )
        for r in rows:
            self.push_alert(
                "warning",
                "lead_follow_up",
                f"Lead follow-up overdue: {r['name']} ({r['phone'] or 'no phone'})",
                {"lead_id": r["id"]},
            )

    def scan_overdue_invoices(self):
        today = today_str()
        rows = self.db.fetchall(
            """
            SELECT i.id, i.amount, i.due_date, c.name
            FROM invoices i
            JOIN clients c ON c.id = i.client_id
            WHERE i.archived = 0 AND i.status = 'unpaid' AND i.due_date < ?
            """,
            (today,),
        )
        for r in rows:
            self.push_alert(
                "critical",
                "invoice_overdue",
                f"Invoice overdue: {r['name']} due {r['due_date']} amount {money(r['amount'])}",
                {"invoice_id": r["id"]},
            )

    def scan_schedule_load(self):
        max_jobs = int(float(self.db.setting("max_jobs_per_day")))
        upcoming = self.db.fetch_df(
            """
            SELECT job_date, COUNT(*) AS jobs
            FROM jobs
            WHERE archived = 0 AND status IN ('scheduled', 'in_progress')
              AND job_date >= ?
            GROUP BY job_date
            ORDER BY job_date
            """,
            (today_str(),),
        )
        if upcoming.empty:
            return

        overloaded = upcoming[upcoming["jobs"] > max_jobs]
        for _, row in overloaded.iterrows():
            job = self.db.fetchone(
                """
                SELECT id, job_date FROM jobs
                WHERE archived = 0 AND status = 'scheduled' AND job_date = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (row["job_date"],),
            )
            if job:
                suggested = parse_date(job["job_date"]) + timedelta(days=1)
                self.create_approval(
                    "reschedule_job",
                    {"job_id": job["id"], "new_date": suggested.strftime(DATE_FMT)},
                    "medium",
                    f"Overloaded day {job['job_date']} detected. Suggest move job {job['id']} to {suggested.strftime(DATE_FMT)}",
                )
                self.push_alert(
                    "warning",
                    "schedule_overload",
                    f"Schedule overload on {job['job_date']}. Approval queued for reschedule.",
                    {"job_id": job["id"]},
                )

    def scan_pipeline_health(self):
        threshold = int(float(self.db.setting("low_pipeline_threshold_14d")))
        end_date = (date.today() + timedelta(days=14)).strftime(DATE_FMT)
        row = self.db.fetchone(
            """
            SELECT COUNT(*) AS cnt
            FROM jobs
            WHERE archived = 0
              AND status IN ('scheduled', 'in_progress')
              AND job_date BETWEEN ? AND ?
            """,
            (today_str(), end_date),
        )
        cnt = int(row["cnt"]) if row else 0
        if cnt < threshold:
            self.push_alert(
                "info",
                "self_promo",
                f"Pipeline below target. Only {cnt} scheduled jobs in next 14 days. Push promo / referrals today.",
                {"scheduled_jobs_14d": cnt},
            )

    def scan_self_care(self):
        threshold = int(float(self.db.setting("self_care_job_threshold_7d")))
        end_date = (date.today() + timedelta(days=7)).strftime(DATE_FMT)
        row = self.db.fetchone(
            """
            SELECT COUNT(*) AS cnt
            FROM jobs
            WHERE archived = 0
              AND status IN ('scheduled', 'in_progress')
              AND job_date BETWEEN ? AND ?
            """,
            (today_str(), end_date),
        )
        cnt = int(row["cnt"]) if row else 0
        if cnt >= threshold:
            self.push_alert(
                "info",
                "self_care",
                f"High workload next 7 days ({cnt} jobs). Add recovery block / reduce overload.",
                {"scheduled_jobs_7d": cnt},
            )

    def auto_archive_soft(self):
        days = int(float(self.db.setting("archive_after_days")))
        cutoff = (date.today() - timedelta(days=days)).strftime(DATE_FMT)

        jobs = self.db.fetchone(
            """
            SELECT COUNT(*) AS cnt FROM jobs
            WHERE archived = 0 AND status = 'completed' AND substr(created_at,1,10) < ?
            """,
            (cutoff,),
        )["cnt"]
        if jobs:
            self.db.execute(
                """
                UPDATE jobs SET archived = 1
                WHERE archived = 0 AND status = 'completed' AND substr(created_at,1,10) < ?
                """,
                (cutoff,),
            )
            self.db.log("archive_jobs", f"{jobs} completed jobs archived")

        invoices = self.db.fetchone(
            """
            SELECT COUNT(*) AS cnt FROM invoices
            WHERE archived = 0 AND status = 'paid' AND substr(created_at,1,10) < ?
            """,
            (cutoff,),
        )["cnt"]
        if invoices:
            self.db.execute(
                """
                UPDATE invoices SET archived = 1
                WHERE archived = 0 AND status = 'paid' AND substr(created_at,1,10) < ?
                """,
                (cutoff,),
            )
            self.db.log("archive_invoices", f"{invoices} paid invoices archived")

        alerts = self.db.fetchone(
            """
            SELECT COUNT(*) AS cnt FROM alerts
            WHERE archived = 0 AND resolved = 1 AND substr(created_at,1,10) < ?
            """,
            (cutoff,),
        )["cnt"]
        if alerts:
            self.db.execute(
                """
                UPDATE alerts SET archived = 1
                WHERE archived = 0 AND resolved = 1 AND substr(created_at,1,10) < ?
                """,
                (cutoff,),
            )
            self.db.log("archive_alerts", f"{alerts} resolved alerts archived")

    def archive_now(self):
        self.auto_archive_soft()


class FinanceEngine:
    def __init__(self, db: DB):
        self.db = db

    def metrics(self):
        month_start = date.today().replace(day=1).strftime(DATE_FMT)
        today = today_str()

        revenue = self.db.fetchone(
            """
            SELECT COALESCE(SUM(amount), 0) AS total
            FROM invoices
            WHERE archived = 0
              AND status = 'paid'
              AND paid_date BETWEEN ? AND ?
            """,
            (month_start, today),
        )["total"]

        outstanding = self.db.fetchone(
            """
            SELECT COALESCE(SUM(amount), 0) AS total
            FROM invoices
            WHERE archived = 0 AND status = 'unpaid'
            """
        )["total"]

        expenses = self.db.fetchone(
            """
            SELECT COALESCE(SUM(amount), 0) AS total
            FROM expenses
            WHERE expense_date BETWEEN ? AND ?
            """,
            (month_start, today),
        )["total"]

        profit = float(revenue) - float(expenses)
        return {
            "month_revenue": float(revenue),
            "month_expenses": float(expenses),
            "month_profit": float(profit),
            "outstanding_ar": float(outstanding),
        }

    def monthly_report(self):
        return self.db.fetch_df(
            """
            SELECT
              substr(COALESCE(paid_date, due_date),1,7) AS month,
              SUM(CASE WHEN status = 'paid' THEN amount ELSE 0 END) AS paid_revenue,
              SUM(CASE WHEN status = 'unpaid' THEN amount ELSE 0 END) AS outstanding
            FROM invoices
            WHERE archived = 0
            GROUP BY substr(COALESCE(paid_date, due_date),1,7)
            ORDER BY month DESC
            """
        )


# =========================
# APP
# =========================
st.set_page_config(page_title="Luxe Ops Dashboard", layout="wide")
db = DB()
auto = AutomationEngine(db)
fin = FinanceEngine(db)

# run awareness scan every load
auto.scan()

brand = db.setting("business_name")
tagline = db.setting("tagline")
phone = db.setting("phone")

st.title(brand)
st.caption(tagline)

# sidebar realtime metrics
metrics = fin.metrics()
leads_open = db.fetchone(
    "SELECT COUNT(*) AS cnt FROM leads WHERE archived = 0 AND status IN ('new','contacted','quoted')"
)["cnt"]
jobs_upcoming = db.fetchone(
    "SELECT COUNT(*) AS cnt FROM jobs WHERE archived = 0 AND status IN ('scheduled','in_progress') AND job_date >= ?",
    (today_str(),),
)["cnt"]
alerts_open = db.fetchone(
    "SELECT COUNT(*) AS cnt FROM alerts WHERE archived = 0 AND resolved = 0"
)["cnt"]

with st.sidebar:
    st.subheader("Realtime")
    st.metric("Open Leads", leads_open)
    st.metric("Upcoming Jobs", jobs_upcoming)
    st.metric("Open Alerts", alerts_open)
    st.metric("Month Revenue", money(metrics["month_revenue"]))
    st.metric("Outstanding", money(metrics["outstanding_ar"]))
    st.write(f"Call/Text: {phone}")
    if st.button("Run Full Scan Now"):
        auto.scan()
        st.success("Scan complete")
        st.rerun()

tabs = st.tabs([
    "Dashboard",
    "Leads",
    "Clients",
    "Jobs",
    "Billing",
    "Approvals",
    "Automation",
    "Settings",
    "Exports",
])

# =========================
# DASHBOARD
# =========================
with tabs[0]:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Revenue MTD", money(metrics["month_revenue"]))
    c2.metric("Expenses MTD", money(metrics["month_expenses"]))
    c3.metric("Profit MTD", money(metrics["month_profit"]))
    c4.metric("A/R", money(metrics["outstanding_ar"]))

    st.subheader("Open Alerts")
    alerts = db.fetch_df(
        """
        SELECT created_at, level, category, message
        FROM alerts
        WHERE archived = 0 AND resolved = 0
        ORDER BY created_at DESC
        """
    )
    st.dataframe(alerts, use_container_width=True, hide_index=True)

    if not alerts.empty:
        alert_ids = db.fetch_df(
            "SELECT id, message FROM alerts WHERE archived = 0 AND resolved = 0 ORDER BY created_at DESC"
        )
        col1, col2 = st.columns([3,1])
        with col1:
            resolve_id = st.selectbox("Resolve alert", alert_ids["id"].tolist(), key="resolve_alert_id")
        with col2:
            if st.button("Resolve Selected Alert"):
                db.execute("UPDATE alerts SET resolved = 1 WHERE id = ?", (resolve_id,))
                db.log("alert_resolved", resolve_id)
                st.success("Resolved")
                st.rerun()

    st.subheader("Upcoming Jobs")
    upcoming = db.fetch_df(
        """
        SELECT j.id, j.job_date, c.name AS client, j.job_type, j.hours_estimate, j.status, COALESCE(j.amount, 0) AS amount
        FROM jobs j
        JOIN clients c ON c.id = j.client_id
        WHERE j.archived = 0 AND j.status IN ('scheduled', 'in_progress') AND j.job_date >= ?
        ORDER BY j.job_date ASC, c.name ASC
        """,
        (today_str(),),
    )
    st.dataframe(upcoming, use_container_width=True, hide_index=True)

    st.subheader("Monthly Financials")
    monthly = fin.monthly_report()
    st.dataframe(monthly, use_container_width=True, hide_index=True)

# =========================
# LEADS
# =========================
with tabs[1]:
    st.subheader("Add Lead")
    with st.form("lead_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        lead_name = c1.text_input("Name")
        lead_phone = c2.text_input("Phone", value="")
        lead_address = c3.text_input("Address", value="")
        c4, c5, c6 = st.columns(3)
        lead_source = c4.selectbox("Source", ["Facebook", "Referral", "Flyer", "Text", "Other"])
        lead_frequency = c5.selectbox("Desired Frequency", ["One-Time", "Bi-Weekly", "Monthly", "Unsure"])
        lead_condition = c6.selectbox("Condition", ["Clean", "Average", "Needs Extra Attention"])
        c7, c8 = st.columns(2)
        lead_priority = c7.selectbox("Priority Focus", ["Low-allergen", "Deep Reset", "Maintenance", "Organization", "Kitchen", "Bathrooms"])
        lead_follow = c8.date_input("Follow-up Date", value=date.today() + timedelta(days=1))
        lead_notes = st.text_area("Notes")
        submitted = st.form_submit_button("Create Lead")
        if submitted and lead_name.strip():
            db.execute(
                """
                INSERT INTO leads(id, created_at, name, phone, address, source, desired_frequency, condition, priority_focus, follow_up_date, status, notes, archived)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, 0)
                """,
                (
                    new_id(), now_ts(), lead_name.strip(), lead_phone.strip(), lead_address.strip(), lead_source,
                    lead_frequency, lead_condition, lead_priority, lead_follow.strftime(DATE_FMT), lead_notes.strip()
                ),
            )
            db.log("lead_created", lead_name)
            st.success("Lead created")
            st.rerun()

    st.subheader("Convert Lead to Client")
    open_leads = db.fetch_df(
        """
        SELECT id, name, phone, address, desired_frequency
        FROM leads
        WHERE archived = 0 AND status IN ('new', 'contacted', 'quoted')
        ORDER BY created_at DESC
        """
    )
    st.dataframe(open_leads, use_container_width=True, hide_index=True)
    if not open_leads.empty:
        with st.form("convert_lead"):
            selected = st.selectbox("Lead ID", open_leads["id"].tolist())
            recurring_rate = st.number_input("Recurring Rate", min_value=0.0, value=float(db.setting("recurring_biweekly_rate")))
            client_status = st.selectbox("Client Status", ["active", "prospect"])
            submitted = st.form_submit_button("Convert")
            if submitted:
                lead = db.fetchone("SELECT * FROM leads WHERE id = ?", (selected,))
                db.execute(
                    """
                    INSERT INTO clients(id, created_at, name, phone, address, frequency, recurring_rate, status, notes, archived)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        new_id(), now_ts(), lead["name"], lead["phone"], lead["address"],
                        lead["desired_frequency"], recurring_rate, client_status, lead["notes"]
                    ),
                )
                db.execute("UPDATE leads SET status = 'converted' WHERE id = ?", (selected,))
                db.log("lead_converted", selected)
                st.success("Lead converted")
                st.rerun()

# =========================
# CLIENTS
# =========================
with tabs[2]:
    st.subheader("Clients")
    clients = db.fetch_df(
        """
        SELECT id, name, phone, address, frequency, recurring_rate, status, notes
        FROM clients
        WHERE archived = 0
        ORDER BY name
        """
    )
    st.dataframe(clients, use_container_width=True, hide_index=True)

    if not clients.empty:
        st.subheader("Request Rate Change (approval gated)")
        with st.form("rate_change_form"):
            client_id = st.selectbox("Client ID", clients["id"].tolist())
            new_rate = st.number_input("New Recurring Rate", min_value=0.0, value=float(db.setting("recurring_biweekly_rate")))
            reason = st.text_input("Reason", value="Rate adjustment request")
            if st.form_submit_button("Queue Approval"):
                auto.create_approval(
                    "change_client_rate",
                    {"client_id": client_id, "new_rate": new_rate},
                    "high",
                    reason,
                )
                st.success("Approval queued")
                st.rerun()

# =========================
# JOBS
# =========================
with tabs[3]:
    st.subheader("Schedule Job")
    client_list = db.fetch_df("SELECT id, name FROM clients WHERE archived = 0 AND status IN ('active', 'prospect') ORDER BY name")
    if client_list.empty:
        st.info("No clients yet. Convert a lead first.")
    else:
        with st.form("job_form", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            job_client = c1.selectbox("Client", client_list["id"].tolist(), format_func=lambda x: dict(zip(client_list["id"], client_list["name"])).get(x, x))
            job_date = c2.date_input("Job Date", value=date.today())
            job_type = c3.selectbox("Job Type", ["Deep Clean", "Bi-Weekly", "Monthly", "One-Time", "Walkthrough"])
            c4, c5 = st.columns(2)
            hours_est = c4.number_input("Estimated Hours", min_value=0.0, value=3.0, step=0.5)
            est_amount = c5.number_input("Estimated Amount", min_value=0.0, value=320.0)
            job_notes = st.text_area("Notes")
            if st.form_submit_button("Create Job"):
                db.execute(
                    """
                    INSERT INTO jobs(id, created_at, client_id, job_date, job_type, hours_estimate, actual_hours, amount, status, notes, archived)
                    VALUES(?, ?, ?, ?, ?, ?, NULL, ?, 'scheduled', ?, 0)
                    """,
                    (new_id(), now_ts(), job_client, job_date.strftime(DATE_FMT), job_type, hours_est, est_amount, job_notes.strip()),
                )
                db.log("job_created", f"{job_client} {job_date}")
                st.success("Job scheduled")
                st.rerun()

    st.subheader("Complete Job")
    scheduled_jobs = db.fetch_df(
        """
        SELECT j.id, j.job_date, c.name AS client, j.job_type, j.hours_estimate, COALESCE(j.amount,0) AS amount
        FROM jobs j
        JOIN clients c ON c.id = j.client_id
        WHERE j.archived = 0 AND j.status IN ('scheduled','in_progress')
        ORDER BY j.job_date
        """
    )
    st.dataframe(scheduled_jobs, use_container_width=True, hide_index=True)

    if not scheduled_jobs.empty:
        with st.form("complete_job_form"):
            complete_job_id = st.selectbox("Job ID", scheduled_jobs["id"].tolist())
            actual_hours = st.number_input("Actual Hours", min_value=0.0, value=3.0, step=0.25)
            final_amount = st.number_input("Final Amount", min_value=0.0, value=320.0)
            create_invoice = st.checkbox("Create invoice now", value=True)
            due_date = st.date_input("Invoice Due Date", value=date.today() + timedelta(days=7))
            if st.form_submit_button("Mark Complete"):
                job = db.fetchone("SELECT client_id FROM jobs WHERE id = ?", (complete_job_id,))
                db.execute(
                    "UPDATE jobs SET status = 'completed', actual_hours = ?, amount = ? WHERE id = ?",
                    (actual_hours, final_amount, complete_job_id),
                )
                if create_invoice:
                    db.execute(
                        """
                        INSERT INTO invoices(id, created_at, client_id, job_id, due_date, amount, status, paid_date, notes, archived)
                        VALUES(?, ?, ?, ?, ?, ?, 'unpaid', NULL, '', 0)
                        """,
                        (new_id(), now_ts(), job["client_id"], complete_job_id, due_date.strftime(DATE_FMT), final_amount),
                    )
                db.log("job_completed", complete_job_id)
                st.success("Job completed")
                st.rerun()

    st.subheader("Queue Reschedule Approval")
    if not scheduled_jobs.empty:
        with st.form("reschedule_form"):
            rid = st.selectbox("Job ID to Move", scheduled_jobs["id"].tolist())
            new_date = st.date_input("Suggested New Date", value=date.today() + timedelta(days=1))
            reason = st.text_input("Reason", value="Manual reschedule request")
            if st.form_submit_button("Queue Reschedule"):
                auto.create_approval(
                    "reschedule_job",
                    {"job_id": rid, "new_date": new_date.strftime(DATE_FMT)},
                    "high",
                    reason,
                )
                st.success("Approval queued")
                st.rerun()

# =========================
# BILLING
# =========================
with tabs[4]:
    st.subheader("Invoices")
    invoices = db.fetch_df(
        """
        SELECT i.id, c.name AS client, i.job_id, i.due_date, i.amount, i.status, i.paid_date
        FROM invoices i
        JOIN clients c ON c.id = i.client_id
        WHERE i.archived = 0
        ORDER BY i.created_at DESC
        """
    )
    st.dataframe(invoices, use_container_width=True, hide_index=True)

    if not invoices.empty:
        with st.form("mark_invoice_paid"):
            inv_id = st.selectbox("Invoice ID", invoices["id"].tolist())
            paid_dt = st.date_input("Paid Date", value=date.today())
            if st.form_submit_button("Mark Paid"):
                db.execute(
                    "UPDATE invoices SET status = 'paid', paid_date = ? WHERE id = ?",
                    (paid_dt.strftime(DATE_FMT), inv_id),
                )
                db.log("invoice_paid", inv_id)
                st.success("Invoice paid")
                st.rerun()

    st.subheader("Add Expense")
    with st.form("expense_form", clear_on_submit=True):
        c1, c2, c3, c4 = st.columns(4)
        edate = c1.date_input("Expense Date", value=date.today())
        ecat = c2.selectbox("Category", ["Supplies", "Fuel", "Payroll", "Equipment", "Software", "Marketing", "Other"])
        evendor = c3.text_input("Vendor")
        eamount = c4.number_input("Amount", min_value=0.0, value=0.0)
        enotes = st.text_area("Notes")
        if st.form_submit_button("Add Expense") and eamount > 0:
            db.execute(
                """
                INSERT INTO expenses(id, created_at, expense_date, category, vendor, amount, notes)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (new_id(), now_ts(), edate.strftime(DATE_FMT), ecat, evendor.strip(), eamount, enotes.strip()),
            )
            db.log("expense_added", f"{ecat} {eamount}")
            st.success("Expense added")
            st.rerun()

    st.subheader("Financial Report")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Revenue MTD", money(metrics["month_revenue"]))
    c2.metric("Expenses MTD", money(metrics["month_expenses"]))
    c3.metric("Profit MTD", money(metrics["month_profit"]))
    c4.metric("Outstanding A/R", money(metrics["outstanding_ar"]))

# =========================
# APPROVALS
# =========================
with tabs[5]:
    st.subheader("Pending Approvals")
    approvals = db.fetch_df(
        """
        SELECT id, created_at, action_type, risk, reason, status, payload
        FROM approvals
        ORDER BY created_at DESC
        """
    )
    st.dataframe(approvals, use_container_width=True, hide_index=True)

    pending = db.fetch_df(
        "SELECT id FROM approvals WHERE status = 'pending' ORDER BY created_at DESC"
    )
    if not pending.empty:
        with st.form("approval_decision"):
            approval_id = st.selectbox("Approval ID", pending["id"].tolist())
            decision = st.selectbox("Decision", ["approve", "reject"])
            note = st.text_input("Decision Note", value="")
            if st.form_submit_button("Submit Decision"):
                result = auto.process_approval(approval_id, decision, note)
                st.success(result)
                st.rerun()

# =========================
# AUTOMATION
# =========================
with tabs[6]:
    st.subheader("Automation Control")
    c1, c2, c3 = st.columns(3)
    if c1.button("Run System Scan"):
        auto.scan()
        st.success("System scan complete")
        st.rerun()
    if c2.button("Archive Now"):
        auto.archive_now()
        st.success("Archive pass complete")
        st.rerun()
    if c3.button("Seed Demo Data"):
        # only if empty enough
        if db.fetchone("SELECT COUNT(*) AS cnt FROM clients")["cnt"] == 0:
            c_id = new_id()
            db.execute(
                """
                INSERT INTO clients(id, created_at, name, phone, address, frequency, recurring_rate, status, notes, archived)
                VALUES(?, ?, ?, ?, ?, ?, ?, 'active', ?, 0)
                """,
                (c_id, now_ts(), "Jenn Demo", "435-994-5348", "84332", "Bi-Weekly", float(db.setting("recurring_biweekly_rate")), "Seeded demo client"),
            )
            job1 = new_id()
            db.execute(
                """
                INSERT INTO jobs(id, created_at, client_id, job_date, job_type, hours_estimate, amount, status, notes, archived)
                VALUES(?, ?, ?, ?, 'Bi-Weekly', 3, 160, 'scheduled', '', 0)
                """,
                (job1, now_ts(), c_id, (date.today() + timedelta(days=1)).strftime(DATE_FMT)),
            )
            inv = new_id()
            db.execute(
                """
                INSERT INTO invoices(id, created_at, client_id, job_id, due_date, amount, status, paid_date, notes, archived)
                VALUES(?, ?, ?, ?, ?, 160, 'unpaid', NULL, '', 0)
                """,
                (inv, now_ts(), c_id, job1, (date.today() - timedelta(days=3)).strftime(DATE_FMT)),
            )
            db.execute(
                """
                INSERT INTO leads(id, created_at, name, phone, address, source, desired_frequency, condition, priority_focus, follow_up_date, status, notes, archived)
                VALUES(?, ?, 'Warm Lead Demo', '435-994-5348', 'Local', 'Flyer', 'Bi-Weekly', 'Average', 'Low-allergen', ?, 'quoted', 'Needs callback', 0)
                """,
                (new_id(), now_ts(), (date.today() - timedelta(days=1)).strftime(DATE_FMT)),
            )
            db.execute(
                """
                INSERT INTO expenses(id, created_at, expense_date, category, vendor, amount, notes)
                VALUES(?, ?, ?, 'Supplies', 'Demo Vendor', 42.50, 'Seeded supplies')
                """,
                (new_id(), now_ts(), today_str()),
            )
            auto.scan()
            st.success("Demo data seeded")
            st.rerun()
        else:
            st.warning("Database already has data")

    st.subheader("System Health")
    health_rows = []
    if leads_open > 0:
        health_rows.append(["Leads", "Active lead pipeline present", "OK"])
    else:
        health_rows.append(["Leads", "No active leads. Run self-promo push.", "ATTENTION"])

    if alerts_open == 0:
        health_rows.append(["Alerts", "No unresolved alerts", "OK"])
    else:
        health_rows.append(["Alerts", f"{alerts_open} unresolved alerts", "ATTENTION"])

    overload_days = db.fetch_df(
        """
        SELECT job_date, COUNT(*) AS jobs
        FROM jobs
        WHERE archived = 0 AND status IN ('scheduled','in_progress')
        GROUP BY job_date
        HAVING COUNT(*) > ?
        ORDER BY job_date
        """,
        (int(float(db.setting("max_jobs_per_day"))),),
    )
    if overload_days.empty:
        health_rows.append(["Schedule", "No overload detected", "OK"])
    else:
        health_rows.append(["Schedule", "Overload detected. Approval queue active.", "ATTENTION"])

    monthly = fin.metrics()
    if monthly["outstanding_ar"] > 0:
        health_rows.append(["Billing", f"Outstanding invoices: {money(monthly['outstanding_ar'])}", "ATTENTION"])
    else:
        health_rows.append(["Billing", "No outstanding invoices", "OK"])

    st.dataframe(pd.DataFrame(health_rows, columns=["Area", "Status", "State"]), use_container_width=True, hide_index=True)

    st.subheader("Audit Log")
    audit = db.fetch_df("SELECT created_at, category, detail FROM audit_log ORDER BY created_at DESC LIMIT 100")
    st.dataframe(audit, use_container_width=True, hide_index=True)

# =========================
# SETTINGS
# =========================
with tabs[7]:
    st.subheader("System Settings")
    with st.form("settings_form"):
        s1, s2, s3 = st.columns(3)
        business_name = s1.text_input("Business Name", value=db.setting("business_name"))
        tagline_in = s2.text_input("Tagline", value=db.setting("tagline"))
        phone_in = s3.text_input("Phone", value=db.setting("phone"))

        c1, c2, c3 = st.columns(3)
        deep_hours = c1.number_input("Deep Base Hours", min_value=0.0, value=float(db.setting("deep_clean_base_hours")))
        deep_base = c2.number_input("Deep Base Price", min_value=0.0, value=float(db.setting("deep_clean_base_price")))
        deep_over = c3.number_input("Deep Overage Hourly", min_value=0.0, value=float(db.setting("deep_clean_overage_hourly")))

        c4, c5, c6 = st.columns(3)
        recur = c4.number_input("Recurring Bi-Weekly Rate", min_value=0.0, value=float(db.setting("recurring_biweekly_rate")))
        max_jobs = c5.number_input("Max Jobs / Day", min_value=1.0, value=float(db.setting("max_jobs_per_day")))
        low_pipe = c6.number_input("Min Jobs next 14d", min_value=0.0, value=float(db.setting("low_pipeline_threshold_14d")))

        c7, c8 = st.columns(2)
        self_care = c7.number_input("Self-Care Threshold next 7d", min_value=0.0, value=float(db.setting("self_care_job_threshold_7d")))
        archive_days = c8.number_input("Archive After Days", min_value=30.0, value=float(db.setting("archive_after_days")))

        if st.form_submit_button("Save Settings"):
            updates = {
                "business_name": business_name,
                "tagline": tagline_in,
                "phone": phone_in,
                "deep_clean_base_hours": deep_hours,
                "deep_clean_base_price": deep_base,
                "deep_clean_overage_hourly": deep_over,
                "recurring_biweekly_rate": recur,
                "max_jobs_per_day": max_jobs,
                "low_pipeline_threshold_14d": low_pipe,
                "self_care_job_threshold_7d": self_care,
                "archive_after_days": archive_days,
            }
            for k, v in updates.items():
                db.set_setting(k, v)
            db.log("settings_updated", json.dumps(updates))
            st.success("Settings saved")
            st.rerun()

# =========================
# EXPORTS
# =========================
with tabs[8]:
    st.subheader("Exports")
    export_map = {
        "leads.csv": db.fetch_df("SELECT * FROM leads WHERE archived = 0 ORDER BY created_at DESC"),
        "clients.csv": db.fetch_df("SELECT * FROM clients WHERE archived = 0 ORDER BY created_at DESC"),
        "jobs.csv": db.fetch_df("SELECT * FROM jobs WHERE archived = 0 ORDER BY created_at DESC"),
        "invoices.csv": db.fetch_df("SELECT * FROM invoices WHERE archived = 0 ORDER BY created_at DESC"),
        "expenses.csv": db.fetch_df("SELECT * FROM expenses ORDER BY created_at DESC"),
        "alerts.csv": db.fetch_df("SELECT * FROM alerts WHERE archived = 0 ORDER BY created_at DESC"),
        "audit_log.csv": db.fetch_df("SELECT * FROM audit_log ORDER BY created_at DESC"),
    }
    for filename, df in export_map.items():
        st.write(filename)
        to_csv_download(df, filename, f"Download {filename}")

    st.caption(f"Database file: {os.path.abspath(DB_PATH)}")