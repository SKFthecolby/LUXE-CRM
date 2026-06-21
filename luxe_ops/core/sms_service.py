import requests

from .helpers import new_id, now_ts


class SMSService:
    def __init__(self, db):
        self.db = db
        self.provider = self.db.setting("sms_provider")

    def refresh(self):
        self.provider = self.db.setting("sms_provider")

    def queue_message(
        self,
        phone,
        body,
        message_type="manual",
        client_id=None,
        lead_id=None,
        approval_required=False,
    ):
        existing = self.db.fetchone(
            """
            SELECT id FROM sms_messages
            WHERE archived = 0
              AND status IN ('queued', 'manual-send')
              AND phone = ?
              AND body = ?
              AND message_type = ?
              AND COALESCE(client_id, '') = COALESCE(?, '')
              AND COALESCE(lead_id, '') = COALESCE(?, '')
            LIMIT 1
            """,
            (phone, body, message_type, client_id, lead_id),
        )
        if existing:
            return existing["id"]

        message_id = new_id()
        self.db.execute(
            """
            INSERT INTO sms_messages(
                id, created_at, client_id, lead_id, phone, direction, message_type,
                body, status, external_id, sent_at, error_text, approval_required, archived
            )
            VALUES(?, ?, ?, ?, ?, 'outbound', ?, ?, 'queued', NULL, NULL, NULL, ?, 0)
            """,
            (
                message_id,
                now_ts(),
                client_id,
                lead_id,
                phone,
                message_type,
                body,
                1 if approval_required else 0,
            ),
        )
        return message_id

    def send_queued(self):
        self.refresh()

        if self.provider == "disabled":
            return {"sent": 0, "failed": 0, "manual": 0, "reason": "sms disabled"}

        if self.provider == "manual_google_voice":
            self.db.execute(
                """
                UPDATE sms_messages
                SET status = 'manual-send'
                WHERE status = 'queued'
                  AND archived = 0
                  AND approval_required = 0
                """
            )
            return {
                "sent": 0,
                "failed": 0,
                "manual": 1,
                "reason": "queued for manual Google Voice send",
            }

        if self.provider == "textbelt_free":
            return self._send_textbelt_free()

        return {"sent": 0, "failed": 0, "manual": 0, "reason": f"unknown provider: {self.provider}"}

    def _send_textbelt_free(self):
        rows = self.db.fetchall(
            """
            SELECT * FROM sms_messages
            WHERE status = 'queued'
              AND archived = 0
              AND approval_required = 0
            ORDER BY created_at ASC
            """
        )

        sent = 0
        failed = 0

        for row in rows:
            try:
                resp = requests.post(
                    "https://textbelt.com/text",
                    data={
                        "phone": row["phone"],
                        "message": row["body"],
                        "key": "textbelt",
                    },
                    timeout=20,
                )
                data = resp.json()

                if data.get("success"):
                    self.db.execute(
                        """
                        UPDATE sms_messages
                        SET status = 'sent', external_id = ?, sent_at = ?
                        WHERE id = ?
                        """,
                        (str(data.get("textId", "")), now_ts(), row["id"]),
                    )
                    self.db.log("sms_sent", f"{row['id']} -> {row['phone']}")
                    sent += 1
                else:
                    self.db.execute(
                        """
                        UPDATE sms_messages
                        SET status = 'failed', error_text = ?
                        WHERE id = ?
                        """,
                        (data.get("error", "unknown error"), row["id"]),
                    )
                    self.db.log("sms_failed", f"{row['id']} -> {data.get('error', 'unknown error')}")
                    failed += 1
            except Exception as exc:
                self.db.execute(
                    """
                    UPDATE sms_messages
                    SET status = 'failed', error_text = ?
                    WHERE id = ?
                    """,
                    (str(exc), row["id"]),
                )
                self.db.log("sms_failed", f"{row['id']} -> {str(exc)}")
                failed += 1

        return {"sent": sent, "failed": failed, "manual": 0, "reason": ""}

    def queue_job_reminder(self, client_id, phone, client_name, job_date):
        body = (
            f"Hi {client_name} — reminder from {self.db.setting('business_name')}: "
            f"your cleaning is scheduled for {job_date}. Reply if anything needs to be updated."
        )
        self.queue_message(
            phone=phone,
            body=body,
            message_type="job_reminder",
            client_id=client_id,
            approval_required=False,
        )

    def queue_invoice_notice(self, client_id, phone, client_name, amount, due_date):
        body = (
            f"Hi {client_name} — your invoice for {self.db.setting('business_name')} "
            f"is ${amount:,.2f} and due {due_date}. Reply if you need anything."
        )
        self.queue_message(
            phone=phone,
            body=body,
            message_type="invoice_notice",
            client_id=client_id,
            approval_required=False,
        )
