from datetime import date

from .helpers import today_str
from .db import DB


class FinanceEngine:
    def __init__(self, db: DB):
        self.db = db

    def metrics(self):
        month_start = date.today().replace(day=1).strftime("%Y-%m-%d")
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
            WHERE archived = 0
              AND status = 'unpaid'
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

        return {
            "month_revenue": float(revenue),
            "month_expenses": float(expenses),
            "month_profit": float(revenue) - float(expenses),
            "outstanding_ar": float(outstanding),
        }

    def monthly_report(self):
        return self.db.fetch_df(
            """
            SELECT
                substr(COALESCE(paid_date, due_date), 1, 7) AS month,
                SUM(CASE WHEN status = 'paid' THEN amount ELSE 0 END) AS paid_revenue,
                SUM(CASE WHEN status = 'unpaid' THEN amount ELSE 0 END) AS outstanding
            FROM invoices
            WHERE archived = 0
            GROUP BY substr(COALESCE(paid_date, due_date), 1, 7)
            ORDER BY month DESC
            """
        )