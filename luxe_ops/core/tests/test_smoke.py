from luxe_ops.core.db import DB
from luxe_ops.core.automation import AutomationEngine
from luxe_ops.core.finance import FinanceEngine


def test_smoke(tmp_path):
    db_path = tmp_path / "luxe_ops_smoke.db"
    db = DB(str(db_path))
    business_tables = [
        "leads",
        "clients",
        "jobs",
        "invoices",
        "expenses",
        "approvals",
        "alerts",
        "audit_log",
        "quotes",
        "sms_messages",
        "portal_access",
    ]
    for table in business_tables:
        row = db.fetchone(f"SELECT COUNT(*) AS cnt FROM {table}")
        assert row["cnt"] == 0

    auto = AutomationEngine(db)
    fin = FinanceEngine(db)
    auto.scan()
    for table in business_tables:
        row = db.fetchone(f"SELECT COUNT(*) AS cnt FROM {table}")
        assert row["cnt"] == 0

    metrics = fin.metrics()
    assert isinstance(metrics, dict)
    assert "month_revenue" in metrics
    db_path.unlink()
