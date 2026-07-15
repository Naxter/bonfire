"""Shared fixtures: an isolated in-memory DB wired into every module that
opens its own sessions, plus a TestClient whose dependency-injected sessions
use the same engine. File-system side effects (archive/failed/uploads) are
redirected into tmp_path."""

from __future__ import annotations

import pytest
from app import categorizer, ingest, insights, jobs, main
from app import settings as settings_module
from app.database import get_session
from app.rate_limit import limiter
from app.routers import jobs_api
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine


@pytest.fixture(autouse=True)
def _no_rate_limits():
    """Rate limits protect the LLM budget in production; in tests they only
    make the suite order-dependent."""
    limiter.enabled = False
    yield
    limiter.enabled = True


@pytest.fixture()
def api_engine(monkeypatch, tmp_path):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    for module in (ingest, insights, jobs, categorizer, settings_module):
        monkeypatch.setattr(module, "engine", engine)
    # Never let a test touch the real data/ tree.
    monkeypatch.setattr(ingest, "DATA_DIR", tmp_path)
    monkeypatch.setattr(ingest, "ARCHIVE_DIR", tmp_path / "archive")
    monkeypatch.setattr(ingest, "FAILED_DIR", tmp_path / "failed")
    monkeypatch.setattr(jobs, "DATA_DIR", tmp_path)
    monkeypatch.setattr(jobs, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(jobs_api, "UPLOAD_DIR", tmp_path / "uploads")
    # Categorizer must never hit a real LLM in tests.
    monkeypatch.setattr(categorizer, "predict_category_llm", lambda name: "Sonstiges")
    return engine


@pytest.fixture()
def client(api_engine):
    def _session():
        with Session(api_engine) as session:
            yield session

    main.app.dependency_overrides[get_session] = _session
    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.clear()
