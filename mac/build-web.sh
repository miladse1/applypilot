#!/bin/sh
# Build the production web app into apps/web/.next-prod, kept apart from `next dev`'s .next folder.
# On failure the previous build is restored, so the app keeps working.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
. "$ROOT/mac/common.sh"
cd "$WEB" || exit 1
[ -d node_modules ] || npm install || exit 1
rm -rf .next-prod.prev
[ -d .next-prod ] && mv .next-prod .next-prod.prev
echo "$(date '+%F %T') building the web app…"
if NEXT_DIST_DIR=.next-prod NEXT_TELEMETRY_DISABLED=1 npx next build; then
  # The standalone server serves static assets and public files from next to itself.
  cp -R .next-prod/static .next-prod/standalone/.next-prod/static
  cp -R public .next-prod/standalone/public
  rm -rf .next-prod.prev
  echo "$(date '+%F %T') build finished"
else
  echo "$(date '+%F %T') build failed; keeping the previous build" >&2
  rm -rf .next-prod
  [ -d .next-prod.prev ] && mv .next-prod.prev .next-prod
  exit 1
fi
