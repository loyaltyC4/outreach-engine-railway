#!/bin/bash
# Deploy the engine to the outreach project on the new Railway account.
# Assembles a clean build directory (engine + seed + Dockerfile), because the seed folder is gitignored on purpose.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
BUILD="$(mktemp -d)"
cp "$HERE/Dockerfile" "$BUILD/"; cp -R "$HERE/engine" "$BUILD/engine"; cp -R "$HERE/seed" "$BUILD/seed"
find "$BUILD" -name __pycache__ -prune -exec rm -rf {} +
: "${RAILWAY_API_TOKEN:?set RAILWAY_API_TOKEN}"; : "${RW_PROJECT:?}"; : "${RW_ENV:?}"; : "${RW_SERVICE:?}"
cd "$BUILD"
npx --yes @railway/cli@latest up --project "$RW_PROJECT" --environment "$RW_ENV" --service "$RW_SERVICE" --detach
echo "deployed from $BUILD"
