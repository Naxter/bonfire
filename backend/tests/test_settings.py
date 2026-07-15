"""Tests for the DB-backed app settings and their endpoint wiring."""

import pytest
from app import main
from app import settings as settings_module
from app.routers import budget_api, insights_api
from app.settings import SPECS, get_settings, update_settings
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

client = TestClient(main.app)


@pytest.fixture()
def mem_engine(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(settings_module, "engine", engine)
    return engine


def test_defaults_when_nothing_saved(mem_engine):
    assert get_settings() == {key: spec.default for key, spec in SPECS.items()}


def test_overrides_persist_and_merge(mem_engine):
    update_settings({"meals.count": 5, "budget.anomaly_factor": 2.0})
    merged = get_settings()
    assert merged["meals.count"] == 5
    assert merged["budget.anomaly_factor"] == 2.0
    assert merged["restock.horizon_days"] == SPECS["restock.horizon_days"].default


@pytest.mark.parametrize("payload", [
    {"does.not.exist": 1},          # unknown key
    {"meals.count": 99},            # out of range
    {"meals.count": 2.5},           # not a whole number
    {"meals.count": True},          # bool is not an int here
    {"meals.context": "yearly"},    # not in choices
    {"meals.profile": ""},          # empty string
])
def test_invalid_values_are_rejected(mem_engine, payload):
    with pytest.raises(ValueError):
        update_settings(payload)


def test_put_endpoint_validates(mem_engine):
    r = client.put("/settings", json={"meals.count": 99})
    assert r.status_code == 422
    r = client.put("/settings", json={"meals.count": 4})
    assert r.status_code == 200
    assert r.json()["meals.count"] == 4


def test_restock_endpoint_uses_saved_settings(mem_engine, monkeypatch):
    update_settings({"restock.horizon_days": 9, "restock.min_purchases": 4})
    captured = {}
    monkeypatch.setattr(insights_api, "restock_report", lambda **kw: captured.update(kw) or [])
    assert client.get("/insights/restock").status_code == 200
    assert captured == {"min_purchases": 4, "horizon_days": 9}


def test_restock_query_param_still_overrides(mem_engine, monkeypatch):
    update_settings({"restock.horizon_days": 9})
    captured = {}
    monkeypatch.setattr(insights_api, "restock_report", lambda **kw: captured.update(kw) or [])
    client.get("/insights/restock?horizon_days=2")
    assert captured["horizon_days"] == 2


def test_budget_endpoint_uses_saved_settings(mem_engine, monkeypatch):
    update_settings({"budget.history_months": 12, "budget.anomaly_factor": 3.0})
    captured = {}
    monkeypatch.setattr(budget_api, "budget_report", lambda **kw: captured.update(kw) or {})
    assert client.get("/insights/budget").status_code == 200
    assert captured == {"history_months": 12, "anomaly_factor": 3.0}
