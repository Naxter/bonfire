"""Product identity: name cleanup, package-size parsing, unit prices, merging.

Receipt lines are noisy ("JOGH.NATUR 500G", "COLA 6X1,5L", "BIO EIER 10ER").
Lower/strip alone treats every spelling, size and multipack as its own
product, which makes price comparisons lie. This module adds the missing
identity layer:

  * ``parse_size``     — package size in a base unit (g / ml / piece)
  * ``clean_name``     — the name with the size tokens stripped
  * ``unit_price``     — price normalized to €/kg, €/l or €/piece
  * ``merge_products`` — collapse duplicate products, remembered via aliases
  * ``resolve_product``— alias-aware lookup used by the ingest pipeline
"""

from __future__ import annotations

import re

from sqlmodel import Session, select

from .models import Item, Product, ProductAlias

# --------------------------------------------------------------------------- #
# Size parsing
# --------------------------------------------------------------------------- #
# Factor to the base unit: weights → grams, volumes → millilitres.
_UNIT_FACTORS: dict[str, tuple[float, str]] = {
    "kg": (1000.0, "g"),
    "gr": (1.0, "g"),
    "g": (1.0, "g"),
    "l": (1000.0, "ml"),
    "ml": (1.0, "ml"),
    "cl": (10.0, "ml"),
}

_NUM = r"\d+(?:[.,]\d+)?"
_UNITS = r"kg|gr|g|ml|cl|l"  # longest first — "ml" must win over "l"

# "6X1,5L" / "2 x 250g" — multipacks multiply out to one total size.
_MULTIPACK_RE = re.compile(
    rf"(?<![\w,.])({_NUM})\s*[x×]\s*({_NUM})\s*({_UNITS})(?![\w%])", re.IGNORECASE
)
# "500G" / "0,75 l" — but not "1,5%" (fat content) and not "0,25 EUR" (Pfand).
_SIZE_RE = re.compile(
    rf"(?<![\w,.])({_NUM})\s*({_UNITS})(?![\w%])(?!\s*(?:eur|€))", re.IGNORECASE
)
# "10ER" / "6 STK" / "4 ST" / "10 STÜCK" — piece counts.
_PIECES_RE = re.compile(
    r"(?<![\w,.])(\d+)\s*(?:er(?:-?pack)?|stk|stck|stück|st)(?![\w%])", re.IGNORECASE
)


def _to_float(raw: str) -> float:
    return float(raw.replace(",", "."))


def parse_size(name: str) -> tuple[float, str] | None:
    """Extract the package size from a receipt name, in a base unit.

    Returns ``(value, unit)`` with unit one of ``g`` / ``ml`` / ``piece``,
    or None when the name carries no recognizable size. Multipacks are the
    most specific pattern and win outright; otherwise the LAST plain size
    wins — sizes usually trail the name ("JOGHURT NATUR 3,8% 500G")."""
    if not name:
        return None

    packs = list(_MULTIPACK_RE.finditer(name))
    if packs:
        m = packs[-1]
        count, each, unit = _to_float(m.group(1)), _to_float(m.group(2)), m.group(3).lower()
        factor, base = _UNIT_FACTORS[unit]
        return (round(count * each * factor, 3), base)

    sizes = list(_SIZE_RE.finditer(name))
    if sizes:
        m = sizes[-1]
        value, unit = _to_float(m.group(1)), m.group(2).lower()
        factor, base = _UNIT_FACTORS[unit]
        return (round(value * factor, 3), base)

    pieces = list(_PIECES_RE.finditer(name))
    if pieces:
        return (float(pieces[-1].group(1)), "piece")
    return None


def clean_name(name: str) -> str:
    """Receipt name minus size/multipack tokens, whitespace collapsed.

    Kept close to the original (no re-casing — abbreviations like "JOGH."
    would only get mangled); its job is a stable display/grouping label."""
    if not name:
        return name
    cleaned = _MULTIPACK_RE.sub(" ", name)
    cleaned = _SIZE_RE.sub(" ", cleaned)
    cleaned = _PIECES_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" -,.")
    return cleaned or name.strip()


# --------------------------------------------------------------------------- #
# Unit prices
# --------------------------------------------------------------------------- #
def unit_price(price: float, size_value: float | None, size_unit: str | None) -> dict | None:
    """Price per comparable unit: €/kg for weights, €/l for volumes, €/piece.

    Returns ``{"value": 2.38, "unit": "kg"}`` or None when the size is
    unknown (comparisons would be meaningless)."""
    if not size_value or size_value <= 0 or size_unit not in ("g", "ml", "piece"):
        return None
    if size_unit == "g":
        return {"value": round(price / size_value * 1000, 2), "unit": "kg"}
    if size_unit == "ml":
        return {"value": round(price / size_value * 1000, 2), "unit": "l"}
    return {"value": round(price / size_value, 2), "unit": "piece"}


# --------------------------------------------------------------------------- #
# Alias-aware resolution + merging
# --------------------------------------------------------------------------- #
def normalize_key(name: str) -> str:
    """The canonical product key — same normalization as CategoryMap."""
    return name.lower().strip()


def resolve_product(session: Session, name: str) -> Product | None:
    """Find the product for an item name, honoring merge aliases first."""
    key = normalize_key(name)
    alias = session.get(ProductAlias, key)
    if alias is not None:
        product = session.get(Product, alias.product_id)
        if product is not None:
            return product
    return session.exec(select(Product).where(Product.name_key == key)).first()


def merge_products(session: Session, target_id: int, source_ids: list[int]) -> dict:
    """Merge ``source_ids`` into ``target_id``.

    Items are re-pointed at the target; each source's name_key (and any
    aliases it already collected) becomes an alias of the target so future
    imports resolve to the merged product. Missing identity fields (brand,
    size) are inherited from the first source that has them. Sources are
    deleted. Caller commits."""
    target = session.get(Product, target_id)
    if target is None:
        raise ValueError("Target product not found.")

    moved_items = 0
    merged = []
    for sid in source_ids:
        if sid == target_id:
            continue
        source = session.get(Product, sid)
        if source is None:
            continue

        for item in session.exec(select(Item).where(Item.product_id == sid)).all():
            item.product_id = target_id
            moved_items += 1

        # The source's own key + everything already aliased to it.
        for alias in session.exec(
            select(ProductAlias).where(ProductAlias.product_id == sid)
        ).all():
            alias.product_id = target_id
        if session.get(ProductAlias, source.name_key) is None:
            session.add(ProductAlias(name_key=source.name_key, product_id=target_id))

        if target.brand is None and source.brand:
            target.brand = source.brand
        if target.size_value is None and source.size_value:
            target.size_value, target.size_unit = source.size_value, source.size_unit

        merged.append(source.name_key)
        session.delete(source)

    return {"target_id": target_id, "merged_keys": merged, "moved_items": moved_items}
