# Running Bonfire unattended on a Raspberry Pi

> Already run Docker on this box? See **[DOCKER.md](DOCKER.md)** for the
> `docker compose` route instead. Both are supported; this file is the native
> systemd setup (lighter on the SD card, wall-clock timers).

This sets the whole thing up to run by itself: the API + dashboard stay up, new
REWE eBons are pulled from your GMX inbox on a schedule, and any PDF you drop
into the inbox folder (e.g. a DM eBon) is ingested automatically.

The LLM runs **in the cloud** (OpenAI or Gemini), so no Ollama / GPU is needed
on the Pi. Switching provider is a one-line `.env` change.

Paths below assume the repo lives at `/home/pi/bonfire`.
Adjust the unit files if you put it elsewhere — the paths are the only thing to
change.

---

## 1. System dependencies (Raspberry Pi OS / Debian bookworm+)

```bash
sudo apt update
sudo apt install -y python3-venv python3-dev gcc libffi-dev libjpeg-dev zlib1g-dev
# Node 18+ for the frontend (nodesource or nvm):
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
```

## 2. Python backend

```bash
cd /home/pi/bonfire
python3 -m venv venv
./venv/bin/pip install -U pip
./venv/bin/pip install -r backend/requirements.txt
```

## 3. Configuration (`.env`)

```bash
cp .env.example .env
nano .env
```

Set the cloud LLM — **just drop in a key** (the provider is auto-detected, no
need to set `LLM_PROVIDER`). For OpenAI:

```
OPENAI_API_KEY=sk-...
# OPENAI_MODEL=gpt-4o-mini   # optional; this is the default
```

…or for Gemini:

```
GEMINI_API_KEY=...
# GEMINI_MODEL=gemini-2.0-flash
```

Then confirm the key works before relying on it:

```
./venv/bin/python check_llm.py     # prints the resolved provider + a live test call
```

Both default models are multimodal, so photographed receipts work with no extra
config. (Set `LLM_PROVIDER=ollama` only if you want the local model instead.)

Also fill in `GMX_USER` / `GMX_PASSWORD` / `REWE_SENDER` for the email scraper,
and set `FRONTEND_ORIGINS=http://<pi-ip>:3000` so the browser can reach the API.

> DM needs no configuration — DM receipts are handled by manually dropping
> their PDFs into the inbox (see step 6).

## 4. Frontend (production build)

`NEXT_PUBLIC_API_URL` is baked in at **build** time, so set it before building:

```bash
cd /home/pi/bonfire/frontend
npm ci
NEXT_PUBLIC_API_URL=http://<pi-ip>:8000 npm run build
```

Re-run `npm run build` whenever you change the frontend or the API URL.

## 5. Install the services

```bash
sudo cp /home/pi/bonfire/deploy/bonfire-*.service /etc/systemd/system/
sudo cp /home/pi/bonfire/deploy/bonfire-*.timer   /etc/systemd/system/
sudo systemctl daemon-reload

# Always-on services:
sudo systemctl enable --now bonfire-backend.service
sudo systemctl enable --now bonfire-watcher.service
sudo systemctl enable --now bonfire-frontend.service

# Scheduled REWE fetch (enable the TIMER, not the service):
sudo systemctl enable --now bonfire-rewe-scrape.timer

# Nightly SQLite backup (enable the TIMER) — important on an SD card:
sudo systemctl enable --now bonfire-backup.timer

# Telegram assistant bot (optional — needs TELEGRAM_BOT_TOKEN in .env):
sudo systemctl enable --now bonfire-telegram.service
```

Check status / logs:

```bash
systemctl status bonfire-watcher.service
journalctl -u bonfire-watcher.service -f
systemctl list-timers bonfire-rewe-scrape.timer
```

## 6. Day-to-day

- **REWE:** nothing to do — the timer polls GMX hourly, drops PDFs into the
  inbox, and the watcher ingests them.
- **DM:** save the eBon PDF into
  `backend/data/inbox/dm/` (via Samba, `scp`, a synced
  folder, etc.). The watcher picks it up within a couple of seconds, parses it,
  and moves it to `data/archive/dm/`. (Dropping into the `inbox/` root still
  works too — the store is then auto-detected from the PDF.)
- **Dashboard:** `http://<pi-ip>:3000` (LAN only — see the README's
  "Security & scope" note).

## Maintenance

- **Backups** land in `backend/data/backups/` (override with `BACKUP_DIR`,
  retention with `BACKUP_KEEP`, default 14). Since this is an SD card, point
  `BACKUP_DIR` at a USB stick or synced folder so a card failure isn't fatal.
  Run one on demand: `./venv/bin/python backup_db.py`.
- **Recategorize** after you tweak the prompt, swap LLM model, or edit the
  taxonomy (the category cache means existing items aren't revisited otherwise):
  `./venv/bin/python recategorize.py` (add `--all` to redo everything, not just
  Uncategorized). Locked manual overrides are always preserved. Same thing over
  HTTP: `curl -X POST 'http://<pi-ip>:8000/categories/recategorize?scope=missing'`.
- **Health check:** `curl http://<pi-ip>:8000/health` reports DB + LLM-config
  status; the dashboard's header badge shows the same at a glance.

## Daily-assistant features

The backend exposes these (used by the dashboard and the Telegram bot); all the
LLM-backed ones need `LLM_PROVIDER` reachable:

- **Photo any receipt** → `POST /ingest/image` (jpg/png/webp) runs it through the
  vision model, so Aldi/Lidl/bakery receipts work, not just REWE/DM. You can also
  just drop an image into `backend/data/inbox/` — the watcher handles images too.
- **Restock radar** → `GET /insights/restock` (predictive shopping list).
- **Budget forecast** → `GET /insights/budget` (month-end projection + anomalies).
- **Meal ideas** → `GET /insights/meals` (from your latest shopping trips;
  the prompt profiles are editable via `/meal-profiles` or the dashboard).
- **Ask anything** → `GET /ask?q=...` (natural language → guarded read-only SQL).

**Telegram bot setup:**
1. Message **@BotFather**, `/newbot`, copy the token → `TELEGRAM_BOT_TOKEN` in `.env`.
2. Start the service, message your bot once; it replies with your chat id.
3. Put that id in `TELEGRAM_ALLOWED_CHAT_IDS` and `systemctl restart bonfire-telegram`.
4. Now: send a receipt photo to file it, or use `/restock`, `/budget`, `/meals`, or
   just ask a question in plain language.

## Notes

- The watcher waits for a file to finish being written before parsing, so
  partial copies/downloads are safe.
- Both stores share one inbox; the store adapter auto-detects REWE vs DM.
- To move the LLM back on-prem later, set `LLM_PROVIDER=ollama` and point
  `OLLAMA_HOST` at a machine on your LAN running Ollama — no code change.
