"""Receipt lifecycle: list, inspect, correct, verify, reprocess, delete.

This is the "data you can trust" layer the dashboard sits on: every receipt
can be checked against its archived source file, every extracted field can be
fixed, and imports are never effectively permanent."""

from __future__ import annotations

import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import desc, func, or_
from sqlmodel import Session, select

from ..api_utils import clamp_limit, clamp_page, parse_dt
from ..categories import VALID_CATEGORIES
from ..database import DATA_DIR, get_session
from ..ingest import ARCHIVE_DIR, TOTAL_MISMATCH_TOLERANCE
from ..jobs import close_review_jobs, start_reprocess
from ..models import CategoryMap, ImportJob, Item, Receipt
from ..products import clean_name, get_or_create_product, normalize_key, resolve_product
from ..schemas import CategoryUpdate, ItemCreate, ItemUpdate, ReceiptPublic, ReceiptUpdate

router = APIRouter()

# "Uncategorized" isn't part of the taxonomy but is a legitimate reset value.
ALLOWED_CATEGORIES = set(VALID_CATEGORIES) | {"Uncategorized"}

_STORE_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")

_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #
def _items_sum(session: Session, receipt_id: int) -> float:
    total = session.exec(
        select(func.sum(Item.price_total)).where(Item.receipt_id == receipt_id)
    ).first()
    return round(float(total or 0.0), 2)


def _refresh_trust(session: Session, receipt: Receipt, touched_by_user: bool) -> None:
    """Re-derive warnings + review status from the CURRENT numbers.

    After a manual correction the receipt counts as human-checked: if the
    items now add up it becomes ``verified``, otherwise it stays flagged."""
    items_sum = _items_sum(session, receipt.id)
    warnings: list[str] = []
    if abs(items_sum - round(receipt.total_amount, 2)) > TOTAL_MISMATCH_TOLERANCE:
        warnings.append(
            f"Line items add up to €{items_sum:.2f} but the receipt total is "
            f"€{receipt.total_amount:.2f}."
        )
    if receipt.total_amount <= 0:
        warnings.append("The receipt total is zero or negative.")
    receipt.parse_warnings = warnings
    if touched_by_user:
        receipt.review_status = "verified" if not warnings else "needs_review"
    elif warnings and receipt.review_status == "ok":
        receipt.review_status = "needs_review"
    if receipt.review_status != "needs_review":
        close_review_jobs(session, receipt.id)


def _find_duplicates(session: Session, receipt: Receipt) -> list[Receipt]:
    """Other receipts from the same store, same calendar day, same total."""
    day = receipt.date.date()
    start = datetime(day.year, day.month, day.day)
    end = datetime(day.year, day.month, day.day, 23, 59, 59)
    rows = session.exec(
        select(Receipt).where(
            Receipt.id != receipt.id,
            Receipt.store_key == receipt.store_key,
            Receipt.date >= start,
            Receipt.date <= end,
        )
    ).all()
    return [r for r in rows if abs(r.total_amount - receipt.total_amount) < 0.01]


def _get_receipt_or_404(session: Session, receipt_id: int) -> Receipt:
    receipt = session.get(Receipt, receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")
    return receipt


def _resolve_source_file(receipt: Receipt):
    """Locate the archived original safely inside data/ (or None)."""
    candidates = []
    if receipt.source_path:
        candidates.append(DATA_DIR / receipt.source_path)
    if receipt.store_key and receipt.pdf_filename:
        candidates.append(ARCHIVE_DIR / receipt.store_key / receipt.pdf_filename)
    data_root = DATA_DIR.resolve()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_file() and resolved.is_relative_to(data_root):
            return resolved
    return None


def set_category_for_name(session: Session, item_name: str, new_category: str) -> int:
    """Category change with 'all' scope, same semantics as the products page:
    the resolved product and ALL its lines (every merged spelling, not just
    this one), with every affected name's mapping locked against LLM
    overrides."""
    items = list(session.exec(select(Item).where(Item.name == item_name)).all())
    product = resolve_product(session, item_name)
    if product:
        product.category = new_category
        seen = {item.id for item in items}
        items += [item for item in
                  session.exec(select(Item).where(Item.product_id == product.id)).all()
                  if item.id not in seen]

    names = {item.name for item in items} | {item_name}
    if product:
        names.add(product.display_name)

    for item in items:
        item.category = new_category
        session.add(item)
    for name in names:
        key = normalize_key(name)
        mapping = session.get(CategoryMap, key)
        if mapping:
            mapping.category = new_category
            mapping.is_locked = True
        else:
            session.add(CategoryMap(item_key=key, category=new_category, is_locked=True))
    return len(items)


# --------------------------------------------------------------------------- #
# List + detail
# --------------------------------------------------------------------------- #
@router.get("/receipts")
def get_recent_receipts(page: int = 1, limit: int = 10, store: str = "all",
                        search: str = None, start: str = None, end: str = None,
                        category: str = None, review: str = None,
                        session: Session = Depends(get_session)):
    """Paginated receipts, filterable by store, time range, category, review
    state, and a free-text search that matches the store name OR any line-item
    name. Each row carries its items-sum so mismatches are visible in the list."""
    page, limit = clamp_page(page), clamp_limit(limit)
    conditions = []

    if store and store != "all":
        conditions.append(Receipt.store_key == store)

    s, e = parse_dt(start), parse_dt(end)
    if s is not None:
        conditions.append(Receipt.date >= s)
    if e is not None:
        conditions.append(Receipt.date < e)

    if category and category != "all":
        conditions.append(
            Receipt.id.in_(select(Item.receipt_id).where(Item.category == category))
        )

    if review and review != "all":
        if review not in ("ok", "needs_review", "verified"):
            raise HTTPException(status_code=422, detail="review must be ok, needs_review or verified")
        conditions.append(Receipt.review_status == review)

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
    receipts = session.exec(query).all()

    # One grouped query for the page's items-sums (no N+1).
    sums: dict[int, float] = {}
    ids = [r.id for r in receipts]
    if ids:
        rows = session.exec(
            select(Item.receipt_id, func.sum(Item.price_total))
            .where(Item.receipt_id.in_(ids)).group_by(Item.receipt_id)
        ).all()
        sums = {rid: round(float(total or 0.0), 2) for rid, total in rows}

    items = []
    for r in receipts:
        data = ReceiptPublic.from_receipt(r).model_dump()
        data["items_sum"] = sums.get(r.id, 0.0)
        data["total_mismatch"] = abs(data["items_sum"] - round(r.total_amount, 2)) > TOTAL_MISMATCH_TOLERANCE
        items.append(data)

    return {"items": items, "total": total}


@router.get("/receipts/needs-review-count")
def needs_review_count(session: Session = Depends(get_session)):
    """Badge feed for the nav: how many receipts still want a human look."""
    count = session.exec(
        select(func.count(Receipt.id)).where(Receipt.review_status == "needs_review")
    ).one()
    return {"count": int(count)}


@router.get("/receipts/duplicate-groups")
def duplicate_groups(limit: int = 20, session: Session = Depends(get_session)):
    """Potential duplicate imports: same store, same day, same total."""
    limit = clamp_limit(limit, cap=100)
    day = func.strftime("%Y-%m-%d", Receipt.date)
    total = func.round(Receipt.total_amount, 2)
    groups = session.exec(
        select(Receipt.store_key, day.label("day"), total.label("total"),
               func.count(Receipt.id).label("n"))
        .group_by(Receipt.store_key, "day", "total")
        .having(func.count(Receipt.id) > 1)
        .order_by(desc("day"))
        .limit(limit)
    ).all()

    result = []
    for store_key, day_str, total_amount, _n in groups:
        s, e = parse_dt(day_str), parse_dt(day_str)
        receipts = session.exec(
            select(Receipt).where(
                Receipt.store_key == store_key,
                Receipt.date >= s,
                Receipt.date < e.replace(hour=23, minute=59, second=59),
                func.round(Receipt.total_amount, 2) == total_amount,
            ).order_by(Receipt.id)
        ).all()
        if len(receipts) > 1:
            result.append({
                "store_key": store_key,
                "date": day_str,
                "total": float(total_amount),
                "receipts": [ReceiptPublic.from_receipt(r) for r in receipts],
            })
    return result


@router.get("/receipts/{receipt_id}")
def get_receipt_details(receipt_id: int, session: Session = Depends(get_session)):
    """A single receipt with its line items, totals check and duplicate hints."""
    receipt = _get_receipt_or_404(session, receipt_id)
    items = session.exec(select(Item).where(Item.receipt_id == receipt_id)).all()
    items_sum = round(sum(i.price_total for i in items), 2)
    return {
        "receipt": ReceiptPublic.from_receipt(receipt),
        "items": items,
        "items_sum": items_sum,
        "total_mismatch": abs(items_sum - round(receipt.total_amount, 2)) > TOTAL_MISMATCH_TOLERANCE,
        "duplicates": [ReceiptPublic.from_receipt(r) for r in _find_duplicates(session, receipt)],
    }


@router.get("/receipts/{receipt_id}/source")
def get_receipt_source(receipt_id: int, download: bool = False,
                       session: Session = Depends(get_session)):
    """Serve the archived original (PDF or photo) for side-by-side review."""
    receipt = _get_receipt_or_404(session, receipt_id)
    path = _resolve_source_file(receipt)
    if path is None:
        raise HTTPException(status_code=404,
                            detail="No source file is archived for this receipt.")
    media_type = _MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
    disposition = "attachment" if download else "inline"
    return FileResponse(path, media_type=media_type, filename=path.name,
                        content_disposition_type=disposition)


# --------------------------------------------------------------------------- #
# Corrections
# --------------------------------------------------------------------------- #
@router.patch("/receipts/{receipt_id}")
def update_receipt(receipt_id: int, data: ReceiptUpdate,
                   session: Session = Depends(get_session)):
    """Edit receipt header fields (store, date, total). Re-runs the totals
    check; a receipt whose numbers now add up becomes ``verified``."""
    receipt = _get_receipt_or_404(session, receipt_id)

    if data.store_name is not None:
        name = data.store_name.strip()
        if not name or len(name) > 120:
            raise HTTPException(status_code=422, detail="Store name must be 1-120 characters.")
        receipt.store_name = name
    if data.store_key is not None:
        key = data.store_key.strip().lower()
        if not _STORE_KEY_RE.match(key):
            raise HTTPException(status_code=422,
                                detail="Store key must be a short lowercase slug (a-z, 0-9, -, _).")
        receipt.store_key = key
    if data.date is not None:
        parsed = parse_dt(data.date)
        if parsed is None:
            raise HTTPException(status_code=422, detail="Date must be an ISO date/datetime.")
        receipt.date = parsed
    if data.total_amount is not None:
        if not (0 <= data.total_amount < 100000):
            raise HTTPException(status_code=422, detail="Total must be between 0 and 100000.")
        receipt.total_amount = round(float(data.total_amount), 2)
    if data.currency is not None:
        cur = data.currency.strip().upper()
        if not re.match(r"^[A-Z]{3}$", cur):
            raise HTTPException(status_code=422, detail="Currency must be a 3-letter code.")
        receipt.currency = cur

    _refresh_trust(session, receipt, touched_by_user=True)
    session.commit()
    session.refresh(receipt)
    return {"receipt": ReceiptPublic.from_receipt(receipt)}


@router.post("/receipts/{receipt_id}/verify")
def verify_receipt(receipt_id: int, session: Session = Depends(get_session)):
    """Mark a receipt as human-checked, warnings and all."""
    receipt = _get_receipt_or_404(session, receipt_id)
    receipt.review_status = "verified"
    # The imports feed shows the *job* status — approving the receipt must not
    # leave its import stuck at "needs review".
    close_review_jobs(session, receipt_id)
    session.commit()
    return {"receipt": ReceiptPublic.from_receipt(receipt)}


@router.post("/receipts/{receipt_id}/reprocess")
def reprocess_receipt(receipt_id: int, session: Session = Depends(get_session)):
    """Re-run extraction from the archived source file (background job)."""
    receipt = _get_receipt_or_404(session, receipt_id)
    path = _resolve_source_file(receipt)
    if path is None:
        raise HTTPException(status_code=404,
                            detail="No source file is archived for this receipt.")
    job_id = start_reprocess(receipt.id, str(path), receipt.store_key, receipt.pdf_filename)
    return {"job_id": job_id}


@router.delete("/receipts/{receipt_id}")
def delete_receipt(receipt_id: int, session: Session = Depends(get_session)):
    """Delete a receipt and its line items. The archived source file is kept
    (re-importing it later works — deletion removes data, not evidence)."""
    receipt = _get_receipt_or_404(session, receipt_id)
    for item in session.exec(select(Item).where(Item.receipt_id == receipt_id)).all():
        session.delete(item)
    # A deleted receipt can never be reviewed — close stale flags, then keep
    # the import history without pointing at a dead row.
    close_review_jobs(session, receipt_id)
    for job in session.exec(select(ImportJob).where(ImportJob.receipt_id == receipt_id)).all():
        job.receipt_id = None
    session.delete(receipt)
    session.commit()
    return {"status": "deleted", "receipt_id": receipt_id}


# --------------------------------------------------------------------------- #
# Line items
# --------------------------------------------------------------------------- #
def _validated_item_fields(name: str | None = None, quantity: float | None = None,
                           price_total: float | None = None,
                           price_single: float | None = None,
                           category: str | None = None) -> None:
    if name is not None and (not name.strip() or len(name) > 200):
        raise HTTPException(status_code=422, detail="Item name must be 1-200 characters.")
    if quantity is not None and not (0 < quantity < 10000):
        raise HTTPException(status_code=422, detail="Quantity must be between 0 and 10000.")
    for label, price in (("price_total", price_total), ("price_single", price_single)):
        if price is not None and not (-100000 < price < 100000):
            raise HTTPException(status_code=422, detail=f"{label} is out of range.")
    if category is not None and category not in ALLOWED_CATEGORIES:
        raise HTTPException(status_code=422,
                            detail=f"Unknown category {category!r}. Use one of the canonical categories.")


@router.post("/receipts/{receipt_id}/items")
def add_item(receipt_id: int, data: ItemCreate, session: Session = Depends(get_session)):
    """Add a missing line item (e.g. one the vision model skipped)."""
    receipt = _get_receipt_or_404(session, receipt_id)
    _validated_item_fields(name=data.name, quantity=data.quantity,
                           price_total=data.price_total, price_single=data.price_single,
                           category=data.category)
    name = data.name.strip()

    # Manually added lines join the product layer like imported ones do; with
    # no explicit category the line follows its product.
    product = resolve_product(session, name)
    if product is not None:
        category = data.category or product.category
    else:
        category = data.category or "Uncategorized"
        product = get_or_create_product(session, name, category)
    item = Item(
        receipt_id=receipt.id,
        product_id=product.id,
        name=name,
        clean_name=clean_name(name),
        category=category,
        price_total=round(float(data.price_total), 2),
        price_single=data.price_single if data.price_single is not None
        else (round(data.price_total / data.quantity, 2) if data.quantity else data.price_total),
        quantity=data.quantity,
        is_discounted=data.price_total < 0,
    )
    session.add(item)
    _refresh_trust(session, receipt, touched_by_user=True)
    session.commit()
    session.refresh(item)
    return {"item": item}


@router.patch("/receipts/{receipt_id}/items/{item_id}")
def update_item(receipt_id: int, item_id: int, data: ItemUpdate,
                session: Session = Depends(get_session)):
    """Correct a line item: name, quantity, prices, category (with scope)."""
    receipt = _get_receipt_or_404(session, receipt_id)
    item = session.get(Item, item_id)
    if not item or item.receipt_id != receipt_id:
        raise HTTPException(status_code=404, detail="Item not found on this receipt.")
    _validated_item_fields(name=data.name, quantity=data.quantity,
                           price_total=data.price_total, price_single=data.price_single,
                           category=data.category)
    if data.category_scope not in ("all", "item"):
        raise HTTPException(status_code=422, detail="category_scope must be 'all' or 'item'.")

    if data.name is not None and data.name.strip() != item.name:
        name = data.name.strip()
        item.name = name
        item.clean_name = clean_name(name)
        # Relink to the (possibly different) canonical product; the line
        # follows its new product's category. Unknown names get a product,
        # like imported lines do.
        product = resolve_product(session, name)
        if product is not None:
            item.category = product.category
        else:
            product = get_or_create_product(session, name, item.category)
        item.product_id = product.id
    if data.quantity is not None:
        item.quantity = float(data.quantity)
    if data.price_total is not None:
        item.price_total = round(float(data.price_total), 2)
        item.is_discounted = item.price_total < 0
    if data.price_single is not None:
        item.price_single = round(float(data.price_single), 2)
    elif (data.price_total is not None or data.quantity is not None) and item.quantity:
        item.price_single = round(item.price_total / item.quantity, 2)

    updated_items = 1
    if data.category is not None:
        if data.category_scope == "all":
            updated_items = set_category_for_name(session, item.name, data.category)
        else:
            item.category = data.category

    _refresh_trust(session, receipt, touched_by_user=True)
    session.commit()
    session.refresh(item)
    return {"item": item, "updated_items": updated_items}


@router.delete("/receipts/{receipt_id}/items/{item_id}")
def delete_item(receipt_id: int, item_id: int, session: Session = Depends(get_session)):
    """Remove a line item (e.g. one the vision model hallucinated)."""
    receipt = _get_receipt_or_404(session, receipt_id)
    item = session.get(Item, item_id)
    if not item or item.receipt_id != receipt_id:
        raise HTTPException(status_code=404, detail="Item not found on this receipt.")
    session.delete(item)
    _refresh_trust(session, receipt, touched_by_user=True)
    session.commit()
    return {"status": "deleted", "item_id": item_id}


# --------------------------------------------------------------------------- #
# Category mutation (typed + validated)
# --------------------------------------------------------------------------- #
@router.put("/categories/update")
def update_item_category(data: CategoryUpdate, session: Session = Depends(get_session)):
    """Set an item's category.

    ``scope="all"`` (default) updates every existing item with that name,
    locks the learned mapping for future imports, and syncs the product.
    ``scope="item"`` changes only the single line identified by ``item_id``."""
    if data.new_category not in ALLOWED_CATEGORIES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown category {data.new_category!r}. Use one of the canonical categories.",
        )
    if data.scope not in ("all", "item"):
        raise HTTPException(status_code=422, detail="scope must be 'all' or 'item'.")

    if data.scope == "item":
        if data.item_id is None:
            raise HTTPException(status_code=422, detail="scope='item' requires item_id.")
        item = session.get(Item, data.item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Item not found.")
        item.category = data.new_category
        session.commit()
        return {"status": "ok", "updated_items": 1, "category": data.new_category,
                "scope": "item"}

    if not data.item_name.strip():
        raise HTTPException(status_code=422, detail="item_name must not be empty.")
    updated = set_category_for_name(session, data.item_name, data.new_category)
    session.commit()
    return {"status": "ok", "updated_items": updated, "category": data.new_category,
            "scope": "all"}
