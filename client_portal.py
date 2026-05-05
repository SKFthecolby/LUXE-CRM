import streamlit as st

from luxe_ops.core.db import DB
from luxe_ops.core.helpers import now_ts, money

st.set_page_config(page_title="Luxe Client Portal", layout="wide")

db = DB()

st.title("Luxe Client Portal")
st.caption(db.setting("tagline"))

with st.form("portal_login"):
    phone = st.text_input("Phone")
    access_code = st.text_input("Access Code", type="password")
    submitted = st.form_submit_button("Open Portal")

if submitted:
    row = db.fetchone(
        """
        SELECT
            c.id AS client_id,
            c.name,
            c.phone,
            c.address,
            c.frequency,
            c.recurring_rate,
            c.status,
            p.id AS portal_id
        FROM portal_access p
        JOIN clients c ON c.id = p.client_id
        WHERE p.archived = 0
          AND p.status = 'active'
          AND c.archived = 0
          AND c.phone = ?
          AND p.access_code = ?
        ORDER BY p.created_at DESC
        LIMIT 1
        """,
        (phone.strip(), access_code.strip()),
    )

    if not row:
        st.error("Invalid portal credentials")
    else:
        db.execute(
            """
            UPDATE portal_access
            SET last_used_at = ?
            WHERE id = ?
            """,
            (now_ts(), row["portal_id"]),
        )

        st.subheader(row["name"])

        c1, c2, c3 = st.columns(3)
        c1.metric("Frequency", row["frequency"] or "N/A")
        c2.metric("Recurring Rate", money(row["recurring_rate"]))
        c3.metric("Status", row["status"])

        st.write(f"Phone: {row['phone'] or ''}")
        st.write(f"Address: {row['address'] or ''}")

        st.subheader("Upcoming Jobs")
        jobs = db.fetch_df(
            """
            SELECT job_date, job_type, hours_estimate, amount, status, notes
            FROM jobs
            WHERE archived = 0
              AND client_id = ?
              AND job_date >= date('now')
            ORDER BY job_date ASC
            """,
            (row["client_id"],),
        )
        st.dataframe(jobs, use_container_width=True, hide_index=True)

        st.subheader("Invoices")
        invoices = db.fetch_df(
            """
            SELECT due_date, amount, status, paid_date, notes
            FROM invoices
            WHERE archived = 0
              AND client_id = ?
            ORDER BY created_at DESC
            """,
            (row["client_id"],),
        )
        st.dataframe(invoices, use_container_width=True, hide_index=True)

        st.subheader("Recent Messages")
        sms = db.fetch_df(
            """
            SELECT created_at, message_type, body, status
            FROM sms_messages
            WHERE archived = 0
              AND client_id = ?
            ORDER BY created_at DESC
            LIMIT 20
            """,
            (row["client_id"],),
        )
        st.dataframe(sms, use_container_width=True, hide_index=True)