"""Download DM eBon PDFs via the dm-tech API.

DM has no mail-forwarding for receipts, so this works off a manually saved
copy of the "Meine eBons" overview page (DM_HTML_FILE): it extracts every
/ebons/<id> link and downloads each PDF with your bearer token. The token is
short-lived — grab a fresh one from the browser's dev tools when it expires.
"""

import os
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from loguru import logger

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

BEARER_TOKEN = os.getenv("DM_BEARER_TOKEN")

# Default download target is the backend inbox's DM folder, which the
# watcher/ingest pipeline reads from (anchored to this file, not the cwd).
_DEFAULT_INBOX = str(Path(__file__).resolve().parents[1] / "backend" / "data" / "inbox" / "dm")
HTML_FILE = os.getenv("DM_HTML_FILE", "dm.html")
DOWNLOAD_DIR = os.getenv("DM_DOWNLOAD_DIR", _DEFAULT_INBOX)


def extract_ebon_ids(html_path: str) -> list[str]:
    """Collect the eBon ids from every /ebons/<id> link in the saved page."""
    logger.info(f"Reading {html_path}...")
    try:
        with open(html_path, encoding="utf-8") as file:
            soup = BeautifulSoup(file.read(), "html.parser")
    except FileNotFoundError:
        logger.error(f"File {html_path!r} not found. Save the DM eBon overview page there first.")
        return []

    ids = set()
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if href.startswith("/ebons/"):
            ebon_id = href.removeprefix("/ebons/").strip()
            # Links may carry query params or fragments.
            ebon_id = ebon_id.split("?")[0].split("#")[0]
            ids.add(ebon_id)
    return sorted(ids)


def download_ebon(ebon_id: str, token: str) -> None:
    url = f"https://ebon-prod.services.dmtech.com/api/customer/ebons/{ebon_id}/download"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/pdf"}

    try:
        response = requests.get(url, headers=headers, timeout=(5, 30))
        response.raise_for_status()
        file_path = os.path.join(DOWNLOAD_DIR, f"dm_ebon_{ebon_id}.pdf")
        with open(file_path, "wb") as f:
            f.write(response.content)
        logger.info(f"Saved {file_path}")
    except requests.exceptions.HTTPError as err:
        logger.error(
            f"HTTP {err.response.status_code} for {ebon_id} — the bearer token may have expired."
        )
    except Exception:
        logger.exception(f"Could not download {ebon_id}.")


def main() -> None:
    if not BEARER_TOKEN:
        raise SystemExit("Missing DM_BEARER_TOKEN. Set it in the repo-root .env file.")

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    ebon_ids = extract_ebon_ids(HTML_FILE)
    if not ebon_ids:
        logger.info("No eBon ids found in the HTML.")
        return

    logger.info(f"Found {len(ebon_ids)} eBon(s). Downloading...")
    for ebon_id in ebon_ids:
        download_ebon(ebon_id, BEARER_TOKEN)
        # Be polite to the API — one request per second.
        time.sleep(1)
    logger.info("Done.")


if __name__ == "__main__":
    main()
