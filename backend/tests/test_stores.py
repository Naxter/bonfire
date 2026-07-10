"""Tests for the store-adapter architecture.

Run from the backend/ directory:  pytest -q
"""

import glob
import os
from datetime import datetime

import pytest
from app.pdf_utils import extract_text_from_pdf
from app.stores import detect, registry
from app.stores.base import ParsedItem, ParsedReceipt, StoreAdapter
from app.stores.dm import DmAdapter
from app.stores.rewe import ReweAdapter

# Real REWE eBons shipped with the repo (…/data/emails/*REWE-eBon.pdf).
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_REWE_PDFS = sorted(glob.glob(os.path.join(_REPO_ROOT, "data", "emails", "*REWE-eBon.pdf")))


@pytest.mark.skipif(not _REWE_PDFS, reason="no sample REWE PDFs available")
def test_rewe_detection_and_parse():
    pdf = _REWE_PDFS[0]
    text = extract_text_from_pdf(pdf)

    adapter = detect(text, pdf)
    assert adapter is not None and adapter.key == "rewe"

    parsed = ReweAdapter().parse(pdf, text=text)
    assert parsed.store_key == "rewe"
    assert parsed.total > 0
    assert parsed.items, "expected at least one line item"
    # Regression: store_id must be a string, never the raw market dict.
    assert parsed.store_id is None or isinstance(parsed.store_id, str)
    assert isinstance(parsed.date, datetime)
    # price_single derives from price_total / quantity
    first = parsed.items[0]
    assert first.price_single == pytest.approx(first.price_total / (first.quantity or 1))


def test_dm_detection_is_string_based():
    dm = DmAdapter()
    assert dm.matches("kassenbon dm-drogerie markt gmbh", "x.pdf")
    assert not dm.matches("rewe markt gmbh", "x.pdf")


def test_registry_lists_registered_stores():
    keys = {s["key"] for s in registry.list_stores()}
    assert {"rewe", "dm"} <= keys


def test_new_store_needs_no_edits_elsewhere():
    """Adding an adapter makes it discoverable via the registry alone."""

    class LidlAdapter(StoreAdapter):
        key = "lidl"
        display_name = "Lidl"

        def matches(self, text, filename):
            return "lidl" in text

        def parse(self, file_path, text=None):
            return ParsedReceipt(
                store_key="lidl", store_name="Lidl",
                date=datetime.now(), total=1.0,
                items=[ParsedItem(name="X", price_total=1.0)],
            )

    original = list(registry.ADAPTERS)
    try:
        registry.ADAPTERS.append(LidlAdapter())
        assert registry.detect("kassenbon lidl gmbh", "x.pdf").key == "lidl"
        assert registry.store_display_name("lidl") == "Lidl"
        assert any(s["key"] == "lidl" for s in registry.list_stores())
    finally:
        registry.ADAPTERS[:] = original
