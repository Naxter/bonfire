# Running Bonfire with Docker Compose

Alternative to the native/systemd setup in [DEPLOY.md](DEPLOY.md). Use this if
you already run Docker on the box and want one ops model for everything.

Works on Raspberry Pi OS Lite (**64-bit**). Everything is arm64-friendly.

---

## 1. Configure

```bash
cp .env.example .env
nano .env
```

Minimum for a cloud LLM (auto-detected — no `LLM_PROVIDER` needed):

```
OPENAI_API_KEY=sk-...
GMX_USER=you@gmx.net
GMX_PASSWORD=your_app_password
REWE_SENDER=forwarder@example.com
FRONTEND_ORIGINS=http://<pi-ip>:3000
NEXT_PUBLIC_API_URL=http://<pi-ip>:8000
```

> `NEXT_PUBLIC_API_URL` is **baked into the frontend at build time** (your browser
> calls it directly, so `localhost` won't work from your phone). Change it →
> `docker compose build frontend`.

> **Access model:** dashboard and API are served directly on the LAN with no
> authentication — intentional for a trusted home network. See the README's
> "Security & scope" section before changing how this box is reachable.

**Port clash with another project?** Set `BACKEND_PORT` / `FRONTEND_PORT` in
`.env`. Check first:

```bash
sudo ss -tlnp | grep -E ':(3000|8000)\b'
docker ps --format '{{.Names}}\t{{.Ports}}'
```

## 2. Up

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f watcher
```

Services: `backend` (API), `frontend` (dashboard), `watcher` (ingests dropped
receipts), `scraper` (hourly REWE fetch), `backup` (SQLite snapshot at start +
daily).

Verify the LLM key works:

```bash
docker compose exec backend python check_llm.py
```

Dashboard: `http://<pi-ip>:3000`

## 3. Telegram bot (optional)

Create a bot with **@BotFather**, set `TELEGRAM_BOT_TOKEN` in `.env`, then:

```bash
docker compose --profile telegram up -d
docker compose logs -f telegram      # message the bot; it replies with your chat id
```

Put that id in `TELEGRAM_ALLOWED_CHAT_IDS`, then
`docker compose --profile telegram up -d --force-recreate telegram`.

---

## Where your data lives

Everything persists on the **host**, bind-mounted into the containers:

```
backend/data/
├── inbox/{rewe,dm}/   # drop receipts here (PDF or photo) — watcher picks them up
├── archive/<store>/   # processed originals
├── backups/           # nightly SQLite snapshots
└── bonfire.db         # the database
```

`docker compose down -v` will **not** touch it (no named volumes). To put backups
on a USB stick, set `BACKUP_DIR` in `.env` and add a matching mount to the
`backup` service.

## Day-to-day

- **REWE:** automatic (the `scraper` service polls GMX).
- **DM / any other store:** drop the PDF or a **photo** into
  `backend/data/inbox/` (use the `dm/` subfolder to force the DM parser). Or
  just send the photo to the Telegram bot.
- **Update after a code change:** `docker compose up -d --build`
- **Reclaim SD-card space:** `docker system df` then `docker image prune`

## Notes / gotchas

- **`.env` is read by python-dotenv only** — the services deliberately have no
  `env_file:`, they just mount `./.env` at `/app/.env`. Compose's env-file parser
  disagrees with python-dotenv about quoting and inline `#`, and because
  `load_dotenv()` defaults to `override=False`, anything Compose injected would
  silently win. That mangles passwords containing `#`, quotes or `$`. One file,
  one parser. Container-only settings (`TZ`, `WATCHER_POLLING`, `GROCERY_API_URL`)
  are set via `environment:` instead.
- Passwords with special characters: single-quote them — `GMX_PASSWORD='a#b$c'`.
- The watcher runs with `WATCHER_POLLING=1`, because inotify events don't
  reliably cross bind-mount boundaries. It stats the inbox instead — negligible
  cost for a small folder, and it always works.
- `scraper` and `backup` are **interval loops**, not wall-clock cron. The backup
  runs once at container start and then every 24h. If you want wall-clock
  scheduling, use the systemd timers in [DEPLOY.md](DEPLOY.md) instead.
- SQLite is shared by `backend`, `watcher` and `backup` over the bind mount —
  same as the native multi-process setup, and fine on a local filesystem. Don't
  put `data/` on an NFS/SMB share.
- Set `TZ` in `.env` so timestamps (and the budget "this month" logic) use your
  local time rather than UTC.
- Image builds on a Pi are slow (especially the frontend). If it drags, build on
  a faster machine with `docker buildx build --platform linux/arm64` and push to
  a registry.
