# Backend image — serves the API, the inbox watcher, the scrapers, the backup
# job and the Telegram bot (same image, different commands).
#
# Build context is the REPO ROOT so the in-container layout mirrors the host:
#   /app/.env                                   (mounted at runtime)
#   /app/backend/...
#   /app/email-scraper/...
# That keeps every path anchor in the code working unchanged.

FROM python:3.12-slim-bookworm

# HOME: compose runs the services as uid 1000, which has no passwd entry —
# give libraries that write to $HOME a writable place.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/tmp

WORKDIR /app

COPY backend/requirements.txt /tmp/requirements.txt

# tzdata stays (so TZ= gives local timestamps); build tools are purged after use.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && apt-get install -y --no-install-recommends build-essential libffi-dev \
 && pip install --no-cache-dir -r /tmp/requirements.txt \
 && apt-get purge -y --auto-remove build-essential libffi-dev \
 && rm -rf /var/lib/apt/lists/* /tmp/requirements.txt

COPY backend       /app/backend
COPY email-scraper /app/email-scraper

WORKDIR /app/backend

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
