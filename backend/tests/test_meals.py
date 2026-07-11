"""Tests for meal profiles and the meal-suggestion context builder.

In-memory SQLite; the LLM call is stubbed. The context builder is the part
with real logic (last-trip-per-store, widening, recency-capping), so it gets
the most coverage.
"""

from datetime import datetime, timedelta

import pytest
from app import database, insights
from app.meal_profiles import BUILTIN_MEAL_PROFILES
from app.models import Item, MealProfile, Receipt
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select


@pytest.fixture()
def mem_engine(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(insights, "engine", engine)
    monkeypatch.setattr(database, "engine", engine)
    return engine


def add_receipt(session, store_key: str, days_ago: float, item_names: list[str],
                category: str = "Obst & Gemüse") -> None:
    receipt = Receipt(
        store_name=store_key.upper(), store_key=store_key,
        date=datetime.now() - timedelta(days=days_ago),
        total_amount=9.99, pdf_filename=f"{store_key}_{days_ago}.pdf",
    )
    session.add(receipt)
    session.commit()
    session.refresh(receipt)
    for name in item_names:
        session.add(Item(receipt_id=receipt.id, name=name, clean_name=name,
                         category=category, price_total=1.0))
    session.commit()


def test_seed_meal_profiles_is_idempotent(mem_engine):
    database.seed_meal_profiles()
    database.seed_meal_profiles()
    with Session(mem_engine) as session:
        rows = session.exec(select(MealProfile)).all()
    assert {r.key for r in rows} == set(BUILTIN_MEAL_PROFILES)
    assert all(r.is_builtin for r in rows)


def test_trip_context_uses_only_latest_receipt_per_store(mem_engine):
    with Session(mem_engine) as session:
        add_receipt(session, "rewe", 2, [f"fresh-{i}" for i in range(5)])
        add_receipt(session, "dm", 1, [f"drug-{i}" for i in range(5)])
        add_receipt(session, "rewe", 20, ["stale-item"])  # older trip, same store

    foods, ctx = insights._meal_ingredients("trip", days=14, max_items=60)
    assert ctx["mode"] == "trip" and ctx["widened"] is False
    assert "stale-item" not in foods
    assert len(foods) == 10


def test_thin_trip_widens_to_window(mem_engine):
    with Session(mem_engine) as session:
        add_receipt(session, "rewe", 1, ["milk", "bread"])       # thin latest trip
        add_receipt(session, "rewe", 5, ["eggs", "butter"])      # within window
        add_receipt(session, "rewe", 40, ["ancient-cheese"])     # outside window

    foods, ctx = insights._meal_ingredients("trip", days=14, max_items=60)
    assert ctx["widened"] is True
    assert {"milk", "bread", "eggs", "butter"} <= set(foods)
    assert "ancient-cheese" not in foods


def test_cap_keeps_newest_not_alphabetical(mem_engine):
    with Session(mem_engine) as session:
        add_receipt(session, "rewe", 9, ["aaa-old-apple"])
        add_receipt(session, "rewe", 2, ["zzz-new-yogurt"])
        add_receipt(session, "rewe", 1, ["yyy-new-milk"])

    foods, _ = insights._meal_ingredients("days", days=14, max_items=2)
    assert foods == ["yyy-new-milk", "zzz-new-yogurt"]


def test_non_food_and_uncategorized_are_filtered(mem_engine):
    with Session(mem_engine) as session:
        add_receipt(session, "rewe", 1, ["tomatoes"])
        add_receipt(session, "dm", 1, ["shampoo"], category="Drogerie & Kosmetik")
        add_receipt(session, "aldi", 1, ["mystery"], category="Uncategorized")

    foods, _ = insights._meal_ingredients("days", days=14, max_items=60)
    assert foods == ["tomatoes"]


def test_meal_suggestions_full_flow(mem_engine, monkeypatch):
    database.seed_meal_profiles()
    with Session(mem_engine) as session:
        add_receipt(session, "rewe", 1, ["Tomaten", "Nudeln", "Zwiebeln"])
        session.add(MealProfile(key="keto", name="Keto", prompt="Only keto meals."))
        session.commit()

    prompts = []

    def fake_complete(prompt, **kwargs):
        prompts.append(prompt)
        return '{"meals": [{"title": "Pasta", "uses": ["Nudeln"], "time_minutes": 20}]}'

    monkeypatch.setattr(insights, "complete", fake_complete)

    result = insights.meal_suggestions(profile="keto", count=99,
                                       avoid=["Old Pasta", "Old Soup"])
    assert result["status"] == "ok"
    assert result["profile"] == {"key": "keto", "name": "Keto"}
    assert result["meals"][0]["title"] == "Pasta"
    assert "Only keto meals." in prompts[0]          # custom profile prompt used
    assert "Suggest 6 meals" in prompts[0]           # count clamped to 6
    assert "Old Pasta; Old Soup" in prompts[0]       # avoid list injected


def test_unknown_profile_falls_back_to_adult(mem_engine, monkeypatch):
    database.seed_meal_profiles()
    with Session(mem_engine) as session:
        add_receipt(session, "rewe", 1, ["Tomaten"])
    monkeypatch.setattr(insights, "complete", lambda *a, **k: '{"meals": []}')

    result = insights.meal_suggestions(profile="does-not-exist")
    assert result["profile"]["key"] == "adult"


def test_llm_failure_is_reported_not_masked(mem_engine, monkeypatch):
    database.seed_meal_profiles()
    with Session(mem_engine) as session:
        add_receipt(session, "rewe", 1, ["Tomaten"])

    def boom(*a, **k):
        raise RuntimeError("provider down")

    monkeypatch.setattr(insights, "complete", boom)
    result = insights.meal_suggestions()
    assert result["status"] == "llm_error"
    assert result["meals"] == []


def test_empty_pantry_is_its_own_status(mem_engine):
    database.seed_meal_profiles()
    result = insights.meal_suggestions()
    assert result["status"] == "no_ingredients"
