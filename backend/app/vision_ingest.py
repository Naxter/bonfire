"""Ingest a photographed receipt from ANY store via a vision LLM.

Unlike the PDF adapters (which key off a text layer), this sends the image
straight to a multimodal model and asks for structured JSON. That turns a phone
photo of an Aldi/Lidl/bakery/market receipt into the same ParsedReceipt the rest
of the pipeline already understands.

Vision extraction is the least trustworthy path in the app, so every receipt it
produces is stored as ``needs_review`` — the review UI shows the photo next to
the parsed lines and asks the user to confirm or fix them.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from datetime import datetime
from pathlib import Path

from .ingest import (
    IngestReport,
    _persist,
    _relative_to_data,
    archive_to,
    move_to_failed,
    plan_archive_path,
)
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
2. Include Pfand (deposit) lines as items if present. Discount/voucher lines
   (RABATT, GUTSCHEIN) are items too, with a NEGATIVE subTotal.
3. Use DOTS for decimals (31.35, not 31,35). Amounts/totals are numbers, not strings.
4. "amount" is the quantity (1 unless the line shows 2x/3x/weight).
5. Identify the store from the header/logo (e.g. "REWE", "DM", "ALDI", "Lidl").
6. "confidence" is YOUR honest 0.0-1.0 estimate that store, date, total and
   every line item are read correctly (blurry photo, cut-off edges → lower).
7. Return ONLY the JSON object — no markdown, no commentary.

FORMAT:
{
  "store_name": "ALDI SÜD",
  "datetime_local": "2026-03-06T16:17:00",
  "total": 31.35,
  "confidence": 0.9,
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


class VisionExtractionError(Exception):
    """Vision extraction failed. ``status`` matches IngestReport statuses:
    ``llm_unavailable`` is retryable, ``no_data`` is a hard failure."""

    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def extract_receipt_from_image(file_path: str) -> tuple[ParsedReceipt, list[str]]:
    """Run the vision LLM over a photo and normalize the result.

    Returns ``(parsed, extra_warnings)`` or raises VisionExtractionError.
    Shared by first-time ingest and reprocessing."""
    ext = os.path.splitext(file_path)[1].lower()
    mime = _MIME.get(ext, "image/jpeg")

    if os.path.getsize(file_path) > MAX_IMAGE_BYTES:
        raise VisionExtractionError(
            "no_data", f"Image larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB.")
    with open(file_path, "rb") as fh:
        image_bytes = fh.read()

    try:
        raw = complete_vision(_PROMPT, image_bytes, mime_type=mime, temperature=0.0)
    except NotImplementedError:
        raise VisionExtractionError(
            "llm_unavailable", "The configured LLM provider has no vision model.") from None
    except Exception as e:
        logger.error("Vision extraction failed for %s: %s", file_path, e)
        raise VisionExtractionError(
            "llm_unavailable", "The vision model could not be reached — try again later.") from None

    try:
        data = extract_json_object(raw)
    except Exception:
        logger.warning("Vision model returned unparseable JSON for %s.", file_path)
        data = {}
    if not isinstance(data, dict):
        data = {}
    raw_items = data.get("items") if isinstance(data.get("items"), list) else []
    items = [
        ParsedItem(
            name=str(line.get("name", "Unknown")),
            price_total=_to_float(line.get("subTotal", line.get("price", 0.0))),
            quantity=_to_float(line.get("amount", 1.0)) or 1.0,
        )
        for line in raw_items
        if isinstance(line, dict)
    ]
    if not items:
        raise VisionExtractionError("no_data", "No line items could be read from the photo.")

    store_name = str(data.get("store_name") or "Unknown Store")
    store_key = _guess_store_key(store_name)
    date = _parse_date(data.get("datetime_local"))
    total = _to_float(data.get("total", 0.0))
    confidence = _to_float(data.get("confidence", 0.0))

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
    extra_warnings = []
    if 0 < confidence < 0.8:
        extra_warnings.append(f"The vision model reported low confidence ({confidence:.0%}).")
    return parsed, extra_warnings


def process_image_file(file_path: str) -> IngestReport:
    """Vision-extract a receipt image, persist it, and archive.

    LLM-unavailable is reported as retryable (``llm_unavailable``) and leaves
    the file where it is; a garbage extraction moves the file to ``failed/``.
    """
    logger.info("Vision-processing image: %s", file_path)
    try:
        parsed, extra_warnings = extract_receipt_from_image(file_path)
    except VisionExtractionError as e:
        parked = move_to_failed(file_path) if e.status == "no_data" else None
        logger.warning("Vision ingest failed for %s: %s", file_path, e.message)
        return IngestReport(status=e.status, error=e.message,
                            file_path=_relative_to_data(parked) if parked else None)

    image_bytes = Path(file_path).read_bytes()
    filename = os.path.basename(file_path)
    dest = plan_archive_path(file_path, parsed.store_key)
    report = _persist(parsed, filename,
                      content_hash=hashlib.sha256(image_bytes).hexdigest(),
                      source_path=_relative_to_data(dest),
                      extraction_source="vision_llm",
                      extra_warnings=extra_warnings)
    archive_to(file_path, dest)
    report.file_path = _relative_to_data(dest)
    return report
