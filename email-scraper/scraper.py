"""Fetch REWE eBon PDFs from a GMX mailbox into the backend inbox.

Connects via IMAP, finds mails from REWE_SENDER whose subject contains
REWE_SUBJECT, and saves their PDF attachments to backend/data/inbox/rewe/,
where the inbox watcher picks them up. Meant to run periodically (systemd
timer or the Docker `scraper` service).
"""

import email
import imaplib
import os
import re
from email.header import decode_header
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

# Ingest moves processed files from the inbox into the archive, so the
# "already downloaded" check must look in both — else every run re-downloads
# the entire mailbox. Paths are anchored to this file, not the cwd.
_DATA_DIR = Path(__file__).resolve().parents[1] / "backend" / "data"
INBOX_DIR = _DATA_DIR / "inbox" / "rewe"
ARCHIVE_DIR = _DATA_DIR / "archive" / "rewe"

MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024


def decode_subject(msg) -> str:
    """Return the decoded subject line (MIME-encoded subjects arrive as bytes)."""
    subject, encoding = decode_header(msg["Subject"])[0]
    if isinstance(subject, bytes):
        subject = subject.decode(encoding or "utf-8", errors="replace")
    return subject or ""


def receipt_date_tag(subject: str) -> str:
    """Filename prefix from the mail subject, e.g. '…eBon vom 01.02.2025' → '01_02_2025'.

    Keeps the historical naming scheme (subject's trailing date, dots to
    underscores) so the already-downloaded check still matches old archives.
    """
    match = re.search(r"(\d{2}\.\d{2}\.\d{4})\s*$", subject)
    tag = match.group(1) if match else subject[-10:]
    return tag.replace(".", "_")


def save_pdf_attachments(msg, date_tag: str) -> None:
    for part in msg.walk():
        if part.get_content_maintype() == "multipart" or part.get("Content-Disposition") is None:
            continue
        raw_name = part.get_filename()
        if not raw_name:
            continue
        # Never trust an attachment filename: reduce to a basename, strip
        # separators, and keep the write inside the inbox.
        safe = os.path.basename(raw_name).replace("\\", "_").replace("/", "_")
        if not safe.lower().endswith(".pdf"):
            logger.debug(f"Skipping non-PDF attachment {safe!r}.")
            continue
        file_name = f"{date_tag}_{safe}"
        base = INBOX_DIR.resolve()
        file_path = base / file_name
        if not file_path.resolve().is_relative_to(base):
            logger.warning(f"Rejected suspicious attachment name: {raw_name!r}")
            continue
        if file_path.is_file() or (ARCHIVE_DIR / file_name).is_file():
            logger.debug(f"File {file_name} already downloaded.")
            continue
        payload = part.get_payload(decode=True) or b""
        if len(payload) > MAX_ATTACHMENT_BYTES:
            logger.warning(f"Skipping oversized attachment {file_name!r}.")
            continue
        file_path.write_bytes(payload)
        logger.info(f"Saved {file_name}")


def fetch_ebons() -> None:
    username = os.getenv("GMX_USER")
    password = os.getenv("GMX_PASSWORD")
    imap_host = os.getenv("GMX_IMAP_HOST", "imap.gmx.net")
    sender = os.getenv("REWE_SENDER")
    search_subject = os.getenv("REWE_SUBJECT", "WG: Dein REWE eBon")

    if not username or not password:
        raise SystemExit("Missing GMX_USER / GMX_PASSWORD. Set them in the repo-root .env file.")
    if not sender:
        raise SystemExit("Missing REWE_SENDER. Set it in the repo-root .env file.")

    INBOX_DIR.mkdir(parents=True, exist_ok=True)

    # Socket timeout so a stalled peer can't hang the scrape loop.
    mail = imaplib.IMAP4_SSL(imap_host, port=993, timeout=30)
    try:
        mail.login(username, password)
        mail.select("inbox")

        _, messages = mail.search(None, "FROM", f'"{sender}"', f'(SUBJECT "{search_subject}")')
        mail_ids = messages[0].split()
        logger.info(f"{len(mail_ids)} matching mail(s) to check.")

        for mail_id in mail_ids:
            _, msg_data = mail.fetch(mail_id, "(RFC822)")
            for response_part in msg_data:
                if not isinstance(response_part, tuple):
                    continue
                msg = email.message_from_bytes(response_part[1])
                save_pdf_attachments(msg, receipt_date_tag(decode_subject(msg)))
        mail.close()
    finally:
        mail.logout()


if __name__ == "__main__":
    fetch_ebons()
