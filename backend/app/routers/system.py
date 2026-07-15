"""System surface: stores, categories, health, settings, meal profiles.

/health goes beyond "DB answers": it reports watcher liveness, mail-fetch and
import freshness, failed imports, backup age and (on demand) a real LLM
round-trip — the stuff you actually check when the dashboard looks stale."""

from __future__ import annotations

import os
import re
import threading
import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, text
from sqlmodel import Session, SQLModel, func, select

from ..categories import VALID_CATEGORIES
from ..database import DATA_DIR, engine, get_session
from ..llm import complete, resolve_provider_name
from ..models import ImportJob, MealProfile, Receipt
from ..settings import get_settings, update_settings
from ..stores import list_stores, store_display_name

router = APIRouter()

_WATCHER_HEARTBEAT = DATA_DIR / ".watcher_heartbeat"
_WATCHER_STALE_SECONDS = 180  # heartbeat is touched every 30s
_BACKUP_DIR = DATA_DIR / "backups"


@router.get("/stores")
def get_stores(session: Session = Depends(get_session)):
    """Store list for the frontend filter. Registered adapters first, then any
    other store_key present in the data (e.g. Aldi/Lidl from photographed
    receipts) so new stores appear in the filter automatically."""
    stores = list_stores()
    keys = {s["key"] for s in stores}
    db_keys = session.exec(select(Receipt.store_key).distinct()).all()
    for key in sorted(k for k in db_keys if k and k not in keys):
        stores.append({"key": key, "display_name": store_display_name(key)})
    return stores


@router.get("/categories")
def get_categories():
    """Canonical category taxonomy — drives the category filter in the UI."""
    return VALID_CATEGORIES


def _llm_configured(provider: str) -> bool:
    """Best-effort check that the selected provider has what it needs, without
    instantiating it (so /health never throws)."""
    if provider == "openai":
        return bool(os.getenv("OPENAI_API_KEY"))
    if provider in ("gemini", "google"):
        return bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    return True  # ollama: assume a reachable local/remote daemon


def _mtime_iso(path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).isoformat()
    except OSError:
        return None


# LLM probe results are cached briefly: the point is "is it up?", not a
# per-request bill.
_probe_lock = threading.Lock()
_probe_cache: dict = {"at": 0.0, "result": None}
_PROBE_TTL_SECONDS = 600


def _probe_llm() -> dict:
    now = time.monotonic()
    with _probe_lock:
        if _probe_cache["result"] is not None and now - _probe_cache["at"] < _PROBE_TTL_SECONDS:
            return {**_probe_cache["result"], "cached": True}
    started = time.monotonic()
    try:
        reply = complete("Reply with exactly: OK", temperature=0.0)
        ok = bool(reply and "ok" in reply.lower())
        result = {"reachable": ok, "latency_ms": int((time.monotonic() - started) * 1000)}
    except Exception as e:
        result = {"reachable": False, "error": str(e)[:200]}
    with _probe_lock:
        _probe_cache["at"] = now
        _probe_cache["result"] = result
    return {**result, "cached": False}


@router.get("/health")
def health(probe: str = ""):
    """Liveness + operational freshness for the status badge and monitoring.

    ``?probe=llm`` additionally makes one real (cached) LLM call."""
    provider = resolve_provider_name()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    llm_ok = _llm_configured(provider)

    data = {
        "status": "ok" if (db_ok and llm_ok) else "degraded",
        "db": db_ok,
        "llm_provider": provider,
        "llm_configured": llm_ok,
        "mail_configured": bool(os.getenv("GMX_USER") and os.getenv("GMX_PASSWORD")
                                and os.getenv("REWE_SENDER")),
        "auth_enabled": bool((os.getenv("BONFIRE_API_TOKEN") or "").strip()),
    }

    # Watcher liveness via its heartbeat file.
    hb = _mtime_iso(_WATCHER_HEARTBEAT)
    watcher_alive = False
    if hb:
        age = datetime.now() - datetime.fromisoformat(hb)
        watcher_alive = age < timedelta(seconds=_WATCHER_STALE_SECONDS)
    data["watcher"] = {"alive": watcher_alive, "last_seen": hb}

    # Backup freshness: newest snapshot in data/backups.
    newest_backup = None
    if _BACKUP_DIR.exists():
        backups = sorted(_BACKUP_DIR.glob("*.db"), key=lambda p: p.stat().st_mtime)
        if backups:
            newest_backup = _mtime_iso(backups[-1])
    data["backup"] = {"last_at": newest_backup}

    # Import + mail freshness from the job history (never throws — table may
    # not exist on a fresh DB before the lifespan hook ran).
    if db_ok:
        try:
            with Session(engine) as session:
                last_import = session.exec(
                    select(ImportJob)
                    .where(ImportJob.status.in_(("done", "needs_review", "duplicate")))  # type: ignore[attr-defined]
                    .order_by(desc(ImportJob.id)).limit(1)
                ).first()
                last_mail = session.exec(
                    select(ImportJob).where(ImportJob.kind == "mail_fetch")
                    .order_by(desc(ImportJob.id)).limit(1)
                ).first()
                failed_24h = session.exec(
                    select(func.count(ImportJob.id)).where(
                        ImportJob.status == "failed",
                        ImportJob.created_at >= datetime.now() - timedelta(hours=24),
                    )
                ).one()
                receipt_count = session.exec(select(func.count(Receipt.id))).one()
                needs_review = session.exec(
                    select(func.count(Receipt.id)).where(Receipt.review_status == "needs_review")
                ).one()
            data["imports"] = {
                "last_success_at": (last_import.finished_at.isoformat()
                                    if last_import and last_import.finished_at else None),
                "failed_24h": int(failed_24h),
            }
            data["mail"] = {
                "configured": data["mail_configured"],
                "last_fetch_at": (last_mail.finished_at.isoformat()
                                  if last_mail and last_mail.finished_at else None),
                "last_fetch_ok": last_mail.status == "done" if last_mail else None,
            }
            data["receipts"] = {"count": int(receipt_count), "needs_review": int(needs_review)}
        except Exception:
            pass

    if probe == "llm":
        data["llm_probe"] = _probe_llm()
        if not data["llm_probe"]["reachable"]:
            data["status"] = "degraded"

    return data


@router.get("/settings")
def read_settings():
    """App-level preferences (the dashboard's gear icon).

    Infrastructure — credentials, ports, schedules — stays in .env by design;
    these are the runtime-safe behavior knobs, merged from code defaults and
    saved overrides."""
    return get_settings()


@router.put("/settings")
def write_settings(values: dict):
    """Save a partial settings update; returns the full merged settings."""
    try:
        return update_settings(values)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None


# --------------------------------------------------------------------------- #
# Meal profiles
# --------------------------------------------------------------------------- #
class MealProfileIn(SQLModel):
    name: str
    prompt: str


def _validated_profile_fields(data: MealProfileIn) -> tuple[str, str]:
    name = (data.name or "").strip()
    prompt = (data.prompt or "").strip()
    if not name or len(name) > 60:
        raise HTTPException(status_code=422, detail="Name must be 1-60 characters.")
    if not prompt or len(prompt) > 4000:
        raise HTTPException(status_code=422, detail="Prompt must be 1-4000 characters.")
    return name, prompt


@router.get("/meal-profiles")
def list_meal_profiles(session: Session = Depends(get_session)):
    """All meal profiles, built-ins first (stable id order)."""
    return session.exec(select(MealProfile).order_by(MealProfile.id)).all()


@router.post("/meal-profiles")
def create_meal_profile(data: MealProfileIn, session: Session = Depends(get_session)):
    name, prompt = _validated_profile_fields(data)
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "profile"
    key, n = base, 2
    while session.exec(select(MealProfile).where(MealProfile.key == key)).first():
        key, n = f"{base}-{n}", n + 1
    row = MealProfile(key=key, name=name, prompt=prompt, is_builtin=False)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


@router.put("/meal-profiles/{profile_id}")
def update_meal_profile(profile_id: int, data: MealProfileIn,
                        session: Session = Depends(get_session)):
    """Edit name/prompt. The key never changes (Telegram + URLs stay stable)."""
    row = session.get(MealProfile, profile_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Profile not found.")
    row.name, row.prompt = _validated_profile_fields(data)
    session.commit()
    session.refresh(row)
    return row


@router.delete("/meal-profiles/{profile_id}")
def delete_meal_profile(profile_id: int, session: Session = Depends(get_session)):
    row = session.get(MealProfile, profile_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Profile not found.")
    if row.is_builtin:
        raise HTTPException(status_code=400, detail="Built-in profiles cannot be deleted.")
    session.delete(row)
    session.commit()
    return {"ok": True}
