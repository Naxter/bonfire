"""Adapter registry — the single place stores are wired in.

Adding a store == importing its adapter and appending it to ADAPTERS.
Everything else (ingest, stats endpoints, the frontend store filter) is driven
off this list and the ``store_key`` it produces.
"""

from __future__ import annotations

import logging

from .base import StoreAdapter
from .dm import DmAdapter
from .rewe import ReweAdapter

logger = logging.getLogger(__name__)

# Order matters only for detection: the first adapter whose matches() returns
# True wins. Put more specific matchers before broader ones.
ADAPTERS: list[StoreAdapter] = [
    DmAdapter(),
    ReweAdapter(),
]


def detect(text: str, filename: str) -> StoreAdapter | None:
    """Return the adapter that should handle this receipt, or None."""
    lowered = (text or "").lower()
    for adapter in ADAPTERS:
        try:
            if adapter.matches(lowered, filename):
                return adapter
        except Exception as e:
            logger.warning("Adapter %s.matches() failed: %s", adapter.key, e)
    return None


def get_adapter(key: str) -> StoreAdapter | None:
    """Return the adapter for a canonical store key (e.g. from a folder name)."""
    for a in ADAPTERS:
        if a.key == key:
            return a
    return None


def list_stores() -> list[dict]:
    """[{key, display_name}] for the API / frontend store filter."""
    return [{"key": a.key, "display_name": a.display_name} for a in ADAPTERS]


def store_display_name(key: str) -> str:
    for a in ADAPTERS:
        if a.key == key:
            return a.display_name
    # Photographed receipts create ad-hoc keys (aldi, lidl, …) with no adapter;
    # title-case them for a presentable label.
    return key.title() if key else "Other"
