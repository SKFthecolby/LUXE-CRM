import json
from datetime import date, timedelta

from .helpers import new_id, now_ts, today_str
from .db import DB


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

    def replace_alert(self, level, category, message, meta=None):
        existing = self.db.fetchone(
            """
            SELECT id FROM alerts
            WHERE category = ? AND message = ? AND resolved = 0 AND archived = 0
            """,
            (category, message),
        )
        if existing:
            self.db.execute(
                """
                UPDATE alerts
                SET resolved = 1, archived = 1
                WHERE category = ?
                  AND resolved = 0
                  AND archived = 0
                  AND id != ?
                """,
                (category, existing["id"]),
            )
            return
        self.db.execute(
            """
            UPDATE alerts
            SET resolved = 1, archived = 1
            WHERE category = ? AND resolved = 0 AND archived = 0
            """,
            (category,),
        )
        self.push_alert(level, category, message, meta)

    def create_approval(self, action_type, payload, risk, reason):
        payload_json = json.dumps(payload, sort_keys=True)
        existing = self.db.fetchone(
            "SELECT id FROM approvals WHERE action_type = ? AND payload = ? AND status = 'pending'",
            (action_type, payload_json),
        )
        if existing:
            return
        self.db.execute(
            """
            INSERT INTO approvals(id, created_at, action_type, payload, risk, reason, status)
            VALUES(?, ?, ?, ?, ?, ?, 'pending')
            """,
            (new_id(), now_ts(), action_type, payload_json, risk, reason),
        )
        self.db.log("approval_created", f"{action_type}: {reason}")

    def queue_bulk_sms_approval(self, sms_ids, reason="Bulk SMS requires approval"):
        self.create_approval(
            "bulk_sms",
            {"sms_ids": sms_ids},
            "high",
            reason,
        )

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
            elif row["action_type"] == "change_client_rate":
                self.db.execute(
                    "UPDATE clients SET recurring_rate = ? WHERE id = ?",
                    (float(payload["new_rate"]), payload["client_id"]),
                )
            elif row["action_type"] == "archive_batch":
                self.archive_now()
            elif row["action_type"] == "quote_override":
                pass
            elif row["action_type"] == "bulk_sms":
                queued_ids = payload.get("sms_ids", [])
                if queued_ids:
                    placeholders = ",".join(["?"] * len(queued_ids))
                    sql = f"UPDATE sms_messages SET approval_required = 0 WHERE id IN ({placeholders})"
                    self.db.execute(sql, tuple(queued_ids))
            status = "approved"
        else:
            status = "rejected"

        self.db.execute(
            "UPDATE approvals SET status = ?, decided_at = ?, decision_note = ? WHERE id = ?",
            (status, now_ts(), note, approval_id),
        )
        self.db.log("approval_processed", f"{approval_id}:{status}")
        return status

    def scan(self):
        if not self._has_operational_data():
            return
        self.scan_overdue_leads()
        self.scan_overdue_invoices()
        self.scan_schedule_load()
        self.scan_pipeline_health()
        self.scan_self_care()
        self.auto_archive_soft()
        self.db.log("automation_scan", "scan complete")

    def _has_operational_data(self):
        row = self.db.fetchone(
            """
            SELECT
                (SELECT COUNT(*) FROM leads) +
                (SELECT COUNT(*) FROM clients) +
                (SELECT COUNT(*) FROM jobs) +
                (SELECT COUNT(*) FROM invoices) +
                (SELECT COUNT(*) FROM expenses) +
                (SELECT COUNT(*) FROM quotes) +
                (SELECT COUNT(*) FROM sms_messages) +
                (SELECT COUNT(*) FROM portal_access) AS cnt
            """
        )
        return bool(row and row["cnt"])

    def scan_overdue_leads(self):
        rows = self.db.fetchall(
            """
            SELECT * FROM leads
            WHERE archived = 0
              AND status IN ('new', 'contacted', 'quoted')
              AND follow_up_date IS NOT NULL
              AND follow_up_date < ?
            """,
            (today_str(),),
        )
        for row in rows:
            self.push_alert(
                "warning",
                "lead_follow_up",
                f"Lead follow-up overdue: {row['name']}",
                {"lead_id": row["id"]},
            )

    def scan_overdue_invoices(self):
        rows = self.db.fetchall(
            """
            SELECT i.id, c.name, i.amount, i.due_date
            FROM invoices i
            JOIN clients c ON c.id = i.client_id
            WHERE i.archived = 0 AND i.status = 'unpaid' AND i.due_date < ?
            """,
            (today_str(),),
        )
        for row in rows:
            self.push_alert(
                "critical",
                "invoice_overdue",
                f"Invoice overdue: {row['name']} due {row['due_date']}",
                {"invoice_id": row["id"]},
            )

    def scan_schedule_load(self):
        max_load = float(self.db.setting("max_jobs_per_day"))
        df = self.db.fetch_df(
            """
            SELECT
                job_date,
                COUNT(*) AS jobs,
                SUM(CASE WHEN lower(job_type) LIKE '%turn%' THEN 1.5 ELSE 1 END) AS load_score
            FROM jobs
            WHERE archived = 0 AND status IN ('scheduled', 'in_progress')
            GROUP BY job_date
            HAVING load_score > ?
            ORDER BY job_date
            """,
            (max_load,),
        )
        if df.empty:
            return

        for _, r in df.iterrows():
            self.push_alert(
                "warning",
                "schedule_overload",
                (
                    f"Schedule load high on {r['job_date']}: "
                    f"{int(r['jobs'])} jobs, load score {float(r['load_score']):.1f}/{max_load:.1f}"
                ),
                {
                    "job_date": r["job_date"],
                    "jobs": int(r["jobs"]),
                    "load_score": float(r["load_score"]),
                    "max_load": max_load,
                },
            )

    def scan_pipeline_health(self):
        threshold = int(float(self.db.setting("low_pipeline_threshold_14d")))
        end_date = (date.today() + timedelta(days=14)).strftime("%Y-%m-%d")
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
        count = int(row["cnt"]) if row else 0
        if count < threshold:
            self.replace_alert(
                "info",
                "self_promo",
                f"Pipeline below target: {count} scheduled jobs in next 14 days",
                {"scheduled_jobs_14d": count},
            )

    def scan_self_care(self):
        threshold = int(float(self.db.setting("self_care_job_threshold_7d")))
        end_date = (date.today() + timedelta(days=7)).strftime("%Y-%m-%d")
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
        count = int(row["cnt"]) if row else 0
        if count >= threshold:
            self.replace_alert(
                "info",
                "self_care",
                f"High workload next 7 days: {count} jobs",
                {"scheduled_jobs_7d": count},
            )

    def auto_archive_soft(self):
        cutoff = (date.today() - timedelta(days=int(float(self.db.setting("archive_after_days"))))).strftime("%Y-%m-%d")
        self.db.execute(
            "UPDATE jobs SET archived = 1 WHERE archived = 0 AND status = 'completed' AND substr(created_at,1,10) < ?",
            (cutoff,),
        )
        self.db.execute(
            "UPDATE invoices SET archived = 1 WHERE archived = 0 AND status = 'paid' AND substr(created_at,1,10) < ?",
            (cutoff,),
        )
        self.db.execute(
            "UPDATE alerts SET archived = 1 WHERE archived = 0 AND resolved = 1 AND substr(created_at,1,10) < ?",
            (cutoff,),
        )

    def archive_now(self):
        self.auto_archive_soft()    
