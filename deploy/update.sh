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

# Require every CI check on the new commit to have succeeded (public repo,
# so no token is needed). Pending or failed checks: try again next tick.
VERDICT=$(curl -sf --max-time 20 \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/${REPO_SLUG}/commits/${REMOTE}/check-runs?filter=latest" \
    | python3 -c '
import json, sys
runs = json.load(sys.stdin).get("check_runs", [])
ok = bool(runs) and all(r.get("conclusion") == "success" for r in runs)
print("success" if ok else "not-ready")
') || VERDICT="not-ready"

if [ "$VERDICT" != "success" ]; then
    echo "New commit ${REMOTE:0:7} found, but CI is not green yet — waiting."
    exit 0
fi

echo "Deploying ${REMOTE:0:7} (CI green)."
git merge --ff-only origin/main
docker compose up -d --build
echo "Deployed ${REMOTE:0:7}."
