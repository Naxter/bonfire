"""Telegram bot — the daily-driver interface to the grocery pipeline.

  * Send a PHOTO of any receipt  -> vision-extracted and ingested
  * /restock                     -> predictive shopping list
  * /budget                      -> month-end spend forecast + anomalies
  * /meals                       -> meal ideas from recent purchases
  * any other text               -> natural-language question over your data

Setup:
  1. Create a bot with @BotFather, put the token in .env as TELEGRAM_BOT_TOKEN.
  2. Message the bot once; it replies with your chat id.
  3. Put that id in TELEGRAM_ALLOWED_CHAT_IDS (comma-separated) and restart.

Talks to the backend over HTTP (GROCERY_API_URL, default http://localhost:8000),
so run it alongside the API service.
"""

import logging
import os
import time
from datetime import datetime
from pathlib import Path

import app.config  # noqa: F401  (loads repo-root .env)
import requests

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("telegram_bot")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


def _redact(msg: object) -> str:
    """requests exceptions embed the full URL — and ours contain the bot token."""
    s = str(msg)
    return s.replace(TOKEN, "***") if TOKEN else s
API = os.getenv("GROCERY_API_URL", "http://localhost:8000").rstrip("/")
ALLOWED = {x.strip() for x in os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").split(",") if x.strip()}

# When the API requires a token (BONFIRE_API_TOKEN in .env), send it along —
# the bot reads the same .env, so this Just Works.
_API_TOKEN = (os.getenv("BONFIRE_API_TOKEN") or "").strip()
API_HEADERS = {"X-Api-Token": _API_TOKEN} if _API_TOKEN else {}

TG = f"https://api.telegram.org/bot{TOKEN}"
TG_FILE = f"https://api.telegram.org/file/bot{TOKEN}"

HELP = (
    "🧾 Bonfire — grocery assistant\n"
    "• Send a photo of any receipt → I'll add it\n"
    "• /restock — what's running low\n"
    "• /budget — this month's spend forecast\n"
    "• /meals — dinner ideas (any profile key works, e.g. /meals family)\n"
    "• Ask anything, e.g. \"how much on drinks last month?\""
)


def send(chat_id, text: str) -> None:
    try:
        requests.post(f"{TG}/sendMessage", json={"chat_id": chat_id, "text": text}, timeout=15)
    except requests.RequestException as e:
        logger.error("sendMessage failed: %s", _redact(e))


# --- handlers -------------------------------------------------------------- #
def handle_photo(chat_id, photo_sizes: list) -> None:
    file_id = photo_sizes[-1]["file_id"]  # largest resolution
    send(chat_id, "📸 Got it — reading the receipt…")
    try:
        fp = requests.get(f"{TG}/getFile", params={"file_id": file_id}, timeout=20).json()
        path = fp["result"]["file_path"]
        image = requests.get(f"{TG_FILE}/{path}", timeout=30).content
        resp = requests.post(f"{API}/ingest/image",
                             files={"file": ("receipt.jpg", image, "image/jpeg")},
                             headers=API_HEADERS, timeout=180)
    except requests.RequestException as e:
        logger.error("photo ingest failed: %s", _redact(e))
        send(chat_id, "❌ Something went wrong reading that. Try again?")
        return

    if resp.status_code == 200:
        d = resp.json()
        if d.get("stored"):
            send(chat_id,
                 f"✅ Added {d['store_name']} — {d['items']} items, €{d['total']:.2f} ({d['date'][:10]})")
        else:
            send(chat_id, f"ℹ️ I already had that {d['store_name']} receipt (€{d['total']:.2f}).")
    else:
        send(chat_id, "❌ Couldn't read a receipt from that photo. A flatter, brighter shot helps.")


def _api_get(path: str):
    return requests.get(f"{API}{path}", headers=API_HEADERS, timeout=180).json()


def cmd_restock(chat_id) -> None:
    items = _api_get("/insights/restock?horizon_days=3")
    if not items:
        send(chat_id, "🛒 Nothing due right now.")
        return
    lines = ["🛒 Running low / due soon:"]
    for x in items[:15]:
        when = "overdue" if x["overdue"] else f"~{max(x['due_in_days'],0)}d"
        lines.append(f"• {x['name']} ({when})")
    send(chat_id, "\n".join(lines))


def cmd_budget(chat_id) -> None:
    b = _api_get("/insights/budget")
    lines = [
        f"💶 {b['month']}: €{b['spent_so_far']:.2f} spent "
        f"(day {b['days_elapsed']}/{b['days_in_month']})",
        f"Projected month-end: €{b['projected_total']:.2f}",
    ]
    if b["anomalies"]:
        lines.append("⚠️ Running hot: " + ", ".join(
            f"{c['category']} (€{c['projected']:.0f} vs €{c['avg_month']:.0f} usual)"
            for c in b["anomalies"]))
    send(chat_id, "\n".join(lines))


def cmd_meals(chat_id, profile: str | None = None) -> None:
    send(chat_id, "🍝 Thinking…")
    if not profile:
        try:
            profile = _api_get("/settings").get("meals.profile") or "family"
        except Exception:
            profile = "family"
    data = _api_get(f"/insights/meals?profile={requests.utils.quote(profile)}")
    meals = data.get("meals", [])
    if data.get("status") == "llm_error":
        send(chat_id, "❌ The meal helper didn't answer (LLM error). Try again in a minute.")
        return
    if not meals:
        send(chat_id, "No meal ideas yet — buy some fresh stuff first!")
        return
    label = (data.get("profile") or {}).get("name", profile)
    lines = [f"🍝 Ideas for {label}:"]
    for m in meals:
        title = m.get("title", "?")
        minutes = m.get("time_minutes")
        lines.append(f"• {title}" + (f" (~{minutes} min)" if minutes else ""))
        uses = ", ".join(m.get("uses", [])[:5])
        if uses:
            lines.append(f"   uses: {uses}")
        missing = ", ".join(m.get("missing", [])[:4])
        if missing:
            lines.append(f"   still needed: {missing}")
        note = m.get("note")
        if note:
            lines.append(f"   ↳ {note}")
        adaptation = m.get("adaptation")
        if adaptation:
            lines.append(f"   ↳ {adaptation}")
    send(chat_id, "\n".join(lines))


# --- optional weekly summary ------------------------------------------------ #
# Set TELEGRAM_WEEKLY_SUMMARY in .env (e.g. "sun 18" — weekday + hour, 24h
# clock; just "sun" defaults to 18:00) and the bot pushes a budget + restock
# recap once a week to every allowed chat. Unset = off.
_DAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
_SUMMARY_MARKER = Path(__file__).resolve().parent / "data" / ".telegram_last_summary"


def _parse_summary_spec(spec: str):
    if not spec:
        return None
    parts = spec.split()
    try:
        day = _DAYS[parts[0][:3]]
        hour = max(0, min(23, int(parts[1]))) if len(parts) > 1 else 18
        return (day, hour)
    except (KeyError, ValueError, IndexError):
        logger.warning("Ignoring invalid TELEGRAM_WEEKLY_SUMMARY %r (use e.g. 'sun 18').", spec)
        return None


_SUMMARY_TARGET = _parse_summary_spec(os.getenv("TELEGRAM_WEEKLY_SUMMARY", "").strip().lower())


def _maybe_weekly_summary() -> None:
    """Called on every poll-loop tick; sends at most one recap per ISO week."""
    if _SUMMARY_TARGET is None or not ALLOWED:
        return
    now = datetime.now()
    day, hour = _SUMMARY_TARGET
    if now.weekday() != day or now.hour != hour:
        return
    week_key = f"{now.isocalendar().year}-W{now.isocalendar().week}"
    try:
        if _SUMMARY_MARKER.exists() and _SUMMARY_MARKER.read_text().strip() == week_key:
            return
    except OSError:
        pass
    for chat_id in ALLOWED:
        try:
            send(chat_id, "🗓 Weekly recap")
            cmd_budget(chat_id)
            cmd_restock(chat_id)
        except Exception:
            logger.exception("Weekly summary failed for chat %s", chat_id)
    try:
        _SUMMARY_MARKER.write_text(week_key)
    except OSError:
        logger.warning("Could not persist the weekly-summary marker.")


def handle_text(chat_id, text: str) -> None:
    t = text.strip()
    low = t.lower()
    if low in ("/start", "/help", "help"):
        send(chat_id, HELP)
    elif low.startswith("/restock"):
        cmd_restock(chat_id)
    elif low.startswith("/budget"):
        cmd_budget(chat_id)
    elif low.startswith("/meals"):
        # Any word after /meals is a profile key (custom profiles included);
        # without one, the default profile from the settings dialog is used.
        parts = low.split()
        cmd_meals(chat_id, parts[1] if len(parts) > 1 else None)
    else:
        send(chat_id, "🤔 Let me check…")
        res = _api_get(f"/ask?q={requests.utils.quote(t)}")
        send(chat_id, res.get("answer") or res.get("error") or "I couldn't work that out.")


# --- poll loop ------------------------------------------------------------- #
def main() -> None:
    if not TOKEN:
        raise SystemExit("Missing TELEGRAM_BOT_TOKEN. Create a bot via @BotFather and set it in .env.")

    # Fail loudly on a bad token: Telegram answers ok=false to every call,
    # which the poll loop would otherwise mistake for "no new messages".
    try:
        me = requests.get(f"{TG}/getMe", timeout=15).json()
    except (requests.RequestException, ValueError):
        me = None  # transient network problem — the poll loop retries anyway
    if me is not None and not me.get("ok"):
        raise SystemExit(
            "Telegram rejected TELEGRAM_BOT_TOKEN (getMe failed) — "
            "re-copy the token from @BotFather into .env and restart."
        )
    if me:
        logger.info("Authenticated as @%s", me["result"]["username"])
    logger.info("Bot polling. Allowed chats: %s", ALLOWED or "(none set — will report chat ids)")

    offset = None
    while True:
        try:
            resp = requests.get(f"{TG}/getUpdates", params={"timeout": 30, "offset": offset}, timeout=40)
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            logger.warning("getUpdates error: %s", _redact(e))
            time.sleep(5)  # back off — don't busy-loop on a persistent failure
            continue
        if not data.get("ok"):
            logger.warning("getUpdates rejected: %s", data.get("description", "unknown reason"))
            time.sleep(5)
            continue
        _maybe_weekly_summary()
        updates = data.get("result", [])

        for upd in updates:
            offset = upd["update_id"] + 1
            msg = upd.get("message") or upd.get("edited_message")
            if not msg:
                continue
            chat_id = msg["chat"]["id"]

            if not ALLOWED:
                send(chat_id, f"Your chat id is {chat_id}. "
                              "Add it to TELEGRAM_ALLOWED_CHAT_IDS in .env, then restart me.")
                continue
            if str(chat_id) not in ALLOWED:
                send(chat_id, "Sorry, this bot is private.")
                continue

            try:
                if "photo" in msg:
                    handle_photo(chat_id, msg["photo"])
                elif "text" in msg:
                    handle_text(chat_id, msg["text"])
                else:
                    send(chat_id, HELP)
            except Exception:
                logger.exception("Handler error")
                send(chat_id, "❌ Something broke handling that.")


if __name__ == "__main__":
    main()
