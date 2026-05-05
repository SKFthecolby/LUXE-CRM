from luxe_ops.core.db import DB
from luxe_ops.core.automation import AutomationEngine
from luxe_ops.core.finance import FinanceEngine


def test_smoke():
    db = DB("test_luxe_ops.db")
    auto = AutomationEngine(db)
    fin = FinanceEngine(db)
    auto.scan()
    metrics = fin.metrics()
    assert isinstance(metrics, dict)
    assert "month_revenue" in metrics