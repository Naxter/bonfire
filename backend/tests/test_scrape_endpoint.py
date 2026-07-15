"""Tests for the on-demand REWE mail fetch endpoint (IMAP stubbed out)."""

from app import main
from fastapi.testclient import TestClient

# No context manager: the lifespan (real-DB setup) must not run for these.
client = TestClient(main.app)


def _configure(monkeypatch):
    monkeypatch.setenv("GMX_USER", "user@example.com")
    monkeypatch.setenv("GMX_PASSWORD", "secret")
    monkeypatch.setenv("REWE_SENDER", "sender@example.com")


def test_unconfigured_scraper_returns_503(monkeypatch):
    for var in ("GMX_USER", "GMX_PASSWORD", "REWE_SENDER"):
        monkeypatch.delenv(var, raising=False)
    r = client.post("/scrape/rewe")
    assert r.status_code == 503


def test_fetch_result_is_passed_through(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(main, "_run_rewe_fetch", lambda: {"mails_matched": 3, "saved": 1})
    r = client.post("/scrape/rewe")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "mails_matched": 3, "saved": 1}


def test_concurrent_fetch_returns_409(monkeypatch):
    _configure(monkeypatch)
    assert main._scrape_lock.acquire(blocking=False)
    try:
        r = client.post("/scrape/rewe")
        assert r.status_code == 409
    finally:
        main._scrape_lock.release()


def test_imap_failure_returns_502_without_leaking_details(monkeypatch):
    _configure(monkeypatch)

    def boom():
        raise ConnectionError("imap.gmx.net: connection refused for user secret-details")

    monkeypatch.setattr(main, "_run_rewe_fetch", boom)
    r = client.post("/scrape/rewe")
    assert r.status_code == 502
    assert "secret-details" not in r.text
