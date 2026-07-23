"""Read-only aggregation endpoints behind the dashboard charts."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import desc
from sqlmodel import Session, func, select

from ..api_utils import apply_store_filter, apply_time_filter, clamp_limit
from ..database import get_session
from ..models import Item, Receipt
from ..stores import store_display_name

router = APIRouter()

# Money-flow line items (deposits, deposit returns, vouchers) — real receipt
# lines, but not groceries. The default top-products view hides them; an
# explicit category pick (e.g. tapping the Pfand pie slice) still shows them.
_MONEY_FLOW_CATEGORIES = ("Pfand", "Gutscheine & Rabatte")


@router.get("/stats/dashboard")
def get_dashboard_stats(store: str = "all", session: Session = Depends(get_session)):
    """Total spent this month vs last month, filtered by store."""
    now = datetime.now()
    current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    if current_month_start.month == 1:
        prev_month_start = current_month_start.replace(year=now.year - 1, month=12)
    else:
        prev_month_start = current_month_start.replace(month=now.month - 1)

    query_curr = apply_store_filter(
        select(func.sum(Receipt.total_amount)).where(Receipt.date >= current_month_start), store
    )
    curr_total = session.exec(query_curr).first() or 0.0

    query_prev = apply_store_filter(
        select(func.sum(Receipt.total_amount)).where(
            Receipt.date >= prev_month_start,
            Receipt.date < current_month_start,
        ),
        store,
    )
    prev_total = session.exec(query_prev).first() or 0.0

    diff_percent = 0.0
    if prev_total > 0:
        diff_percent = ((curr_total - prev_total) / prev_total) * 100

    receipt_count = session.exec(
        apply_store_filter(select(func.count(Receipt.id)), store)
    ).one()

    return {
        "current_month_total": round(curr_total, 2),
        "previous_month_total": round(prev_total, 2),
        "diff_percent": round(diff_percent, 1),
        "receipt_count": int(receipt_count),
    }


@router.get("/stats/monthly")
def get_monthly_spending(store: str = "all", session: Session = Depends(get_session)):
    """Spending history grouped by month and split by store (aggregated in SQL)."""
    month_col = func.strftime("%Y-%m", Receipt.date).label("month")
    query = apply_store_filter(
        select(month_col, Receipt.store_key, func.sum(Receipt.total_amount).label("total")),
        store,
    ).group_by("month", Receipt.store_key)

    rows = session.exec(query).all()

    # Pivot into one dict per month with a column per store display name.
    monthly: dict[str, dict] = {}
    for month, store_key, total in rows:
        if not month:
            continue
        bucket = monthly.setdefault(month, {"month": month})
        label = store_display_name(store_key)
        bucket[label] = round(bucket.get(label, 0.0) + float(total or 0.0), 2)

    return [monthly[m] for m in sorted(monthly)]


@router.get("/stats/category")
def get_category_spending(mode: str = "all", month: str = None, week: str = None, store: str = "all",
                          start: str = None, end: str = None,
                          session: Session = Depends(get_session)):
    """Total spent per category, filtered by store and time range."""
    query = apply_store_filter(
        select(Item.category, func.sum(Item.price_total).label("total")).join(Receipt), store
    )
    query = apply_time_filter(query, start, end)

    if mode == "month" and month:
        query = query.where(func.strftime("%Y-%m", Receipt.date) == month)
    elif mode == "week" and week:
        query = query.where(func.strftime("%Y-W%W", Receipt.date) == week)

    query = query.group_by(Item.category).order_by(desc("total"))
    results = session.exec(query).all()

    return [{"name": c, "value": round(t, 2)} for c, t in results if c]


@router.get("/stats/top-products")
def get_top_products(mode: str = "all", year: str = None, month: str = None, store: str = "all",
                     start: str = None, end: str = None, category: str = None,
                     limit: int = 1000,
                     session: Session = Depends(get_session)):
    """Most frequently bought products, tagged with their store badge.

    Grouped by the raw receipt name: within one chain the receipt text is
    per-article and stable, so this stays truthful even when a product-layer
    merge is wrong. Curate identity on the products page instead.

    Like price-volatility, the default limit is high on purpose: the client
    search box filters this list, so a product bought a handful of times must
    not silently fall off a short leaderboard."""
    limit = clamp_limit(limit, cap=2000)
    query = apply_store_filter(
        select(
            Item.name,
            func.sum(Item.quantity).label("quantity"),
            func.max(Receipt.store_key).label("store_key"),
        ).join(Receipt),
        store,
    )
    query = apply_time_filter(query, start, end)

    if category and category != "all":
        query = query.where(Item.category == category)
    else:
        query = query.where(Item.category.notin_(_MONEY_FLOW_CATEGORIES))

    if mode == "year" and year:
        query = query.where(func.strftime("%Y", Receipt.date) == year)
    elif mode == "month" and month:
        query = query.where(func.strftime("%Y-%m", Receipt.date) == month)

    query = query.group_by(Item.name).order_by(desc("quantity")).limit(limit)
    results = session.exec(query).all()

    return [
        {"name": name, "quantity": qty, "store": store_display_name(store_key)}
        for name, qty, store_key in results
    ]


@router.get("/stats/price-volatility")
def get_price_volatility(store: str = "all", limit: int = 1000,
                         session: Session = Depends(get_session)):
    """Items whose price has changed the most, with store badges.

    Grouped by the raw receipt name (see top-products for the rationale).
    The default limit is deliberately high: the client search box filters this
    list, so an item must not silently fall off a short leaderboard."""
    limit = clamp_limit(limit, cap=2000)
    query = apply_store_filter(
        select(
            Item.name,
            func.min(Item.price_single).label("min_price"),
            func.max(Item.price_single).label("max_price"),
            func.count(Item.id).label("times_bought"),
            func.max(Receipt.store_key).label("store_key"),
        ).join(Receipt),
        store,
    ).group_by(Item.name).having(func.count(Item.id) > 1)

    results = session.exec(query).all()

    volatility = []
    for name, min_p, max_p, count, store_key in results:
        if min_p and min_p > 0 and max_p > min_p:
            if max_p > (min_p * 3):  # drop obvious outliers (weight vs unit price)
                continue
            pct_change = ((max_p - min_p) / min_p) * 100
            volatility.append({
                "name": name,
                "min_price": round(min_p, 2),
                "max_price": round(max_p, 2),
                "change_percent": round(pct_change, 1),
                "times_bought": count,
                "store": store_display_name(store_key),
            })

    volatility.sort(key=lambda x: x["change_percent"], reverse=True)
    return volatility[:limit]


@router.get("/stats/price-history")
def get_price_history(item_name: str, store: str = "all", limit: int = 500,
                      session: Session = Depends(get_session)):
    """Chronological price history of a specific item."""
    limit = clamp_limit(limit, cap=1000)
    query = apply_store_filter(
        select(Receipt.date, Item.price_single).join(Receipt).where(Item.name == item_name), store
    ).order_by(desc(Receipt.date)).limit(limit)

    results = list(reversed(session.exec(query).all()))

    return [
        {
            "date": date.strftime("%b %Y"),
            "exact_date": date.strftime("%d.%m.%Y"),
            "iso_date": date.strftime("%Y-%m-%d"),
            "price": round(price, 2),
        }
        for date, price in results
        if price is not None
    ]


@router.get("/stats/wallet-share")
def get_wallet_share(start: str = None, end: str = None,
                     session: Session = Depends(get_session)):
    """Total money spent per supermarket chain (optionally time-boxed)."""
    query = select(
        Receipt.store_key, func.sum(Receipt.total_amount).label("total")
    )
    query = apply_time_filter(query, start, end)
    query = query.group_by(Receipt.store_key)

    results = session.exec(query).all()
    return [
        {"name": store_display_name(store_key), "value": float(total or 0.0)}
        for store_key, total in results
    ]
