from datetime import date, timedelta

import pandas as pd
import streamlit as st

from luxe_ops.core.helpers import new_id, now_ts, today_str, money
from luxe_ops.core.quote_engine import QuoteInput


def _download_csv(df, file_name, label):
    st.download_button(
        label,
        df.to_csv(index=False).encode("utf-8"),
        file_name=file_name,
        mime="text/csv",
    )


def run_app(db, auto, finance, quotes, sms):
    st.set_page_config(page_title="Luxe Ops Dashboard", layout="wide")
    auto.scan()

    brand = db.setting("business_name")
    tagline = db.setting("tagline")
    phone = db.setting("phone")

    st.title(brand)
    st.caption(tagline)

    metrics = finance.metrics()
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
        st.metric("Revenue MTD", money(metrics["month_revenue"]))
        st.metric("Outstanding", money(metrics["outstanding_ar"]))
        st.write(f"Call/Text: {phone}")
        if st.button("Run Full Scan"):
            auto.scan()
            st.rerun()

    tabs = st.tabs(
        [
            "Dashboard",
            "Leads",
            "Clients",
            "Quotes",
            "Jobs",
            "Billing",
            "SMS",
            "Portal",
            "Approvals",
            "Automation",
            "Settings",
            "Exports",
        ]
    )

    with tabs[0]:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Revenue MTD", money(metrics["month_revenue"]))
        c2.metric("Expenses MTD", money(metrics["month_expenses"]))
        c3.metric("Profit MTD", money(metrics["month_profit"]))
        c4.metric("Outstanding A/R", money(metrics["outstanding_ar"]))

        st.subheader("Open Alerts")
        alerts = db.fetch_df(
            "SELECT id, created_at, level, category, message FROM alerts WHERE archived = 0 AND resolved = 0 ORDER BY created_at DESC"
        )
        st.dataframe(alerts, use_container_width=True, hide_index=True)

        if not alerts.empty:
            selected_alert = st.selectbox("Resolve Alert ID", alerts["id"].tolist())
            if st.button("Resolve Alert"):
                db.execute("UPDATE alerts SET resolved = 1 WHERE id = ?", (selected_alert,))
                db.log("alert_resolved", selected_alert)
                st.rerun()

        st.subheader("Upcoming Jobs")
        jobs = db.fetch_df(
            """
            SELECT j.id, j.job_date, c.name AS client, j.job_type, j.hours_estimate,
                   COALESCE(j.amount,0) AS amount, j.status
            FROM jobs j
            JOIN clients c ON c.id = j.client_id
            WHERE j.archived = 0 AND j.status IN ('scheduled','in_progress') AND j.job_date >= ?
            ORDER BY j.job_date ASC
            """,
            (today_str(),),
        )
        st.dataframe(jobs, use_container_width=True, hide_index=True)

        st.subheader("Monthly Financials")
        monthly = finance.monthly_report()
        st.dataframe(monthly, use_container_width=True, hide_index=True)

    with tabs[1]:
        st.subheader("Add Lead")
        with st.form("lead_form", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            name = c1.text_input("Name")
            lead_phone = c2.text_input("Phone")
            address = c3.text_input("Address")
            c4, c5, c6 = st.columns(3)
            source = c4.selectbox("Source", ["Facebook", "Referral", "Flyer", "Text", "Other"])
            desired_frequency = c5.selectbox("Desired Frequency", ["One-Time", "Bi-Weekly", "Monthly", "Unsure"])
            condition = c6.selectbox("Condition", ["Clean", "Average", "Needs Extra Attention"])
            c7, c8 = st.columns(2)
            priority = c7.selectbox("Priority Focus", ["Low-allergen", "Deep Reset", "Maintenance", "Organization", "Kitchen", "Bathrooms"])
            follow_up = c8.date_input("Follow-up Date", value=date.today() + timedelta(days=1))
            notes = st.text_area("Notes")
            submitted = st.form_submit_button("Create Lead")

            if submitted and name.strip():
                db.execute(
                    """
                    INSERT INTO leads(
                        id, created_at, name, phone, address, source, desired_frequency,
                        condition, priority_focus, follow_up_date, status, notes, archived
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, 0)
                    """,
                    (
                        new_id(),
                        now_ts(),
                        name.strip(),
                        lead_phone.strip(),
                        address.strip(),
                        source,
                        desired_frequency,
                        condition,
                        priority,
                        follow_up.strftime("%Y-%m-%d"),
                        notes.strip(),
                    ),
                )
                db.log("lead_created", name)
                st.rerun()

        leads = db.fetch_df(
            "SELECT id, name, phone, address, desired_frequency, condition, follow_up_date, status FROM leads WHERE archived = 0 ORDER BY created_at DESC"
        )
        st.dataframe(leads, use_container_width=True, hide_index=True)

        if not leads.empty:
            st.subheader("Convert Lead")
            with st.form("convert_lead"):
                lead_id = st.selectbox("Lead ID", leads["id"].tolist())
                recurring_rate = st.number_input("Recurring Rate", min_value=0.0, value=float(db.setting("recurring_biweekly_rate")))
                status = st.selectbox("Client Status", ["active", "prospect"])
                submitted = st.form_submit_button("Convert to Client")
                if submitted:
                    lead = db.fetchone("SELECT * FROM leads WHERE id = ?", (lead_id,))
                    client_id = new_id()
                    db.execute(
                        """
                        INSERT INTO clients(
                            id, created_at, name, phone, address, frequency,
                            recurring_rate, status, notes, archived
                        )
                        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                        """,
                        (
                            client_id,
                            now_ts(),
                            lead["name"],
                            lead["phone"],
                            lead["address"],
                            lead["desired_frequency"],
                            recurring_rate,
                            status,
                            lead["notes"],
                        ),
                    )
                    db.execute("UPDATE leads SET status = 'converted' WHERE id = ?", (lead_id,))
                    db.log("lead_converted", lead_id)
                    st.rerun()

    with tabs[2]:
        clients = db.fetch_df(
            "SELECT id, name, phone, address, frequency, recurring_rate, status, notes FROM clients WHERE archived = 0 ORDER BY name"
        )
        st.dataframe(clients, use_container_width=True, hide_index=True)

        if not clients.empty:
            with st.form("rate_change"):
                client_id = st.selectbox("Client ID", clients["id"].tolist())
                new_rate = st.number_input("New Rate", min_value=0.0, value=float(db.setting("recurring_biweekly_rate")))
                reason = st.text_input("Reason", value="Requested rate change")
                submitted = st.form_submit_button("Queue Rate Change Approval")
                if submitted:
                    auto.create_approval(
                        "change_client_rate",
                        {"client_id": client_id, "new_rate": new_rate},
                        "high",
                        reason,
                    )
                    st.rerun()

    with tabs[3]:
        st.subheader("Create Quote")

        source_type = st.selectbox("Source Type", ["manual", "lead", "client"])
        source_id = None
        client_name = ""
        client_phone = ""
        client_address = ""

        if source_type == "lead":
            lead_df = db.fetch_df(
                "SELECT id, name, phone, address FROM leads WHERE archived = 0 ORDER BY created_at DESC"
            )
            if not lead_df.empty:
                source_id = st.selectbox("Lead", lead_df["id"].tolist())
                row = db.fetchone("SELECT * FROM leads WHERE id = ?", (source_id,))
                client_name = row["name"]
                client_phone = row["phone"] or ""
                client_address = row["address"] or ""
        elif source_type == "client":
            client_df = db.fetch_df(
                "SELECT id, name, phone, address FROM clients WHERE archived = 0 ORDER BY name"
            )
            if not client_df.empty:
                source_id = st.selectbox("Client", client_df["id"].tolist())
                row = db.fetchone("SELECT * FROM clients WHERE id = ?", (source_id,))
                client_name = row["name"]
                client_phone = row["phone"] or ""
                client_address = row["address"] or ""
        else:
            c1, c2, c3 = st.columns(3)
            client_name = c1.text_input("Client Name")
            client_phone = c2.text_input("Phone")
            client_address = c3.text_input("Address")

        c1, c2, c3 = st.columns(3)
        service_type = c1.selectbox("Service Type", ["Standard", "Deep Clean", "Move-Out"])
        kitchen_size = c2.selectbox("Kitchen Size", ["Small", "Medium", "Large"])
        condition = c3.selectbox("Condition", ["Clean", "Average", "Needs Extra Attention"])

        c4, c5, c6, c7 = st.columns(4)
        bedrooms = c4.number_input("Bedrooms", min_value=0, value=3, step=1)
        bathrooms = c5.number_input("Bathrooms", min_value=0.0, value=2.0, step=0.5, format="%.1f")
        living_rooms = c6.number_input("Living Rooms", min_value=0, value=1, step=1)
        additional_rooms = c7.number_input("Additional Rooms", min_value=0, value=0, step=1)

        c8, c9, c10 = st.columns(3)
        pets = c8.checkbox("Pets in Home", value=False)
        supplies = c9.checkbox("Bringing Supplies", value=True)
        pantry_org = c10.checkbox("Pantry / Org Included", value=False)

        quote_input = QuoteInput(
            service_type=service_type,
            bedrooms=int(bedrooms),
            bathrooms=int(bathrooms),
            living_rooms=int(living_rooms),
            additional_rooms=int(additional_rooms),
            kitchen_size=kitchen_size,
            condition=condition,
            pets=bool(pets),
            supplies=bool(supplies),
            pantry_org=bool(pantry_org),
        )

        result = quotes.estimate(quote_input)
        hour_result = quotes.hours(quote_input)

        c11, c12, c13 = st.columns(3)
        c11.metric("Low Estimate", money(result["low_estimate"]))
        c12.metric("High Estimate", money(result["high_estimate"]))
        c13.metric("Recommended", money(result["recommended"]))

        c14, c15 = st.columns(2)
        c14.metric("Low Hours", hour_result["low_hours"])
        c15.metric("High Hours", hour_result["high_hours"])

        final_amount = st.number_input("Final Quote Amount", min_value=0.0, value=float(result["recommended"]), step=5.0)
        quote_notes = st.text_area("Quote Notes")

        midpoint = float(result["recommended"])
        diff_pct = abs(final_amount - midpoint) / midpoint if midpoint else 0.0

        c16, c17 = st.columns(2)

        if c16.button("Save Quote"):
            db.execute(
                """
                INSERT INTO quotes(
                    id, created_at, source_type, source_id, client_name, phone, address, service_type,
                    bedrooms, bathrooms, living_rooms, additional_rooms, kitchen_size, condition,
                    pets, supplies, pantry_org, low_estimate, high_estimate, recommended,
                    low_hours, high_hours, final_amount, status, notes, archived
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, 0)
                """,
                (
                    new_id(),
                    now_ts(),
                    source_type,
                    source_id,
                    client_name,
                    client_phone,
                    client_address,
                    service_type,
                    int(bedrooms),
                    int(bathrooms),
                    int(living_rooms),
                    int(additional_rooms),
                    kitchen_size,
                    condition,
                    1 if pets else 0,
                    1 if supplies else 0,
                    1 if pantry_org else 0,
                    result["low_estimate"],
                    result["high_estimate"],
                    result["recommended"],
                    hour_result["low_hours"],
                    hour_result["high_hours"],
                    final_amount,
                    quote_notes.strip(),
                ),
            )
            db.log("quote_saved", client_name)
            st.success("Quote saved")
            st.rerun()

        if c17.button("Queue Override Approval") and diff_pct >= 0.20:
            auto.create_approval(
                "quote_override",
                {"client_name": client_name, "recommended": result["recommended"], "final_amount": final_amount},
                "high",
                f"Quote override exceeds 20% for {client_name}",
            )
            st.success("Override approval queued")

        st.subheader("Saved Quotes")
        quote_df = db.fetch_df(
            """
            SELECT id, created_at, client_name, service_type, low_estimate, high_estimate,
                   recommended, final_amount, status
            FROM quotes
            WHERE archived = 0
            ORDER BY created_at DESC
            """
        )
        st.dataframe(quote_df, use_container_width=True, hide_index=True)

        if not quote_df.empty:
            with st.form("quote_to_job"):
                quote_id = st.selectbox("Quote ID", quote_df["id"].tolist())
                job_date = st.date_input("Create Job Date", value=date.today() + timedelta(days=1), key="quote_job_date")
                create_client = st.checkbox("Create client if missing", value=True)
                submitted = st.form_submit_button("Convert Quote to Job")
                if submitted:
                    q = db.fetchone("SELECT * FROM quotes WHERE id = ?", (quote_id,))
                    client = db.fetchone(
                        "SELECT id FROM clients WHERE name = ? AND archived = 0 ORDER BY created_at DESC LIMIT 1",
                        (q["client_name"],),
                    )
                    client_id = client["id"] if client else None

                    if not client_id and create_client:
                        client_id = new_id()
                        db.execute(
                            """
                            INSERT INTO clients(id, created_at, name, phone, address, frequency, recurring_rate, status, notes, archived)
                            VALUES(?, ?, ?, ?, ?, ?, ?, 'active', ?, 0)
                            """,
                            (
                                client_id,
                                now_ts(),
                                q["client_name"],
                                q["phone"],
                                q["address"],
                                "Unsure",
                                float(db.setting("recurring_biweekly_rate")),
                                q["notes"],
                            ),
                        )

                    if client_id:
                        db.execute(
                            """
                            INSERT INTO jobs(id, created_at, client_id, job_date, job_type, hours_estimate, actual_hours, amount, status, notes, archived)
                            VALUES(?, ?, ?, ?, ?, ?, NULL, ?, 'scheduled', ?, 0)
                            """,
                            (
                                new_id(),
                                now_ts(),
                                client_id,
                                job_date.strftime("%Y-%m-%d"),
                                q["service_type"],
                                q["high_hours"],
                                q["final_amount"] or q["recommended"],
                                q["notes"],
                            ),
                        )
                        db.execute("UPDATE quotes SET status = 'scheduled' WHERE id = ?", (quote_id,))
                        db.log("quote_converted_to_job", quote_id)
                        st.success("Quote converted to job")
                        st.rerun()
                    else:
                        st.error("No client found and client creation disabled")

    with tabs[4]:
        clients_for_jobs = db.fetch_df("SELECT id, name FROM clients WHERE archived = 0 ORDER BY name")
        if clients_for_jobs.empty:
            st.info("No clients yet")
        else:
            name_map = dict(zip(clients_for_jobs["id"], clients_for_jobs["name"]))
            with st.form("job_create", clear_on_submit=True):
                c1, c2, c3 = st.columns(3)
                client_id = c1.selectbox("Client", clients_for_jobs["id"].tolist(), format_func=lambda x: name_map.get(x, x))
                job_date = c2.date_input("Job Date", value=date.today())
                job_type = c3.selectbox("Job Type", ["Deep Clean", "Bi-Weekly", "Monthly", "One-Time", "Walkthrough"])
                c4, c5 = st.columns(2)
                hours_estimate = c4.number_input("Estimated Hours", min_value=0.0, value=3.0, step=0.5)
                amount = c5.number_input("Estimated Amount", min_value=0.0, value=float(db.setting("deep_clean_base_price")))
                notes = st.text_area("Notes", key="job_notes")
                submitted = st.form_submit_button("Schedule Job")
                if submitted:
                    db.execute(
                        """
                        INSERT INTO jobs(id, created_at, client_id, job_date, job_type, hours_estimate,
                                         actual_hours, amount, status, notes, archived)
                        VALUES(?, ?, ?, ?, ?, ?, NULL, ?, 'scheduled', ?, 0)
                        """,
                        (
                            new_id(),
                            now_ts(),
                            client_id,
                            job_date.strftime("%Y-%m-%d"),
                            job_type,
                            hours_estimate,
                            amount,
                            notes.strip(),
                        ),
                    )
                    db.log("job_created", f"{client_id}:{job_date}")
                    st.rerun()

        jobs = db.fetch_df(
            """
            SELECT j.id, c.name AS client, j.job_date, j.job_type, j.hours_estimate,
                   j.actual_hours, j.amount, j.status
            FROM jobs j
            JOIN clients c ON c.id = j.client_id
            WHERE j.archived = 0
            ORDER BY j.job_date DESC
            """
        )
        st.dataframe(jobs, use_container_width=True, hide_index=True)

        scheduled = db.fetch_df("SELECT id FROM jobs WHERE archived = 0 AND status IN ('scheduled','in_progress') ORDER BY job_date")
        if not scheduled.empty:
            with st.form("complete_job"):
                job_id = st.selectbox("Complete Job ID", scheduled["id"].tolist())
                actual_hours = st.number_input("Actual Hours", min_value=0.0, value=3.0, step=0.25)
                final_amount = st.number_input("Final Amount", min_value=0.0, value=float(db.setting("deep_clean_base_price")))
                create_invoice = st.checkbox("Create Invoice", value=True)
                due_date = st.date_input("Due Date", value=date.today() + timedelta(days=7))
                submitted = st.form_submit_button("Mark Completed")
                if submitted:
                    row = db.fetchone("SELECT client_id FROM jobs WHERE id = ?", (job_id,))
                    db.execute(
                        "UPDATE jobs SET status = 'completed', actual_hours = ?, amount = ? WHERE id = ?",
                        (actual_hours, final_amount, job_id),
                    )
                    if create_invoice:
                        db.execute(
                            """
                            INSERT INTO invoices(id, created_at, client_id, job_id, due_date, amount,
                                                 status, paid_date, notes, archived)
                            VALUES(?, ?, ?, ?, ?, ?, 'unpaid', NULL, '', 0)
                            """,
                            (
                                new_id(),
                                now_ts(),
                                row["client_id"],
                                job_id,
                                due_date.strftime("%Y-%m-%d"),
                                final_amount,
                            ),
                        )
                        client_row = db.fetchone("SELECT name, phone FROM clients WHERE id = ?", (row["client_id"],))
                        if db.setting("sms_auto_invoice_notice") == "1" and client_row and client_row["phone"]:
                            sms.queue_invoice_notice(
                                client_id=row["client_id"],
                                phone=client_row["phone"],
                                client_name=client_row["name"],
                                amount=final_amount,
                                due_date=due_date.strftime("%Y-%m-%d"),
                            )

                    db.log("job_completed", job_id)
                    st.rerun()

            with st.form("reschedule"):
                job_id = st.selectbox("Job ID", scheduled["id"].tolist(), key="job_resched")
                new_date = st.date_input("Suggested New Date", value=date.today() + timedelta(days=1))
                reason = st.text_input("Reason", value="Manual reschedule request")
                submitted = st.form_submit_button("Queue Reschedule Approval")
                if submitted:
                    auto.create_approval(
                        "reschedule_job",
                        {"job_id": job_id, "new_date": new_date.strftime("%Y-%m-%d")},
                        "high",
                        reason,
                    )
                    st.rerun()

    with tabs[5]:
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
            with st.form("pay_invoice"):
                inv_id = st.selectbox("Invoice ID", invoices["id"].tolist())
                paid_date = st.date_input("Paid Date", value=date.today())
                submitted = st.form_submit_button("Mark Paid")
                if submitted:
                    db.execute(
                        "UPDATE invoices SET status = 'paid', paid_date = ? WHERE id = ?",
                        (paid_date.strftime("%Y-%m-%d"), inv_id),
                    )
                    db.log("invoice_paid", inv_id)
                    st.rerun()

        with st.form("expense_form", clear_on_submit=True):
            c1, c2, c3, c4 = st.columns(4)
            expense_date = c1.date_input("Expense Date", value=date.today())
            category = c2.selectbox("Category", ["Supplies", "Fuel", "Payroll", "Equipment", "Software", "Marketing", "Other"])
            vendor = c3.text_input("Vendor")
            expense_amount = c4.number_input("Amount", min_value=0.0, value=0.0)
            notes = st.text_area("Notes", key="expense_notes")
            submitted = st.form_submit_button("Add Expense")
            if submitted and expense_amount > 0:
                db.execute(
                    """
                    INSERT INTO expenses(id, created_at, expense_date, category, vendor, amount, notes)
                    VALUES(?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id(),
                        now_ts(),
                        expense_date.strftime("%Y-%m-%d"),
                        category,
                        vendor.strip(),
                        expense_amount,
                        notes.strip(),
                    ),
                )
                db.log("expense_added", f"{category}:{expense_amount}")
                st.rerun()

        current = finance.metrics()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Revenue MTD", money(current["month_revenue"]))
        c2.metric("Expenses MTD", money(current["month_expenses"]))
        c3.metric("Profit MTD", money(current["month_profit"]))
        c4.metric("Outstanding", money(current["outstanding_ar"]))

    with tabs[6]:
        st.subheader("SMS Center")
        st.caption("Free start mode = manual Google Voice queue")

        c1, c2 = st.columns(2)
        if c1.button("Send Queued SMS"):
            result = sms.send_queued()
            st.success(f"Sent: {result['sent']} | Failed: {result['failed']} | {result['reason']}")
            st.rerun()

        if c2.button("Queue Tomorrow Job Reminders"):
            rows = db.fetchall(
                """
                SELECT j.id, j.job_date, c.id AS client_id, c.name, c.phone
                FROM jobs j
                JOIN clients c ON c.id = j.client_id
                WHERE j.archived = 0
                  AND c.archived = 0
                  AND j.status = 'scheduled'
                  AND j.job_date = date('now', '+1 day')
                  AND c.phone IS NOT NULL
                  AND c.phone != ''
                """
            )
            count = 0
            for row in rows:
                sms.queue_job_reminder(
                    client_id=row["client_id"],
                    phone=row["phone"],
                    client_name=row["name"],
                    job_date=row["job_date"],
                )
                count += 1
            st.success(f"Queued {count} reminders")
            st.rerun()

        clients_sms = db.fetch_df(
            "SELECT id, name, phone FROM clients WHERE archived = 0 AND phone IS NOT NULL AND phone != '' ORDER BY name"
        )

        st.subheader("Manual SMS")
        if not clients_sms.empty:
            name_map = dict(zip(clients_sms["id"], clients_sms["name"]))
            with st.form("manual_sms"):
                sms_client_id = st.selectbox("Client", clients_sms["id"].tolist(), format_func=lambda x: name_map.get(x, x))
                sms_body = st.text_area("Message")
                sms_kind = st.selectbox("Type", ["manual", "followup", "promo"])
                require_approval = st.checkbox("Require approval before sending", value=(sms_kind == "promo"))
                submitted = st.form_submit_button("Queue SMS")
                if submitted and sms_body.strip():
                    row = db.fetchone("SELECT * FROM clients WHERE id = ?", (sms_client_id,))
                    sms.queue_message(
                        phone=row["phone"],
                        body=sms_body.strip(),
                        message_type=sms_kind,
                        client_id=sms_client_id,
                        approval_required=require_approval,
                    )
                    st.success("SMS queued")
                    st.rerun()

        st.subheader("Bulk SMS Approval Queue")
        if not clients_sms.empty:
            name_map = dict(zip(clients_sms["id"], clients_sms["name"]))
            with st.form("bulk_sms"):
                bulk_ids = st.multiselect("Clients", clients_sms["id"].tolist(), format_func=lambda x: name_map.get(x, x))
                bulk_body = st.text_area("Bulk Message")
                submitted = st.form_submit_button("Queue Bulk SMS")
                if submitted and bulk_ids and bulk_body.strip():
                    created_ids = []
                    for cid in bulk_ids:
                        row = db.fetchone("SELECT * FROM clients WHERE id = ?", (cid,))
                        sms.queue_message(
                            phone=row["phone"],
                            body=bulk_body.strip(),
                            message_type="promo",
                            client_id=cid,
                            approval_required=True,
                        )
                    new_sms = db.fetchall(
                        """
                        SELECT id FROM sms_messages
                        WHERE status = 'queued'
                          AND approval_required = 1
                          AND archived = 0
                        ORDER BY created_at DESC
                        LIMIT ?
                        """,
                        (len(bulk_ids),),
                    )
                    for item in new_sms:
                        created_ids.append(item["id"])
                    auto.queue_bulk_sms_approval(created_ids, "Bulk promotional SMS")
                    st.success("Bulk SMS queued with approval gate")
                    st.rerun()

        manual_df = db.fetch_df(
            """
            SELECT id, created_at, phone, message_type, body, status
            FROM sms_messages
            WHERE archived = 0 AND status = 'manual-send'
            ORDER BY created_at DESC
            """
        )
        st.subheader("Manual Send Queue")
        st.dataframe(manual_df, use_container_width=True, hide_index=True)

        if not manual_df.empty:
            with st.form("mark_manual_sent"):
                sms_id = st.selectbox("Manual SMS ID", manual_df["id"].tolist())
                submitted = st.form_submit_button("Mark Sent Manually")
                if submitted:
                    db.execute(
                        """
                        UPDATE sms_messages
                        SET status = 'sent', sent_at = ?
                        WHERE id = ?
                        """,
                        (now_ts(), sms_id),
                    )
                    db.log("sms_manual_sent", sms_id)
                    st.rerun()

        sms_df = db.fetch_df(
            """
            SELECT id, created_at, phone, message_type, status, approval_required, sent_at, error_text
            FROM sms_messages
            WHERE archived = 0
            ORDER BY created_at DESC
            """
        )
        st.subheader("All SMS")
        st.dataframe(sms_df, use_container_width=True, hide_index=True)

    with tabs[7]:
        st.subheader("Client Portal Access")

        clients_portal = db.fetch_df("SELECT id, name, phone FROM clients WHERE archived = 0 ORDER BY name")
        if not clients_portal.empty:
            name_map = dict(zip(clients_portal["id"], clients_portal["name"]))
            with st.form("portal_access_form"):
                portal_client_id = st.selectbox("Client", clients_portal["id"].tolist(), format_func=lambda x: name_map.get(x, x))
                access_code = st.text_input("Access Code")
                submitted = st.form_submit_button("Create / Rotate Access Code")
                if submitted and access_code.strip():
                    existing = db.fetchone(
                        "SELECT id FROM portal_access WHERE client_id = ? AND archived = 0 ORDER BY created_at DESC LIMIT 1",
                        (portal_client_id,),
                    )
                    if existing:
                        db.execute(
                            """
                            UPDATE portal_access
                            SET access_code = ?, status = 'active'
                            WHERE id = ?
                            """,
                            (access_code.strip(), existing["id"]),
                        )
                    else:
                        db.execute(
                            """
                            INSERT INTO portal_access(id, created_at, client_id, access_code, status, last_used_at, archived)
                            VALUES(?, ?, ?, ?, 'active', NULL, 0)
                            """,
                            (new_id(), now_ts(), portal_client_id, access_code.strip()),
                        )
                    db.log("portal_access_updated", portal_client_id)
                    st.success("Portal access updated")
                    st.rerun()

        portal_df = db.fetch_df(
            """
            SELECT p.id, c.name, c.phone, p.access_code, p.status, p.last_used_at
            FROM portal_access p
            JOIN clients c ON c.id = p.client_id
            WHERE p.archived = 0
            ORDER BY c.name
            """
        )
        st.dataframe(portal_df, use_container_width=True, hide_index=True)
        st.info("Run portal with: streamlit run client_portal.py")

    with tabs[8]:
        approvals = db.fetch_df(
            "SELECT id, created_at, action_type, risk, reason, status, payload FROM approvals ORDER BY created_at DESC"
        )
        st.dataframe(approvals, use_container_width=True, hide_index=True)

        pending = approvals[approvals["status"] == "pending"] if not approvals.empty else pd.DataFrame()
        if not pending.empty:
            with st.form("approval_form"):
                approval_id = st.selectbox("Approval ID", pending["id"].tolist())
                decision = st.selectbox("Decision", ["approve", "reject"])
                note = st.text_input("Decision Note")
                submitted = st.form_submit_button("Submit")
                if submitted:
                    auto.process_approval(approval_id, decision, note)
                    st.rerun()

    with tabs[9]:
        c1, c2, c3 = st.columns(3)
        if c1.button("Run Scan Now"):
            auto.scan()
            st.rerun()
        if c2.button("Archive Now"):
            auto.archive_now()
            st.rerun()
        if c3.button("Seed Demo Data"):
            if db.fetchone("SELECT COUNT(*) AS cnt FROM clients")["cnt"] == 0:
                client_id = new_id()
                db.execute(
                    """
                    INSERT INTO clients(id, created_at, name, phone, address, frequency, recurring_rate, status, notes, archived)
                    VALUES(?, ?, 'Jenn Demo', ?, '84332', 'Bi-Weekly', ?, 'active', 'Demo', 0)
                    """,
                    (client_id, now_ts(), db.setting("phone"), float(db.setting("recurring_biweekly_rate"))),
                )
                db.execute(
                    """
                    INSERT INTO jobs(id, created_at, client_id, job_date, job_type, hours_estimate, actual_hours, amount, status, notes, archived)
                    VALUES(?, ?, ?, ?, 'Bi-Weekly', 3, NULL, ?, 'scheduled', '', 0)
                    """,
                    (
                        new_id(),
                        now_ts(),
                        client_id,
                        (date.today() + timedelta(days=1)).strftime("%Y-%m-%d"),
                        float(db.setting("recurring_biweekly_rate")),
                    ),
                )
                db.execute(
                    """
                    INSERT INTO invoices(id, created_at, client_id, job_id, due_date, amount, status, paid_date, notes, archived)
                    VALUES(?, ?, ?, NULL, ?, 160, 'unpaid', NULL, '', 0)
                    """,
                    (new_id(), now_ts(), client_id, (date.today() - timedelta(days=3)).strftime("%Y-%m-%d")),
                )
                db.execute(
                    """
                    INSERT INTO leads(id, created_at, name, phone, address, source, desired_frequency, condition, priority_focus, follow_up_date, status, notes, archived)
                    VALUES(?, ?, 'Warm Lead Demo', ?, 'Local', 'Flyer', 'Bi-Weekly', 'Average', 'Low-allergen', ?, 'quoted', 'Needs callback', 0)
                    """,
                    (
                        new_id(),
                        now_ts(),
                        db.setting("phone"),
                        (date.today() - timedelta(days=1)).strftime("%Y-%m-%d"),
                    ),
                )
                db.execute(
                    """
                    INSERT INTO expenses(id, created_at, expense_date, category, vendor, amount, notes)
                    VALUES(?, ?, ?, 'Supplies', 'Demo Vendor', 42.5, 'Seeded')
                    """,
                    (new_id(), now_ts(), today_str()),
                )
                auto.scan()
                st.rerun()

        health = []
        health.append(["Leads", "OK" if leads_open > 0 else "ATTENTION", f"{leads_open} active leads"])
        health.append(["Alerts", "OK" if alerts_open == 0 else "ATTENTION", f"{alerts_open} unresolved alerts"])
        st.dataframe(pd.DataFrame(health, columns=["Area", "State", "Detail"]), use_container_width=True, hide_index=True)

        audit = db.fetch_df("SELECT created_at, category, detail FROM audit_log ORDER BY created_at DESC LIMIT 100")
        st.dataframe(audit, use_container_width=True, hide_index=True)

    with tabs[10]:
        with st.form("settings_form"):
            c1, c2, c3 = st.columns(3)
            business_name = c1.text_input("Business Name", value=db.setting("business_name"))
            tagline_val = c2.text_input("Tagline", value=db.setting("tagline"))
            phone_val = c3.text_input("Phone", value=db.setting("phone"))

            c4, c5, c6 = st.columns(3)
            deep_hours = c4.number_input("Deep Base Hours", min_value=0.0, value=float(db.setting("deep_clean_base_hours")))
            deep_base = c5.number_input("Deep Base Price", min_value=0.0, value=float(db.setting("deep_clean_base_price")))
            deep_over = c6.number_input("Deep Overage Hourly", min_value=0.0, value=float(db.setting("deep_clean_overage_hourly")))

            c7, c8, c9 = st.columns(3)
            recurring = c7.number_input("Recurring Rate", min_value=0.0, value=float(db.setting("recurring_biweekly_rate")))
            max_jobs = c8.number_input("Max Jobs / Day", min_value=1.0, value=float(db.setting("max_jobs_per_day")))
            min_pipeline = c9.number_input("Min Jobs next 14d", min_value=0.0, value=float(db.setting("low_pipeline_threshold_14d")))

            c10, c11, c12 = st.columns(3)
            self_care = c10.number_input("Self-Care Threshold next 7d", min_value=0.0, value=float(db.setting("self_care_job_threshold_7d")))
            archive_days = c11.number_input("Archive After Days", min_value=30.0, value=float(db.setting("archive_after_days")))
            sms_provider = c12.selectbox("SMS Provider", ["disabled", "manual_google_voice", "textbelt_free"], index=["disabled", "manual_google_voice", "textbelt_free"].index(db.setting("sms_provider")) if db.setting("sms_provider") in ["disabled", "manual_google_voice", "textbelt_free"] else 1)

            c13, c14, c15 = st.columns(3)
            sms_enabled = c13.selectbox("SMS Enabled", ["0", "1"], index=1 if db.setting("sms_enabled") == "1" else 0)
            sms_job = c14.selectbox("Auto Job Reminder SMS", ["0", "1"], index=1 if db.setting("sms_auto_job_reminder") == "1" else 0)
            sms_invoice = c15.selectbox("Auto Invoice SMS", ["0", "1"], index=1 if db.setting("sms_auto_invoice_notice") == "1" else 0)

            submitted = st.form_submit_button("Save Settings")
            if submitted:
                updates = {
                    "business_name": business_name,
                    "tagline": tagline_val,
                    "phone": phone_val,
                    "deep_clean_base_hours": deep_hours,
                    "deep_clean_base_price": deep_base,
                    "deep_clean_overage_hourly": deep_over,
                    "recurring_biweekly_rate": recurring,
                    "max_jobs_per_day": max_jobs,
                    "low_pipeline_threshold_14d": min_pipeline,
                    "self_care_job_threshold_7d": self_care,
                    "archive_after_days": archive_days,
                    "sms_provider": sms_provider,
                    "sms_enabled": sms_enabled,
                    "sms_auto_job_reminder": sms_job,
                    "sms_auto_invoice_notice": sms_invoice,
                }
                for k, v in updates.items():
                    db.set_setting(k, v)
                db.log("settings_updated", str(updates))
                st.rerun()

    with tabs[11]:
        exports = {
            "leads.csv": db.fetch_df("SELECT * FROM leads WHERE archived = 0 ORDER BY created_at DESC"),
            "clients.csv": db.fetch_df("SELECT * FROM clients WHERE archived = 0 ORDER BY created_at DESC"),
            "quotes.csv": db.fetch_df("SELECT * FROM quotes WHERE archived = 0 ORDER BY created_at DESC"),
            "jobs.csv": db.fetch_df("SELECT * FROM jobs WHERE archived = 0 ORDER BY created_at DESC"),
            "invoices.csv": db.fetch_df("SELECT * FROM invoices WHERE archived = 0 ORDER BY created_at DESC"),
            "expenses.csv": db.fetch_df("SELECT * FROM expenses ORDER BY created_at DESC"),
            "sms_messages.csv": db.fetch_df("SELECT * FROM sms_messages WHERE archived = 0 ORDER BY created_at DESC"),
            "portal_access.csv": db.fetch_df("SELECT * FROM portal_access WHERE archived = 0 ORDER BY created_at DESC"),
            "alerts.csv": db.fetch_df("SELECT * FROM alerts WHERE archived = 0 ORDER BY created_at DESC"),
            "audit_log.csv": db.fetch_df("SELECT * FROM audit_log ORDER BY created_at DESC"),
        }
        for name, df in exports.items():
            st.write(name)
            _download_csv(df, name, f"Download {name}")