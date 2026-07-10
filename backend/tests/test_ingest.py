"""Tests for receipt persistence (dedupe) and the category cache.

Everything runs against an in-memory SQLite database; the LLM is stubbed out.
"""

from datetime import datetime

import pytest
from app import categorizer, ingest
from app.models import CategoryMap, Item, Receipt
from app.stores.base import ParsedItem, ParsedReceipt
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select


@pytest.fixture()
def mem_engine(monkeypatch):
    # StaticPool: every Session shares the one in-memory connection.
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(ingest, "engine", engine)
    monkeypatch.setattr(ingest, "get_category", lambda name, session=None: "Sonstiges")
    return engine


def parsed_receipt(**overrides) -> ParsedReceipt:
    base = dict(
        store_key="rewe",
        store_name="REWE",
        date=datetime(2026, 1, 5, 12, 0),
        total=3.48,
        items=[ParsedItem(name="Banane", price_total=1.49),
               ParsedItem(name="Milch", price_total=1.99)],
    )
    base.update(overrides)
    return ParsedReceipt(**base)


def test_persist_stores_receipt_items_and_products(mem_engine):
    assert ingest._persist(parsed_receipt(), "a.pdf", content_hash="h1") is True
    with Session(mem_engine) as session:
        receipt = session.exec(select(Receipt)).one()
        assert receipt.store_key == "rewe"
        items = session.exec(select(Item)).all()
        assert len(items) == 2
        # Every item is linked to a canonical product.
        assert all(i.product_id is not None for i in items)


def test_same_content_hash_is_deduped_across_filenames(mem_engine):
    assert ingest._persist(parsed_receipt(), "a.pdf", content_hash="h1") is True
    assert ingest._persist(parsed_receipt(), "renamed.pdf", content_hash="h1") is False
    with Session(mem_engine) as session:
        assert len(session.exec(select(Receipt)).all()) == 1


def test_same_transaction_id_is_deduped_without_hash(mem_engine):
    first = parsed_receipt(transaction_id="tx-1")
    second = parsed_receipt(transaction_id="tx-1")
    assert ingest._persist(first, "a.pdf") is True
    assert ingest._persist(second, "b.pdf") is False


def test_rehash_adopts_hash_on_existing_receipt(mem_engine):
    # Rows ingested before content hashing existed get the hash on re-sight.
    assert ingest._persist(parsed_receipt(transaction_id="tx-1"), "a.pdf") is True
    assert ingest._persist(parsed_receipt(transaction_id="tx-1"), "a.pdf", content_hash="h9") is False
    with Session(mem_engine) as session:
        assert session.exec(select(Receipt)).one().content_hash == "h9"


def test_pfand_bypasses_the_llm(mem_engine):
    receipt = parsed_receipt(items=[ParsedItem(name="PFAND 0,25 EUR", price_total=0.25)])
    ingest._persist(receipt, "pfand.pdf", content_hash="h2")
    with Session(mem_engine) as session:
        assert session.exec(select(Item)).one().category == "Pfand"


def test_store_hint_from_inbox_subfolder():
    assert ingest.store_hint_from_path("/data/inbox/dm/bon.pdf") == "dm"
    assert ingest.store_hint_from_path("/data/inbox/rewe/bon.pdf") == "rewe"
    assert ingest.store_hint_from_path("/data/inbox/bon.pdf") is None


def test_category_cache_skips_llm_on_known_items(mem_engine, monkeypatch):
    def boom(name):
        raise AssertionError("LLM must not be called for cached items")

    monkeypatch.setattr(categorizer, "predict_category_llm", boom)
    with Session(mem_engine) as session:
        session.add(CategoryMap(item_key="banane", category="Obst & Gemüse"))
        session.commit()
        assert categorizer.get_category("  BANANE ", session=session) == "Obst & Gemüse"


def test_new_item_is_predicted_once_then_cached(mem_engine, monkeypatch):
    calls = []

    def fake_predict(name):
        calls.append(name)
        return "Getränke"

    monkeypatch.setattr(categorizer, "predict_category_llm", fake_predict)
    with Session(mem_engine) as session:
        assert categorizer.get_category("Apfelschorle", session=session) == "Getränke"
        assert categorizer.get_category("Apfelschorle", session=session) == "Getränke"
    assert calls == ["Apfelschorle"]
