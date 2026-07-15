"""Daily-assistant endpoints: restock radar, meal ideas, Q&A, recategorize."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from ..categorizer import recategorize
from ..insights import answer_question, meal_suggestions, restock_report
from ..rate_limit import limiter
from ..settings import get_settings

router = APIRouter()


@router.get("/insights/restock")
def get_restock(horizon_days: int | None = None):
    """Predictive shopping list — items due (or overdue) for repurchase.
    Defaults come from the settings dialog; the query param still overrides."""
    s = get_settings()
    if horizon_days is not None:
        horizon_days = max(1, min(int(horizon_days), 60))
    return restock_report(
        min_purchases=int(s["restock.min_purchases"]),
        horizon_days=int(horizon_days if horizon_days is not None else s["restock.horizon_days"]),
    )


@router.get("/insights/meals")
@limiter.limit("10/minute")
def get_meals(request: Request, profile: str = "adult", audience: str | None = None,
              count: int = 3, quick: bool = False, vegetarian: bool = False,
              context: str = "trip", days: int = 14,
              avoid: list[str] = Query(default=[])):
    """LLM meal ideas from food that's already in the house.

    ``profile`` is a MealProfile key (``audience`` is a legacy alias).
    ``context``: "trip" (latest shopping trip per store, widened when thin)
    or "days" (rolling window). ``avoid``: titles the user already saw, so a
    refresh yields different ideas. A maintained pantry is always included.
    """
    days = max(3, min(int(days), 60))
    return meal_suggestions(profile=audience or profile, count=count, quick=quick,
                            vegetarian=vegetarian, context=context, days=days, avoid=avoid)


@router.get("/ask")
@limiter.limit("10/minute")
def get_ask(request: Request, q: str):
    """Natural-language question answered over the receipt data."""
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="Provide a question via ?q=")
    return answer_question(q.strip())


@router.post("/categories/recategorize")
@limiter.limit("3/hour")
def recategorize_items(request: Request, scope: str = "missing"):
    """Re-run the LLM over stored items so prompt/model changes take effect.

    ``scope=missing`` (default) revisits only Uncategorized/Sonstiges items;
    ``scope=all`` revisits everything. Locked manual overrides are preserved.
    """
    if scope not in ("missing", "all"):
        raise HTTPException(status_code=400, detail="scope must be 'missing' or 'all'")
    return recategorize(scope=scope)
