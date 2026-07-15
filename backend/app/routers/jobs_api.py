"""Import center: file uploads, on-demand mail fetch, and the job history.

Uploads and mail fetches return a job id immediately; the frontend polls
``/jobs`` and refreshes its data when the job lands — no more "reload the
page and hope the watcher was done"."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import desc
from sqlmodel import Session, func, select

from ..api_utils import clamp_limit
from ..database import get_session
from ..jobs import (
    TERMINAL_STATUSES,
    UPLOAD_DIR,
    process_tracked_file,
    retry_job,
    start_file_job,
    start_mail_fetch,
)
from ..models import ImportJob
from ..rate_limit import limiter
from ..vision_ingest import IMAGE_EXTS, MAX_IMAGE_BYTES

router = APIRouter()

MAX_PDF_BYTES = 20 * 1024 * 1024
UPLOAD_EXTS = IMAGE_EXTS | {".pdf"}


def _save_upload(payload: bytes, original_name: str, ext: str) -> str:
    """Persist an upload into data/uploads with a collision-proof name."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    safe_stem = os.path.basename(original_name or "receipt").rsplit(".", 1)[0][:60] or "receipt"
    dest = UPLOAD_DIR / f"{stamp}-{safe_stem}{ext}"
    dest.write_bytes(payload)
    return str(dest)


async def _read_bounded_upload(file: UploadFile) -> tuple[bytes, str]:
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in UPLOAD_EXTS:
        raise HTTPException(status_code=400,
                            detail=f"Unsupported type '{ext}'. Use pdf/jpg/png/webp.")
    max_bytes = MAX_PDF_BYTES if ext == ".pdf" else MAX_IMAGE_BYTES
    payload = await file.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise HTTPException(status_code=413,
                            detail=f"File too large (max {max_bytes // (1024 * 1024)} MB).")
    if not payload:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    return payload, ext


@router.post("/ingest/upload")
@limiter.limit("120/hour")
async def ingest_upload(request: Request, file: UploadFile = File(...)):
    """Queue a receipt file (PDF or photo) for ingestion; returns a job id."""
    payload, ext = await _read_bounded_upload(file)
    path = _save_upload(payload, file.filename or "receipt", ext)
    job_id = start_file_job(path, kind="upload")
    return {"job_id": job_id}


@router.post("/ingest/image")
@limiter.limit("20/hour")
async def ingest_image(request: Request, file: UploadFile = File(...)):
    """Synchronous photo ingest (kept for the Telegram bot): blocks until the
    vision model answered and returns the parsed summary."""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in IMAGE_EXTS:
        raise HTTPException(status_code=400, detail=f"Unsupported type '{ext}'. Use jpg/png/webp.")
    payload, ext = await _read_bounded_upload(file)
    path = _save_upload(payload, file.filename or "receipt", ext)

    report = await asyncio.to_thread(process_tracked_file, path, "upload")

    if report.status == "llm_unavailable":
        raise HTTPException(status_code=503, detail=report.error)
    if report.status not in ("stored", "duplicate"):
        raise HTTPException(status_code=422,
                            detail=report.error or "Could not read a receipt from that image.")
    return {
        "status": "ok",
        "stored": report.stored,
        "store_name": report.store_name,
        "store_key": report.store_key,
        "total": round(report.total or 0.0, 2),
        "items": report.items,
        "date": report.date,
        "receipt_id": report.receipt_id,
        "review_status": report.review_status,
    }


@router.post("/scrape/rewe")
@limiter.limit("4/minute")
async def scrape_rewe(request: Request):
    """Fetch REWE eBons from the mailbox, as a tracked background job."""
    if not (os.getenv("GMX_USER") and os.getenv("GMX_PASSWORD") and os.getenv("REWE_SENDER")):
        raise HTTPException(
            status_code=503,
            detail="The mail scraper is not configured (GMX_USER / GMX_PASSWORD / REWE_SENDER).",
        )
    job_id = start_mail_fetch()
    if job_id is None:
        raise HTTPException(status_code=409, detail="A mail fetch is already running.")
    return {"job_id": job_id}


@router.get("/jobs")
def list_jobs(limit: int = 30, status: str = "all", active: bool = False,
              session: Session = Depends(get_session)):
    """Recent import jobs, newest first — the import/error history."""
    limit = clamp_limit(limit, cap=200)
    query = select(ImportJob)
    if active:
        query = query.where(ImportJob.status.in_(("queued", "running")))  # type: ignore[attr-defined]
    elif status != "all":
        if status not in TERMINAL_STATUSES | {"queued", "running", "failed"}:
            raise HTTPException(status_code=422, detail=f"Unknown job status {status!r}.")
        query = query.where(ImportJob.status == status)
    jobs = session.exec(query.order_by(desc(ImportJob.id)).limit(limit)).all()
    active_count = session.exec(
        select(func.count(ImportJob.id))
        .where(ImportJob.status.in_(("queued", "running")))  # type: ignore[attr-defined]
    ).one()
    return {"jobs": jobs, "active": int(active_count)}


@router.get("/jobs/{job_id}")
def get_job(job_id: int, session: Session = Depends(get_session)):
    job = session.get(ImportJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


@router.post("/jobs/{job_id}/retry")
def retry_failed_job(job_id: int, session: Session = Depends(get_session)):
    """Re-run a failed import from wherever its file was parked."""
    job = session.get(ImportJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.status != "failed":
        raise HTTPException(status_code=409, detail="Only failed jobs can be retried.")
    new_id = retry_job(job_id)
    if new_id is None:
        raise HTTPException(status_code=410,
                            detail="The file for this job is no longer available.")
    return {"job_id": new_id}
