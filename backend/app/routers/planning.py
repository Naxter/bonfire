"""Planning surface: shopping list, pantry, and restock-suggestion actions.

The restock radar only *suggests*; these endpoints let the user act on a
suggestion (dismiss it, snooze it, mark it bought, put it on the list) and
maintain an actual shopping list + pantry the suggestions can't invent."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc
from sqlmodel import Session, select

from ..database import get_session
from ..models import Item, PantryItem, Receipt, RestockAction, ShoppingListItem
from ..products import normalize_key
from ..schemas import PantryItemIn, PantryItemUpdate, RestockActionIn, ShoppingItemIn, ShoppingItemUpdate

router = APIRouter()

_MAX_LIST_ROWS = 500  # hard cap; a household shopping list is not big data


def _validate_name(name: str | None) -> str:
    name = (name or "").strip()
    if not name or len(name) > 120:
        raise HTTPException(status_code=422, detail="Name must be 1-120 characters.")
    return name


def _validate_qty(quantity: float | None) -> float:
    if quantity is None:
        return 1.0
    if not (0 < quantity < 10000):
        raise HTTPException(status_code=422, detail="Quantity must be between 0 and 10000.")
    return float(quantity)


# --------------------------------------------------------------------------- #
# Shopping list
# --------------------------------------------------------------------------- #
@router.get("/shopping-list")
def get_shopping_list(session: Session = Depends(get_session)):
    """Open items first (newest on top), checked items trailing."""
    rows = session.exec(
        select(ShoppingListItem)
        .order_by(ShoppingListItem.checked, desc(ShoppingListItem.id))
        .limit(_MAX_LIST_ROWS)
    ).all()
    return rows


@router.post("/shopping-list")
def add_shopping_item(data: ShoppingItemIn, session: Session = Depends(get_session)):
    name = _validate_name(data.name)
    quantity = _validate_qty(data.quantity)

    # Adding the same open item again bumps its quantity instead of duplicating.
    existing = session.exec(
        select(ShoppingListItem).where(
            ShoppingListItem.checked == False,  # noqa: E712
        )
    ).all()
    for row in existing:
        if normalize_key(row.name) == normalize_key(name):
            row.quantity = round(row.quantity + quantity, 2)
            session.commit()
            session.refresh(row)
            return row

    row = ShoppingListItem(name=name, quantity=quantity, unit=(data.unit or None),
                           category=(data.category or None), source="manual")
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


@router.patch("/shopping-list/{item_id}")
def update_shopping_item(item_id: int, data: ShoppingItemUpdate,
                         session: Session = Depends(get_session)):
    row = session.get(ShoppingListItem, item_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Shopping list item not found.")
    if data.name is not None:
        row.name = _validate_name(data.name)
    if data.quantity is not None:
        row.quantity = _validate_qty(data.quantity)
    if data.unit is not None:
        row.unit = data.unit.strip()[:20] or None
    if data.checked is not None:
        row.checked = bool(data.checked)
        row.checked_at = datetime.now() if row.checked else None
    session.commit()
    session.refresh(row)
    return row


@router.delete("/shopping-list/{item_id}")
def delete_shopping_item(item_id: int, session: Session = Depends(get_session)):
    row = session.get(ShoppingListItem, item_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Shopping list item not found.")
    session.delete(row)
    session.commit()
    return {"status": "deleted"}


@router.post("/shopping-list/clear-checked")
def clear_checked(session: Session = Depends(get_session)):
    rows = session.exec(
        select(ShoppingListItem).where(ShoppingListItem.checked == True)  # noqa: E712
    ).all()
    for row in rows:
        session.delete(row)
    session.commit()
    return {"removed": len(rows)}


# --------------------------------------------------------------------------- #
# Restock actions
# --------------------------------------------------------------------------- #
@router.post("/insights/restock/actions")
def restock_action(data: RestockActionIn, session: Session = Depends(get_session)):
    """Act on a restock suggestion.

    dismiss      never suggest this item again (undoable)
    snooze       hide it for ``days`` (default 7)
    bought       already picked it up — hide for ``days`` (default 7)
    add_to_list  put it on the shopping list AND snooze the suggestion
    """
    name = _validate_name(data.name)
    key = normalize_key(name)
    days = data.days if data.days and 0 < data.days <= 365 else 7

    if data.action not in ("dismiss", "snooze", "bought", "add_to_list"):
        raise HTTPException(status_code=422,
                            detail="action must be dismiss, snooze, bought or add_to_list.")

    added_to_list = False
    if data.action == "add_to_list":
        add_shopping_item(ShoppingItemIn(name=name), session)
        # Re-fetch: add_shopping_item committed; mark the row's origin.
        rows = session.exec(
            select(ShoppingListItem).where(ShoppingListItem.checked == False)  # noqa: E712
        ).all()
        for row in rows:
            if normalize_key(row.name) == key:
                row.source = "restock"
        added_to_list = True

    action = "dismissed" if data.action == "dismiss" else "snoozed"
    until = None if data.action == "dismiss" else datetime.now() + timedelta(days=days)

    existing = session.get(RestockAction, key)
    if existing:
        existing.action = action
        existing.until = until
        existing.created_at = datetime.now()
    else:
        session.add(RestockAction(name_key=key, action=action, until=until))
    session.commit()
    return {"status": "ok", "name": name, "action": action,
            "until": until.isoformat() if until else None, "added_to_list": added_to_list}


@router.delete("/insights/restock/actions/{name}")
def undo_restock_action(name: str, session: Session = Depends(get_session)):
    """Undo a dismiss/snooze so the item can be suggested again."""
    row = session.get(RestockAction, normalize_key(name))
    if row is None:
        raise HTTPException(status_code=404, detail="No action recorded for this item.")
    session.delete(row)
    session.commit()
    return {"status": "ok"}


@router.get("/insights/restock/actions")
def list_restock_actions(session: Session = Depends(get_session)):
    """Currently hidden suggestions (for an 'undo' UI)."""
    now = datetime.now()
    rows = session.exec(select(RestockAction).limit(_MAX_LIST_ROWS)).all()
    return [r for r in rows if r.action == "dismissed" or (r.until and r.until > now)]


# --------------------------------------------------------------------------- #
# Pantry
# --------------------------------------------------------------------------- #
@router.get("/pantry")
def get_pantry(session: Session = Depends(get_session)):
    rows = session.exec(
        select(PantryItem).order_by(PantryItem.name).limit(_MAX_LIST_ROWS)
    ).all()
    return rows


@router.post("/pantry")
def add_pantry_item(data: PantryItemIn, session: Session = Depends(get_session)):
    name = _validate_name(data.name)
    quantity = _validate_qty(data.quantity)
    key = normalize_key(name)

    existing = session.exec(select(PantryItem).where(PantryItem.name_key == key)).first()
    if existing:
        existing.quantity = round(existing.quantity + quantity, 2)
        existing.updated_at = datetime.now()
        session.commit()
        session.refresh(existing)
        return existing

    row = PantryItem(name=name, name_key=key, quantity=quantity,
                     unit=(data.unit or None), category=(data.category or None))
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


@router.patch("/pantry/{item_id}")
def update_pantry_item(item_id: int, data: PantryItemUpdate,
                       session: Session = Depends(get_session)):
    row = session.get(PantryItem, item_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Pantry item not found.")
    if data.name is not None:
        row.name = _validate_name(data.name)
        row.name_key = normalize_key(row.name)
    if data.quantity is not None:
        if not (0 <= data.quantity < 10000):
            raise HTTPException(status_code=422, detail="Quantity must be between 0 and 10000.")
        row.quantity = float(data.quantity)
    if data.unit is not None:
        row.unit = data.unit.strip()[:20] or None
    if data.category is not None:
        row.category = data.category.strip()[:60] or None
    row.updated_at = datetime.now()
    session.commit()
    session.refresh(row)
    return row


@router.delete("/pantry/{item_id}")
def delete_pantry_item(item_id: int, session: Session = Depends(get_session)):
    row = session.get(PantryItem, item_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Pantry item not found.")
    session.delete(row)
    session.commit()
    return {"status": "deleted"}


@router.post("/pantry/from-receipt/{receipt_id}")
def pantry_from_receipt(receipt_id: int, session: Session = Depends(get_session)):
    """Seed/refresh the pantry from a receipt's line items (skips Pfand etc.)."""
    receipt = session.get(Receipt, receipt_id)
    if receipt is None:
        raise HTTPException(status_code=404, detail="Receipt not found.")
    skipped_categories = {"Pfand", "Gutscheine & Rabatte"}
    added, bumped = 0, 0
    items = session.exec(select(Item).where(Item.receipt_id == receipt_id)).all()
    for item in items:
        if item.category in skipped_categories or item.price_total < 0:
            continue
        key = normalize_key(item.name)
        existing = session.exec(select(PantryItem).where(PantryItem.name_key == key)).first()
        if existing:
            existing.quantity = round(existing.quantity + (item.quantity or 1.0), 2)
            existing.updated_at = datetime.now()
            bumped += 1
        else:
            session.add(PantryItem(name=item.name, name_key=key,
                                   quantity=item.quantity or 1.0,
                                   category=item.category))
            added += 1
    session.commit()
    return {"added": added, "updated": bumped}
