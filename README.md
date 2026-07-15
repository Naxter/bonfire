<p align="center">
  <img src="docs/banner.png" alt="Bonfire" width="100%">
</p>

# Bonfire

Turn a mailbox full of German supermarket receipts (*Bons*) into a spending
dashboard.

Scrapes REWE eBons from email, ingests DM eBons and photographed receipts from
any store, parses them into SQLite, categorizes every line item with an LLM,
and serves analytics on a self-hosted dashboard — designed to run unattended on
a Raspberry Pi.

[![CI](https://github.com/Naxter/bonfire/actions/workflows/ci.yml/badge.svg)](https://github.com/Naxter/bonfire/actions/workflows/ci.yml)
![MIT license](https://img.shields.io/badge/license-MIT-green)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![Node 18+](https://img.shields.io/badge/node-18%2B-brightgreen)

![Today view](docs/screenshot.png)

<details>
<summary>Analytics view</summary>

![Analytics](docs/screenshot-full.png)

</details>

## Features

- **Automatic ingest with a visible lifecycle** — an IMAP scraper pulls REWE
  eBon PDFs from your inbox on a schedule; a folder watcher ingests anything
  you drop into `backend/data/inbox/` (PDF or photo) within seconds. Every
  import is a tracked job: the dashboard shows queued/running/failed states,
  keeps an import history, and failed files can be retried with one click.
- **Any store via photos** — receipts from stores without an adapter
  (Aldi, Lidl, the bakery) are photographed and structured by a multimodal
  LLM; new stores appear in the dashboard filter automatically. Drag-and-drop
  PDFs/photos or use the mobile camera right from the Receipts page.
- **Data you can trust** — every import is validated (line items must add up
  to the printed total) and vision imports are flagged for review. The review
  screen shows the archived original next to the parsed fields; store, date,
  total and every line item are editable, receipts can be verified,
  reprocessed from the source file, or deleted, and duplicate imports are
  detected and resolvable.
- **LLM categorization with a cache** — every line item is filed into a
  German grocery taxonomy once, then remembered. Manual overrides are locked
  and never overwritten — and when you change a category you choose whether
  it applies everywhere or just to one receipt line.
- **Restock radar with actions** — predicts what you're about to run out of
  (with quantity suggestions) from your own purchase cadence; put it on the
  shopping list, mark it bought, snooze it, or dismiss it for good.
- **Shopping list & pantry** — a real shopping list (restock suggestions feed
  it) and an optional pantry that meal ideas use once you maintain it.
- **Budgets, not just forecasts** — monthly and per-category targets with
  remaining amounts, overspend alerts, a month-end projection, and a
  "what changed vs. last month?" breakdown.
- **Product identity & price comparison** — receipt-name variants are merged
  into canonical products with package sizes parsed from the names, so prices
  compare as €/kg / €/l across pack sizes and stores. Price-jump alerts flag
  items that suddenly got dearer.
- **Inflation tracker** — per-product price history and the biggest price
  hikes across your receipts.
- **Ask your groceries** — natural-language questions ("how much did I spend
  on drinks last month?") become guarded, read-only SQL.
- **Meal ideas** — recipe suggestions from what's already in the house
  (your latest shopping trip per store, plus your pantry), with cooking time
  and what's still missing. Suggestions are driven by meal profiles whose
  prompts you edit — or create from scratch — right in the dashboard.
- **Telegram bot** — snap a photo of a receipt to file it; `/restock`,
  `/budget`, `/meals`, or plain-language questions from your phone.
- **German & English UI, three themes** — locale-aware dates and numbers,
  dark/light/system plus a high-contrast theme.
- **Your data stays portable** — one-click CSV/JSON export and a consistent
  SQLite snapshot download, plus scheduled on-disk backups.
- **Pluggable LLM** — Ollama (local), OpenAI, or Gemini. Drop an API key in
  `.env` and the provider is auto-detected; swap with one line.

## How it works

```
email-scraper/   -> downloads REWE eBon PDFs from your mailbox (IMAP)
        |
        v
backend/data/inbox/*.pdf|*.jpg
        |
  watch_inbox.py ──> app/ingest.py ──> app/stores/<store>.py (detect + parse)
        |                                       |
        |                                 normalized ParsedReceipt
        v                                       v
   SQLite (WAL)  <── categorizer (LLM) ── items + receipts
        |
        v
   FastAPI (app/routers/*)  ──>  Next.js dashboard
```

Store parsing is adapter-based: REWE eBons are parsed from their PDF text
layer, DM eBons are structured by the LLM, photos go through the vision
model. Receipts are deduplicated by content hash, so re-downloads and renames
are harmless.

## Quickstart (with demo data)

Prerequisites: Python 3.10+, Node 18+.

```sh
# Backend
cd backend
pip install -r requirements.txt
python seed_demo.py                    # ~6 months of synthetic receipts, no API key needed
uvicorn app.main:app --reload          # http://localhost:8000

# Frontend (second terminal)
cd frontend
npm install
npm run dev                            # http://localhost:3000
```

Open http://localhost:3000 and you get the dashboard above. Delete
`backend/data/bonfire.db` when you're ready to start with your own receipts.

## Using your own receipts

1. **Configure:** `cp .env.example .env` and fill in what you use. Setting
   `OPENAI_API_KEY` *or* `GEMINI_API_KEY` is enough to pick the LLM — or run a
   local [Ollama](https://ollama.com) with `LLM_PROVIDER=ollama`. Verify with
   `python check_llm.py`.
2. **Import:** drop receipt PDFs (or photos) into `backend/data/inbox/` and
   run `python process_backlog.py` — or keep `python watch_inbox.py` running
   and files are ingested the moment they land.
3. **Automate REWE:** forward your eBon mails to a mailbox the scraper can
   read (GMX credentials in `.env`), then run `email-scraper/scraper.py` on a
   schedule. DM offers no comparable automation — download the eBon PDF from
   the DM app/website (or photograph the paper receipt) and drop it into
   `backend/data/inbox/dm/`.

## Adding a new store

The pipeline is store-agnostic. To support a new chain (e.g. Lidl):

1. Create `backend/app/stores/lidl.py` with a `StoreAdapter` subclass
   implementing `matches(text, filename)` and `parse(file_path, text)` →
   returns a normalized `ParsedReceipt` (see `stores/base.py`).
2. Register it in `backend/app/stores/registry.py` by adding it to `ADAPTERS`.

That's it. Ingestion, the `store_key` column, every stats endpoint, and the
frontend store filter are all driven off the registry — no other file changes.
(There's a test asserting exactly this.)

## Deployment

Two supported paths for an always-on box (Raspberry Pi OS 64-bit or any
Linux host):

- **systemd** — services + timers, lightest on resources:
  [deploy/DEPLOY.md](deploy/DEPLOY.md)
- **Docker Compose** — one ops model for everything:
  [deploy/DOCKER.md](deploy/DOCKER.md)

## Security & scope

This is a **single-user app designed to run on a trusted home LAN**. By
default it has **no authentication** — anyone who can reach the host on your
network can read the dashboard and API. That is intentional for a personal
tool. The services bind to `0.0.0.0` so other devices on your WiFi (your
phone) can reach them; this is required for normal use.

If "anyone on the WiFi" is too broad for your household, set
`BONFIRE_API_TOKEN` in `.env`: every endpoint except `/health` then requires
the token (`Authorization: Bearer …`, `X-Api-Token`, or `?token=`). Enter the
same token once under **Settings → Security** in the dashboard and that
browser keeps access; the Telegram bot picks it up from `.env` automatically.
It's a shared secret, not a login system — good against curious LAN
neighbours, not against the internet.

**Do not expose the app to the internet** (no port-forwarding, no public
tunnel) without first putting it behind an authenticating reverse proxy
(e.g. Caddy or nginx with Basic Auth + TLS).

## Backups & restore

The `backup` service (or `python backend/backup_db.py`) writes consistent
SQLite snapshots to `backend/data/backups/` (env: `BACKUP_DIR`,
`BACKUP_KEEP`); the dashboard's health panel shows the age of the newest one,
and **Settings → Data** can download a snapshot on demand.

To restore: stop the services, replace `backend/data/bonfire.db` with a
snapshot (also delete `bonfire.db-wal`/`-shm` if present), start again — the
schema migrations re-apply automatically. Archived receipt originals live in
`backend/data/archive/` and are worth backing up alongside the database.

## Development

```sh
pip install pytest ruff
(cd backend && pytest -q)              # unit tests (in-memory DB, LLM stubbed)
ruff check .                           # lint, config in pyproject.toml

(cd frontend && npm run lint && npx tsc --noEmit)
```

The database schema and lightweight migrations are applied automatically on
API startup and by `process_backlog.py` — there is no migration tool to run.

CI runs the same checks on every push and PR
([.github/workflows/ci.yml](.github/workflows/ci.yml)). A self-hosted box can
auto-deploy commits whose CI is green — see the CD section in
[deploy/DOCKER.md](deploy/DOCKER.md).

## License

[MIT](LICENSE)
