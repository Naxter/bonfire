"""One-shot ingest of everything sitting in ``data/inbox/``.

The watcher (``watch_inbox.py``) does this continuously; run this instead for
an initial bulk import or after the watcher was down.
"""

import logging
from pathlib import Path

import app.config  # noqa: F401  (loads repo-root .env)
from app.database import create_db_and_tables
from app.ingest import ensure_inbox_dirs, process_pdf_file

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# Anchor to the repo layout, not the current working directory.
INBOX_DIR = Path(__file__).resolve().parent / "data" / "inbox"


def main():
    logger.info("--- Starting Receipt Import ---")
    create_db_and_tables()
    ensure_inbox_dirs(INBOX_DIR)

    pdf_files = sorted(INBOX_DIR.rglob("*.pdf"))
    logger.info("Found %s receipts in inbox.", len(pdf_files))

    imported = 0
    for pdf in pdf_files:
        # process_pdf_file archives the file itself (new or duplicate).
        if process_pdf_file(str(pdf)):
            imported += 1

    logger.info("--- Import Finished: %s new receipt(s) ---", imported)


if __name__ == "__main__":
    main()
