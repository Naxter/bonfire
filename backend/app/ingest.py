"""Store-agnostic ingest pipeline: detect -> parse -> persist -> archive.

Contains no store-specific logic. Adding a store never touches this file.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
from pathlib import Path

from sqlmodel import Session, select

from .categorizer import get_category
from .database import engine
from .models import Item, Product, Receipt
from .pdf_utils import extract_text_from_pdf
from .stores import ParsedReceipt, detect, get_adapter, list_stores

logger = logging.getLogger(__name__)

ARCHIVE_DIR = Path(__file__).resolve().parent.parent / "data" / "archive"

# Canonical store keys, used to recognise inbox/<store>/ subfolders.
STORE_KEYS = {s["key"] for s in list_stores()}


def store_hint_from_path(file_path: str) -> str | None:
    """A receipt sitting in an inbox subfolder named after a store (e.g.
    ``inbox/dm/…``) is treated as that store. Handy for manual DM drops whose
    text layer doesn't always auto-detect cleanly.
    """
    parent = Path(file_path).parent.name.strip().lower()
    return parent if parent in STORE_KEYS else None


def ensure_inbox_dirs(inbox: Path) -> None:
    """Create an ``inbox/<store>`` subfolder per store so there's an obvious
    place to drop files. Dropping into the inbox root still works (auto-detect).
    """
    for key in sorted(STORE_KEYS):
        (inbox / key).mkdir(parents=True, exist_ok=True)


def process_pdf_file(file_path: str) -> bool:
    """Ingest a single PDF. Returns True if a new receipt was stored.

    Handles its own archiving (successes and duplicates both get archived), so
    callers must NOT archive again.
    """
    logger.info("Processing: %s", file_path)

    # Extract text once; reused for detection AND (for OCR stores) parsing.
    text = extract_text_from_pdf(file_path)
    filename = os.path.basename(file_path)

    # A store-named subfolder wins over content detection; the inbox root falls
    # back to auto-detection.
    hint = store_hint_from_path(file_path)
    if hint:
        adapter = get_adapter(hint)
        logger.info("Store folder '%s' selected for %s.", hint, filename)
    else:
        adapter = detect(text, filename)

    if adapter is None:
        logger.warning("No store adapter matched %s — leaving in place.", filename)
        return False

    try:
        parsed = adapter.parse(file_path, text=text)
    except Exception as e:
        logger.error("Adapter '%s' failed to parse %s: %s", adapter.key, filename, e)
        return False

    if not parsed or not parsed.items:
        logger.warning("No data extracted from %s — skipping.", filename)
        return False

    content_hash = hashlib.sha256(Path(file_path).read_bytes()).hexdigest()
    stored = _persist(parsed, filename, content_hash=content_hash)
    archive_file(file_path, parsed.store_key)  # single archiving point (new or duplicate)
    return stored


def _get_or_create_product(session: Session, name: str, category: str) -> Product:
    """Resolve the canonical product for an item name (same normalization as
    CategoryMap), creating it on first sight and keeping its category current."""
    key = name.lower().strip()
    product = session.exec(select(Product).where(Product.name_key == key)).first()
    if product is None:
        product = Product(name_key=key, display_name=name, category=category)
        session.add(product)
        session.flush()  # assign product.id
    elif product.category != category:
        product.category = category
    return product


def _persist(parsed: ParsedReceipt, filename: str, content_hash: str | None = None) -> bool:
    with Session(engine) as session:
        # Dedup: content hash (robust — survives renames and re-downloads),
        # then transaction id, then filename as the last resort.
        existing = None
        if content_hash:
            existing = session.exec(
                select(Receipt).where(Receipt.content_hash == content_hash)
            ).first()
        if existing is None and parsed.transaction_id:
            existing = session.exec(
                select(Receipt).where(Receipt.transaction_id == parsed.transaction_id)
            ).first()
        if existing is None and not parsed.transaction_id:
            existing = session.exec(
                select(Receipt).where(Receipt.pdf_filename == filename)
            ).first()

        if existing:
            # Older rows predate content hashing — adopt the hash on re-sight.
            if content_hash and not existing.content_hash:
                existing.content_hash = content_hash
                session.commit()
            logger.info("Skipping %s (duplicate).", filename)
            return False

        receipt = Receipt(
            store_name=parsed.store_name,
            store_key=parsed.store_key,
            store_address=parsed.store_address,
            store_id=parsed.store_id,
            date=parsed.date,
            total_amount=parsed.total,
            transaction_id=parsed.transaction_id,
            loyalty_program=parsed.loyalty_program,
            loyalty_details=parsed.loyalty_details,
            raw_data=parsed.raw_data,
            pdf_filename=filename,
            content_hash=content_hash,
        )
        session.add(receipt)
        session.commit()
        session.refresh(receipt)

        for line in parsed.items:
            if "pfand" in line.name.lower():
                category = "Pfand"
            else:
                category = get_category(line.name, session=session)

            product = _get_or_create_product(session, line.name, category)
            session.add(Item(
                receipt_id=receipt.id,
                product_id=product.id,
                name=line.name,
                clean_name=line.name,
                category=category,
                price_total=line.price_total,
                price_single=line.price_single,
                quantity=line.quantity,
                tax_rate=line.tax_rate,
                loyalty_qualified=line.loyalty_qualified,
            ))

        session.commit()
        logger.info("Imported %s items from %s (%s).", len(parsed.items), filename, parsed.store_key)
        return True


def archive_file(file_path: str, store_key: str = "") -> None:
    """Move a processed file into ``archive/<store_key>/`` (idempotent)."""
    dest_dir = ARCHIVE_DIR / (store_key or "unmatched")
    dest_dir.mkdir(parents=True, exist_ok=True)
    src = Path(file_path)
    if not src.exists():
        return
    shutil.move(str(src), str(dest_dir / src.name))
