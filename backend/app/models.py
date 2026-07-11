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


class CategoryMap(SQLModel, table=True):
    item_key: str = Field(primary_key=True)
    category: str
    is_locked: bool = Field(default=False)


class MealProfile(SQLModel, table=True):
    """A meal-suggestion persona: the user-editable instruction block of the
    prompt. Built-ins (adult/toddler/family) are seeded at startup; their
    prompts may be edited but they can't be deleted, and their keys stay
    stable so the Telegram bot and existing URLs keep working."""
    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(index=True, unique=True)
    name: str
    prompt: str
    is_builtin: bool = False
