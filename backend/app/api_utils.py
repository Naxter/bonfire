"""Small helpers shared by the API routers: query filters and input bounds."""

from __future__ import annotations

from datetime import datetime

from .models import Receipt

# Hard ceilings so a stray ?limit=1000000 can't make the Pi swap.
MAX_PAGE_SIZE = 100
MAX_LIST_LIMIT = 500


def clamp_page(page: int) -> int:
    return max(1, int(page))


def clamp_limit(limit: int, cap: int = MAX_PAGE_SIZE, floor: int = 1) -> int:
    return max(floor, min(int(limit), cap))


def parse_dt(value: str | None) -> datetime | None:
    """Parse an ISO date/datetime string, or return None if empty/invalid."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def apply_store_filter(query, store: str):
    """Filter a query by canonical store_key. 'all' means no filter."""
    if store and store != "all":
        query = query.where(Receipt.store_key == store)
    return query


def apply_time_filter(query, start: str | None, end: str | None):
    """Restrict to receipts with ``start <= date < end`` (both optional, ISO)."""
    s, e = parse_dt(start), parse_dt(end)
    if s is not None:
        query = query.where(Receipt.date >= s)
    if e is not None:
        query = query.where(Receipt.date < e)
    return query
