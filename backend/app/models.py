from datetime import datetime
from typing import Any

from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, Relationship, SQLModel


class Receipt(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    store_name: str
    store_key: str = Field(default="other", index=True)
    store_address: str | None = None
    store_id: str | None = None
    date: datetime = Field(index=True)
    total_amount: float
    currency: str = "EUR"
    transaction_id: str | None = None
    payment_method: str | None = None
    loyalty_program: str | None = None
    loyalty_details: dict[str, Any] = Field(default={}, sa_column=Column(JSON))
    raw_data: dict[str, Any] = Field(default={}, sa_column=Column(JSON))
    pdf_filename: str
    # sha256 of the source file — the robust dedup key (filenames can change,
    # REWE eBons carry no transaction id). Unique index in _run_migrations.
    content_hash: str | None = None
    # --- Data-trust layer -------------------------------------------------- #
    # ok            parsed cleanly by a deterministic store adapter
    # needs_review  vision-LLM import, or the line items don't add up
    # verified      a human looked at it and confirmed the numbers
    review_status: str = Field(default="ok", index=True)
    # Where the archived original lives, relative to backend/data (e.g.
    # "archive/rewe/xyz.pdf"). Lets the UI show the source next to the parse.
    source_path: str | None = None
    # Human-readable extraction problems ("items sum 12.30 ≠ total 14.10").
    parse_warnings: list[str] = Field(default=[], sa_column=Column(JSON))
    # "pdf_adapter" | "vision_llm" | "manual" — how the data was extracted.
    extraction_source: str = Field(default="pdf_adapter")
    items: list["Item"] = Relationship(back_populates="receipt")


class Product(SQLModel, table=True):
    """Canonical product: one row per normalized item name.

    Items reference it so analytics can survive name variants and a
    recategorization is a single-row update instead of the CategoryMap/items
    sync dance. ``name_key`` uses the same normalization as CategoryMap
    (lower + strip)."""
    id: int | None = Field(default=None, primary_key=True)
    name_key: str = Field(index=True, unique=True)
    display_name: str
    category: str = Field(index=True)
    # --- Identity beyond lower/strip -------------------------------------- #
    brand: str | None = None
    # Package size, parsed from the receipt name where possible ("JOGH. 500G"
    # → 500 g). Base units only: "g", "ml" or "piece" — so unit prices are
    # comparable across pack sizes and stores.
    size_value: float | None = None
    size_unit: str | None = None


class ProductAlias(SQLModel, table=True):
    """Alternate receipt spellings of a product (created by merging).

    Ingest resolves an incoming item name through this table first, so once
    two variants are merged every future import lands on the same product."""
    name_key: str = Field(primary_key=True)
    product_id: int = Field(foreign_key="product.id", index=True)


class Item(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    receipt_id: int = Field(foreign_key="receipt.id", index=True)
    product_id: int | None = Field(default=None, foreign_key="product.id", index=True)
    name: str = Field(index=True)
    clean_name: str
    category: str = Field(index=True)
    price_total: float
    price_single: float | None = None
    quantity: float = 1.0
    tax_rate: str | None = None
    is_discounted: bool = False
    loyalty_qualified: bool = False
    receipt: Receipt | None = Relationship(back_populates="items")


class ImportJob(SQLModel, table=True):
    """One tracked ingestion attempt (upload, mail fetch, watcher pickup…).

    The UI polls these instead of reloading the page: every import gets a
    visible lifecycle (queued → running → done/failed) and failures stay
    inspectable afterwards — the import/error history."""
    id: int | None = Field(default=None, primary_key=True)
    kind: str = Field(index=True)      # upload | mail_fetch | watcher | reprocess
    status: str = Field(default="queued", index=True)
    # queued | running | done | duplicate | needs_review | no_data | failed
    filename: str | None = None
    store_key: str | None = None
    receipt_id: int | None = Field(default=None, foreign_key="receipt.id")
    message: str | None = None         # short human-readable outcome
    error: str | None = None           # failure detail (safe to show in the UI)
    detail: dict[str, Any] = Field(default={}, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.now, index=True)
    finished_at: datetime | None = None


class BudgetTarget(SQLModel, table=True):
    """Monthly spending target. ``category=""`` is the overall budget;
    otherwise one row per canonical category."""
    category: str = Field(primary_key=True)
    amount: float


class ShoppingListItem(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    quantity: float = 1.0
    unit: str | None = None
    category: str | None = None
    product_id: int | None = Field(default=None, foreign_key="product.id")
    checked: bool = Field(default=False, index=True)
    source: str = "manual"             # manual | restock
    created_at: datetime = Field(default_factory=datetime.now)
    checked_at: datetime | None = None


class RestockAction(SQLModel, table=True):
    """User verdict on a restock suggestion, keyed by normalized item name.

    ``dismissed`` hides the item forever (until undone); ``snoozed`` hides it
    until ``until`` — also how "already bought" is stored (snoozed for one
    typical purchase interval)."""
    name_key: str = Field(primary_key=True)
    action: str                        # dismissed | snoozed
    until: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.now)


class PantryItem(SQLModel, table=True):
    """What's actually in the house — maintained by the user, optionally
    seeded from a receipt. Purchases can't track consumption, so this is the
    honest source for meal planning when the user keeps it up to date."""
    id: int | None = Field(default=None, primary_key=True)
    name: str
    name_key: str = Field(index=True, unique=True)
    quantity: float = 1.0
    unit: str | None = None
    category: str | None = None
    updated_at: datetime = Field(default_factory=datetime.now)


class CategoryMap(SQLModel, table=True):
    item_key: str = Field(primary_key=True)
    category: str
    is_locked: bool = Field(default=False)


class Setting(SQLModel, table=True):
    """App-level preference (the dashboard's settings dialog). Values are
    stored JSON-encoded; defaults and validation live in app/settings.py —
    the table only ever holds user overrides."""
    key: str = Field(primary_key=True)
    value: str


class MealProfile(SQLModel, table=True):
    """A meal-suggestion persona: the user-editable instruction block of the
    prompt. Built-ins (see meal_profiles.py) are seeded at startup; their
    prompts may be edited but they can't be deleted, and their keys stay
    stable so the Telegram bot and existing URLs keep working."""
    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(index=True, unique=True)
    name: str
    prompt: str
    is_builtin: bool = False
