import os
import re
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import desc, or_, text
from sqlmodel import Session, SQLModel, func, select

from . import config  # noqa: F401  (loads repo-root .env before reading env vars)
from .categories import VALID_CATEGORIES
from .categorizer import recategorize
from .database import create_db_and_tables, engine, get_session
from .insights import answer_question, budget_report, meal_suggestions, restock_report
from .llm import resolve_provider_name
from .models import CategoryMap, Item, MealProfile, Product, Receipt
from .stores import list_stores, store_display_name
from .vision_ingest import IMAGE_EXTS, MAX_IMAGE_BYTES, process_image_file


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure the schema exists (and migrations/backfill run) before serving.
    create_db_and_tables()
    yield


app = FastAPI(lifespan=lifespan)

# Rate-limit the endpoints that cost money (LLM calls) or mutate in bulk —
# defense in depth behind the reverse proxy's Basic Auth.
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS: wildcard + credentials is rejected by browsers, so pin the origin(s).
# Configure via FRONTEND_ORIGINS (comma-separated) in the environment. With the
# same-origin Caddy proxy this only matters for local dev.
_origins = [o.strip() for o in os.getenv("FRONTEND_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)


class ReceiptPublic(SQLModel):
    """Client-facing receipt: omits raw_data / loyalty_details / transaction_id
    (full parsed eBon incl. payment + loyalty info stays server-side)."""
    id: int
    store_name: str
    store_key: str
    store_address: str | None = None
    date: datetime
    total_amount: float
    currency: str = "EUR"
    pdf_filename: str


def _apply_store_filter(query, store: str):
    """Filter a query by canonical store_key. 'all' means no filter."""
    if store and store != "all":
        query = query.where(Receipt.store_key == store)
    return query


def _parse_dt(value: str | None):
    """Parse an ISO date/datetime string, or return None if empty/invalid."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _apply_time_filter(query, start: str | None, end: str | None):
    """Restrict to receipts with ``start <= date < end`` (both optional, ISO)."""
    s, e = _parse_dt(start), _parse_dt(end)
    if s is not None:
        query = query.where(Receipt.date >= s)
    if e is not None:
        query = query.where(Receipt.date < e)
    return query


@app.get("/stores")
def get_stores(session: Session = Depends(get_session)):
    """Store list for the frontend filter. Registered adapters first, then any
    other store_key present in the data (e.g. Aldi/Lidl from photographed
    receipts) so new stores appear in the filter automatically."""
    stores = list_stores()
    keys = {s["key"] for s in stores}
    db_keys = session.exec(select(Receipt.store_key).distinct()).all()
    for key in sorted(k for k in db_keys if k and k not in keys):
        stores.append({"key": key, "display_name": store_display_name(key)})
    return stores


@app.get("/categories")
def get_categories():
    """Canonical category taxonomy — drives the category filter in the UI."""
    return VALID_CATEGORIES


def _llm_configured(provider: str) -> bool:
    """Best-effort check that the selected provider has what it needs, without
    instantiating it (so /health never throws)."""
    if provider == "openai":
        return bool(os.getenv("OPENAI_API_KEY"))
    if provider in ("gemini", "google"):
        return bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    return True  # ollama: assume a reachable local/remote daemon


@app.get("/health")
def health():
    """Liveness + config check for the status badge and unattended monitoring."""
    provider = resolve_provider_name()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    llm_ok = _llm_configured(provider)
    return {
        "status": "ok" if (db_ok and llm_ok) else "degraded",
        "db": db_ok,
        "llm_provider": provider,
        "llm_configured": llm_ok,
    }


@app.get("/stats/dashboard")
def get_dashboard_stats(store: str = "all", session: Session = Depends(get_session)):
    """Total spent this month vs last month, filtered by store."""
    now = datetime.now()
    current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    if current_month_start.month == 1:
        prev_month_start = current_month_start.replace(year=now.year - 1, month=12)
    else:
        prev_month_start = current_month_start.replace(month=now.month - 1)

    query_curr = _apply_store_filter(
        select(func.sum(Receipt.total_amount)).where(Receipt.date >= current_month_start), store
    )
    curr_total = session.exec(query_curr).first() or 0.0

    query_prev = _apply_store_filter(
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

    return {
        "current_month_total": round(curr_total, 2),
        "previous_month_total": round(prev_total, 2),
        "diff_percent": round(diff_percent, 1),
    }


@app.get("/stats/monthly")
def get_monthly_spending(store: str = "all", session: Session = Depends(get_session)):
    """Spending history grouped by month and split by store (aggregated in SQL)."""
    month_col = func.strftime("%Y-%m", Receipt.date).label("month")
    query = _apply_store_filter(
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


@app.get("/stats/category")
def get_category_spending(mode: str = "all", month: str = None, week: str = None, store: str = "all",
                          start: str = None, end: str = None,
                          session: Session = Depends(get_session)):
    """Total spent per category, filtered by store and time range."""
    query = _apply_store_filter(
        select(Item.category, func.sum(Item.price_total).label("total")).join(Receipt), store
    )
    query = _apply_time_filter(query, start, end)

    if mode == "month" and month:
        query = query.where(func.strftime("%Y-%m", Receipt.date) == month)
    elif mode == "week" and week:
        query = query.where(func.strftime("%Y-W%W", Receipt.date) == week)

    query = query.group_by(Item.category).order_by(desc("total"))
    results = session.exec(query).all()

    return [{"name": c, "value": round(t, 2)} for c, t in results if c]


@app.get("/stats/top-products")
def get_top_products(mode: str = "all", year: str = None, month: str = None, store: str = "all",
                     start: str = None, end: str = None, category: str = None,
                     session: Session = Depends(get_session)):
    """Most frequently bought products, tagged with their store badge."""
    query = _apply_store_filter(
        select(
            Item.name,
            func.sum(Item.quantity).label("quantity"),
            func.max(Receipt.store_key).label("store_key"),
        ).join(Receipt),
        store,
    )
    query = _apply_time_filter(query, start, end)

    if category and category != "all":
        query = query.where(Item.category == category)

    if mode == "year" and year:
        query = query.where(func.strftime("%Y", Receipt.date) == year)
    elif mode == "month" and month:
        query = query.where(func.strftime("%Y-%m", Receipt.date) == month)

    query = query.group_by(Item.name).order_by(desc("quantity")).limit(50)
    results = session.exec(query).all()

    return [
        {"name": name, "quantity": qty, "store": store_display_name(store_key)}
        for name, qty, store_key in results
    ]


@app.get("/stats/price-volatility")
def get_price_volatility(store: str = "all", session: Session = Depends(get_session)):
    """Items whose price has changed the most, with store badges."""
    query = _apply_store_filter(
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
    return volatility


@app.get("/stats/price-history")
def get_price_history(item_name: str, store: str = "all", session: Session = Depends(get_session)):
    """Chronological price history of a specific item."""
    query = _apply_store_filter(
        select(Receipt.date, Item.price_single).join(Receipt).where(Item.name == item_name), store
    ).order_by(Receipt.date)

    results = session.exec(query).all()

    return [
        {
            "date": date.strftime("%b %Y"),
            "exact_date": date.strftime("%d.%m.%Y"),
            "price": round(price, 2),
        }
        for date, price in results
    ]


@app.get("/stats/wallet-share")
def get_wallet_share(session: Session = Depends(get_session)):
    """Total money spent per supermarket chain."""
    query = select(
        Receipt.store_key, func.sum(Receipt.total_amount).label("total")
    ).group_by(Receipt.store_key)

    results = session.exec(query).all()
    return [
        {"name": store_display_name(store_key), "value": float(total or 0.0)}
        for store_key, total in results
    ]


@app.get("/receipts")
def get_recent_receipts(page: int = 1, limit: int = 10, store: str = "all",
                        search: str = None, start: str = None, end: str = None,
                        category: str = None,
                        session: Session = Depends(get_session)):
    """Paginated receipts, filterable by store, time range, category, and a
    free-text search that matches the store name OR any line-item name."""
    conditions = []

    if store and store != "all":
        conditions.append(Receipt.store_key == store)

    s, e = _parse_dt(start), _parse_dt(end)
    if s is not None:
        conditions.append(Receipt.date >= s)
    if e is not None:
        conditions.append(Receipt.date < e)

    if category and category != "all":
        conditions.append(
            Receipt.id.in_(select(Item.receipt_id).where(Item.category == category))
        )

    if search and search.strip():
        like = f"%{search.strip()}%"
        conditions.append(
            or_(
                Receipt.store_name.ilike(like),
                Receipt.id.in_(select(Item.receipt_id).where(Item.name.ilike(like))),
            )
        )

    query = select(Receipt)
    count_query = select(func.count(Receipt.id))
    if conditions:
        query = query.where(*conditions)
        count_query = count_query.where(*conditions)

    total = session.exec(count_query).one()

    offset = (page - 1) * limit
    query = query.order_by(desc(Receipt.date)).offset(offset).limit(limit)
    items = session.exec(query).all()

    return {"items": [ReceiptPublic.model_validate(r) for r in items], "total": total}


@app.get("/receipts/{receipt_id}")
def get_receipt_details(receipt_id: int, session: Session = Depends(get_session)):
    """A single receipt with its line items."""
    receipt = session.get(Receipt, receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")

    items = session.exec(select(Item).where(Item.receipt_id == receipt_id)).all()
    return {"receipt": ReceiptPublic.model_validate(receipt), "items": items}


@app.put("/categories/update")
def update_item_category(item_name: str, new_category: str, session: Session = Depends(get_session)):
    """Set an item's category: update all existing rows and remember it for future imports."""
    updated = 0
    for item in session.exec(select(Item).where(Item.name == item_name)).all():
        item.category = new_category
        session.add(item)
        updated += 1

    # Upsert the learned mapping (locked so the LLM won't override it later).
    key = item_name.lower().strip()
    mapping = session.get(CategoryMap, key)
    if mapping:
        mapping.category = new_category
        mapping.is_locked = True
    else:
        mapping = CategoryMap(item_key=key, category=new_category, is_locked=True)
    session.add(mapping)

    # Keep the canonical product in sync.
    product = session.exec(select(Product).where(Product.name_key == key)).first()
    if product:
        product.category = new_category

    session.commit()
    return {"status": "ok", "updated_items": updated, "category": new_category}


@app.post("/ingest/image")
@limiter.limit("20/hour")
async def ingest_image(request: Request, file: UploadFile = File(...)):
    """Ingest a photographed receipt from any store via the vision LLM."""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in IMAGE_EXTS:
        raise HTTPException(status_code=400, detail=f"Unsupported type '{ext}'. Use jpg/png/webp.")

    # Bound the upload before buffering it fully (OOM defense on the Pi).
    payload = await file.read(MAX_IMAGE_BYTES + 1)
    if len(payload) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413,
                            detail=f"Image too large (max {MAX_IMAGE_BYTES // (1024 * 1024)} MB).")

    # Save outside the watched inbox so the watcher doesn't also grab it.
    upload_dir = Path(tempfile.gettempdir()) / "bonfire_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    dest = upload_dir / f"upload-{stamp}{ext}"
    dest.write_bytes(payload)

    result = process_image_file(str(dest))
    if result is None:
        raise HTTPException(status_code=422, detail="Could not read a receipt from that image.")
    return {"status": "ok", **result}


@app.get("/insights/restock")
def get_restock(horizon_days: int = 3):
    """Predictive shopping list — items due (or overdue) for repurchase."""
    return restock_report(horizon_days=horizon_days)


@app.get("/insights/budget")
def get_budget():
    """Month-end spend forecast plus category anomalies."""
    return budget_report()


@app.get("/insights/meals")
@limiter.limit("10/minute")
def get_meals(request: Request, profile: str = "adult", audience: str | None = None,
              count: int = 3, quick: bool = False, vegetarian: bool = False,
              context: str = "trip", days: int = 14,
              avoid: list[str] = Query(default=[])):
    """LLM meal ideas from food that's already in the house.

    ``profile`` is a MealProfile key (``audience`` is a legacy alias).
    ``context``: "trip" (latest shopping trip per store, widened when thin)
    or "days" (rolling window). ``avoid``: titles the user already saw, so a
    refresh yields different ideas.
    """
    return meal_suggestions(profile=audience or profile, count=count, quick=quick,
                            vegetarian=vegetarian, context=context, days=days, avoid=avoid)


class MealProfileIn(SQLModel):
    name: str
    prompt: str


def _validated_profile_fields(data: MealProfileIn) -> tuple[str, str]:
    name = (data.name or "").strip()
    prompt = (data.prompt or "").strip()
    if not name or len(name) > 60:
        raise HTTPException(status_code=422, detail="Name must be 1-60 characters.")
    if not prompt or len(prompt) > 4000:
        raise HTTPException(status_code=422, detail="Prompt must be 1-4000 characters.")
    return name, prompt


@app.get("/meal-profiles")
def list_meal_profiles(session: Session = Depends(get_session)):
    """All meal profiles, built-ins first (stable id order)."""
    return session.exec(select(MealProfile).order_by(MealProfile.id)).all()


@app.post("/meal-profiles")
def create_meal_profile(data: MealProfileIn, session: Session = Depends(get_session)):
    name, prompt = _validated_profile_fields(data)
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "profile"
    key, n = base, 2
    while session.exec(select(MealProfile).where(MealProfile.key == key)).first():
        key, n = f"{base}-{n}", n + 1
    row = MealProfile(key=key, name=name, prompt=prompt, is_builtin=False)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


@app.put("/meal-profiles/{profile_id}")
def update_meal_profile(profile_id: int, data: MealProfileIn,
                        session: Session = Depends(get_session)):
    """Edit name/prompt. The key never changes (Telegram + URLs stay stable)."""
    row = session.get(MealProfile, profile_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Profile not found.")
    row.name, row.prompt = _validated_profile_fields(data)
    session.commit()
    session.refresh(row)
    return row


@app.delete("/meal-profiles/{profile_id}")
def delete_meal_profile(profile_id: int, session: Session = Depends(get_session)):
    row = session.get(MealProfile, profile_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Profile not found.")
    if row.is_builtin:
        raise HTTPException(status_code=400, detail="Built-in profiles cannot be deleted.")
    session.delete(row)
    session.commit()
    return {"ok": True}


@app.get("/ask")
@limiter.limit("10/minute")
def get_ask(request: Request, q: str):
    """Natural-language question answered over the receipt data."""
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="Provide a question via ?q=")
    return answer_question(q.strip())


@app.post("/categories/recategorize")
@limiter.limit("3/hour")
def recategorize_items(request: Request, scope: str = "missing"):
    """Re-run the LLM over stored items so prompt/model changes take effect.

    ``scope=missing`` (default) revisits only Uncategorized/Sonstiges items;
    ``scope=all`` revisits everything. Locked manual overrides are preserved.
    """
    if scope not in ("missing", "all"):
        raise HTTPException(status_code=400, detail="scope must be 'missing' or 'all'")
    return recategorize(scope=scope)
