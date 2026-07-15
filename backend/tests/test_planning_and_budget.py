"""Shopping list, restock actions, pantry, and budget targets."""

from datetime import datetime, timedelta

from app import ingest, insights
from app.stores.base import ParsedItem, ParsedReceipt


def _weekly_purchases(engine, name="Milch", weeks=4):
    """Seed a weekly cadence ending ~8 days ago, so the item is due."""
    now = datetime.now()
    for i in range(weeks):
        date = now - timedelta(days=8 + (weeks - 1 - i) * 7)
        parsed = ParsedReceipt(store_key="rewe", store_name="REWE", date=date, total=1.0,
                               transaction_id=f"w{i}",
                               items=[ParsedItem(name=name, price_total=1.0)])
        ingest._persist(parsed, f"w{i}.pdf", content_hash=f"wh{i}")


# ---- Shopping list ----------------------------------------------------------
def test_shopping_list_roundtrip(api_engine, client):
    r = client.post("/shopping-list", json={"name": "Milch", "quantity": 2})
    assert r.status_code == 200
    item = r.json()

    # Same name again bumps the quantity instead of duplicating.
    r = client.post("/shopping-list", json={"name": " milch ", "quantity": 1})
    assert r.json()["id"] == item["id"] and r.json()["quantity"] == 3

    r = client.patch(f"/shopping-list/{item['id']}", json={"checked": True})
    assert r.json()["checked"] is True

    assert client.post("/shopping-list/clear-checked").json()["removed"] == 1
    assert client.get("/shopping-list").json() == []


def test_shopping_list_validation(api_engine, client):
    assert client.post("/shopping-list", json={"name": ""}).status_code == 422
    assert client.post("/shopping-list", json={"name": "x", "quantity": -1}).status_code == 422


# ---- Restock actions --------------------------------------------------------
def test_restock_reports_due_items_with_qty(api_engine):
    _weekly_purchases(api_engine)
    due = insights.restock_report(min_purchases=3, horizon_days=3)
    assert [d["name"] for d in due] == ["Milch"]
    assert due[0]["suggested_qty"] == 1.0
    assert due[0]["overdue"] is True


def test_dismissed_items_disappear(api_engine, client):
    _weekly_purchases(api_engine)
    r = client.post("/insights/restock/actions", json={"name": "Milch", "action": "dismiss"})
    assert r.status_code == 200
    assert insights.restock_report(min_purchases=3, horizon_days=3) == []
    # Undo brings it back.
    assert client.delete("/insights/restock/actions/Milch").status_code == 200
    assert len(insights.restock_report(min_purchases=3, horizon_days=3)) == 1


def test_snooze_and_bought_hide_temporarily(api_engine, client):
    _weekly_purchases(api_engine)
    r = client.post("/insights/restock/actions",
                    json={"name": "Milch", "action": "bought", "days": 5})
    assert r.status_code == 200
    assert insights.restock_report(min_purchases=3, horizon_days=3) == []
    hidden = client.get("/insights/restock/actions").json()
    assert len(hidden) == 1 and hidden[0]["action"] == "snoozed"


def test_add_to_list_creates_shopping_item(api_engine, client):
    _weekly_purchases(api_engine)
    r = client.post("/insights/restock/actions", json={"name": "Milch", "action": "add_to_list"})
    assert r.status_code == 200 and r.json()["added_to_list"] is True
    rows = client.get("/shopping-list").json()
    assert len(rows) == 1 and rows[0]["source"] == "restock"


def test_restock_action_validation(api_engine, client):
    assert client.post("/insights/restock/actions",
                       json={"name": "x", "action": "explode"}).status_code == 422


# ---- Pantry ------------------------------------------------------------------
def test_pantry_crud_and_from_receipt(api_engine, client):
    r = client.post("/pantry", json={"name": "Reis", "quantity": 2})
    assert r.status_code == 200
    pantry_id = r.json()["id"]
    assert client.post("/pantry", json={"name": "reis"}).json()["quantity"] == 3

    _weekly_purchases(api_engine, name="Nudeln", weeks=1)
    receipts = client.get("/receipts").json()["items"]
    r = client.post(f"/pantry/from-receipt/{receipts[0]['id']}")
    assert r.status_code == 200 and r.json()["added"] == 1

    r = client.patch(f"/pantry/{pantry_id}", json={"quantity": 0.5})
    assert r.json()["quantity"] == 0.5
    assert client.delete(f"/pantry/{pantry_id}").status_code == 200


# ---- Budget targets -----------------------------------------------------------
def test_budget_targets_validation(api_engine, client):
    assert client.put("/budget/targets",
                      json={"overall": -5, "categories": {}}).status_code == 422
    assert client.put("/budget/targets",
                      json={"categories": {"Nonsense": 50}}).status_code == 422


def test_budget_targets_roundtrip_and_report(api_engine, client):
    # The UI sends EVERY category, cleared ones as null — must not 422.
    r = client.put("/budget/targets",
                   json={"overall": 400, "categories": {"Getränke": 50, "Obst & Gemüse": None}})
    assert r.status_code == 200
    assert r.json() == {"overall": 400.0, "categories": {"Getränke": 50.0}}

    # Spend this month → the report knows the remaining budget.
    now = datetime.now()
    parsed = ParsedReceipt(store_key="rewe", store_name="REWE", date=now, total=100.0,
                           items=[ParsedItem(name="Cola", price_total=100.0)])
    ingest._persist(parsed, "b.pdf", content_hash="bh1")

    report = insights.budget_report()
    assert report["target"] == 400.0
    assert report["remaining"] == 300.0
    assert report["over_target"] is False

    # Clearing a target removes it.
    r = client.put("/budget/targets", json={"overall": None, "categories": {"Getränke": 0}})
    assert r.json() == {"overall": None, "categories": {}}


def test_budget_report_what_changed(api_engine):
    now = datetime.now()
    last_month = (now.replace(day=1) - timedelta(days=1)).replace(day=1)
    for i, (date, total) in enumerate([(last_month, 50.0), (now, 120.0)]):
        parsed = ParsedReceipt(store_key="rewe", store_name="REWE", date=date, total=total,
                               items=[ParsedItem(name="Cola", price_total=total)])
        ingest._persist(parsed, f"c{i}.pdf", content_hash=f"ch{i}")
    report = insights.budget_report()
    assert report["changes"], "expected a what-changed entry"
    assert report["changes"][0]["category"] == "Sonstiges"
