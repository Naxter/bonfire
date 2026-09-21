"""Kaufland digital-receipt API client and Bonfire importer.

Kaufland exposes receipt history as JSON behind a Cidaas OAuth/PKCE login.
This module keeps that provider-specific protocol at the edge of Bonfire:
transactions are converted into the existing ``ParsedReceipt`` contract, while
the complete provider transaction is archived in ``Receipt.raw_data`` and as a
JSON source file next to the normalized receipt.

The API details are intentionally isolated here so a later supermarket
integration can use a different client and payload without changing the
ingest, database, or dashboard code.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import stat
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .database import DATA_DIR
from .stores.base import ParsedItem, ParsedReceipt

LOGGER = logging.getLogger("bonfire.kaufland")


class KauflandError(RuntimeError):
    """Expected, user-actionable error from the Kaufland integration."""


class KauflandAuthenticationError(KauflandError):
    """The saved login is missing, expired, or was rejected."""


class KauflandApiError(KauflandError):
    """The receipt API returned an invalid or unsuccessful response."""


def _optional_env(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


def _https_url(value: str, name: str, *, expected_host: str | None = None) -> str:
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
        raise KauflandError(f"{name} must be an HTTPS URL without query or fragment")
    if expected_host and parsed.hostname != expected_host:
        raise KauflandError(f"{name} must use host {expected_host}")
    return value.rstrip("/")


def _atomic_write(path: Path, content: bytes, *, secret: bool = False) -> None:
    """Write a file without exposing a partial token or raw API response."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            if secret:
                os.chmod(temp_path, stat.S_IRUSR | stat.S_IWUSR)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        if secret:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _write_json(path: Path, value: Any, *, secret: bool = False) -> None:
    content = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _atomic_write(path, content, secret=secret)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        raise KauflandError(f"Could not read Kaufland data file: {path}") from exc


@dataclass(frozen=True)
class KauflandConfig:
    """Environment-backed settings for the Kaufland API integration."""

    data_dir: Path
    country: str = "DE"
    user_id: str | None = None
    app_version: str = "6.17.1"
    loyalty_client_id: str = "88207bfc-780b-400d-92ee-893ae72dab40"
    cidaas_client_id: str = "fb1b425b-ab2f-4140-aef9-20263b6cfa49"
    api_base_url: str = "https://p.crm-dynamics.schwarz"
    cidaas_base_url: str = "https://account.kaufland.com"
    userinfo_url: str = "https://account.kaufland.com/users-srv/userinfo"
    redirect_uri: str = "com.kaufland.kaufland://oauth/callback"
    oauth_version: str = "1.5.22"
    ui_locales: str = "de-DE"
    view_type: str | None = "login"
    preferred_store: str | None = None
    page_size: int = 20
    max_pages: int = 1000
    timeout_seconds: float = 30.0
    max_retries: int = 3

    @classmethod
    def from_environment(cls) -> KauflandConfig:
        data_dir = Path(_optional_env("KAUFLAND_DATA_DIR") or str(DATA_DIR / "kaufland")).expanduser()
        try:
            page_size = int(_optional_env("KAUFLAND_PAGE_SIZE") or "20")
            max_pages = int(_optional_env("KAUFLAND_MAX_PAGES") or "1000")
            timeout = float(_optional_env("KAUFLAND_TIMEOUT_SECONDS") or "30")
            retries = int(_optional_env("KAUFLAND_MAX_RETRIES") or "3")
        except ValueError as exc:
            raise KauflandError(
                "KAUFLAND_PAGE_SIZE, MAX_PAGES, TIMEOUT_SECONDS, and MAX_RETRIES must be numeric"
            ) from exc
        if not 1 <= page_size <= 500:
            raise KauflandError("KAUFLAND_PAGE_SIZE must be between 1 and 500")
        if not 1 <= max_pages <= 100_000:
            raise KauflandError("KAUFLAND_MAX_PAGES must be between 1 and 100000")
        if timeout <= 0 or not 0 <= retries <= 10:
            raise KauflandError("KAUFLAND_TIMEOUT_SECONDS must be positive and MAX_RETRIES must be 0-10")
        country = (_optional_env("KAUFLAND_COUNTRY") or "DE").upper()
        if len(country) != 2 or not country.isalpha():
            raise KauflandError("KAUFLAND_COUNTRY must be a two-letter country code")
        return cls(
            data_dir=data_dir,
            country=country,
            user_id=_optional_env("KAUFLAND_USER_ID"),
            app_version=_optional_env("KAUFLAND_APP_VERSION") or cls.app_version,
            loyalty_client_id=_optional_env("KAUFLAND_LOYALTY_CLIENT_ID") or cls.loyalty_client_id,
            cidaas_client_id=_optional_env("KAUFLAND_CIDAAS_CLIENT_ID") or cls.cidaas_client_id,
            api_base_url=_https_url(
                _optional_env("KAUFLAND_API_BASE_URL") or cls.api_base_url,
                "KAUFLAND_API_BASE_URL",
                expected_host="p.crm-dynamics.schwarz",
            ),
            cidaas_base_url=_https_url(
                _optional_env("KAUFLAND_CIDAAS_BASE_URL") or cls.cidaas_base_url,
                "KAUFLAND_CIDAAS_BASE_URL",
                expected_host="account.kaufland.com",
            ),
            userinfo_url=_https_url(
                _optional_env("KAUFLAND_USERINFO_URL") or cls.userinfo_url,
                "KAUFLAND_USERINFO_URL",
                expected_host="account.kaufland.com",
            ),
            redirect_uri=_optional_env("KAUFLAND_REDIRECT_URI") or cls.redirect_uri,
            oauth_version=_optional_env("KAUFLAND_OAUTH_VERSION") or cls.oauth_version,
            ui_locales=_optional_env("KAUFLAND_UI_LOCALES") or f"{country.lower()}-{country}",
            view_type=_optional_env("KAUFLAND_VIEW_TYPE") or cls.view_type,
            preferred_store=_optional_env("KAUFLAND_PREFERRED_STORE"),
            page_size=page_size,
            max_pages=max_pages,
            timeout_seconds=timeout,
            max_retries=retries,
        )

    @property
    def token_path(self) -> Path:
        return self.data_dir / "tokens.json"

    @property
    def account_path(self) -> Path:
        return self.data_dir / "account.json"


@dataclass(frozen=True)
class TokenSet:
    access_token: str
    refresh_token: str | None
    access_expires_at: float
    token_type: str = "Bearer"

    @classmethod
    def from_response(cls, payload: Mapping[str, Any], previous_refresh: str | None = None) -> TokenSet:
        access = payload.get("access_token")
        if not isinstance(access, str) or not access:
            raise KauflandAuthenticationError("Kaufland token response contained no access token")
        refresh = payload.get("refresh_token") or previous_refresh
        if refresh is not None and not isinstance(refresh, str):
            raise KauflandAuthenticationError("Kaufland token response contained an invalid refresh token")
        try:
            expires_in = max(float(payload.get("expires_in", 300)), 1.0)
        except (TypeError, ValueError) as exc:
            raise KauflandAuthenticationError("Kaufland token response contained an invalid expiry") from exc
        token_type = payload.get("token_type")
        return cls(
            access,
            refresh,
            time.time() + expires_in,
            token_type if isinstance(token_type, str) else "Bearer",
        )

    @classmethod
    def from_storage(cls, value: Any) -> TokenSet:
        if not isinstance(value, dict):
            raise KauflandAuthenticationError("Kaufland token store is not a JSON object")
        access = value.get("access_token")
        if not isinstance(access, str) or not access:
            raise KauflandAuthenticationError("Kaufland token store has no access token")
        try:
            expires_at = float(value["access_expires_at"])
        except (KeyError, TypeError, ValueError) as exc:
            raise KauflandAuthenticationError("Kaufland token store has an invalid access expiry") from exc
        refresh = value.get("refresh_token")
        if refresh is not None and not isinstance(refresh, str):
            raise KauflandAuthenticationError("Kaufland token store has an invalid refresh token")
        return cls(access, refresh, expires_at, str(value.get("token_type") or "Bearer"))

    def to_storage(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "access_expires_at": self.access_expires_at,
            "token_type": self.token_type,
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }


class TokenStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> TokenSet | None:
        raw = _read_json(self.path)
        return None if raw is None else TokenSet.from_storage(raw)

    def save(self, token_set: TokenSet) -> None:
        _atomic_write(
            self.path,
            (json.dumps(token_set.to_storage(), ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
            secret=True,
        )


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class HttpClient:
    """Small urllib wrapper that never logs URLs, headers, or response bodies."""

    def __init__(self, timeout_seconds: float):
        self.timeout_seconds = timeout_seconds

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
    ) -> HttpResponse:
        request = urllib.request.Request(url, data=body, headers=dict(headers or {}), method=method.upper())
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return HttpResponse(int(response.status), dict(response.headers.items()), response.read())
        except urllib.error.HTTPError as exc:
            return HttpResponse(int(exc.code), dict((exc.headers or {}).items()), exc.read())
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise KauflandError("Kaufland network request failed or timed out") from exc


def _request_with_retries(
    http: HttpClient,
    method: str,
    url: str,
    *,
    headers: Mapping[str, str],
    retries: int,
    sleeper: Callable[[float], None] = time.sleep,
) -> HttpResponse:
    retryable = {408, 429, 500, 502, 503, 504}
    for attempt in range(retries + 1):
        try:
            response = http.request(method, url, headers=headers)
        except KauflandError:
            if attempt >= retries:
                raise
            sleeper(min(30.0, 0.5 * (2**attempt)))
            continue
        if response.status not in retryable or attempt >= retries:
            return response
        retry_after = next((v for k, v in response.headers.items() if k.lower() == "retry-after"), None)
        try:
            delay = min(max(float(retry_after or 0), 0.0), 60.0)
        except ValueError:
            delay = 0.0
        sleeper(delay or min(30.0, 0.5 * (2**attempt)))
    raise AssertionError("Kaufland retry loop unexpectedly exhausted")


class AuthClient:
    TOKEN_PATH = "/token-srv/token"
    AUTHZ_PATH = "/authz-srv/authz"

    def __init__(self, config: KauflandConfig, http: HttpClient):
        self.config = config
        self.http = http

    def authorization_url(self, *, state: str, code_challenge: str) -> str:
        params = {
            "client_id": self.config.cidaas_client_id,
            "response_type": "code",
            "redirect_uri": self.config.redirect_uri,
            "ui_locales": self.config.ui_locales,
            "v": self.config.oauth_version,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
        if self.config.view_type:
            params["view_type"] = self.config.view_type
        if self.config.preferred_store:
            params["preferredStore"] = self.config.preferred_store
        return self.config.cidaas_base_url + self.AUTHZ_PATH + "?" + urllib.parse.urlencode(params)

    def _token_request(self, form: Mapping[str, str], previous_refresh: str | None = None) -> TokenSet:
        response = self.http.request(
            "POST",
            self.config.cidaas_base_url + self.TOKEN_PATH,
            headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
            body=urllib.parse.urlencode(form).encode("utf-8"),
        )
        if response.status != 200:
            raise KauflandAuthenticationError(f"Kaufland token endpoint returned HTTP {response.status}")
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise KauflandAuthenticationError("Kaufland token endpoint returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise KauflandAuthenticationError("Kaufland token endpoint returned an unexpected payload")
        return TokenSet.from_response(payload, previous_refresh)

    def exchange(self, code: str, verifier: str) -> TokenSet:
        form = {
            "code": code,
            "client_id": self.config.cidaas_client_id,
            "redirect_uri": self.config.redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": verifier,
            "v": self.config.oauth_version,
        }
        if self.config.preferred_store:
            form["preferredStore"] = self.config.preferred_store
        return self._token_request(form)

    def refresh(self, refresh_token: str) -> TokenSet:
        form = {
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
            "client_id": self.config.cidaas_client_id,
            "v": self.config.oauth_version,
        }
        if self.config.preferred_store:
            form["preferredStore"] = self.config.preferred_store
        return self._token_request(form, previous_refresh=refresh_token)


class TokenManager:
    def __init__(self, auth: AuthClient, store: TokenStore):
        self.auth = auth
        self.store = store

    def access_token(self) -> str:
        token = self.store.load()
        if token is None:
            raise KauflandAuthenticationError(
                "No Kaufland login is saved; run 'python kaufland_sync.py login'"
            )
        if token.access_expires_at > time.time() + 60:
            return token.access_token
        if not token.refresh_token:
            raise KauflandAuthenticationError("Kaufland login expired; run 'python kaufland_sync.py login'")
        try:
            refreshed = self.auth.refresh(token.refresh_token)
        except KauflandError as exc:
            raise KauflandAuthenticationError("Kaufland refresh token was rejected; run login again") from exc
        self.store.save(refreshed)
        return refreshed.access_token

    def force_refresh(self) -> str:
        token = self.store.load()
        if token is None or not token.refresh_token:
            raise KauflandAuthenticationError("Kaufland login cannot be refreshed; run login again")
        refreshed = self.auth.refresh(token.refresh_token)
        self.store.save(refreshed)
        return refreshed.access_token


def generate_pkce() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    return verifier, challenge


def parse_callback_input(raw: str, *, expected_state: str) -> str:
    value = raw.strip()
    if not value:
        raise KauflandAuthenticationError("No OAuth callback was supplied")
    if "://" in value:
        parsed = urllib.parse.urlsplit(value)
        query, fragment = parsed.query, parsed.fragment
    else:
        query, fragment = value.lstrip("?"), ""
    params = urllib.parse.parse_qs(query, keep_blank_values=True)
    if not params and fragment:
        params = urllib.parse.parse_qs(fragment, keep_blank_values=True)
    error = params.get("error", [None])[0]
    if error:
        description = params.get("error_description", [""])[0]
        raise KauflandAuthenticationError(
            f"Kaufland authorization was declined ({error}: {description[:120]})"
        )
    state = params.get("state", [None])[0]
    if not state:
        raise KauflandAuthenticationError("Callback has no state; paste the complete redirected URL")
    if not hmac.compare_digest(state, expected_state):
        raise KauflandAuthenticationError("Kaufland OAuth state did not match this login attempt")
    code = params.get("code", [None])[0]
    if not code:
        raise KauflandAuthenticationError("Callback has no authorization code")
    return code


def extract_user_id(payload: Any) -> str:
    paths = (("user_id",), ("userId",), ("user", "user_id"), ("user", "userId"), ("sub",))
    for path in paths:
        current = payload
        for part in path:
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(part)
        if isinstance(current, (str, int)):
            candidate = str(current).strip()
            if candidate and "@" not in candidate:
                return candidate
    raise KauflandAuthenticationError("Could not find the Kaufland user ID; set KAUFLAND_USER_ID explicitly")


def resolve_user_id(config: KauflandConfig) -> str:
    if config.user_id:
        if "@" in config.user_id:
            raise KauflandError("KAUFLAND_USER_ID must be the provider user ID, not an email address")
        return config.user_id
    account = _read_json(config.account_path)
    user_id = account.get("user_id") if isinstance(account, dict) else None
    if isinstance(user_id, str) and user_id.strip():
        return user_id.strip()
    raise KauflandAuthenticationError("No Kaufland user ID is configured; set KAUFLAND_USER_ID or run login")


def is_configured(config: KauflandConfig | None = None) -> bool:
    try:
        config = config or KauflandConfig.from_environment()
        resolve_user_id(config)
        return config.token_path.is_file()
    except (KauflandError, OSError):
        return False


class UserInfoClient:
    def __init__(self, config: KauflandConfig, http: HttpClient):
        self.config = config
        self.http = http

    def user_id(self, access_token: str) -> str:
        response = self.http.request(
            "GET",
            self.config.userinfo_url,
            headers={"Accept": "application/json", "Authorization": f"Bearer {access_token}"},
        )
        if response.status != 200:
            raise KauflandAuthenticationError(f"Kaufland userinfo endpoint returned HTTP {response.status}")
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise KauflandAuthenticationError("Kaufland userinfo endpoint returned invalid JSON") from exc
        return extract_user_id(payload)


def build_receipt_url(config: KauflandConfig, *, user_id: str, start: int, limit: int) -> str:
    encoded = urllib.parse.quote(user_id, safe="")
    query = urllib.parse.urlencode({"start": start, "limit": limit, "country": config.country, "version": 2})
    return f"{config.api_base_url}/api/v2/customers/{encoded}/transactions?{query}"


class KauflandReceiptClient:
    def __init__(
        self,
        config: KauflandConfig,
        http: HttpClient,
        token_manager: TokenManager,
        *,
        sleeper: Callable[[float], None] | None = None,
    ):
        self.config = config
        self.http = http
        self.token_manager = token_manager
        self.sleeper = sleeper or time.sleep

    def list_page(self, *, user_id: str, start: int, limit: int) -> HttpResponse:
        url = build_receipt_url(self.config, user_id=user_id, start=start, limit=limit)
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.token_manager.access_token()}",
            "client-id": self.config.loyalty_client_id,
            "app-platform": "Android",
            "app-version": self.config.app_version,
        }
        response = _request_with_retries(
            self.http, "GET", url, headers=headers, retries=self.config.max_retries, sleeper=self.sleeper
        )
        if response.status != 401:
            return response
        refreshed = self.token_manager.force_refresh()
        headers["Authorization"] = f"Bearer {refreshed}"
        response = _request_with_retries(
            self.http, "GET", url, headers=headers, retries=self.config.max_retries, sleeper=self.sleeper
        )
        if response.status == 401:
            raise KauflandAuthenticationError("Kaufland rejected the refreshed token; run login again")
        return response


def extract_transactions(payload: Any) -> list[dict[str, Any]]:
    """Accept the known Kaufland response wrappers without losing raw data."""
    value: Any = payload if isinstance(payload, list) else None
    if isinstance(payload, dict):
        for key in ("transactions", "items", "receipts", "results"):
            if isinstance(payload.get(key), list):
                value = payload[key]
                break
        if value is None and isinstance(payload.get("data"), list):
            value = payload["data"]
        if value is None and isinstance(payload.get("data"), dict):
            nested = payload["data"]
            for key in ("transactions", "items", "receipts", "results"):
                if isinstance(nested.get(key), list):
                    value = nested[key]
                    break
    if value is None or not all(isinstance(item, dict) for item in value):
        raise KauflandApiError("Kaufland receipt response did not contain a transaction list")
    return list(value)


def transaction_id(transaction: Mapping[str, Any]) -> str | None:
    value = transaction.get("id")
    if isinstance(value, (str, int)) and str(value).strip():
        return str(value).strip()
    return None


def _number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, str):
        value = value.replace(",", ".")
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _minor_units(value: Any) -> float:
    return _number(value) / 100.0


def _date(value: Any) -> datetime:
    if isinstance(value, str) and value.strip():
        raw = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(raw)
            return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed
        except ValueError:
            LOGGER.warning("Could not parse Kaufland receipt timestamp")
    return datetime.now()


def _text(value: Any, default: str = "") -> str:
    return str(value).strip() if value is not None else default


def _position_items(value: Any, *, refund: bool = False) -> list[ParsedItem]:
    items: list[ParsedItem] = []
    for position in value if isinstance(value, list) else []:
        if not isinstance(position, dict):
            continue
        name = _text(position.get("name") or position.get("description"), "Unknown item")
        raw_total = position.get("total", position.get("price", position.get("amount", 0)))
        quantity = _number(position.get("quantity"), 1.0) or 1.0
        tax_rate = position.get("taxRate") or position.get("taxClass")
        price_total = _minor_units(raw_total)
        if refund and price_total > 0:
            price_total = -price_total
        items.append(
            ParsedItem(
                name=name,
                price_total=price_total,
                quantity=quantity,
                tax_rate=_text(tax_rate) or None,
                loyalty_qualified=bool(
                    position.get("loyaltyProgramQualified") or position.get("isLoyaltyPrice")
                ),
            )
        )
    return items


def transaction_to_parsed_receipt(transaction: Mapping[str, Any]) -> ParsedReceipt:
    identifier = transaction_id(transaction)
    if identifier is None:
        raise KauflandApiError("Kaufland transaction has no non-empty id")
    store = transaction.get("store") if isinstance(transaction.get("store"), dict) else {}
    items = _position_items(transaction.get("positions"))
    items.extend(_position_items(transaction.get("refundPositions"), refund=True))
    street = _text(store.get("street"))
    city = _text(store.get("city"))
    address = ", ".join(part for part in (street, city) if part) or None
    store_name = _text(store.get("name"), "Kaufland")
    currency = _text(transaction.get("currency"), "EUR").upper()
    if len(currency) != 3 or not currency.isalpha():
        currency = "EUR"
    loyalty_details = {
        "saving_minor_units": transaction.get("saving"),
        "payoff_minor_units": transaction.get("payoff"),
        "promotions": transaction.get("promotions", []),
        "taxes": transaction.get("taxes", []),
        "card_number": transaction.get("cardNumber"),
        "bonus_points": transaction.get("bonusPoints"),
    }
    return ParsedReceipt(
        store_key="kaufland",
        store_name=store_name,
        date=_date(transaction.get("timestamp") or transaction.get("date")),
        total=_minor_units(transaction.get("sum", transaction.get("total", 0))),
        items=items,
        currency=currency,
        payment_method=_text(transaction.get("paymentType")) or None,
        store_address=address,
        store_id=_text(store.get("id")) or None,
        transaction_id=identifier,
        loyalty_program="Kaufland Card" if transaction.get("cardNumber") else None,
        loyalty_details=loyalty_details,
        raw_data=dict(transaction),
    )


def archive_remote_receipt(parsed: ParsedReceipt) -> Any:
    """Hand the transaction to the store-agnostic API-ingest entry point.

    Archiving, hashing, and dedup are the same for every API-based store, so
    they live in ``app/ingest.py``; this module only owns the Kaufland protocol.
    """
    from . import ingest

    return ingest.ingest_api_receipt(parsed, extraction_source="kaufland_api")


def _run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + secrets.token_hex(4)


class KauflandDownloader:
    def __init__(self, config: KauflandConfig, client: KauflandReceiptClient | Any | None = None):
        self.config = config
        if client is None:
            http = HttpClient(config.timeout_seconds)
            auth = AuthClient(config, http)
            client = KauflandReceiptClient(config, http, TokenManager(auth, TokenStore(config.token_path)))
        self.client = client

    def run(self) -> dict[str, Any]:
        user_id = resolve_user_id(self.config)
        run_id = _run_id()
        raw_dir = self.config.data_dir / "raw" / run_id
        raw_dir.mkdir(parents=True, exist_ok=True)
        report: dict[str, Any] = {
            "run_id": run_id,
            "status": "running",
            "pages": 0,
            "transactions_received": 0,
            "new_receipts": 0,
            "duplicates": 0,
            "skipped": 0,
            "raw_directory": str(raw_dir),
        }
        completed = False
        try:
            for page_number in range(self.config.max_pages):
                start = page_number * self.config.page_size
                response = self.client.list_page(user_id=user_id, start=start, limit=self.config.page_size)
                response_hash = hashlib.sha256(response.body).hexdigest()
                try:
                    raw_body: Any = json.loads(response.body.decode("utf-8")) if response.body else None
                except (UnicodeDecodeError, json.JSONDecodeError):
                    raw_body = {"raw_text": response.body.decode("utf-8", errors="replace")}
                content_type = next(
                    (value for key, value in response.headers.items() if key.lower() == "content-type"),
                    None,
                )
                _write_json(
                    raw_dir / f"page_{page_number:04d}.json",
                    {
                        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "request": {
                            "start": start,
                            "limit": self.config.page_size,
                            "country": self.config.country,
                            "version": 2,
                            "app_version": self.config.app_version,
                        },
                        "status": response.status,
                        "content_type": content_type,
                        "body_sha256": response_hash,
                        "body": raw_body,
                    },
                )
                report["pages"] = page_number + 1
                if response.status == 204:
                    transactions: list[dict[str, Any]] = []
                elif response.status == 200:
                    try:
                        transactions = extract_transactions(json.loads(response.body.decode("utf-8")))
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise KauflandApiError(f"Kaufland page {page_number} was not valid JSON") from exc
                elif response.status == 400:
                    raise KauflandApiError("Kaufland returned HTTP 400; check country and paging")
                elif response.status == 403:
                    raise KauflandAuthenticationError("Kaufland denied access to receipt history")
                elif response.status == 404:
                    raise KauflandApiError("Kaufland returned HTTP 404; check KAUFLAND_USER_ID")
                else:
                    raise KauflandApiError(f"Kaufland receipt API returned HTTP {response.status}")
                report["transactions_received"] += len(transactions)
                for transaction in transactions:
                    if transaction_id(transaction) is None:
                        report["skipped"] += 1
                        continue
                    parsed = transaction_to_parsed_receipt(transaction)
                    if not parsed.items:
                        report["skipped"] += 1
                        continue
                    outcome = archive_remote_receipt(parsed)
                    if outcome.status == "stored":
                        report["new_receipts"] += 1
                    elif outcome.status == "duplicate":
                        report["duplicates"] += 1
                    else:
                        report["skipped"] += 1
                if len(transactions) < self.config.page_size:
                    completed = True
                    break
            if not completed:
                raise KauflandApiError(
                    "maximum page limit reached before the receipt API returned a short page"
                )
            report["status"] = "complete"
            return report
        finally:
            _write_json(self.config.data_dir / "runs" / f"{run_id}.json", report)


def download_kaufland_receipts(config: KauflandConfig | None = None) -> dict[str, Any]:
    return KauflandDownloader(config or KauflandConfig.from_environment()).run()


def login(config: KauflandConfig | None = None, *, no_browser: bool = False) -> dict[str, str]:
    """Run the manual browser PKCE flow and save tokens for later syncs."""
    config = config or KauflandConfig.from_environment()
    http = HttpClient(config.timeout_seconds)
    auth = AuthClient(config, http)
    verifier, challenge = generate_pkce()
    state = secrets.token_urlsafe(32)
    url = auth.authorization_url(state=state, code_challenge=challenge)
    if not no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    print("Open this Kaufland authorization URL in a browser:\n" + url)
    callback = input("After login, paste the complete redirected callback URL: ").strip()
    code = parse_callback_input(callback, expected_state=state)
    tokens = auth.exchange(code, verifier)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    TokenStore(config.token_path).save(tokens)
    user_id = config.user_id
    if not user_id:
        user_id = UserInfoClient(config, http).user_id(tokens.access_token)
    _write_json(
        config.account_path,
        {"user_id": user_id, "updated_at": datetime.now(timezone.utc).isoformat()},
        secret=True,
    )
    return {"user_id": user_id, "token_path": str(config.token_path)}
