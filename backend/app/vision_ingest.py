"""Ingest a photographed receipt from ANY store via a vision LLM.

Unlike the PDF adapters (which key off a text layer), this sends the image
straight to a multimodal model and asks for structured JSON. That turns a phone
photo of an Aldi/Lidl/bakery/market receipt into the same ParsedReceipt the rest
of the pipeline already understands.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from datetime import datetime

from .ingest import _persist, archive_file
from .llm import complete_vision
from .receipt_json import extract_json_object
from .stores import ParsedItem, ParsedReceipt, list_stores

logger = logging.getLogger(__name__)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

# Receipt photos are a few MB at most; refuse anything bigger before buffering
# it into memory / shipping it to the LLM.
MAX_IMAGE_BYTES = 15 * 1024 * 1024

_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}

_PROMPT = """
You are an expert receipt data extractor. This is a photo of a store receipt
(often German). Extract the contents into STRICT JSON.

RULES:
1. Exclude payment, change, card, and subtotal-summary lines from "items".
2. Include Pfand (deposit) lines as items if present.
3. Use DOTS for decimals (31.35, not 31,35). Amounts/totals are numbers, not strings.
4. "amount" is the quantity (1 unless the line shows 2x/3x/weight).
5. Identify the store from the header/logo (e.g. "REWE", "DM", "ALDI", "Lidl").
6. Return ONLY the JSON object — no markdown, no commentary.

FORMAT:
{
  "store_name": "ALDI SÜD",
  "datetime_local": "2026-03-06T16:17:00",
  "total": 31.35,
  "items": [ {"name": "Item Name", "amount": 1.0, "subTotal": 0.00} ]
}
"""


def _to_float(value) -> float:
    if isinstance(value, str):
        try:
            return float(value.replace(",", "."))
        except ValueError:
            return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _guess_store_key(store_name: str) -> str:
    """Map an extracted store name onto a canonical key.

    Known adapters win (so photographed REWE/DM receipts merge with scraped
    ones); otherwise slugify the first word (aldi, lidl, ...).
    """
    name = (store_name or "").lower()
    for store in list_stores():
        if store["key"] in name or store["display_name"].lower() in name:
            return store["key"]
    slug = re.sub(r"[^a-z0-9]", "", name.split()[0]) if name.strip() else ""
    return slug or "other"


def _parse_date(raw) -> datetime:
    if raw:
        try:
            return datetime.fromisoformat(str(raw)).replace(tzinfo=None)
        except ValueError:
            pass
    return datetime.now()


def process_image_file(file_path: str) -> dict | None:
    """Vision-extract a receipt image, persist it, and archive.

    Returns a small summary dict on success (``stored`` False = duplicate), or
    ``None`` if the image couldn't be read (left in place for a retry).
    """
    logger.info("Vision-processing image: %s", file_path)
    ext = os.path.splitext(file_path)[1].lower()
    mime = _MIME.get(ext, "image/jpeg")

    if os.path.getsize(file_path) > MAX_IMAGE_BYTES:
        logger.error("Image too large (> %s MB), skipping: %s",
                     MAX_IMAGE_BYTES // (1024 * 1024), file_path)
        return None
    with open(file_path, "rb") as fh:
        image_bytes = fh.read()

    try:
        raw = complete_vision(_PROMPT, image_bytes, mime_type=mime, temperature=0.0)
    except NotImplementedError:
        logger.error("Active LLM provider has no vision model; cannot read %s.", file_path)
        return None
    except Exception as e:
        logger.error("Vision extraction failed for %s: %s", file_path, e)
        return None

    data = extract_json_object(raw)
    items = [
        ParsedItem(
            name=line.get("name", "Unknown"),
            price_total=_to_float(line.get("subTotal", line.get("price", 0.0))),
            quantity=_to_float(line.get("amount", 1.0)) or 1.0,
        )
        for line in data.get("items", [])
    ]
    if not items:
        logger.warning("No items extracted from %s — leaving in place.", file_path)
        return None

    store_name = data.get("store_name", "Unknown Store")
    store_key = _guess_store_key(store_name)
    date = _parse_date(data.get("datetime_local"))
    total = _to_float(data.get("total", 0.0))
    filename = os.path.basename(file_path)

    parsed = ParsedReceipt(
        store_key=store_key,
        store_name=store_name,
        date=date,
        total=total,
        # Synthesize a stable id so re-uploading the same receipt de-dupes.
        transaction_id=f"photo-{store_key}-{date:%Y%m%d}-{total:.2f}",
        items=items,
        raw_data=data,
    )

    stored = _persist(parsed, filename, content_hash=hashlib.sha256(image_bytes).hexdigest())
    archive_file(file_path, store_key)
    return {
        "stored": stored,
        "store_name": store_name,
        "store_key": store_key,
        "total": round(total, 2),
        "items": len(items),
        "date": date.isoformat(),
    }
