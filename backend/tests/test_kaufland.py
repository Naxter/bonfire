"""Kaufland API parsing, authentication, and Bonfire persistence tests."""

import json
from datetime import datetime
from pathlib import Path

import pytest
from app import ingest
from app.kaufland import (
    AuthClient,
    HttpResponse,
    KauflandApiError,
    KauflandConfig,
    KauflandDownloader,
    KauflandError,
    KauflandReceiptClient,
    extract_transactions,
    generate_pkce,
    parse_callback_input,
    transaction_to_parsed_receipt,
)
from app.models import Receipt
from app.schemas import ReceiptPublic
from sqlmodel import Session, select


def _transaction(**overrides):
    value = {
        "id": "tx-123",
        "timestamp": "2026-03-08T12:30:00Z",
        "sum": 349,
        "saving": 50,
        "currency": "EUR",
        "paymentType": "card",
        "store": {"id": "42", "name": "Kaufland Mitte", "street": "Hauptstr. 1", "city": "Berlin"},
        "positions": [
            {"name": "Milch", "total": 199, "quantity": 1, "taxRate": "7"},
            {"name": "Brot", "total": 150, "quantity": 1},
        ],
        "promotions": [{"desc": "Card saving", "saving": 50}],
        "cardNumber": "masked-card",
    }
    value.update(overrides)
    return value


def test_extract_transactions_accepts_known_wrappers_and_rejects_scalars():
    transaction = _transaction()
    assert extract_transactions({"data": {"transactions": [transaction]}}) == [transaction]
    assert extract_transactions([transaction]) == [transaction]
    with pytest.raises(KauflandApiError, match="transaction list"):
        extract_transactions({"data": "not-a-list"})


def test_transaction_to_parsed_receipt_converts_minor_units_and_keeps_raw_detail():
    parsed = transaction_to_parsed_receipt(_transaction())

    assert parsed.store_key == "kaufland"
    assert parsed.store_name == "Kaufland Mitte"
    assert parsed.store_address == "Hauptstr. 1, Berlin"
    assert parsed.date == datetime(2026, 3, 8, 12, 30)
    assert parsed.total == pytest.approx(3.49)
    assert parsed.currency == "EUR"
    assert parsed.payment_method == "card"
    assert [item.name for item in parsed.items] == ["Milch", "Brot"]
    assert [item.price_total for item in parsed.items] == pytest.approx([1.99, 1.50])
    assert parsed.loyalty_program == "Kaufland Card"
    assert parsed.raw_data["promotions"][0]["saving"] == 50


def test_transaction_parser_keeps_refunds_as_negative_items():
    parsed = transaction_to_parsed_receipt(
        _transaction(refundPositions=[{"name": "Pfand retour", "total": 50}])
    )

    assert parsed.items[-1].name == "Pfand retour"
    assert parsed.items[-1].price_total == pytest.approx(-0.50)


def test_callback_parser_validates_state_and_pkce():
    verifier, challenge = generate_pkce()
    assert verifier and challenge
    assert parse_callback_input("?code=abc&state=expected", expected_state="expected") == "abc"
    with pytest.raises(KauflandError, match="state"):
        parse_callback_input("?code=abc&state=wrong", expected_state="expected")


def test_environment_rejects_non_https_provider_urls(monkeypatch):
    monkeypatch.setenv("KAUFLAND_API_BASE_URL", "http://localhost:8080")
    with pytest.raises(KauflandError, match="HTTPS"):
        KauflandConfig.from_environment()


def test_auth_client_builds_pkce_authorization_url_and_refresh_request():
    class FakeHttp:
        def __init__(self):
            self.calls = []

        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            return HttpResponse(200, {}, b'{"access_token":"new","expires_in":300}')

    config = KauflandConfig(data_dir=Path("data"))
    http = FakeHttp()
    auth = AuthClient(config, http)
    url = auth.authorization_url(state="state", code_challenge="challenge")
    assert "code_challenge=challenge" in url
    token = auth.refresh("refresh-token")
    assert token.access_token == "new"
    assert http.calls[0][0] == "POST"
    assert b"refresh_token=refresh-token" in http.calls[0][2]["body"]


class _FakeReceiptClient:
    def __init__(self, pages):
        self.pages = iter(pages)
        self.calls = []

    def list_page(self, **kwargs):
        self.calls.append(kwargs)
        return next(self.pages)


def test_downloader_persists_normalized_receipt_and_raw_json(api_engine, tmp_path, monkeypatch):
    monkeypatch.setattr(ingest, "DATA_DIR", tmp_path)
    monkeypatch.setattr(ingest, "ARCHIVE_DIR", tmp_path / "archive")
    monkeypatch.setattr(ingest, "get_category", lambda name, session=None: "Sonstiges")
    config = KauflandConfig(
        data_dir=tmp_path / "kaufland", user_id="cidaas-user", page_size=20, max_retries=0
    )
    body = json.dumps({"transactions": [_transaction()]}).encode()
    client = _FakeReceiptClient([HttpResponse(200, {"Content-Type": "application/json"}, body)])

    result = KauflandDownloader(config, client).run()

    assert result["status"] == "complete"
    assert result["new_receipts"] == 1
    assert client.calls == [{"user_id": "cidaas-user", "start": 0, "limit": 20}]
    source = tmp_path / "archive" / "kaufland" / "tx-123.json"
    assert source.is_file()
    assert json.loads(source.read_text(encoding="utf-8"))["id"] == "tx-123"
    raw_page = next((config.data_dir / "raw").rglob("page_0000.json"))
    raw_page_data = json.loads(raw_page.read_text(encoding="utf-8"))
    assert raw_page_data["request"]["start"] == 0
    assert raw_page_data["body_sha256"]
    with Session(api_engine) as session:
        receipt = session.exec(select(Receipt)).one()
        assert receipt.extraction_source == "kaufland_api"
        assert receipt.source_path == "archive/kaufland/tx-123.json"
        assert receipt.raw_data["cardNumber"] == "masked-card"
        assert len(receipt.items) == 2
        assert ReceiptPublic.from_receipt(receipt).source_kind == "json"


def test_receipt_client_refreshes_once_after_401(monkeypatch, tmp_path):
    class FakeHttp:
        def __init__(self):
            self.calls = []

        def request(self, method, url, **kwargs):
            self.calls.append(kwargs["headers"]["Authorization"])
            status = 401 if len(self.calls) == 1 else 200
            return HttpResponse(status, {}, b"[]")

    class FakeTokens:
        def __init__(self):
            self.refreshed = 0

        def access_token(self):
            return "old" if not self.refreshed else "new"

        def force_refresh(self):
            self.refreshed += 1
            return "new"

    config = KauflandConfig(data_dir=tmp_path, user_id="user", max_retries=0)
    tokens = FakeTokens()
    response = KauflandReceiptClient(config, FakeHttp(), tokens, sleeper=lambda _: None).list_page(
        user_id="user", start=0, limit=20
    )
    assert response.status == 200
    assert tokens.refreshed == 1
