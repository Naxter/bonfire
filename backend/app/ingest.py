"""Store-agnostic ingest pipeline: detect -> parse -> validate -> persist -> archive.

Contains no store-specific logic. Adding a store never touches this file.

Every ingest produces an :class:`IngestReport` — rich enough for the import-job
tracking layer (``app/jobs.py``) to tell the user exactly what happened, and
truthy only when a new receipt was stored (so old boolean call sites keep
working).
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from sqlmodel import Session, select

from .categorizer import get_category
from .database import DATA_DIR, engine
from .models import Item, Product, Receipt
from .pdf_utils import extract_text_from_pdf
from .products import clean_name, normalize_key, parse_size, resolve_product
from .stores import ParsedReceipt, detect, get_adapter, list_stores

logger = logging.getLogger(__name__)

ARCHIVE_DIR = DATA_DIR / "archive"
# Files that could not be ingested land here (instead of looping through the
# watcher forever). The import history keeps a job entry pointing at them, and
# the UI offers a retry.
FAILED_DIR = DATA_DIR / "failed"

# Line items that don't add up to the printed total beyond this many euros get
# flagged for review — enough slack for float noise, tight enough to catch a
# missed or hallucinated line.
TOTAL_MISMATCH_TOLERANCE = 0.02

# Canonical store keys, used to recognise inbox/<store>/ subfolders.
STORE_KEYS = {s["key"] for s in list_stores()}


@dataclass
class IngestReport:
    """Outcome of ingesting one file.

    ``status``: stored | duplicate | no_adapter | parse_failed | no_data |
    llm_unavailable. Only "stored" is truthy."""
    status: str
    receipt_id: int | None = None
    store_key: str | None = None
    store_name: str | None = None
    total: float | None = None
    items: int = 0
    date: str | None = None
    review_status: str = "ok"
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    # Where the file ended up (archive/… or failed/…), relative to data/ —
    # lets the import history link to the source and offer retries.
    file_path: str | None = None

    @property
    def stored(self) -> bool:
        return self.status == "stored"

    def __bool__(self) -> bool:  # keeps `if process_pdf_file(...):` call sites honest
        return self.stored


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


def process_pdf_file(file_path: str) -> IngestReport:
    """Ingest a single PDF.

    Handles its own file disposition: stored/duplicate files are archived,
    unreadable ones are moved to ``data/failed/`` (so the watcher never loops
    on them), and the report says which happened.
    """
    logger.info("Processing: %s", file_path)
    filename = os.path.basename(file_path)

    # Extract text once; reused for detection AND (for OCR stores) parsing.
    # Corrupt/oversized files must fail the *job*, not the worker. The move
    # happens OUTSIDE the except block: on Windows the live traceback keeps
    # PyMuPDF's file handle open, which would make the move fail.
    text = None
    read_failed = False
    try:
        text = extract_text_from_pdf(file_path)
    except Exception as e:
        logger.error("Could not read %s as a PDF: %s", filename, e)
        read_failed = True
    if read_failed:
        parked = move_to_failed(file_path)
        return IngestReport(status="parse_failed",
                            error="This file could not be read as a PDF.",
                            file_path=_relative_to_data(parked) if parked else None)

    # A store-named subfolder wins over content detection; the inbox root falls
    # back to auto-detection.
    hint = store_hint_from_path(file_path)
    if hint:
        adapter = get_adapter(hint)
        logger.info("Store folder '%s' selected for %s.", hint, filename)
    else:
        adapter = detect(text, filename)

    if adapter is None:
        logger.warning("No store adapter matched %s.", filename)
        parked = move_to_failed(file_path)
        return IngestReport(status="no_adapter",
                            error="No store adapter recognized this file.",
                            file_path=_relative_to_data(parked) if parked else None)

    try:
        parsed = adapter.parse(file_path, text=text)
    except Exception as e:
        logger.error("Adapter '%s' failed to parse %s: %s", adapter.key, filename, e)
        parked = move_to_failed(file_path)
        return IngestReport(status="parse_failed", store_key=adapter.key,
                            error=f"The {adapter.display_name} parser failed: {e}",
                            file_path=_relative_to_data(parked) if parked else None)

    if not parsed or not parsed.items:
        logger.warning("No data extracted from %s.", filename)
        parked = move_to_failed(file_path)
        return IngestReport(status="no_data", store_key=adapter.key,
                            error="The parser found no line items in this file.",
                            file_path=_relative_to_data(parked) if parked else None)

    content_hash = hashlib.sha256(Path(file_path).read_bytes()).hexdigest()
    dest = plan_archive_path(file_path, parsed.store_key)
    report = _persist(parsed, filename, content_hash=content_hash,
                      source_path=_relative_to_data(dest))
    archive_to(file_path, dest)  # single archiving point (new or duplicate)
    report.file_path = _relative_to_data(dest)
    return report


def validate_parsed(parsed: ParsedReceipt) -> list[str]:
    """Cross-check the extraction before it becomes data. Returns warnings."""
    warnings: list[str] = []
    items_sum = round(sum(i.price_total for i in parsed.items), 2)
    total = round(parsed.total or 0.0, 2)
    if abs(items_sum - total) > TOTAL_MISMATCH_TOLERANCE:
        warnings.append(
            f"Line items add up to €{items_sum:.2f} but the receipt total is €{total:.2f}."
        )
    if total <= 0:
        warnings.append("The receipt total is zero or negative.")
    if not parsed.date:
        warnings.append("No purchase date could be extracted.")
    return warnings


def _get_or_create_product(session: Session, name: str, category: str) -> Product:
    """Resolve the canonical product for an item name — honoring merge aliases —
    creating it on first sight (with a best-effort package size) and keeping
    its category current."""
    product = resolve_product(session, name)
    if product is None:
        size = parse_size(name)
        product = Product(
            name_key=normalize_key(name),
            display_name=name,
            category=category,
            size_value=size[0] if size else None,
            size_unit=size[1] if size else None,
        )
        session.add(product)
        session.flush()  # assign product.id
    elif product.category != category:
        product.category = category
    return product


def _persist(parsed: ParsedReceipt, filename: str, content_hash: str | None = None,
             source_path: str | None = None,
             extraction_source: str = "pdf_adapter",
             extra_warnings: list[str] | None = None) -> IngestReport:
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
            # Older rows predate content hashing / source tracking — adopt both.
            changed = False
            if content_hash and not existing.content_hash:
                existing.content_hash = content_hash
                changed = True
            if source_path and not existing.source_path:
                existing.source_path = source_path
                changed = True
            if changed:
                session.commit()
            logger.info("Skipping %s (duplicate).", filename)
            return IngestReport(status="duplicate", receipt_id=existing.id,
                                store_key=existing.store_key, store_name=existing.store_name,
                                total=existing.total_amount,
                                date=existing.date.isoformat() if existing.date else None)

        warnings = validate_parsed(parsed) + list(extra_warnings or [])
        review_status = "needs_review" if (warnings or extraction_source == "vision_llm") else "ok"

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
            review_status=review_status,
            source_path=source_path,
            parse_warnings=warnings,
            extraction_source=extraction_source,
        )
        session.add(receipt)
        session.commit()
        session.refresh(receipt)

        _insert_items(session, receipt.id, parsed)
        session.commit()
        logger.info("Imported %s items from %s (%s)%s.", len(parsed.items), filename,
                    parsed.store_key, " — flagged for review" if review_status == "needs_review" else "")
        return IngestReport(status="stored", receipt_id=receipt.id,
                            store_key=parsed.store_key, store_name=parsed.store_name,
                            total=parsed.total, items=len(parsed.items),
                            date=parsed.date.isoformat() if parsed.date else None,
                            review_status=review_status, warnings=warnings)


def _insert_items(session: Session, receipt_id: int, parsed: ParsedReceipt) -> None:
    """Categorize + product-link every parsed line and add it to the session."""
    for line in parsed.items:
        if "pfand" in line.name.lower():
            category = "Pfand"
        elif line.price_total < 0:
            # Negative lines are discounts/vouchers/deposit returns — they
            # would only pollute the LLM category cache.
            category = "Gutscheine & Rabatte"
        else:
            category = get_category(line.name, session=session)

        product = _get_or_create_product(session, line.name, category)
        session.add(Item(
            receipt_id=receipt_id,
            product_id=product.id,
            name=line.name,
            clean_name=clean_name(line.name),
            category=category,
            price_total=line.price_total,
            price_single=line.price_single,
            quantity=line.quantity,
            tax_rate=line.tax_rate,
            is_discounted=line.price_total < 0,
            loyalty_qualified=line.loyalty_qualified,
        ))


def replace_receipt_data(receipt_id: int, parsed: ParsedReceipt,
                         extraction_source: str,
                         extra_warnings: list[str] | None = None) -> IngestReport:
    """Reprocess: overwrite an existing receipt's fields and line items in
    place (same id — nothing referencing the receipt breaks), re-running
    validation. Used when the parser improved or the user hits "reprocess"."""
    with Session(engine) as session:
        receipt = session.get(Receipt, receipt_id)
        if receipt is None:
            return IngestReport(status="no_data", error="Receipt no longer exists.")

        warnings = validate_parsed(parsed) + list(extra_warnings or [])
        review_status = "needs_review" if (warnings or extraction_source == "vision_llm") else "ok"

        receipt.store_name = parsed.store_name
        receipt.store_key = parsed.store_key
        receipt.store_address = parsed.store_address
        receipt.store_id = parsed.store_id
        receipt.date = parsed.date
        receipt.total_amount = parsed.total
        receipt.loyalty_program = parsed.loyalty_program
        receipt.loyalty_details = parsed.loyalty_details
        receipt.raw_data = parsed.raw_data
        receipt.parse_warnings = warnings
        receipt.review_status = review_status
        receipt.extraction_source = extraction_source

        for item in session.exec(select(Item).where(Item.receipt_id == receipt_id)).all():
            session.delete(item)
        session.flush()
        _insert_items(session, receipt_id, parsed)
        session.commit()

        logger.info("Reprocessed receipt %s: %s items%s.", receipt_id, len(parsed.items),
                    " — flagged for review" if review_status == "needs_review" else "")
        return IngestReport(status="stored", receipt_id=receipt_id,
                            store_key=parsed.store_key, store_name=parsed.store_name,
                            total=parsed.total, items=len(parsed.items),
                            date=parsed.date.isoformat() if parsed.date else None,
                            review_status=review_status, warnings=warnings)


def _relative_to_data(path: Path) -> str:
    """Path relative to backend/data as a portable forward-slash string."""
    try:
        return path.resolve().relative_to(DATA_DIR.resolve()).as_posix()
    except ValueError:
        return path.name


def _collision_free(dest: Path) -> Path:
    """Never overwrite an archived file: append -1, -2, … on name collisions."""
    if not dest.exists():
        return dest
    stem, suffix = dest.stem, dest.suffix
    for n in range(1, 1000):
        candidate = dest.with_name(f"{stem}-{n}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not find a free archive name for {dest.name}")


def plan_archive_path(file_path: str, store_key: str = "") -> Path:
    """The archive destination for a file (created, collision-free) — decided
    BEFORE persisting so the receipt row can record where its source will live."""
    dest_dir = ARCHIVE_DIR / (store_key or "unmatched")
    dest_dir.mkdir(parents=True, exist_ok=True)
    return _collision_free(dest_dir / Path(file_path).name)


def _move_resilient(src: Path, dest: Path) -> Path:
    """shutil.move with a short retry — Windows/AV can hold a file briefly.
    Falls back to copy (leaving the original) rather than losing the file."""
    for attempt in range(5):
        try:
            shutil.move(str(src), str(dest))
            return dest
        except PermissionError:
            if attempt == 4:
                break
            time.sleep(0.2)
    logger.warning("Could not move %s (still in use) — copying instead.", src.name)
    shutil.copy2(str(src), str(dest))
    try:
        src.unlink()
    except OSError:
        pass
    return dest


def archive_to(file_path: str, dest: Path) -> Path | None:
    """Move a processed file to its planned destination (idempotent)."""
    src = Path(file_path)
    if not src.exists():
        return None
    return _move_resilient(src, dest)


def archive_file(file_path: str, store_key: str = "") -> Path | None:
    """Plan + move in one step, for callers that don't need the path upfront."""
    src = Path(file_path)
    if not src.exists():
        return None
    return archive_to(file_path, plan_archive_path(file_path, store_key))


def move_to_failed(file_path: str) -> Path | None:
    """Park an unreadable file in ``data/failed/`` so it stops re-triggering
    the watcher but stays available for a manual retry from the import history."""
    src = Path(file_path)
    if not src.exists():
        return None
    FAILED_DIR.mkdir(parents=True, exist_ok=True)
    dest = _collision_free(FAILED_DIR / src.name)
    return _move_resilient(src, dest)
