"""Mail scraper download rules.

The scraper decides what to download by comparing file *contents*, not names:
an eBon's filename only carries the subject's date and REWE names every
attachment alike, so two shops on one day collide on a single name. The old
name-only check skipped the second bon forever — it never reached the inbox,
so nothing downstream ever saw it."""

import importlib.util
from email.message import EmailMessage
from pathlib import Path

import pytest

_SCRAPER_PATH = Path(__file__).resolve().parents[2] / "email-scraper" / "scraper.py"


@pytest.fixture()
def scraper(tmp_path):
    """The scraper module with its inbox/archive pointed at a temp dir."""
    spec = importlib.util.spec_from_file_location("rewe_scraper", _SCRAPER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.INBOX_DIR = tmp_path / "inbox" / "rewe"
    module.ARCHIVE_DIR = tmp_path / "archive" / "rewe"
    module.INBOX_DIR.mkdir(parents=True)
    module.ARCHIVE_DIR.mkdir(parents=True)
    return module


def _mail(payload: bytes, filename: str = "REWE-ebon.pdf") -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = "WG: Dein REWE eBon vom 01.02.2025"
    msg.set_content("Dein eBon im Anhang.")
    msg.add_attachment(payload, maintype="application", subtype="pdf", filename=filename)
    return msg


def _inbox(scraper) -> list[str]:
    return sorted(p.name for p in scraper.INBOX_DIR.iterdir())


def test_date_tag_comes_from_the_subject(scraper):
    assert scraper.receipt_date_tag("WG: Dein REWE eBon vom 01.02.2025") == "01_02_2025"


def test_attachment_is_saved(scraper):
    assert scraper.save_pdf_attachments(_mail(b"%PDF-1.4 first"), "01_02_2025") == 1
    assert _inbox(scraper) == ["01_02_2025_REWE-ebon.pdf"]


def test_identical_attachment_is_not_downloaded_twice(scraper):
    scraper.save_pdf_attachments(_mail(b"%PDF-1.4 first"), "01_02_2025")
    assert scraper.save_pdf_attachments(_mail(b"%PDF-1.4 first"), "01_02_2025") == 0
    assert _inbox(scraper) == ["01_02_2025_REWE-ebon.pdf"]


def test_archived_copy_still_counts_as_downloaded(scraper):
    """Ingest moves files to the archive, so the check must look there too —
    otherwise every sweep re-downloads the whole mailbox."""
    scraper.save_pdf_attachments(_mail(b"%PDF-1.4 first"), "01_02_2025")
    for f in scraper.INBOX_DIR.iterdir():
        f.rename(scraper.ARCHIVE_DIR / f.name)

    assert scraper.save_pdf_attachments(_mail(b"%PDF-1.4 first"), "01_02_2025") == 0
    assert _inbox(scraper) == []


def test_second_shop_same_day_is_kept_alongside_the_first(scraper):
    """The regression: same subject date, same attachment name, different bon."""
    scraper.save_pdf_attachments(_mail(b"%PDF-1.4 morning shop"), "01_02_2025")
    assert scraper.save_pdf_attachments(_mail(b"%PDF-1.4 afternoon shop"), "01_02_2025") == 1
    assert _inbox(scraper) == ["01_02_2025_REWE-ebon-1.pdf", "01_02_2025_REWE-ebon.pdf"]


def test_second_shop_is_kept_once_the_first_is_archived(scraper):
    """How it actually fails in production: the first bon is long archived by
    the time the second mail is swept."""
    scraper.save_pdf_attachments(_mail(b"%PDF-1.4 morning shop"), "01_02_2025")
    for f in scraper.INBOX_DIR.iterdir():
        f.rename(scraper.ARCHIVE_DIR / f.name)

    assert scraper.save_pdf_attachments(_mail(b"%PDF-1.4 afternoon shop"), "01_02_2025") == 1
    assert _inbox(scraper) == ["01_02_2025_REWE-ebon-1.pdf"]
    # …and a re-sweep of both mails adds nothing.
    scraper.save_pdf_attachments(_mail(b"%PDF-1.4 morning shop"), "01_02_2025")
    assert scraper.save_pdf_attachments(_mail(b"%PDF-1.4 afternoon shop"), "01_02_2025") == 0
    assert _inbox(scraper) == ["01_02_2025_REWE-ebon-1.pdf"]


def test_third_shop_same_day_gets_its_own_name(scraper):
    for payload in (b"%PDF-1.4 one", b"%PDF-1.4 two", b"%PDF-1.4 three"):
        assert scraper.save_pdf_attachments(_mail(payload), "01_02_2025") == 1
    assert _inbox(scraper) == ["01_02_2025_REWE-ebon-1.pdf",
                               "01_02_2025_REWE-ebon-2.pdf",
                               "01_02_2025_REWE-ebon.pdf"]


def test_non_pdf_and_empty_attachments_are_skipped(scraper):
    assert scraper.save_pdf_attachments(_mail(b"GIF89a", filename="logo.gif"), "01_02_2025") == 0
    assert scraper.save_pdf_attachments(_mail(b"", filename="empty.pdf"), "01_02_2025") == 0
    assert _inbox(scraper) == []


def test_oversized_attachment_is_skipped(scraper, monkeypatch):
    monkeypatch.setattr(scraper, "MAX_ATTACHMENT_BYTES", 10)
    assert scraper.save_pdf_attachments(_mail(b"%PDF-1.4 far too long"), "01_02_2025") == 0
    assert _inbox(scraper) == []


def test_traversing_attachment_name_stays_in_the_inbox(scraper):
    """The directory part is stripped, so the write lands in the inbox."""
    evil = _mail(b"%PDF-1.4 x", filename="../../evil.pdf")
    assert scraper.save_pdf_attachments(evil, "01_02_2025") == 1
    assert _inbox(scraper) == ["01_02_2025_evil.pdf"]
