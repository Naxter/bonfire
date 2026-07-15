"""Category mutation validation + product identity (sizes, merge, aliases)."""

from datetime import datetime

from app import ingest
from app.models import CategoryMap, Item, Product, ProductAlias
from app.products import clean_name, parse_size, unit_price
from app.stores.base import ParsedItem, ParsedReceipt
from sqlmodel import Session, select


def _seed(engine, names=("Banane", "Milch"), tx="t1", content_hash="h1"):
    parsed = ParsedReceipt(
        store_key="rewe", store_name="REWE", date=datetime(2026, 1, 5), total=0.0,
        transaction_id=tx,
        items=[ParsedItem(name=n, price_total=1.0) for n in names],
    )
    parsed.total = float(len(names))
    return ingest._persist(parsed, f"{tx}.pdf", content_hash=content_hash)


# ---- /categories/update ------------------------------------------------------
def test_category_update_rejects_unknown_category(api_engine, client):
    _seed(api_engine)
    r = client.put("/categories/update",
                   json={"item_name": "Banane", "new_category": "Nonsense"})
    assert r.status_code == 422


def test_category_update_rejects_arbitrary_scope(api_engine, client):
    _seed(api_engine)
    r = client.put("/categories/update",
                   json={"item_name": "Banane", "new_category": "Getränke", "scope": "everything"})
    assert r.status_code == 422


def test_category_update_all_locks_mapping(api_engine, client):
    _seed(api_engine)
    r = client.put("/categories/update",
                   json={"item_name": "Banane", "new_category": "Obst & Gemüse"})
    assert r.status_code == 200
    assert r.json()["updated_items"] == 1
    with Session(api_engine) as session:
        assert session.get(CategoryMap, "banane").is_locked is True
        product = session.exec(select(Product).where(Product.name_key == "banane")).one()
        assert product.category == "Obst & Gemüse"


def test_category_update_single_item_scope(api_engine, client):
    _seed(api_engine, tx="t1", content_hash="h1")
    _seed(api_engine, tx="t2", content_hash="h2")
    with Session(api_engine) as session:
        item = session.exec(select(Item).where(Item.name == "Banane")).first()
    r = client.put("/categories/update",
                   json={"item_name": "Banane", "new_category": "Getränke",
                         "scope": "item", "item_id": item.id})
    assert r.status_code == 200
    with Session(api_engine) as session:
        cats = {i.id: i.category for i in session.exec(select(Item).where(Item.name == "Banane")).all()}
        assert cats[item.id] == "Getränke"
        assert list(cats.values()).count("Getränke") == 1
        mapping = session.get(CategoryMap, "banane")
        assert mapping is None or mapping.is_locked is False  # no lock for single-item edits


# ---- Size parsing / unit prices ----------------------------------------------
def test_parse_size_examples():
    assert parse_size("JOGH.NATUR 500G") == (500.0, "g")
    assert parse_size("COLA 6X1,5L") == (9000.0, "ml")
    assert parse_size("BIO EIER 10ER") == (10.0, "piece")
    assert parse_size("MILCH 1,5% 1L") == (1000.0, "ml")
    assert parse_size("PFAND 0,25 EUR") is None
    assert parse_size("GURKE") is None


def test_clean_name_strips_sizes():
    assert clean_name("JOGH.NATUR 500G") == "JOGH.NATUR"
    assert clean_name("COLA 6X1,5L") == "COLA"
    assert clean_name("GURKE") == "GURKE"


def test_unit_price_normalization():
    assert unit_price(2.99, 500, "g") == {"value": 5.98, "unit": "kg"}
    assert unit_price(1.19, 1000, "ml") == {"value": 1.19, "unit": "l"}
    assert unit_price(3.0, 10, "piece") == {"value": 0.3, "unit": "piece"}
    assert unit_price(3.0, None, None) is None


def test_ingest_fills_product_size(api_engine):
    _seed(api_engine, names=("H-MILCH 3,5% 1L",))
    with Session(api_engine) as session:
        product = session.exec(select(Product)).one()
        assert (product.size_value, product.size_unit) == (1000.0, "ml")


# ---- Merge + aliases ------------------------------------------------------------
def test_merge_moves_items_and_future_imports(api_engine, client):
    _seed(api_engine, names=("MILCH 1L",), tx="t1", content_hash="h1")
    _seed(api_engine, names=("MILCH FRISCH 1L",), tx="t2", content_hash="h2")
    with Session(api_engine) as session:
        products = {p.name_key: p for p in session.exec(select(Product)).all()}
    target = products["milch 1l"]
    source = products["milch frisch 1l"]

    r = client.post("/products/merge",
                    json={"target_id": target.id, "source_ids": [source.id]})
    assert r.status_code == 200
    assert r.json()["moved_items"] == 1

    with Session(api_engine) as session:
        assert session.get(Product, source.id) is None
        assert session.get(ProductAlias, "milch frisch 1l").product_id == target.id
        assert all(i.product_id == target.id for i in session.exec(select(Item)).all())

    # A future import of the merged spelling resolves to the target product.
    _seed(api_engine, names=("MILCH FRISCH 1L",), tx="t3", content_hash="h3")
    with Session(api_engine) as session:
        items = session.exec(select(Item)).all()
        assert all(i.product_id == target.id for i in items)


def test_product_patch_validates(api_engine, client):
    _seed(api_engine, names=("MILCH 1L",))
    with Session(api_engine) as session:
        product = session.exec(select(Product)).one()
    assert client.patch(f"/products/{product.id}",
                        json={"size_unit": "barrels", "size_value": 3}).status_code == 422
    assert client.patch(f"/products/{product.id}",
                        json={"category": "Nonsense"}).status_code == 422
    r = client.patch(f"/products/{product.id}",
                     json={"brand": "Weihenstephan", "size_value": 1000, "size_unit": "ml"})
    assert r.status_code == 200
    assert r.json()["product"]["brand"] == "Weihenstephan"


def test_products_list_carries_stats_and_unit_price(api_engine, client):
    _seed(api_engine, names=("MILCH 1L",))
    body = client.get("/products").json()
    assert body["total"] == 1
    entry = body["items"][0]
    assert entry["times_bought"] == 1
    assert entry["unit_price"] == {"value": 1.0, "unit": "l"}
