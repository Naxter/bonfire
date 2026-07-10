import logging
from contextlib import nullcontext

from sqlmodel import Session, select

from .categories import VALID_CATEGORIES
from .database import engine
from .llm import complete
from .models import CategoryMap, Item, Product

logger = logging.getLogger(__name__)


def predict_category_llm(item_name: str) -> str:
    """Ask the configured LLM to categorize the grocery item."""

    prompt = f"""
    You are a strict data categorization bot for German supermarket receipts.
    Categorize the following receipt item into exactly ONE of these categories:
    {', '.join(VALID_CATEGORIES)}

    Item Name: "{item_name}"

    Rules:
    - Return ONLY the exact category name from the list. No punctuation or explanations.
    - 'MIWA' means Mineralwasser -> 'Getränke'.
    - 'RABATT', 'GUTSCHEIN', 'AMAZON' -> 'Gutscheine & Rabatte'.
    - 'CHIPS', 'NIC NACS', 'NÜSSE', 'MANDELN' -> 'Süßwaren & Snacks'.
    - 'PESTO', 'KETCHUP', 'MAYO', 'SALZ', 'ÖL' -> 'Gewürze, Saucen & Öle'.
    - 'NUDELN', 'REIS', 'MEHL', 'HAFERFLOCKEN' -> 'Nährmittel & Vorrat'.
    - 'PIZZA', 'FRZ' -> 'Tiefkühlprodukte'.
    - 'TASCHENTÜCHER', 'DEO' -> 'Drogerie & Kosmetik'.
    """

    try:
        predicted = complete(prompt)
        predicted = predicted.replace('"', '').replace("'", '').replace('.', '').strip()

        if predicted in VALID_CATEGORIES:
            return predicted
        else:
            logger.warning("LLM returned unknown category '%s'. Defaulting to Sonstiges.", predicted)
            return "Sonstiges"

    except Exception as e:
        logger.error("LLM error for item '%s': %s", item_name, e)
        return "Uncategorized"


def get_category(item_name: str, session: Session | None = None) -> str:
    """Return the category for an item, caching new predictions in CategoryMap.

    Pass an existing ``session`` to avoid opening a new connection per item
    (the parser calls this in a per-line loop).
    """
    key = item_name.lower().strip()

    # Reuse the caller's session if given; otherwise open a scoped one.
    ctx = nullcontext(session) if session is not None else Session(engine)
    with ctx as sess:
        statement = select(CategoryMap).where(CategoryMap.item_key == key)
        result = sess.exec(statement).first()

        if result:
            return result.category

        logger.info("New item: '%s'. Asking LLM...", item_name)
        predicted = predict_category_llm(item_name)

        sess.add(CategoryMap(item_key=key, category=predicted))
        sess.commit()

        return predicted


def _category_for(item_name: str) -> str:
    """Fresh category for a name, mirroring the ingest pipeline's Pfand rule."""
    if "pfand" in item_name.lower():
        return "Pfand"
    return predict_category_llm(item_name)


def recategorize(scope: str = "missing") -> dict:
    """Re-run the LLM over existing items so prompt/model improvements take effect.

    ``scope="missing"`` (default) only revisits items currently ``Uncategorized``
    or ``Sonstiges`` — cheap, fixes past failures. ``scope="all"`` revisits every
    item (one LLM call per distinct name — can be slow/costly).

    Manual overrides (``CategoryMap.is_locked``) are never changed.
    """
    with Session(engine) as session:
        locked = {
            m.item_key
            for m in session.exec(select(CategoryMap).where(CategoryMap.is_locked == True)).all()  # noqa: E712
        }

        if scope == "all":
            names = session.exec(select(Item.name).distinct()).all()
        else:
            names = session.exec(
                select(Item.name).where(Item.category.in_(["Uncategorized", "Sonstiges"])).distinct()
            ).all()

        names_updated = 0
        items_updated = 0
        skipped_locked = 0

        for name in names:
            key = name.lower().strip()
            if key in locked:
                skipped_locked += 1
                continue

            new_cat = _category_for(name)

            mapping = session.get(CategoryMap, key)
            if mapping:
                mapping.category = new_cat
            else:
                session.add(CategoryMap(item_key=key, category=new_cat))

            # Keep the canonical product in sync with the new category.
            product = session.exec(select(Product).where(Product.name_key == key)).first()
            if product and product.category != new_cat:
                product.category = new_cat

            changed = False
            for item in session.exec(select(Item).where(Item.name == name)).all():
                if item.category != new_cat:
                    item.category = new_cat
                    items_updated += 1
                    changed = True
            if changed:
                names_updated += 1

        session.commit()

    result = {
        "scope": scope,
        "names_processed": len(names),
        "names_updated": names_updated,
        "items_updated": items_updated,
        "skipped_locked": skipped_locked,
    }
    logger.info("Recategorize done: %s", result)
    return result
