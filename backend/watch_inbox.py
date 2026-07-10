"""Watch the inbox folder and ingest PDFs the moment they appear.

Long-running companion to ``process_backlog.py``: instead of running on a timer,
it reacts to files being dropped into ``data/inbox/`` — whether by the REWE email
scraper or by you manually saving a DM eBon there. Each PDF is parsed and moved
to ``data/archive/`` by the shared ingest pipeline.

Run it as a service (see ``deploy/bonfire-watcher.service``) or directly:

    python watch_inbox.py
"""

import logging
import os
import threading
import time
from pathlib import Path

import app.config  # noqa: F401  (loads repo-root .env)
from app.database import create_db_and_tables
from app.ingest import ensure_inbox_dirs, process_pdf_file
from app.vision_ingest import IMAGE_EXTS, process_image_file
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

# inotify events don't always cross container/bind-mount boundaries reliably.
# Set WATCHER_POLLING=1 (the Docker setup does) to stat the folder instead.
_USE_POLLING = os.getenv("WATCHER_POLLING", "").strip().lower() in ("1", "true", "yes")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("watch_inbox")

# Anchor to the repo layout, not the current working directory.
INBOX_DIR = Path(__file__).resolve().parent / "data" / "inbox"

# How long a file's size must stay unchanged before we treat the write as done.
_STABLE_SECONDS = 1.5
_STABLE_TIMEOUT = 60.0

# The startup drain (main thread) and watchdog's dispatch thread can see the
# same file; process_pdf_file's dedup check isn't transactional, so serialize.
_ingest_lock = threading.Lock()


def _wait_until_stable(path: Path) -> bool:
    """Block until ``path`` stops growing (a copy/download has finished)."""
    last_size = -1
    stable_since = None
    deadline = time.monotonic() + _STABLE_TIMEOUT

    while time.monotonic() < deadline:
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            return False  # moved/removed out from under us

        now = time.monotonic()
        if size == last_size and size > 0:
            if stable_since is None:
                stable_since = now
            elif now - stable_since >= _STABLE_SECONDS:
                return True
        else:
            last_size = size
            stable_since = None
        time.sleep(0.5)

    logger.warning("Timed out waiting for %s to stop growing; processing anyway.", path.name)
    return True


def _ingest(path: Path) -> None:
    if not path.exists():
        return
    ext = path.suffix.lower()
    is_pdf = ext == ".pdf"
    is_image = ext in IMAGE_EXTS
    if not (is_pdf or is_image):
        return
    with _ingest_lock:
        if not _wait_until_stable(path):
            return
        try:
            # both parse, persist, and archive the file themselves
            if is_pdf:
                process_pdf_file(str(path))
            else:
                process_image_file(str(path))
        except Exception:
            logger.exception("Failed to ingest %s", path.name)


class _InboxHandler(FileSystemEventHandler):
    def on_created(self, event):
        if not event.is_directory:
            _ingest(Path(event.src_path))

    def on_moved(self, event):
        # e.g. a downloader writing to a .part file then renaming into place
        if not event.is_directory:
            _ingest(Path(event.dest_path))


def main() -> None:
    create_db_and_tables()
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    ensure_inbox_dirs(INBOX_DIR)  # create inbox/<store>/ drop folders

    # Watch BEFORE draining. Files that land while the drain runs get an event;
    # draining first left a gap (minutes, when a scraper dumps a whole mailbox)
    # in which arrivals predated the baseline snapshot and were never seen —
    # they sat in the inbox until the next restart.
    observer = PollingObserver() if _USE_POLLING else Observer()
    observer.schedule(_InboxHandler(), str(INBOX_DIR), recursive=True)
    observer.start()
    time.sleep(2)  # give the emitter time to take its baseline snapshot
    logger.info("Watching %s for new receipts (%s)...", INBOX_DIR,
                "polling" if _USE_POLLING else "inotify")

    # Drain anything that predates the watch (root + store subfolders).
    for f in sorted(INBOX_DIR.rglob("*")):
        if f.is_file():
            logger.info("Draining backlog: %s", f.name)
            _ingest(f)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join()


if __name__ == "__main__":
    main()
