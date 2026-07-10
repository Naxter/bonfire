"""Store adapters.

Each supermarket is a self-contained adapter implementing StoreAdapter.
To add a store, drop a new module in this package and register its adapter in
``registry.ADAPTERS`` — nothing else in the codebase needs to change.
"""

from .base import ParsedItem, ParsedReceipt, StoreAdapter
from .registry import ADAPTERS, detect, get_adapter, list_stores, store_display_name

__all__ = [
    "ParsedItem",
    "ParsedReceipt",
    "StoreAdapter",
    "ADAPTERS",
    "detect",
    "get_adapter",
    "list_stores",
    "store_display_name",
]
