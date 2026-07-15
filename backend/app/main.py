"""FastAPI app assembly: middleware, rate limiting, and the feature routers.

The endpoints themselves live in ``app/routers/`` — one module per surface
(receipts, stats, jobs, planning, products, budget, export, insights, system).
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from . import config  # noqa: F401  (loads repo-root .env before reading env vars)
from .database import create_db_and_tables
from .rate_limit import limiter
from .routers import (
    budget_api,
    export_api,
    insights_api,
    jobs_api,
    planning,
    products_api,
    receipts,
    stats,
    system,
)
from .security import TokenAuthMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure the schema exists (and migrations/backfill run) before serving.
    create_db_and_tables()
    yield


app = FastAPI(lifespan=lifespan)

# Rate-limit the endpoints that cost money (LLM calls) or mutate in bulk —
# defense in depth behind the optional token / reverse proxy.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Optional shared-secret auth (BONFIRE_API_TOKEN) — see app/security.py.
app.add_middleware(TokenAuthMiddleware)

# CORS: wildcard + credentials is rejected by browsers, so pin the origin(s).
# Configure via FRONTEND_ORIGINS (comma-separated) in the environment. With the
# same-origin Caddy proxy this only matters for local dev.
_origins = [o.strip() for o in os.getenv("FRONTEND_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Api-Token"],
)

app.include_router(system.router)
app.include_router(stats.router)
app.include_router(receipts.router)
app.include_router(jobs_api.router)
app.include_router(insights_api.router)
app.include_router(budget_api.router)
app.include_router(planning.router)
app.include_router(products_api.router)
app.include_router(export_api.router)
