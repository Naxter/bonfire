"""Small PDF text helpers shared by the ingest pipeline and store adapters."""

import logging
import os

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

# Untrusted input bounds: receipts are tiny, so anything near these limits is
# junk or a decompression bomb — refuse instead of OOMing the Pi.
MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PAGES = 50
MAX_TEXT_CHARS = 2_000_000


def _check_size(file_path: str) -> None:
    if os.path.getsize(file_path) > MAX_PDF_BYTES:
        raise ValueError(f"PDF too large (> {MAX_PDF_BYTES // (1024 * 1024)} MB): {file_path}")


def extract_text_from_pdf(file_path: str) -> str:
    """Extract the text layer of a (digital) PDF, bounded in size/pages/output."""
    _check_size(file_path)
    doc = fitz.open(file_path)
    try:
        parts: list[str] = []
        total = 0
        for page in doc.pages(0, min(doc.page_count, MAX_PAGES)):
            t = page.get_text()
            total += len(t)
            parts.append(t)
            if total > MAX_TEXT_CHARS:
                logger.warning("PDF text truncated at %s chars: %s", MAX_TEXT_CHARS, file_path)
                break
        return "".join(parts)
    finally:
        doc.close()


def extract_first_page_text(file_path: str) -> str:
    """Extract just the first page's text — enough for store detection."""
    try:
        _check_size(file_path)
        doc = fitz.open(file_path)
        try:
            return doc[0].get_text() if doc.page_count else ""
        finally:
            doc.close()
    except Exception as e:
        logger.warning("Failed to read PDF text from %s: %s", file_path, e)
        return ""
