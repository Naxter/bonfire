"""One-off: backfill receipt.content_hash from archived receipt files.

New ingests hash automatically; this covers rows that predate content hashing
by matching pdf_filename against the files in data/archive/. Idempotent — rows
that already have a hash (or whose source file is gone) are left alone.

    python backfill_hashes.py
"""

import hashlib
import logging

import app.config  # noqa: F401  (loads repo-root .env)
from app.database import DATA_DIR, create_db_and_tables, engine
from app.models import Receipt
from sqlmodel import Session, select

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("backfill_hashes")

ARCHIVE_DIR = DATA_DIR / "archive"


def main() -> None:
    create_db_and_tables()
    files = {p.name: p for p in ARCHIVE_DIR.rglob("*") if p.is_file()}
    seen_hashes: set[str] = set()

    with Session(engine) as session:
        for r in session.exec(select(Receipt)).all():
            if r.content_hash:
                seen_hashes.add(r.content_hash)

        hashed = missing = skipped = 0
        for r in session.exec(select(Receipt).where(Receipt.content_hash == None)).all():  # noqa: E711
            src = files.get(r.pdf_filename)
            if src is None:
                missing += 1
                continue
            digest = hashlib.sha256(src.read_bytes()).hexdigest()
            if digest in seen_hashes:
                # Same bytes already claimed by another receipt — don't violate
                # the unique index; leave this row for manual review.
                logger.warning("Duplicate content for %s (receipt %s) — skipped.", r.pdf_filename, r.id)
                skipped += 1
                continue
            r.content_hash = digest
            seen_hashes.add(digest)
            hashed += 1
        session.commit()

    print(f"Hashed {hashed} receipt(s); {missing} without a source file; "
          f"{skipped} skipped (duplicate bytes).")


if __name__ == "__main__":
    main()
