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
from .meal_profiles import BUILTIN_MEAL_PROFILES
from .models import Item, MealProfile, Receipt
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
# A lone top-up trip makes sad menus — widen the context below this many foods.
_MIN_TRIP_ITEMS = 10


def _resolve_profile(key: str) -> dict:
    """Profile by key from the DB, falling back to the built-in definitions."""
    key = (key or "adult").strip().lower()
    with Session(engine) as session:
        row = session.exec(select(MealProfile).where(MealProfile.key == key)).first()
        if row is None:
            row = session.exec(select(MealProfile).where(MealProfile.key == "adult")).first()
    if row is not None:
        return {"key": row.key, "name": row.name, "prompt": row.prompt}
    name, prompt = BUILTIN_MEAL_PROFILES.get(key, BUILTIN_MEAL_PROFILES["adult"])
    return {"key": key if key in BUILTIN_MEAL_PROFILES else "adult", "name": name, "prompt": prompt}


def _collect_foods(rows) -> dict[str, datetime]:
    """name -> newest purchase date, food items only."""
    newest: dict[str, datetime] = {}
    for name, cat, date in rows:
        if cat in _NON_FOOD or cat == "Uncategorized":
            continue
        if name not in newest or date > newest[name]:
            newest[name] = date
    return newest


def _meal_ingredients(context: str, days: int, max_items: int) -> tuple[list[str], dict]:
    """Candidate ingredients plus a description of the context used.

    ``trip``: the most recent shopping trip (latest receipt) of each store —
    the closest model of "what's in the house", widened with a ``days``-day
    window when the trips alone yield too few foods. ``days``: plain rolling
    window. Items are recency-ordered before capping so a big pantry doesn't
    get truncated alphabetically.
    """
    window_start = datetime.now() - timedelta(days=days)
    with Session(engine) as session:
        window_rows = session.exec(
            select(Item.name, Item.category, Receipt.date).join(Receipt)
            .where(Receipt.date >= window_start)
        ).all()

        trip_rows = []
        if context == "trip":
            last_per_store = (
                select(Receipt.store_key, func.max(Receipt.date).label("last_date"))
                .group_by(Receipt.store_key).subquery()
            )
            trip_rows = session.exec(
                select(Item.name, Item.category, Receipt.date).join(Receipt).join(
                    last_per_store,
                    (Receipt.store_key == last_per_store.c.store_key)
                    & (Receipt.date == last_per_store.c.last_date),
                )
            ).all()

    if context == "trip":
        newest = _collect_foods(trip_rows)
        widened = len(newest) < _MIN_TRIP_ITEMS
        if widened:
            for name, date in _collect_foods(window_rows).items():
                newest.setdefault(name, date)
        label = "your latest shopping trip per store"
        if widened:
            label += f", widened to the last {days} days"
        info = {"mode": "trip", "widened": widened, "label": label}
    else:
        newest = _collect_foods(window_rows)
        info = {"mode": "days", "widened": False, "label": f"the last {days} days"}

    foods = sorted(newest, key=newest.get, reverse=True)[:max_items]
    return foods, info


def meal_suggestions(profile: str = "adult", count: int = 3, quick: bool = False,
                     vegetarian: bool = False, context: str = "trip", days: int = 14,
                     avoid: list[str] | None = None, max_items: int = 60) -> dict:
    """Ask the LLM for meals mostly using food that's already in the house.

    ``profile`` selects a MealProfile (the persona/instruction block). The
    scaffold around it — ingredients, constraints, output schema — stays
    code-owned so user-edited prompts can't break response parsing.
    ``status`` in the result distinguishes an LLM failure from a genuinely
    empty pantry, so the UI never has to lie about why there are no meals.
    """
    count = max(1, min(int(count), 6))
    if context not in ("trip", "days"):
        context = "trip"
    prof = _resolve_profile(profile)
    foods, ctx = _meal_ingredients(context, days, max_items)
    base = {"profile": {"key": prof["key"], "name": prof["name"]},
            "context": ctx, "ingredients": foods}
    if not foods:
        return {**base, "status": "no_ingredients", "meals": []}

    constraints = []
    if quick:
        constraints.append("Each meal must be quick — about 20 minutes or less of active cooking.")
    if vegetarian:
        constraints.append("Every meal must be vegetarian (no meat, no fish).")
    constraint_line = (" ".join(constraints) + "\n") if constraints else ""

    avoid_line = ""
    if avoid:
        titles = "; ".join(t.strip() for t in avoid if t.strip())[:600]
        if titles:
            avoid_line = f"The user has already seen these and wants DIFFERENT ideas: {titles}.\n"

    prompt = f"""
You are a practical home-cooking assistant for a German household.
{prof["prompt"]}

Grocery items bought recently ({ctx["label"]}) — raw receipt names, interpret them sensibly:
{", ".join(foods)}

{constraint_line}{avoid_line}Prefer meals that mostly use the items above and use up perishables
(fresh produce, meat, dairy). Suggest {count} meals. Return ONLY JSON:
{{"meals": [{{"title": "...", "time_minutes": 25, "uses": ["items from the list above"],
"missing": ["ingredients still needed, [] if none"], "note": "one or two short lines",
"adaptation": "how to adapt the meal to the profile's requirements, or null when not applicable"}}]}}
"""
    try:
        data = extract_json_object(complete(prompt, temperature=0.4))
        meals = data.get("meals", []) if isinstance(data, dict) else []
    except Exception as e:
        logger.error("Meal suggestion failed: %s", e)
        return {**base, "status": "llm_error", "meals": []}
    return {**base, "status": "ok", "meals": meals[:count]}


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
