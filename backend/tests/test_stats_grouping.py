"""Grouping contract of the analytics endpoints: raw receipt names, on
purpose — a wrong product-layer merge must not bend the price series shown
in the inflation tracker (identity curation lives on the products page)."""

from datetime import datetime

from app import ingest
from app.stores.base import ParsedItem, ParsedReceipt


def _persist_one(engine, name, price, day, tx):
    parsed = ParsedReceipt(
        store_key="rewe", store_name="REWE",
        date=datetime(2026, 1, day, 12, 0), total=price,
        transaction_id=tx,
        items=[ParsedItem(name=name, price_total=price)],
    )
    return ingest._persist(parsed, f"{tx}.pdf", content_hash=tx,
                           extraction_source="pdf_adapter")


def test_volatility_groups_by_receipt_name(api_engine, client):
    _persist_one(api_engine, "Nougat Creme", 2.99, 1, "v1")
    _persist_one(api_engine, "Nougat Creme", 3.19, 2, "v2")
    # Same product key after lower/strip, but a different receipt string —
    # stays out of the series (and alone it has too few purchases to rank).
    _persist_one(api_engine, "NOUGAT CREME", 1.79, 3, "v3")

    rows = client.get("/stats/price-volatility").json()
    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "Nougat Creme"
    assert row["times_bought"] == 2
    assert row["min_price"] == 2.99 and row["max_price"] == 3.19
    assert row["change_percent"] == 6.7

    history = client.get("/stats/price-history?item_name=Nougat%20Creme").json()
    assert [p["price"] for p in history] == [2.99, 3.19]


def test_top_products_hide_money_flow_lines_by_default(api_engine, client):
    _persist_one(api_engine, "Apfelschorle", 1.06, 1, "d1")
    _persist_one(api_engine, "LEERGUT EINWEG", -0.25, 2, "d2")  # deposit return

    names = [r["name"] for r in client.get("/stats/top-products").json()]
    assert names == ["Apfelschorle"]

    # An explicit category pick still shows them (pie-slice drill-down).
    filtered = client.get("/stats/top-products",
                          params={"category": "Gutscheine & Rabatte"}).json()
    assert [r["name"] for r in filtered] == ["LEERGUT EINWEG"]


def test_top_products_group_by_receipt_name(api_engine, client):
    _persist_one(api_engine, "Nougat Creme", 2.99, 1, "t1")
    _persist_one(api_engine, "NOUGAT CREME", 1.79, 2, "t2")

    rows = client.get("/stats/top-products").json()
    assert {(r["name"], r["quantity"]) for r in rows} == {
        ("Nougat Creme", 1.0), ("NOUGAT CREME", 1.0),
    }
