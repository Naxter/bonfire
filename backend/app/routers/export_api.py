"""Data portability: CSV/JSON exports and a downloadable database snapshot.

Your receipts are yours — these endpoints make sure the data can leave the
app in formats a spreadsheet (or the next tool) understands."""

from __future__ import annotations

import csv
import io
import json
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import desc
from sqlmodel import Session, select
from starlette.background import BackgroundTask

from ..database import SQLITE_PATH, get_session
from ..models import Item, Receipt
from ..rate_limit import limiter

router = APIRouter()

_CSV_HEADER = [
    "receipt_id", "store_key", "store_name", "date", "receipt_total", "currency",
    "item_id", "item_name", "clean_name", "category", "quantity",
    "price_single", "price_total", "is_discounted", "review_status",
]


@router.get("/export/items.csv")
@limiter.limit("10/hour")
def export_items_csv(request: Request, session: Session = Depends(get_session)):
    """Every line item joined with its receipt — one flat CSV for spreadsheets."""
    rows = session.exec(
        select(Receipt, Item).join(Item, Item.receipt_id == Receipt.id)
        .order_by(desc(Receipt.date), Item.id)
    ).all()

    def generate():
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(_CSV_HEADER)
        for receipt, item in rows:
            writer.writerow([
                receipt.id, receipt.store_key, receipt.store_name,
                receipt.date.isoformat() if receipt.date else "",
                f"{receipt.total_amount:.2f}", receipt.currency,
                item.id, item.name, item.clean_name, item.category,
                item.quantity,
                f"{item.price_single:.2f}" if item.price_single is not None else "",
                f"{item.price_total:.2f}",
                int(item.is_discounted), receipt.review_status,
            ])
            if buffer.tell() > 64 * 1024:
                yield buffer.getvalue()
                buffer.seek(0)
                buffer.truncate(0)
        yield buffer.getvalue()

    stamp = datetime.now().strftime("%Y%m%d")
    return StreamingResponse(
        generate(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="bonfire-items-{stamp}.csv"'},
    )


@router.get("/export/receipts.json")
@limiter.limit("10/hour")
def export_receipts_json(request: Request, session: Session = Depends(get_session)):
    """Receipts with nested items — lossless-ish JSON for re-import elsewhere."""
    receipts = session.exec(select(Receipt).order_by(desc(Receipt.date))).all()
    items = session.exec(select(Item)).all()
    by_receipt: dict[int, list] = {}
    for item in items:
        by_receipt.setdefault(item.receipt_id, []).append({
            "name": item.name, "clean_name": item.clean_name, "category": item.category,
            "quantity": item.quantity, "price_single": item.price_single,
            "price_total": item.price_total, "is_discounted": item.is_discounted,
            "tax_rate": item.tax_rate,
        })
    payload = [{
        "id": r.id, "store_key": r.store_key, "store_name": r.store_name,
        "store_address": r.store_address, "date": r.date.isoformat() if r.date else None,
        "total_amount": r.total_amount, "currency": r.currency,
        "review_status": r.review_status, "extraction_source": r.extraction_source,
        "parse_warnings": r.parse_warnings, "pdf_filename": r.pdf_filename,
        "items": by_receipt.get(r.id, []),
    } for r in receipts]

    stamp = datetime.now().strftime("%Y%m%d")
    return StreamingResponse(
        iter([json.dumps(payload, ensure_ascii=False, indent=1)]),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="bonfire-receipts-{stamp}.json"'},
    )


@router.get("/export/database")
@limiter.limit("4/hour")
def export_database(request: Request):
    """A consistent snapshot of the SQLite database (same mechanism as the
    scheduled backups — safe while the app is writing)."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()

    src = sqlite3.connect(f"file:{SQLITE_PATH}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(tmp_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return FileResponse(
        tmp_path,
        media_type="application/vnd.sqlite3",
        filename=f"bonfire-{stamp}.db",
        background=BackgroundTask(tmp_path.unlink, missing_ok=True),
    )
