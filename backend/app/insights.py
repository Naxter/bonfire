"""Higher-level insights derived from the receipt data + LLM.

Powers the "daily assistant" features, exposed as API endpoints and consumed by
both the dashboard and the Telegram bot:

  * restock_report   — predictive shopping list from purchase cadence  (#2)
  * budget_report    — month-end forecast + category anomalies          (#8)
  * meal_suggestions — recipe ideas from recent purchases (LLM)         (#6)
  * answer_question  — natural-language Q&A over the data (guarded SQL) (#5)
"""

from __future__ import annotations

import calendar
import logging
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import mean

from sqlmodel import Session, func, select

from .database import SQLITE_PATH, engine
from .llm import complete
from .models import Item, Receipt
from .receipt_json import extract_json_object

logger = logging.getLogger(__name__)

# Categories that aren't things you "run out of" / shouldn't drive restock or meals.
_NON_CONSUMABLE = {"Pfand", "Gutscheine & Rabatte"}
_NON_FOOD = _NON_CONSUMABLE | {"Haushalt & Non-Food", "Drogerie & Kosmetik"}


# --------------------------------------------------------------------------- #
# #2  Restock radar
# --------------------------------------------------------------------------- #
def restock_report(min_purchases: int = 3, horizon_days: int = 3, max_interval_days: int = 100,
                   max_overdue_factor: float = 2.0) -> list[dict]:
    """Items likely due (or overdue) for repurchase, based on how regularly you
    buy them. Returns those due within ``horizon_days``, most overdue first.

    Items overdue by more than ``max_overdue_factor`` × their usual interval are
    treated as abandoned (fell out of rotation) and skipped."""
    with Session(engine) as session:
        rows = session.exec(
            select(Item.name, Item.category, Receipt.date).join(Receipt)
        ).all()

    per_item: dict[str, list] = defaultdict(list)
    category: dict[str, str] = {}
    for name, cat, date in rows:
        if cat in _NON_CONSUMABLE:
            continue
        per_item[name].append(date)
        category[name] = cat

    today = datetime.now().date()
    due = []
    for name, dates in per_item.items():
        days = sorted({d.date() for d in dates})  # one purchase per calendar day
        if len(days) < min_purchases:
            continue
        intervals = [(days[i] - days[i - 1]).days for i in range(1, len(days))]
        avg_interval = mean(intervals)
        if avg_interval <= 0 or avg_interval > max_interval_days:
            continue

        last = days[-1]
        days_since = (today - last).days
        due_in = round(avg_interval - days_since)
        if due_in > horizon_days:
            continue
        if due_in < -avg_interval * max_overdue_factor:
            continue  # abandoned — fell out of rotation, not a real restock

        due.append({
            "name": name,
            "category": category.get(name, "Sonstiges"),
            "times_bought": len(days),
            "avg_interval_days": round(avg_interval, 1),
            "last_purchased": last.isoformat(),
            "due_in_days": due_in,
            "overdue": due_in < 0,
        })

    due.sort(key=lambda x: x["due_in_days"])
    return due


# --------------------------------------------------------------------------- #
# #8  Budget forecast + anomalies
# --------------------------------------------------------------------------- #
def budget_report(history_months: int = 6, anomaly_factor: float = 1.5) -> dict:
    """Project this month's spend from the current pace and flag categories
    running hot vs. their historical monthly average."""
    now = datetime.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    days_in_month = calendar.monthrange(now.year, now.month)[1]
    days_elapsed = now.day
    hist_start = month_start - timedelta(days=history_months * 31)

    def project(spent: float) -> float:
        return round(spent / days_elapsed * days_in_month, 2) if days_elapsed else 0.0

    with Session(engine) as session:
        month_total = session.exec(
            select(func.sum(Receipt.total_amount)).where(Receipt.date >= month_start)
        ).first() or 0.0

        cur_rows = session.exec(
            select(Item.category, func.sum(Item.price_total))
            .join(Receipt).where(Receipt.date >= month_start)
            .group_by(Item.category)
        ).all()

        # Historical spend per (month, category) to derive a per-category monthly average.
        hist_rows = session.exec(
            select(
                func.strftime("%Y-%m", Receipt.date),
                Item.category,
                func.sum(Item.price_total),
            ).join(Receipt)
            .where(Receipt.date >= hist_start, Receipt.date < month_start)
            .group_by(func.strftime("%Y-%m", Receipt.date), Item.category)
        ).all()

    hist_by_cat: dict[str, list] = defaultdict(list)
    for _month, cat, total in hist_rows:
        hist_by_cat[cat].append(float(total or 0.0))

    categories = []
    for cat, spent in cur_rows:
        spent = float(spent or 0.0)
        avg = mean(hist_by_cat[cat]) if hist_by_cat.get(cat) else 0.0
        projected = project(spent)
        delta_pct = round((projected - avg) / avg * 100, 1) if avg > 0 else None
        anomaly = avg >= 5 and projected > avg * anomaly_factor
        categories.append({
            "category": cat,
            "spent": round(spent, 2),
            "projected": projected,
            "avg_month": round(avg, 2),
            "delta_pct": delta_pct,
            "anomaly": anomaly,
        })
    categories.sort(key=lambda c: c["projected"], reverse=True)

    return {
        "month": now.strftime("%Y-%m"),
        "days_elapsed": days_elapsed,
        "days_in_month": days_in_month,
        "spent_so_far": round(float(month_total), 2),
        "projected_total": project(float(month_total)),
        "categories": categories,
        "anomalies": [c for c in categories if c["anomaly"]],
    }


# --------------------------------------------------------------------------- #
# #6  Meal suggestions
# --------------------------------------------------------------------------- #
MEAL_AUDIENCES = ("adult", "toddler", "family")

_AUDIENCE_BLOCK = {
    "adult": "Suggest simple, tasty dinners for adults.",
    "toddler": (
        "Suggest meals suitable for a 1-year-old (12+ months). Follow these safety "
        "rules STRICTLY:\n"
        "- NO added salt and NO added sugar (a baby's kidneys can't handle much salt).\n"
        "- No honey.\n"
        "- Avoid choking hazards: quarter grapes and cherry tomatoes lengthwise, no "
        "whole nuts (only smooth nut butter thinly spread), no hard raw chunks — cook "
        "vegetables until soft.\n"
        "- Soft, mashable or easy-to-chew, finger-food-friendly textures.\n"
        "Favour iron-rich, nutrient-dense ingredients and keep it very simple. In each "
        "meal's note, give a short prep/safety tip (texture, how to cut) and flag common "
        "allergens (egg, dairy, wheat, nuts, fish) if the meal contains them."
    ),
    "family": (
        "Suggest ONE meal the whole family can eat together, easily adapted for a "
        "1-year-old. Cook once. For the baby's portion: set some aside BEFORE adding "
        "salt, sugar or spicy seasoning, and mash or cut it into soft small pieces; "
        "avoid choking hazards (quarter grapes/tomatoes, no whole nuts). In each meal's "
        "note, explain briefly how to adapt that meal for the 1-year-old."
    ),
}


def meal_suggestions(days: int = 10, count: int = 3, audience: str = "adult",
                     quick: bool = False, vegetarian: bool = False, max_items: int = 60) -> dict:
    """Ask the LLM for meals mostly using recently bought food items, tailored to
    the chosen audience (adult / toddler / family) and optional constraints."""
    audience = (audience or "adult").lower()
    if audience not in MEAL_AUDIENCES:
        audience = "adult"

    since = datetime.now() - timedelta(days=days)
    with Session(engine) as session:
        rows = session.exec(
            select(Item.name, Item.category).join(Receipt)
            .where(Receipt.date >= since).distinct()
        ).all()

    foods = [name for name, cat in rows if cat not in _NON_FOOD]
    foods = sorted(set(foods))[:max_items]
    if not foods:
        return {"ingredients": [], "meals": [], "audience": audience}

    constraints = []
    if quick:
        constraints.append("Each meal must be quick — about 20 minutes or less of active cooking.")
    if vegetarian:
        constraints.append("Every meal must be vegetarian (no meat, no fish).")
    constraint_line = (" ".join(constraints) + "\n") if constraints else ""

    prompt = f"""
You are a practical home-cooking assistant for a German household with a 1-year-old.
Grocery items bought in the last {days} days:
{", ".join(foods)}

{_AUDIENCE_BLOCK[audience]}
{constraint_line}Prefer meals that mostly use the items above and use up perishables
(fresh produce, meat, dairy). Suggest {count} meals. Return ONLY JSON:
{{"meals": [{{"title": "...", "uses": ["item", "item"], "note": "one or two short lines"}}]}}
"""
    try:
        data = extract_json_object(complete(prompt, temperature=0.3))
        meals = data.get("meals", []) if isinstance(data, dict) else []
    except Exception as e:
        logger.error("Meal suggestion failed: %s", e)
        meals = []

    return {"ingredients": foods, "meals": meals, "audience": audience}


# --------------------------------------------------------------------------- #
# #5  Natural-language Q&A  (guarded read-only SQL)
# --------------------------------------------------------------------------- #
_SCHEMA_DOC = """
SQLite schema (grocery receipts):
  receipt(id, store_name, store_key, date [ISO datetime], total_amount)
  item(id, receipt_id -> receipt.id, name, category, price_total, price_single, quantity)
Notes: money in EUR; join item.receipt_id = receipt.id; category is a German label
(e.g. 'Getränke', 'Obst & Gemüse', 'Fleisch, Fisch & Veggie').
Today is {today}.
"""

_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|ATTACH|DETACH|PRAGMA|REPLACE|VACUUM|"
    r"TRUNCATE|GRANT|REINDEX)\b",
    re.IGNORECASE,
)


# The only tables the generated SQL may touch (plus its own CTE names).
_ALLOWED_TABLES = {"receipt", "item"}


def _sanitize_sql(sql: str) -> str | None:
    """Return a safe single read-only SELECT, or None if it looks unsafe."""
    s = sql.strip()
    if "```" in s:
        s = s.split("```")[1] if s.count("```") >= 2 else s.replace("```", "")
        s = re.sub(r"^sql", "", s.strip(), flags=re.IGNORECASE).strip()
    s = s.rstrip(";").strip()
    if ";" in s:  # reject multiple statements
        return None
    if "--" in s or "/*" in s:  # reject comment sequences
        return None
    if not re.match(r"(?is)^\s*(SELECT|WITH)\b", s):
        return None
    if _FORBIDDEN.search(s):
        return None
    # Identifier allowlist: every FROM/JOIN target must be a known table or a
    # CTE the statement itself defines (blocks sqlite_master, pragma_*, etc.).
    cte_pattern = r"(?is)(?:\bwith\s+(?:recursive\s+)?|,\s*)([A-Za-z_]\w*)\s+as\s*\("
    ctes = {m.lower() for m in re.findall(cte_pattern, s)}
    for target in re.findall(r"(?is)\b(?:from|join)\s+([A-Za-z_]\w*)", s):
        if target.lower() not in _ALLOWED_TABLES | ctes:
            return None
    return s


def answer_question(question: str, row_limit: int = 200) -> dict:
    """Turn a natural-language question into a guarded SELECT, run it read-only,
    and have the LLM phrase the answer."""
    schema = _SCHEMA_DOC.format(today=datetime.now().strftime("%Y-%m-%d"))
    sql_prompt = (
        f"{schema}\nWrite ONE read-only SQLite SELECT that answers this question. "
        f"Return ONLY the SQL, no explanation.\nQuestion: {question}"
    )
    try:
        raw_sql = complete(sql_prompt, temperature=0.0)
    except Exception as e:
        logger.error("Ask: SQL generation failed: %s", e)
        return {"question": question, "error": "The language model is unavailable right now."}
    sql = _sanitize_sql(raw_sql)
    if not sql:
        # Log the raw model output server-side only — never reflect it to the client.
        logger.warning("Ask: rejected generated SQL for %r: %s", question, raw_sql.strip())
        return {"question": question, "error": "Could not build a safe query for that."}

    if not re.search(r"(?is)\blimit\b", sql):
        sql = f"{sql}\nLIMIT {row_limit}"

    try:
        conn = sqlite3.connect(f"file:{SQLITE_PATH}?mode=ro", uri=True)
        try:
            conn.execute("PRAGMA query_only = ON")  # second guard behind mode=ro
            conn.row_factory = sqlite3.Row
            cur = conn.execute(sql)
            cols = [c[0] for c in cur.description] if cur.description else []
            # fetchmany enforces the row cap even if the model supplied its own LIMIT.
            rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchmany(row_limit)]
        finally:
            conn.close()
    except sqlite3.Error as e:
        logger.warning("Ask: query failed for %r: %s (sql: %s)", question, e, sql)
        return {"question": question, "error": "That query could not be run against the data."}

    answer_prompt = (
        f"Question: {question}\n"
        f"SQL result rows (JSON): {rows[:50]}\n"
        f"Answer the question in one or two short sentences, in the user's language. "
        f"Include concrete numbers with a € sign where relevant."
    )
    try:
        answer = complete(answer_prompt, temperature=0.2)
    except Exception as e:
        logger.error("Answer phrasing failed: %s", e)
        answer = None

    # NOTE: no "sql" field — generated SQL stays server-side (information disclosure).
    return {"question": question, "rows": rows, "answer": answer}
