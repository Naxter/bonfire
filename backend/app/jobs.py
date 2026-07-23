"""Tracked background import jobs.

Uploads, mail fetches, watcher pickups and reprocess runs all record an
ImportJob row and update it as they go. The frontend polls ``/jobs`` instead
of reloading the page, and failed imports stay visible (with a retry) instead
of vanishing into the server log.

Work runs on daemon threads — plenty for a single-household Pi deployment, and
the job rows in SQLite make the state survive across processes (the watcher
and the API each see the other's jobs).
"""

from __future__ import annotations

import importlib.util
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path

from sqlmodel import Session, select

from .database import DATA_DIR, engine
from .ingest import IngestReport, process_pdf_file, replace_receipt_data
from .models import ImportJob
from .pdf_utils import extract_text_from_pdf
from .stores import detect, get_adapter
from .vision_ingest import (
    IMAGE_EXTS,
    VisionExtractionError,
    extract_receipt_from_image,
    process_image_file,
)

logger = logging.getLogger(__name__)

# Uploads land here (NOT the watched inbox — the watcher would race the API
# for them). Same bind-mounted data dir, so retries survive restarts.
UPLOAD_DIR = DATA_DIR / "uploads"

TERMINAL_STATUSES = {"done", "duplicate", "needs_review", "failed"}

# Keep the import history bounded; nobody needs a 10k-row job table on a Pi.
_PRUNE_AFTER_DAYS = 90
_PRUNE_KEEP = 500

# One mail fetch at a time (the IMAP mailbox is a shared resource).
_mail_fetch_lock = threading.Lock()

_SCRAPER_PATH = Path(__file__).resolve().parents[2] / "email-scraper" / "scraper.py"


def _spawn(target, *args) -> None:
    """Run ``target(*args)`` on a daemon thread (tests patch this to inline)."""
    threading.Thread(target=target, args=args, daemon=True).start()


def create_job(kind: str, *, filename: str | None = None, store_key: str | None = None,
               status: str = "queued", detail: dict | None = None) -> int:
    with Session(engine) as session:
        job = ImportJob(kind=kind, status=status, filename=filename,
                        store_key=store_key, detail=detail or {})
        session.add(job)
        session.commit()
        session.refresh(job)
        _prune(session)
        return job.id


def update_job(job_id: int, **fields) -> None:
    with Session(engine) as session:
        job = session.get(ImportJob, job_id)
        if job is None:
            return
        for key, value in fields.items():
            setattr(job, key, value)
        if fields.get("status") in TERMINAL_STATUSES and job.finished_at is None:
            job.finished_at = datetime.now()
        session.commit()


def close_review_jobs(session: Session, receipt_id: int) -> None:
    """A receipt left the review queue (verified, corrected or deleted): its
    import jobs must not keep saying "needs review" in the feed. Caller
    commits."""
    for job in session.exec(
        select(ImportJob).where(ImportJob.receipt_id == receipt_id,
                                ImportJob.status == "needs_review")
    ).all():
        job.status = "done"
        if job.message:
            job.message = job.message.replace(" (needs review)", "")


def _prune(session: Session) -> None:
    """Drop ancient finished jobs (best effort, called on create)."""
    cutoff = datetime.now() - timedelta(days=_PRUNE_AFTER_DAYS)
    old = session.exec(
        select(ImportJob)
        .where(ImportJob.created_at < cutoff, ImportJob.status.in_(TERMINAL_STATUSES))  # type: ignore[attr-defined]
    ).all()
    for job in old:
        session.delete(job)
    if old:
        session.commit()


def _job_status_for(report: IngestReport) -> str:
    if report.status == "stored":
        return "needs_review" if report.review_status == "needs_review" else "done"
    if report.status == "duplicate":
        return "duplicate"
    return "failed"


def _message_for(report: IngestReport) -> str | None:
    if report.status == "stored":
        base = f"{report.store_name or 'Receipt'} — {report.items} items, €{(report.total or 0):.2f}"
        if report.review_status == "needs_review":
            base += " (needs review)"
        return base
    if report.status == "duplicate":
        return f"Already imported ({report.store_name or 'receipt'}, €{(report.total or 0):.2f})."
    return None


def run_file_job(path: str, job_id: int) -> IngestReport:
    """Ingest one file under an existing job id, recording the outcome."""
    update_job(job_id, status="running")
    try:
        if Path(path).suffix.lower() in IMAGE_EXTS:
            report = process_image_file(path)
        elif Path(path).suffix.lower() == ".pdf":
            report = process_pdf_file(path)
        else:
            report = IngestReport(status="no_data",
                                  error=f"Unsupported file type '{Path(path).suffix}'.")
    except Exception as e:  # never let a worker die silently
        logger.exception("Import job %s crashed on %s", job_id, path)
        report = IngestReport(status="parse_failed", error=f"Unexpected error: {e}")

    detail: dict = {"ingest_status": report.status}
    if report.warnings:
        detail["warnings"] = report.warnings
    if report.file_path:
        detail["file"] = report.file_path
    elif report.status == "llm_unavailable":
        # File was left in place for retry — remember where.
        try:
            detail["file"] = Path(path).resolve().relative_to(DATA_DIR.resolve()).as_posix()
        except ValueError:
            detail["file"] = str(path)

    update_job(job_id,
               status=_job_status_for(report),
               receipt_id=report.receipt_id,
               store_key=report.store_key,
               message=_message_for(report),
               error=report.error,
               detail=detail)
    return report


def process_tracked_file(path: str, kind: str) -> IngestReport:
    """Synchronous ingest with job tracking — the watcher's entry point."""
    job_id = create_job(kind, filename=Path(path).name)
    return run_file_job(path, job_id)


def start_file_job(path: str, kind: str) -> int:
    """Asynchronous ingest: create the job, process on a daemon thread,
    return the job id immediately (the API's entry point)."""
    job_id = create_job(kind, filename=Path(path).name)
    _spawn(run_file_job, path, job_id)
    return job_id


def retry_job(job_id: int) -> int | None:
    """Re-run a failed import from wherever its file was parked.

    Returns the NEW job id, or None when the job/file can't be retried."""
    with Session(engine) as session:
        job = session.get(ImportJob, job_id)
        if job is None or job.status != "failed":
            return None
        rel = (job.detail or {}).get("file")
    if not rel:
        return None
    path = (DATA_DIR / rel).resolve()
    # The recorded path must stay inside data/ (it came from our own detail
    # payload, but the DB is user-writable — don't turn it into a gadget).
    if not path.is_relative_to(DATA_DIR.resolve()) or not path.is_file():
        return None
    return start_file_job(str(path), kind="upload")


# --------------------------------------------------------------------------- #
# Reprocess
# --------------------------------------------------------------------------- #
def _reprocess_worker(job_id: int, receipt_id: int, path: str,
                      store_key: str | None, filename: str) -> None:
    update_job(job_id, status="running")
    try:
        if Path(path).suffix.lower() in IMAGE_EXTS:
            try:
                parsed, extra = extract_receipt_from_image(path)
            except VisionExtractionError as e:
                update_job(job_id, status="failed", error=e.message)
                return
            report = replace_receipt_data(receipt_id, parsed, "vision_llm", extra)
        else:
            text = extract_text_from_pdf(path)
            adapter = get_adapter(store_key or "") or detect(text, filename)
            if adapter is None:
                update_job(job_id, status="failed",
                           error="No store adapter recognized the source file.")
                return
            parsed = adapter.parse(path, text=text)
            if not parsed or not parsed.items:
                update_job(job_id, status="failed",
                           error="The parser found no line items in the source file.")
                return
            report = replace_receipt_data(receipt_id, parsed, "pdf_adapter")

        update_job(job_id,
                   status=_job_status_for(report),
                   receipt_id=report.receipt_id,
                   store_key=report.store_key,
                   message=_message_for(report),
                   error=report.error,
                   detail={"ingest_status": report.status, "warnings": report.warnings})
        # A clean reprocess resolves the review — earlier jobs for this
        # receipt must not keep flagging it.
        if report.status == "stored" and report.review_status != "needs_review":
            with Session(engine) as session:
                close_review_jobs(session, receipt_id)
                session.commit()
    except Exception as e:
        logger.exception("Reprocess job %s crashed for receipt %s", job_id, receipt_id)
        update_job(job_id, status="failed", error=f"Unexpected error: {e}")


def start_reprocess(receipt_id: int, path: str, store_key: str | None, filename: str) -> int:
    """Re-extract a receipt from its archived source on a background thread."""
    job_id = create_job("reprocess", filename=filename, store_key=store_key)
    update_job(job_id, receipt_id=receipt_id)
    _spawn(_reprocess_worker, job_id, receipt_id, path, store_key, filename)
    return job_id


# --------------------------------------------------------------------------- #
# Mail fetch
# --------------------------------------------------------------------------- #
def _run_rewe_fetch() -> dict:
    spec = importlib.util.spec_from_file_location("rewe_scraper", _SCRAPER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.fetch_ebons()


def _mail_fetch_worker(job_id: int) -> None:
    try:
        update_job(job_id, status="running")
        result = _run_rewe_fetch()
        saved = int(result.get("saved", 0))
        matched = int(result.get("mails_matched", 0))
        if saved > 0:
            message = (f"{saved} new eBon{'s' if saved != 1 else ''} saved — "
                       "the watcher is importing them now.")
        else:
            message = f"Mailbox checked ({matched} matching mails) — nothing new."
        update_job(job_id, status="done", message=message, detail=result)
    except SystemExit as e:  # scraper signals missing config this way
        update_job(job_id, status="failed", error=str(e))
    except Exception:
        logger.exception("Mail fetch job %s failed", job_id)
        update_job(job_id, status="failed",
                   error="Mail fetch failed — IMAP login or network problem; check the server logs.")
    finally:
        _mail_fetch_lock.release()


def start_mail_fetch() -> int | None:
    """Kick off a background mailbox sweep. Returns the job id, or None when
    a fetch is already running."""
    if not _mail_fetch_lock.acquire(blocking=False):
        return None
    try:
        job_id = create_job("mail_fetch", filename=None)
        _spawn(_mail_fetch_worker, job_id)
        return job_id
    except Exception:
        _mail_fetch_lock.release()
        raise
