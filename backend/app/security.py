"""Optional trusted-device token for LAN deployments.

The app intentionally ships without accounts (see README "Security & scope"),
but "anyone on the WiFi can delete receipts" is a real objection. Setting
``BONFIRE_API_TOKEN`` in .env turns on a shared-secret check for every
endpoint except ``/health`` (Docker's healthcheck needs that one).

Clients may send the token as::

    Authorization: Bearer <token>
    X-Api-Token: <token>
    ?token=<token>          (for <img>/<iframe> loads that can't set headers)

This is deliberately a static token, not a login system: it keeps casual LAN
neighbours and curious kids out. For internet exposure, put a reverse proxy
with real auth in front (see docs/deployment.md).
"""

from __future__ import annotations

import hmac
import os

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# Liveness must work unauthenticated (container healthchecks, uptime monitors).
PUBLIC_PATHS = {"/health"}


def expected_token() -> str:
    return (os.getenv("BONFIRE_API_TOKEN") or "").strip()


def _supplied_token(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    header = request.headers.get("x-api-token", "")
    if header:
        return header.strip()
    return (request.query_params.get("token") or "").strip()


class TokenAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        expected = expected_token()
        if not expected or request.method == "OPTIONS" or request.url.path in PUBLIC_PATHS:
            return await call_next(request)
        supplied = _supplied_token(request)
        if supplied and hmac.compare_digest(supplied.encode(), expected.encode()):
            return await call_next(request)
        return JSONResponse({"detail": "Missing or invalid API token."}, status_code=401)
