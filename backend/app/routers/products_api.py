"""Product identity APIs: browse, edit, merge/unmerge, compare prices across stores.

Products are the canonical layer over noisy receipt names. These endpoints
expose them for curation (fix a name, set the package size, merge duplicates)
and answer "where is this cheapest?" with standardized unit prices."""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlmodel import Session, func, select

from ..api_utils import clamp_limit, clamp_page
from ..categories import VALID_CATEGORIES
from ..database import get_session
from ..models import CategoryMap, Item, Product, ProductAlias, Receipt
from ..products import merge_products, normalize_key, split_product, unit_price
from ..schemas import ProductMergeIn, ProductSplitIn, ProductUpdate
from ..settings import get_settings
from ..stores import store_display_name

router = APIRouter()

ALLOWED_CATEGORIES = set(VALID_CATEGORIES) | {"Uncategorized"}
_SIZE_UNITS = ("g", "ml", "piece")


def _product_or_404(session: Session, product_id: int) -> Product:
    product = session.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found.")
    return product


def _page_stats(session: Session, product_ids: list[int]) -> dict[int, dict]:
    """Purchase stats for one page of products, computed in two queries."""
    if not product_ids:
        return {}
    rows = session.exec(
        select(
            Item.product_id,
            func.count(Item.id),
            func.sum(Item.quantity),
            func.max(Receipt.date),
        )
        .join(Receipt)
        .where(Item.product_id.in_(product_ids))
        .group_by(Item.product_id)
    ).all()
    stats = {
        pid: {"times_bought": int(n or 0), "total_qty": round(float(q or 0), 1),
              "last_purchased": d.isoformat() if d else None}
        for pid, n, q, d in rows
    }

    # Latest + min/max price per product (small page — fetch and fold).
    price_rows = session.exec(
        select(Item.product_id, Item.price_single, Receipt.date, Receipt.store_key)
        .join(Receipt)
        .where(Item.product_id.in_(product_ids), Item.price_single > 0)
        .order_by(Receipt.date)
    ).all()
    for pid, price, _date, store_key in price_rows:
        s = stats.setdefault(pid, {})
        s["last_price"] = round(float(price), 2)  # ordered by date → last wins
        s["min_price"] = round(min(s.get("min_price", price), price), 2)
        s["max_price"] = round(max(s.get("max_price", price), price), 2)
        s.setdefault("stores", set()).add(store_key)
    for s in stats.values():
        if "stores" in s:
            s["stores"] = sorted(s["stores"])
    return stats


@router.get("/products")
def list_products(search: str = "", category: str = "all", page: int = 1, limit: int = 50,
                  sort: str = "last_purchased",
                  session: Session = Depends(get_session)):
    """Canonical products with purchase stats and unit prices."""
    page, limit = clamp_page(page), clamp_limit(limit)
    if sort not in ("last_purchased", "name", "times_bought"):
        raise HTTPException(status_code=422,
                            detail="sort must be last_purchased, name or times_bought.")

    query = select(Product)
    count_query = select(func.count(Product.id))
    if search.strip():
        like = f"%{search.strip()}%"
        # Also match merged receipt spellings — a merged-away name must still
        # find its surviving product.
        aliased = select(ProductAlias.product_id).where(ProductAlias.name_key.ilike(like))
        matches = or_(Product.display_name.ilike(like), Product.id.in_(aliased))
        query = query.where(matches)
        count_query = count_query.where(matches)
    if category != "all":
        query = query.where(Product.category == category)
        count_query = count_query.where(Product.category == category)

    total = session.exec(count_query).one()

    if sort == "name":
        products = session.exec(
            query.order_by(Product.display_name).offset((page - 1) * limit).limit(limit)
        ).all()
    else:
        # Purchase-driven sorts need the aggregate: rank product ids first.
        order = (func.max(Receipt.date) if sort == "last_purchased"
                 else func.count(Item.id))
        id_query = (
            select(Item.product_id)
            .join(Receipt)
            .where(Item.product_id.isnot(None))
            .group_by(Item.product_id)
            .order_by(order.desc())
        )
        ranked_ids = [pid for pid in session.exec(id_query).all() if pid is not None]
        filtered = session.exec(query).all()
        by_id = {p.id: p for p in filtered}
        ordered = [by_id[pid] for pid in ranked_ids if pid in by_id]
        rest = [p for p in filtered if p.id not in set(ranked_ids)]
        products = (ordered + rest)[(page - 1) * limit:(page - 1) * limit + limit]

    stats = _page_stats(session, [p.id for p in products])
    result = []
    for p in products:
        s = stats.get(p.id, {})
        last_price = s.get("last_price")
        result.append({
            "id": p.id,
            "name_key": p.name_key,
            "display_name": p.display_name,
            "category": p.category,
            "brand": p.brand,
            "size_value": p.size_value,
            "size_unit": p.size_unit,
            "times_bought": s.get("times_bought", 0),
            "total_qty": s.get("total_qty", 0),
            "last_purchased": s.get("last_purchased"),
            "last_price": last_price,
            "min_price": s.get("min_price"),
            "max_price": s.get("max_price"),
            "stores": [{"key": k, "name": store_display_name(k)} for k in s.get("stores", [])],
            "unit_price": unit_price(last_price, p.size_value, p.size_unit) if last_price else None,
        })
    return {"items": result, "total": int(total)}


@router.get("/products/{product_id}")
def product_detail(product_id: int, session: Session = Depends(get_session)):
    """One product: purchase history and a per-store price comparison."""
    product = _product_or_404(session, product_id)
    rows = session.exec(
        select(Item.price_single, Item.quantity, Receipt.date, Receipt.store_key, Item.name)
        .join(Receipt)
        .where(Item.product_id == product_id)
        .order_by(Receipt.date)
    ).all()

    history = [
        {"date": d.isoformat(), "price": round(float(p), 2),
         "store_key": sk, "store": store_display_name(sk)}
        for p, _q, d, sk, _n in rows if p and p > 0
    ]

    per_store: dict[str, list[float]] = defaultdict(list)
    latest_per_store: dict[str, float] = {}
    for p, _q, _d, sk, _n in rows:
        if p and p > 0:
            per_store[sk].append(float(p))
            latest_per_store[sk] = float(p)  # date-ordered → last wins

    comparison = []
    for sk, prices in per_store.items():
        latest = latest_per_store[sk]
        comparison.append({
            "store_key": sk,
            "store": store_display_name(sk),
            "latest_price": round(latest, 2),
            "min_price": round(min(prices), 2),
            "max_price": round(max(prices), 2),
            "purchases": len(prices),
            "unit_price": unit_price(latest, product.size_value, product.size_unit),
        })
    comparison.sort(key=lambda c: c["latest_price"])

    aliases = session.exec(
        select(ProductAlias.name_key).where(ProductAlias.product_id == product_id)
    ).all()
    names = sorted({n for _p, _q, _d, _sk, n in rows})

    return {
        "product": product,
        "history": history,
        "stores": comparison,
        "aliases": list(aliases),
        "receipt_names": names,
    }


@router.patch("/products/{product_id}")
def update_product(product_id: int, data: ProductUpdate,
                   session: Session = Depends(get_session)):
    """Curate a product: display name, brand, package size, category."""
    product = _product_or_404(session, product_id)

    if data.display_name is not None:
        name = data.display_name.strip()
        if not name or len(name) > 200:
            raise HTTPException(status_code=422, detail="Display name must be 1-200 characters.")
        product.display_name = name
    if data.brand is not None:
        product.brand = data.brand.strip()[:80] or None
    if data.size_value is not None or data.size_unit is not None:
        value = data.size_value if data.size_value is not None else product.size_value
        unit = data.size_unit if data.size_unit is not None else product.size_unit
        if value in (0, None) or unit in ("", None):
            product.size_value, product.size_unit = None, None  # explicit clear
        else:
            if unit not in _SIZE_UNITS:
                raise HTTPException(status_code=422, detail="size_unit must be g, ml or piece.")
            if not (0 < value < 1_000_000):
                raise HTTPException(status_code=422, detail="size_value is out of range.")
            product.size_value, product.size_unit = float(value), unit
    if data.category is not None:
        if data.category not in ALLOWED_CATEGORIES:
            raise HTTPException(status_code=422, detail=f"Unknown category {data.category!r}.")
        product.category = data.category
        # Sync every linked item + lock the learned mapping for future imports.
        names = set()
        for item in session.exec(select(Item).where(Item.product_id == product_id)).all():
            item.category = data.category
            names.add(item.name)
        for name in names | {product.display_name}:
            key = normalize_key(name)
            mapping = session.get(CategoryMap, key)
            if mapping:
                mapping.category = data.category
                mapping.is_locked = True
            else:
                session.add(CategoryMap(item_key=key, category=data.category, is_locked=True))

    session.commit()
    session.refresh(product)
    return {"product": product}


@router.post("/products/merge")
def merge(data: ProductMergeIn, session: Session = Depends(get_session)):
    """Merge duplicate products into one (aliases make it stick for future
    imports). Source products disappear; their purchases move to the target."""
    if not data.source_ids:
        raise HTTPException(status_code=422, detail="source_ids must not be empty.")
    if len(data.source_ids) > 50:
        raise HTTPException(status_code=422, detail="At most 50 products per merge.")
    try:
        result = merge_products(session, data.target_id, data.source_ids)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    session.commit()
    return result


@router.post("/products/{product_id}/split")
def split(product_id: int, data: ProductSplitIn, session: Session = Depends(get_session)):
    """Undo a merge: detach one aliased receipt name into its own product
    (purchases move back with it; future imports stay separate)."""
    try:
        result = split_product(session, product_id, normalize_key(data.name_key))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    session.commit()
    return result


@router.get("/insights/price-alerts")
def price_alerts(session: Session = Depends(get_session)):
    """Products whose latest price jumped vs. their recent history.

    Threshold comes from settings (``alerts.price_increase_pct``). Uses unit
    prices when the package size is known, so a pack-size change doesn't
    masquerade as inflation."""
    threshold = float(get_settings()["alerts.price_increase_pct"]) / 100.0

    rows = session.exec(
        select(Item.product_id, Item.price_single, Receipt.date, Receipt.store_key)
        .join(Receipt)
        .where(Item.product_id.isnot(None), Item.price_single > 0)
        .order_by(Receipt.date)
    ).all()

    series: dict[int, list[tuple]] = defaultdict(list)
    for pid, price, date, store_key in rows:
        series[pid].append((date, float(price), store_key))

    interesting = [(pid, s) for pid, s in series.items() if len(s) >= 3]
    if not interesting:
        return []

    products = {
        p.id: p for p in session.exec(
            select(Product).where(Product.id.in_([pid for pid, _ in interesting]))
        ).all()
    }

    alerts = []
    for pid, points in interesting:
        product = products.get(pid)
        if product is None:
            continue
        *history, (last_date, last_price, last_store) = points
        recent = [p for _d, p, _s in history[-5:]]
        baseline = min(recent)
        if baseline <= 0 or last_price <= baseline * (1 + threshold):
            continue
        alerts.append({
            "product_id": pid,
            "name": product.display_name,
            "category": product.category,
            "store": store_display_name(last_store),
            "date": last_date.isoformat(),
            "previous_price": round(baseline, 2),
            "latest_price": round(last_price, 2),
            "increase_pct": round((last_price - baseline) / baseline * 100, 1),
            "unit_price": unit_price(last_price, product.size_value, product.size_unit),
        })
    alerts.sort(key=lambda a: a["increase_pct"], reverse=True)
    return alerts[:50]
