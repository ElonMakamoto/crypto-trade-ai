#!/usr/bin/env bash
# Commit the bot's site feed + state and push, which triggers the Cloudflare deploy.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
git config user.name "instagram-auto-bot"
git config user.email "instagram-auto-bot@users.noreply.github.com"
git add public/instagram instagram_auto/state/posted.json 2>/dev/null || true
if git diff --cached --quiet; then
  echo "nothing to publish"
  exit 0
fi
git commit -q -m "instagram_auto: new posts $(date -u +%Y-%m-%dT%H:%MZ)"
for i in 1 2 3; do
  git pull -q --rebase origin "${GITHUB_REF_NAME:-main}" && git push -q origin "HEAD:${GITHUB_REF_NAME:-main}" && exit 0
  sleep $((i * 5))
done
echo "push failed" >&2
exit 1
