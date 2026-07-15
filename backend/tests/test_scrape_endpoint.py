"""Tests for the on-demand REWE mail fetch endpoint (IMAP stubbed out).

The endpoint is job-based now: POST returns a job id immediately and the sweep
runs on a worker thread, so the tests make the thread synchronous and assert
on the recorded job."""

import pytest
from app import jobs, main
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

# No context manager: the lifespan (real-DB setup) must not run for these.
client = TestClient(main.app)


@pytest.fixture()
def job_env(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(jobs, "engine", engine)
    monkeypatch.setattr(jobs, "_spawn", lambda target, *args: target(*args))
    monkeypatch.setenv("GMX_USER", "user@example.com")
    monkeypatch.setenv("GMX_PASSWORD", "secret")
    monkeypatch.setenv("REWE_SENDER", "sender@example.com")
    return engine


def _job(engine, job_id):
    from app.models import ImportJob
    with Session(engine) as session:
        return session.get(ImportJob, job_id)


def test_unconfigured_scraper_returns_503(monkeypatch):
    for var in ("GMX_USER", "GMX_PASSWORD", "REWE_SENDER"):
        monkeypatch.delenv(var, raising=False)
    r = client.post("/scrape/rewe")
    assert r.status_code == 503


def test_fetch_records_a_done_job(job_env, monkeypatch):
    monkeypatch.setattr(jobs, "_run_rewe_fetch", lambda: {"mails_matched": 3, "saved": 1})
    r = client.post("/scrape/rewe")
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    job = _job(job_env, job_id)
    assert job.status == "done"
    assert job.kind == "mail_fetch"
    assert job.detail == {"mails_matched": 3, "saved": 1}
    assert "1 new eBon" in job.message


def test_concurrent_fetch_returns_409(job_env):
    assert jobs._mail_fetch_lock.acquire(blocking=False)
    try:
        r = client.post("/scrape/rewe")
        assert r.status_code == 409
    finally:
        jobs._mail_fetch_lock.release()


def test_lock_is_released_after_a_run(job_env, monkeypatch):
    monkeypatch.setattr(jobs, "_run_rewe_fetch", lambda: {"mails_matched": 0, "saved": 0})
    assert client.post("/scrape/rewe").status_code == 200
    # A second run must not hit the 409 path — the worker released the lock.
    assert client.post("/scrape/rewe").status_code == 200


def test_imap_failure_fails_the_job_without_leaking_details(job_env, monkeypatch):
    def boom():
        raise ConnectionError("imap.gmx.net: connection refused for user secret-details")

    monkeypatch.setattr(jobs, "_run_rewe_fetch", boom)
    r = client.post("/scrape/rewe")
    assert r.status_code == 200
    job = _job(job_env, r.json()["job_id"])
    assert job.status == "failed"
    assert "secret-details" not in (job.error or "")
