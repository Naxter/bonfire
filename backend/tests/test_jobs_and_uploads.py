"""Import jobs: upload endpoint, watcher tracking, malformed vision output,
retry, and the auth/bounds hardening."""

from pathlib import Path

import pytest
from app import jobs, vision_ingest
from app.models import ImportJob
from sqlmodel import Session, select


@pytest.fixture()
def sync_threads(monkeypatch):
    monkeypatch.setattr(jobs, "_spawn", lambda target, *args: target(*args))


def _jobs(engine):
    with Session(engine) as session:
        return session.exec(select(ImportJob)).all()


# ---- Upload endpoint -----------------------------------------------------------
def test_upload_rejects_unsupported_type(api_engine, client):
    r = client.post("/ingest/upload", files={"file": ("evil.exe", b"MZ", "application/x-msdownload")})
    assert r.status_code == 400


def test_upload_rejects_empty_file(api_engine, client):
    r = client.post("/ingest/upload", files={"file": ("empty.pdf", b"", "application/pdf")})
    assert r.status_code == 400


def test_upload_unparseable_pdf_fails_job_and_parks_file(api_engine, client, sync_threads, tmp_path):
    r = client.post("/ingest/upload",
                    files={"file": ("garbage.pdf", b"%PDF-1.4 not really", "application/pdf")})
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    job = client.get(f"/jobs/{job_id}").json()
    assert job["status"] == "failed"
    assert job["error"]
    # The file was parked under failed/ (inside the test tmp data dir).
    parked = job["detail"].get("file", "")
    assert parked.startswith("failed/")
    assert (tmp_path / parked).is_file()


def test_failed_upload_can_be_retried(api_engine, client, sync_threads):
    r = client.post("/ingest/upload",
                    files={"file": ("garbage.pdf", b"%PDF-1.4 not really", "application/pdf")})
    job_id = r.json()["job_id"]
    r = client.post(f"/jobs/{job_id}/retry")
    assert r.status_code == 200
    assert r.json()["job_id"] != job_id


def test_retry_rejects_non_failed_jobs(api_engine, client):
    job_id = jobs.create_job("upload", filename="x.pdf")
    jobs.update_job(job_id, status="done")
    assert client.post(f"/jobs/{job_id}/retry").status_code == 409


# ---- Malformed vision output ----------------------------------------------------
def _write_image(tmp_path) -> str:
    path = tmp_path / "inbox" / "receipt.jpg"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xd8\xff\xe0 fake jpeg")
    return str(path)


def test_vision_garbage_json_fails_cleanly(api_engine, tmp_path, monkeypatch):
    monkeypatch.setattr(vision_ingest, "complete_vision",
                        lambda *a, **k: "I am not JSON at all {{{")
    path = _write_image(tmp_path)
    report = vision_ingest.process_image_file(path)
    assert report.status == "no_data"
    assert not Path(path).exists()  # parked in failed/, not left to loop


def test_vision_wrong_shape_fails_cleanly(api_engine, tmp_path, monkeypatch):
    monkeypatch.setattr(vision_ingest, "complete_vision",
                        lambda *a, **k: '{"items": "not-a-list", "total": "??"}')
    report = vision_ingest.process_image_file(_write_image(tmp_path))
    assert report.status == "no_data"


def test_vision_llm_down_is_retryable_and_leaves_file(api_engine, tmp_path, monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("api unreachable")

    monkeypatch.setattr(vision_ingest, "complete_vision", boom)
    path = _write_image(tmp_path)
    report = vision_ingest.process_image_file(path)
    assert report.status == "llm_unavailable"
    assert Path(path).exists()  # stays for retry


def test_vision_success_needs_review(api_engine, tmp_path, monkeypatch):
    monkeypatch.setattr(
        vision_ingest, "complete_vision",
        lambda *a, **k: '{"store_name": "ALDI", "datetime_local": "2026-03-06T16:17:00",'
                        ' "total": 3.98, "confidence": 0.95,'
                        ' "items": [{"name": "MILCH", "amount": 2, "subTotal": 3.98}]}')
    report = vision_ingest.process_image_file(_write_image(tmp_path))
    assert report.stored and report.review_status == "needs_review"
    assert report.store_key == "aldi"


# ---- Watcher-tracked ingest ------------------------------------------------------
def test_process_tracked_file_records_job(api_engine, tmp_path, monkeypatch):
    monkeypatch.setattr(
        vision_ingest, "complete_vision",
        lambda *a, **k: '{"store_name": "ALDI", "total": 1.0, "confidence": 1.0,'
                        ' "items": [{"name": "BROT", "amount": 1, "subTotal": 1.0}]}')
    report = jobs.process_tracked_file(_write_image(tmp_path), kind="watcher")
    assert report.stored
    recorded = _jobs(api_engine)
    assert len(recorded) == 1
    assert recorded[0].kind == "watcher"
    assert recorded[0].status == "needs_review"
    assert recorded[0].receipt_id == report.receipt_id


# ---- Bounds + auth ---------------------------------------------------------------
def test_pagination_bounds_are_clamped(api_engine, client):
    assert client.get("/receipts?page=0&limit=999999").status_code == 200
    assert client.get("/jobs?limit=999999").status_code == 200
    assert client.get("/stats/top-products?limit=999999").status_code == 200
    assert client.get("/receipts?review=banana").status_code == 422
    assert client.get("/jobs?status=banana").status_code == 422


def test_token_auth_guards_everything_but_health(api_engine, client, monkeypatch):
    monkeypatch.setenv("BONFIRE_API_TOKEN", "sekrit")
    assert client.get("/receipts").status_code == 401
    assert client.get("/health").status_code == 200
    assert client.get("/receipts", headers={"X-Api-Token": "wrong"}).status_code == 401
    assert client.get("/receipts", headers={"X-Api-Token": "sekrit"}).status_code == 200
    assert client.get("/receipts", headers={"Authorization": "Bearer sekrit"}).status_code == 200
    assert client.get("/receipts?token=sekrit").status_code == 200


def test_no_token_configured_means_open(api_engine, client, monkeypatch):
    monkeypatch.delenv("BONFIRE_API_TOKEN", raising=False)
    assert client.get("/receipts").status_code == 200


# ---- Export ---------------------------------------------------------------------
def test_csv_export_streams_rows(api_engine, client):
    from datetime import datetime

    from app import ingest
    from app.stores.base import ParsedItem, ParsedReceipt
    parsed = ParsedReceipt(store_key="rewe", store_name="REWE",
                           date=datetime(2026, 1, 5), total=1.49,
                           items=[ParsedItem(name="Banane", price_total=1.49)])
    ingest._persist(parsed, "e.pdf", content_hash="eh1")
    r = client.get("/export/items.csv")
    assert r.status_code == 200
    lines = r.text.strip().splitlines()
    assert lines[0].startswith("receipt_id,store_key")
    assert len(lines) == 2 and "Banane" in lines[1]
