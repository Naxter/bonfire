"""The store-agnostic data contract and adapter interface.

Every store adapter turns a PDF into a normalized ``ParsedReceipt``. The ingest
pipeline only ever sees ``ParsedReceipt`` objects, so it contains zero
store-specific logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ParsedItem:
    name: str
    price_total: float
    quantity: float = 1.0
    tax_rate: str | None = None
    loyalty_qualified: bool = False

    @property
    def price_single(self) -> float:
        return self.price_total / self.quantity if self.quantity else self.price_total


@dataclass
class ParsedReceipt:
    store_key: str                     # canonical slug, e.g. "rewe" / "dm"
    store_name: str                    # human display name
    date: datetime
    total: float
    items: list[ParsedItem] = field(default_factory=list)
    store_address: str | None = None
    store_id: str | None = None
    transaction_id: str | None = None
    loyalty_program: str | None = None
    loyalty_details: dict[str, Any] = field(default_factory=dict)
    raw_data: dict[str, Any] = field(default_factory=dict)


class StoreAdapter(ABC):
    """Interface every store must implement.

    Subclasses set ``key`` (canonical slug) and ``display_name``, and implement
    ``matches`` (detection) and ``parse`` (extraction).
    """

    key: str = ""
    display_name: str = ""

    @abstractmethod
    def matches(self, text: str, filename: str) -> bool:
        """Return True if this adapter should handle the given receipt.

        ``text`` is the lower-cased first-page text of the PDF; ``filename`` is
        the base filename (useful when the text layer is empty/scanned).
        """
        raise NotImplementedError

    @abstractmethod
    def parse(self, file_path: str, text: str | None = None) -> ParsedReceipt:
        """Parse the PDF into a normalized ParsedReceipt.

        ``text`` is the already-extracted PDF text (passed in so the pipeline
        never has to read the file twice); adapters may ignore it and re-read
        if they need per-page or binary access.
        """
        raise NotImplementedError
