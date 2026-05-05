import uuid
from datetime import datetime, date
from .config import DATE_FMT, NOW_FMT


def new_id() -> str:
    return str(uuid.uuid4())[:8]


def now_ts() -> str:
    return datetime.now().strftime(NOW_FMT)


def today_str() -> str:
    return date.today().strftime(DATE_FMT)


def parse_date(value: str):
    return datetime.strptime(value, DATE_FMT).date()


def money(value) -> str:
    try:
        return f"${float(value):,.2f}"
    except Exception:
        return "$0.00"