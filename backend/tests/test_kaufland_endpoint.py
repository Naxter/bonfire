"""The dashboard endpoint for a tracked Kaufland download."""

import pytest
from app import jobs, main
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

client = TestClient(main.app)


@pytest.fixture()
def job_env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(jobs, "engine", engine)
    monkeypatch.setattr(jobs, "_spawn", lambda target, *args: target(*args))
    return engine


def _job(engine, job_id):
    from app.models import ImportJob

    with Session(engine) as session:
        return session.get(ImportJob, job_id)


def test_unconfigured_kaufland_returns_503(monkeypatch):
    monkeypatch.setattr("app.kaufland.is_configured", lambda config: False)
    response = client.post("/scrape/kaufland")
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_kaufland_fetch_records_a_done_job(job_env, monkeypatch):
    monkeypatch.setattr("app.kaufland.is_configured", lambda config: True)
    monkeypatch.setattr(
        jobs,
        "_run_kaufland_fetch",
        lambda: {"status": "complete", "transactions_received": 2, "new_receipts": 2, "duplicates": 0},
    )

    response = client.post("/scrape/kaufland")

    assert response.status_code == 200
    job = _job(job_env, response.json()["job_id"])
    assert job.status == "done"
    assert job.kind == "kaufland_fetch"
    assert job.store_key == "kaufland"
    assert job.detail["new_receipts"] == 2
    assert "2 new receipts" in job.message


def test_concurrent_kaufland_fetch_returns_409(job_env, monkeypatch):
    monkeypatch.setattr("app.kaufland.is_configured", lambda config: True)
    assert jobs._kaufland_fetch_lock.acquire(blocking=False)
    try:
        response = client.post("/scrape/kaufland")
        assert response.status_code == 409
    finally:
        jobs._kaufland_fetch_lock.release()
