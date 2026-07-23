#!/usr/bin/env bash
# Poll-based continuous deployment for the Docker Compose setup.
#
# Fetches origin/main and redeploys ONLY when there is a new commit AND its
# CI checks are green — a broken build never reaches the box. Meant to run
# from a systemd timer (see bonfire-deploy.timer); safe to run by hand.
#
# The box never accepts inbound connections for this: it polls GitHub, which
# is also why this is a script and not a self-hosted Actions runner (GitHub
# advises against self-hosted runners on public repositories).
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")/.."
REPO_SLUG=$(git remote get-url origin | sed -E 's#.*github.com[:/]##; s#\.git$##')

git fetch -q origin main
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)
if [ "$LOCAL" = "$REMOTE" ]; then
    exit 0
fi

# Require the CI workflow on the new commit to have succeeded (public repo,
# so no token is needed). Gate on the CI workflow specifically — other apps
# (e.g. Dependabot's own update jobs) attach unrelated check-runs to the same
# commit, and their failures must not block a deploy.
VERDICT=$(curl -sf --max-time 20 \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/${REPO_SLUG}/actions/runs?head_sha=${REMOTE}" \
    | python3 -c '
import json, sys
runs = [r for r in json.load(sys.stdin).get("workflow_runs", []) if r.get("name") == "CI"]
ok = bool(runs) and runs[0].get("status") == "completed" and runs[0].get("conclusion") == "success"
print("success" if ok else "not-ready")
') || VERDICT="not-ready"

if [ "$VERDICT" != "success" ]; then
    echo "New commit ${REMOTE:0:7} found, but CI is not green yet — waiting."
    exit 0
fi

echo "Deploying ${REMOTE:0:7} (CI green)."
git merge --ff-only origin/main
# Profiled services are invisible to a plain `compose up`, so an active bot
# would keep running its pre-deploy image forever. Include the profile
# whenever the container exists on this box; boxes without the bot stay
# bot-free.
if docker ps -a --format '{{.Names}}' | grep -q '^bonfire-telegram$'; then
    docker compose --profile telegram up -d --build
else
    docker compose up -d --build
fi
echo "Deployed ${REMOTE:0:7}."
