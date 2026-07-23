"""Client-facing request/response models shared by the routers."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import SQLModel

from .models import Receipt


class ReceiptPublic(SQLModel):
    """Client-facing receipt: omits raw_data / loyalty_details / transaction_id
    (full parsed eBon incl. payment + loyalty info stays server-side)."""
    id: int
    store_name: str
    store_key: str
    store_address: str | None = None
    date: datetime
    total_amount: float
    currency: str = "EUR"
    pdf_filename: str
    review_status: str = "ok"
    extraction_source: str = "pdf_adapter"
    parse_warnings: list[str] = []
    # Derived, never the raw path: whether /receipts/{id}/source has something
    # to serve, and how the UI should embed it.
    has_source: bool = False
    source_kind: str | None = None  # "pdf" | "image" | None

    @classmethod
    def from_receipt(cls, receipt: Receipt) -> ReceiptPublic:
        data = cls.model_validate(receipt)
        source = receipt.source_path or ""
        if source:
            data.has_source = True
            data.source_kind = "pdf" if source.lower().endswith(".pdf") else "image"
        return data


# ---- Receipt lifecycle -----------------------------------------------------
class ReceiptUpdate(SQLModel):
    store_name: str | None = None
    store_key: str | None = None
    date: str | None = None          # ISO datetime string
    total_amount: float | None = None
    currency: str | None = None


class ItemUpdate(SQLModel):
    name: str | None = None
    quantity: float | None = None
    price_total: float | None = None
    price_single: float | None = None
    category: str | None = None
    # How far a category change reaches: this line only, or every item of the
    # same product (+ the learned mapping for future imports).
    category_scope: str = "all"      # "all" | "item"


class ItemCreate(SQLModel):
    name: str
    quantity: float = 1.0
    price_total: float
    price_single: float | None = None
    category: str | None = None


class CategoryUpdate(SQLModel):
    item_name: str
    new_category: str
    scope: str = "all"               # "all" | "item"
    item_id: int | None = None       # required when scope == "item"


# ---- Budget ------------------------------------------------------------------
class BudgetTargetsIn(SQLModel):
    overall: float | None = None
    # None/0 clears a category's target — the UI sends every category each save.
    categories: dict[str, float | None] = {}


# ---- Planning ------------------------------------------------------------------
class ShoppingItemIn(SQLModel):
    name: str
    quantity: float = 1.0
    unit: str | None = None
    category: str | None = None


class ShoppingItemUpdate(SQLModel):
    name: str | None = None
    quantity: float | None = None
    unit: str | None = None
    checked: bool | None = None


class RestockActionIn(SQLModel):
    name: str
    action: str                      # dismiss | snooze | bought | add_to_list
    days: int | None = None          # snooze duration (default 7)


class PantryItemIn(SQLModel):
    name: str
    quantity: float = 1.0
    unit: str | None = None
    category: str | None = None


class PantryItemUpdate(SQLModel):
    name: str | None = None
    quantity: float | None = None
    unit: str | None = None
    category: str | None = None


# ---- Products ------------------------------------------------------------------
class ProductUpdate(SQLModel):
    display_name: str | None = None
    category: str | None = None
    brand: str | None = None
    size_value: float | None = None
    size_unit: str | None = None     # "g" | "ml" | "piece"


class ProductMergeIn(SQLModel):
    target_id: int
    source_ids: list[int]


class ProductSplitIn(SQLModel):
    name_key: str
