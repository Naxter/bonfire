"""Budget targets + the monthly budget report.

Targets turn the forecast into an actual budget: the report says how much is
left, and the alerts say which categories are over (or heading over)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..categories import VALID_CATEGORIES
from ..database import get_session
from ..insights import budget_report
from ..models import BudgetTarget
from ..schemas import BudgetTargetsIn
from ..settings import get_settings

router = APIRouter()

_MAX_TARGET = 1_000_000.0


@router.get("/insights/budget")
def get_budget():
    """Month-end spend forecast, targets, alerts and what-changed (tuned via settings)."""
    s = get_settings()
    return budget_report(history_months=int(s["budget.history_months"]),
                         anomaly_factor=float(s["budget.anomaly_factor"]))


@router.get("/budget/targets")
def get_targets(session: Session = Depends(get_session)):
    """Saved monthly targets: ``overall`` plus one entry per category."""
    rows = session.exec(select(BudgetTarget)).all()
    overall = next((r.amount for r in rows if r.category == ""), None)
    categories = {r.category: r.amount for r in rows if r.category}
    return {"overall": overall, "categories": categories}


@router.put("/budget/targets")
def put_targets(data: BudgetTargetsIn, session: Session = Depends(get_session)):
    """Upsert targets. ``null``/``0`` removes a target; categories must be
    canonical so a typo can't create a phantom budget line."""
    def validate_amount(label: str, amount: float | None) -> float | None:
        if amount is None or amount == 0:
            return None
        if not (0 < amount <= _MAX_TARGET):
            raise HTTPException(status_code=422,
                                detail=f"{label}: target must be between 0 and {_MAX_TARGET:.0f}.")
        return round(float(amount), 2)

    for category in data.categories:
        if category not in VALID_CATEGORIES:
            raise HTTPException(status_code=422,
                                detail=f"Unknown category {category!r}.")

    wanted: dict[str, float | None] = {"": validate_amount("overall", data.overall)}
    for category, amount in data.categories.items():
        wanted[category] = validate_amount(category, amount)

    for category, amount in wanted.items():
        row = session.get(BudgetTarget, category)
        if amount is None:
            if row is not None:
                session.delete(row)
        elif row is None:
            session.add(BudgetTarget(category=category, amount=amount))
        else:
            row.amount = amount
    session.commit()

    return get_targets(session)
