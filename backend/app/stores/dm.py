"""DM Drogerie adapter.

DM eBons carry a text layer but no clean structured fields, so this adapter
routes the extracted text through the configured LLM (Ollama / OpenAI / Gemini)
to turn it into JSON.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime

from ..llm import complete
from .base import ParsedItem, ParsedReceipt, StoreAdapter

logger = logging.getLogger(__name__)

_PROMPT = """
You are an expert data extraction assistant.
Analyze the following raw text from a German supermarket receipt and extract the data into a strict JSON format.

CRITICAL RULES:
1. Do not include taxes, pfand, or card payment info in the items array.
2. Ignore the last number of each line, this is not the amount. The amount is either 1 or is marked with 2x, 3x, 4x, etc.
3. USE DOTS (.) FOR DECIMALS, NOT COMMAS (,). (e.g. 31.35 instead of 31,35)
4. Amounts and subTotals MUST be numbers, not strings.
5. Return ONLY the raw JSON object. Do not wrap it in ```json markdown blocks. Do not add any conversational text.

EXPECTED JSON FORMAT:
{
    "store_name": "DM Drogerie",
    "datetime_local": "2023-04-11T18:44:00",
    "total": 31.35,
    "items": [
        {"name": "Item Name", "amount": 1.0, "subTotal": 0.00}
    ]
}

RECEIPT TEXT TO ANALYZE:

"""


def _to_float(value) -> float:
    if isinstance(value, str):
        return float(value.replace(",", "."))
    return float(value)


class DmAdapter(StoreAdapter):
    key = "dm"
    display_name = "DM"

    def matches(self, text: str, filename: str) -> bool:
        return "dm-drogerie" in text or "dm " in text

    def parse(self, file_path: str, text: str | None = None) -> ParsedReceipt:
        if text is None:
            from ..pdf_utils import extract_text_from_pdf
            text = extract_text_from_pdf(file_path)

        data = self._llm_extract(text, file_path)

        # DM receipts carry no clean transaction id; the download filename embeds
        # the eBon UUID — extract it explicitly. (Some downloaded filenames carry
        # an extra suffix after the UUID, e.g. a _2026 year, so taking the last
        # "_" segment yields "2026" for every such file and dedupe then silently
        # drops all but the first.)
        stem = os.path.splitext(os.path.basename(file_path))[0]
        uuid_match = re.search(
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", stem
        )
        transaction_id = uuid_match.group(0) if uuid_match else stem

        items = [
            ParsedItem(
                name=line.get("name", "Unknown"),
                price_total=_to_float(line.get("subTotal", line.get("price", 0.0))),
                quantity=_to_float(line.get("amount", 1.0)) or 1.0,
            )
            for line in data.get("items", [])
        ]

        return ParsedReceipt(
            store_key=self.key,
            store_name=data.get("store_name", "DM Drogerie"),
            store_address=None,  # not reliably present in the OCR text
            store_id=None,
            date=self._parse_date(data.get("datetime_local"), file_path),
            total=_to_float(data.get("total", 0.0)),
            transaction_id=transaction_id,
            items=items,
            raw_data=data,
        )

    def _llm_extract(self, text: str, file_path: str) -> dict:
        logger.info("Routing to extraction LLM for %s", file_path)
        try:
            raw = complete(_PROMPT + text, temperature=0.0)

            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()

            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if not match:
                logger.error("No JSON object in LLM response for %s:\n%s", file_path, raw)
                return {}
            return json.loads(match.group(0))
        except Exception as e:
            logger.error("OCR parsing failed for %s: %s", file_path, e)
            return {}

    @staticmethod
    def _parse_date(raw_datetime, file_path: str) -> datetime:
        if raw_datetime:
            try:
                return datetime.fromisoformat(raw_datetime).replace(tzinfo=None)
            except Exception as e:
                logger.warning("Failed to parse DM date '%s' (%s): %s", raw_datetime, file_path, e)
        return datetime.now()
