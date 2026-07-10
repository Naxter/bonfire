"""Consistent, online backup of the SQLite database, keeping the last N copies.

Uses SQLite's online backup API, so it's safe to run while the API/watcher are
writing. Intended to run on a schedule (see ``deploy/bonfire-backup.timer``) —
important on a Raspberry Pi where the SD card can fail without warning.

    python backup_db.py

Config (env / .env):
    BACKUP_DIR   where to write backups   (default: <data>/backups)
    BACKUP_KEEP  how many to retain        (default: 14)
"""

import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path

import app.config  # noqa: F401  (loads repo-root .env)
from app.database import SQLITE_PATH

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("backup_db")

BACKUP_DIR = Path(os.getenv("BACKUP_DIR", SQLITE_PATH.parent / "backups"))
KEEP = int(os.getenv("BACKUP_KEEP", "14"))


def make_backup() -> Path | None:
    if not SQLITE_PATH.exists():
        logger.warning("No database at %s yet — nothing to back up.", SQLITE_PATH)
        return None

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = BACKUP_DIR / f"rewe-{stamp}.db"

    # Read-only source connection + online .backup() = a consistent snapshot
    # even if another process is mid-write.
    src = sqlite3.connect(f"file:{SQLITE_PATH}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    logger.info("Backup written: %s (%.1f KB)", dest.name, dest.stat().st_size / 1024)
    return dest


def prune() -> None:
    backups = sorted(BACKUP_DIR.glob("rewe-*.db"))
    excess = len(backups) - KEEP
    for old in backups[: max(0, excess)]:
        old.unlink()
        logger.info("Pruned old backup: %s", old.name)


def main() -> None:
    if make_backup():
        prune()


if __name__ == "__main__":
    main()
