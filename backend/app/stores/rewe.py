"""REWE eBon adapter — wraps the `rewe-ebon-parser` library."""

from __future__ import annotations

import logging
import os
from datetime import datetime

from rewe_ebon_parser import parse_pdf_ebon

from .base import ParsedItem, ParsedReceipt, StoreAdapter

logger = logging.getLogger(__name__)


def _coerce_store_id(market) -> str | None:
    """rewe-ebon-parser may return `market` as a dict or a scalar id."""
    if isinstance(market, dict):
        for k in ("id", "marketId", "number"):
            if market.get(k):
                return str(market[k])
        return None
    return str(market) if market else None


def _parse_date(raw_datetime, file_path: str) -> datetime:
    if raw_datetime:
        try:
            return datetime.fromisoformat(raw_datetime).replace(tzinfo=None)
        except Exception as e:
            logger.warning("Failed to parse REWE date '%s' (%s): %s", raw_datetime, file_path, e)
    else:
        logger.warning("No datetime_local found in %s", file_path)
    return datetime.now()


class ReweAdapter(StoreAdapter):
    key = "rewe"
    display_name = "REWE"

    def matches(self, text: str, filename: str) -> bool:
        return "rewe" in text

    def parse(self, file_path: str, text: str | None = None) -> ParsedReceipt:
        data = parse_pdf_ebon(file_path) or {}

        market_address = data.get("marketAddress", {}) or {}
        store_address = f"{market_address.get('street', '')}, {market_address.get('city', '')}".strip(", ")

        loyalty = data.get("loyalty", {}) or {}
        program_name = loyalty.get("program")
        loyalty_details = loyalty.get("details", {}) or {}
        if not program_name and "payback" in data:
            program_name = "PAYBACK"
            loyalty_details = data.get("payback", {}) or {}

        items = []
        for line in data.get("items", []):
            price = line.get("subTotal", line.get("price", 0.0))
            qty = line.get("amount", 1.0) or 1.0
            items.append(ParsedItem(
                name=line.get("name", "Unknown"),
                price_total=price,
                quantity=qty,
                tax_rate=line.get("taxCategory", line.get("tax", "")),
                loyalty_qualified=bool(line.get("loyaltyProgramQualified", False)),
            ))

        return ParsedReceipt(
            store_key=self.key,
            # Display name for the dashboard — set REWE_STORE_NAME in .env to
            # show your local market's name instead of the generic chain name.
            store_name=os.getenv("REWE_STORE_NAME", "REWE"),
            store_address=store_address or None,
            store_id=_coerce_store_id(data.get("market")),
            date=_parse_date(data.get("datetime_local"), file_path),
            total=data.get("total", 0.0),
            transaction_id=data.get("transaction_id"),
            loyalty_program=program_name,
            loyalty_details=loyalty_details,
            items=items,
            raw_data=data,
        )
