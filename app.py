## app.py
##python
from luxe_ops.core.db import DB
from luxe_ops.core.automation import AutomationEngine
from luxe_ops.core.finance import FinanceEngine
from luxe_ops.core.quote_engine import QuoteEngine
from luxe_ops.core.sms_service import SMSService
from luxe_ops.ui.pages import run_app


def main():
    db = DB()
    auto = AutomationEngine(db)
    finance = FinanceEngine(db)
    quotes = QuoteEngine(db)
    sms = SMSService(db)
    run_app(db, auto, finance, quotes, sms)


if __name__ == "__main__":
    main()