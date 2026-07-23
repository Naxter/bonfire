"""Receipt lifecycle: totals validation, review states, edit/delete/duplicates."""

from datetime import datetime

from app import ingest
from app.models import CategoryMap, ImportJob, Item, Product, Receipt
from app.stores.base import ParsedItem, ParsedReceipt
from sqlmodel import Session, select


def _persist(session_engine, *, total=3.48, items=None, tx=None, content_hash=None,
             extraction_source="pdf_adapter"):
    parsed = ParsedReceipt(
        store_key="rewe", store_name="REWE",
        date=datetime(2026, 1, 5, 12, 0), total=total,
        transaction_id=tx,
        items=items or [ParsedItem(name="Banane", price_total=1.49),
                        ParsedItem(name="Milch", price_total=1.99)],
    )
    return ingest._persist(parsed, f"{tx or content_hash or 'r'}.pdf",
                           content_hash=content_hash, extraction_source=extraction_source)


def test_matching_totals_import_clean(api_engine):
    report = _persist(api_engine, content_hash="h1")
    assert report.stored and report.review_status == "ok" and report.warnings == []


def test_total_mismatch_flags_review(api_engine):
    report = _persist(api_engine, total=10.00, content_hash="h2")
    assert report.review_status == "needs_review"
    assert any("add up to" in w for w in report.warnings)
    with Session(api_engine) as session:
        receipt = session.exec(select(Receipt)).one()
        assert receipt.review_status == "needs_review"
        assert receipt.parse_warnings


def test_vision_imports_always_need_review(api_engine):
    report = _persist(api_engine, content_hash="h3", extraction_source="vision_llm")
    assert report.review_status == "needs_review"


def test_discount_lines_are_flagged_and_categorized(api_engine):
    items = [ParsedItem(name="Chips", price_total=2.19),
             ParsedItem(name="RABATT COUPON", price_total=-0.50)]
    _persist(api_engine, total=1.69, items=items, content_hash="h4")
    with Session(api_engine) as session:
        rabatt = session.exec(select(Item).where(Item.price_total < 0)).one()
        assert rabatt.is_discounted is True
        assert rabatt.category == "Gutscheine & Rabatte"


def test_patch_receipt_revalidates_and_verifies(api_engine, client):
    receipt_id = _persist(api_engine, total=10.0, content_hash="h5").receipt_id
    r = client.patch(f"/receipts/{receipt_id}", json={"total_amount": 3.48})
    assert r.status_code == 200
    body = r.json()["receipt"]
    assert body["review_status"] == "verified"
    assert body["parse_warnings"] == []


def test_patch_receipt_validates_inputs(api_engine, client):
    receipt_id = _persist(api_engine, content_hash="h6").receipt_id
    assert client.patch(f"/receipts/{receipt_id}", json={"date": "not-a-date"}).status_code == 422
    assert client.patch(f"/receipts/{receipt_id}", json={"store_key": "NOT OK!"}).status_code == 422
    assert client.patch(f"/receipts/{receipt_id}", json={"total_amount": -5}).status_code == 422
    assert client.patch(f"/receipts/{receipt_id}", json={"store_name": ""}).status_code == 422


def test_item_edit_scope_item_vs_all(api_engine, client):
    first = _persist(api_engine, content_hash="h7", tx="t7").receipt_id
    second = _persist(api_engine, content_hash="h8", tx="t8").receipt_id
    with Session(api_engine) as session:
        item = session.exec(select(Item).where(Item.receipt_id == first,
                                               Item.name == "Banane")).one()

    # scope=item: only this row changes
    r = client.patch(f"/receipts/{first}/items/{item.id}",
                     json={"category": "Obst & Gemüse", "category_scope": "item"})
    assert r.status_code == 200
    with Session(api_engine) as session:
        other = session.exec(select(Item).where(Item.receipt_id == second,
                                                Item.name == "Banane")).one()
        assert other.category != "Obst & Gemüse"

    # scope=all: every matching row + locked mapping
    r = client.patch(f"/receipts/{first}/items/{item.id}",
                     json={"category": "Obst & Gemüse", "category_scope": "all"})
    assert r.status_code == 200 and r.json()["updated_items"] == 2
    with Session(api_engine) as session:
        mapping = session.get(CategoryMap, "banane")
        assert mapping.category == "Obst & Gemüse" and mapping.is_locked


def test_item_add_and_delete_refresh_totals_check(api_engine, client):
    receipt_id = _persist(api_engine, content_hash="h9").receipt_id
    r = client.post(f"/receipts/{receipt_id}/items",
                    json={"name": "Brot", "price_total": 2.49, "quantity": 1})
    assert r.status_code == 200
    detail = client.get(f"/receipts/{receipt_id}").json()
    assert detail["total_mismatch"] is True  # 3.48 + 2.49 != 3.48

    item_id = r.json()["item"]["id"]
    assert client.delete(f"/receipts/{receipt_id}/items/{item_id}").status_code == 200
    detail = client.get(f"/receipts/{receipt_id}").json()
    assert detail["total_mismatch"] is False


def test_delete_receipt_removes_items(api_engine, client):
    receipt_id = _persist(api_engine, content_hash="h10").receipt_id
    assert client.delete(f"/receipts/{receipt_id}").status_code == 200
    assert client.get(f"/receipts/{receipt_id}").status_code == 404
    with Session(api_engine) as session:
        assert session.exec(select(Item)).all() == []


def test_duplicates_show_up_in_detail(api_engine, client):
    a = _persist(api_engine, content_hash="d1", tx="x1").receipt_id
    _persist(api_engine, content_hash="d2", tx="x2")
    detail = client.get(f"/receipts/{a}").json()
    assert len(detail["duplicates"]) == 1
    groups = client.get("/receipts/duplicate-groups").json()
    assert len(groups) == 1 and len(groups[0]["receipts"]) == 2


def test_review_filter_and_count(api_engine, client):
    _persist(api_engine, total=99.0, content_hash="h11", tx="t11")   # mismatch
    _persist(api_engine, content_hash="h12", tx="t12")               # clean
    assert client.get("/receipts/needs-review-count").json()["count"] == 1
    listed = client.get("/receipts?review=needs_review").json()
    assert listed["total"] == 1
    assert listed["items"][0]["total_mismatch"] is True


def test_verify_endpoint(api_engine, client):
    receipt_id = _persist(api_engine, total=99.0, content_hash="h13").receipt_id
    r = client.post(f"/receipts/{receipt_id}/verify")
    assert r.status_code == 200
    assert r.json()["receipt"]["review_status"] == "verified"


def _needs_review_job(engine, receipt_id):
    with Session(engine) as session:
        job = ImportJob(kind="upload", status="needs_review", receipt_id=receipt_id,
                        message="REWE — 2 items, €99.00 (needs review)")
        session.add(job)
        session.commit()
        return job.id


def test_verify_flips_import_job_status(api_engine, client):
    receipt_id = _persist(api_engine, total=99.0, content_hash="h14").receipt_id
    job_id = _needs_review_job(api_engine, receipt_id)

    assert client.post(f"/receipts/{receipt_id}/verify").status_code == 200
    with Session(api_engine) as session:
        job = session.get(ImportJob, job_id)
        assert job.status == "done"
        assert job.message == "REWE — 2 items, €99.00"


def test_receipt_correction_closes_review_jobs(api_engine, client):
    """Fixing the numbers in the edit dialog resolves the review — the feed
    row must not keep saying "needs review"."""
    receipt_id = _persist(api_engine, total=99.0, content_hash="h15").receipt_id
    job_id = _needs_review_job(api_engine, receipt_id)

    r = client.patch(f"/receipts/{receipt_id}", json={"total_amount": 3.48})
    assert r.json()["receipt"]["review_status"] == "verified"
    with Session(api_engine) as session:
        job = session.get(ImportJob, job_id)
        assert job.status == "done"
        assert "(needs review)" not in job.message


def test_delete_receipt_closes_review_jobs(api_engine, client):
    """A deleted receipt can never be reviewed — no eternal "needs review"
    rows in the feed."""
    receipt_id = _persist(api_engine, total=99.0, content_hash="h16").receipt_id
    job_id = _needs_review_job(api_engine, receipt_id)

    assert client.delete(f"/receipts/{receipt_id}").status_code == 200
    with Session(api_engine) as session:
        job = session.get(ImportJob, job_id)
        assert job.status == "done"
        assert job.receipt_id is None


def test_quantity_edit_recomputes_price_single(api_engine, client):
    receipt_id = _persist(api_engine, content_hash="h17").receipt_id
    with Session(api_engine) as session:
        item = session.exec(select(Item).where(Item.name == "Banane")).one()
    client.patch(f"/receipts/{receipt_id}/items/{item.id}", json={"price_total": 3.0})
    r = client.patch(f"/receipts/{receipt_id}/items/{item.id}", json={"quantity": 2})
    assert r.json()["item"]["price_single"] == 1.5


def test_added_and_renamed_items_join_product_layer(api_engine, client):
    receipt_id = _persist(api_engine, content_hash="h18").receipt_id

    # A brand-new name gets its own product immediately (like an import would).
    r = client.post(f"/receipts/{receipt_id}/items",
                    json={"name": "Kürbiskerne 200g", "price_total": 3.49, "quantity": 1})
    created = r.json()["item"]
    assert created["product_id"] is not None
    with Session(api_engine) as session:
        product = session.get(Product, created["product_id"])
        assert product.name_key == "kürbiskerne 200g"
        assert (product.size_value, product.size_unit) == (200.0, "g")

    # Renaming a line onto an existing product makes it follow that
    # product's category.
    client.put("/categories/update",
               json={"item_name": "Milch", "new_category": "Molkereiprodukte & Eier"})
    with Session(api_engine) as session:
        banane = session.exec(select(Item).where(Item.name == "Banane")).one()
    r = client.patch(f"/receipts/{receipt_id}/items/{banane.id}", json={"name": "Milch"})
    assert r.json()["item"]["category"] == "Molkereiprodukte & Eier"
