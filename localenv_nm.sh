#!/bin/bash
set -a
KEYS=~/AutoClaw/Shared/.secrets/keys.env
export AGENTMAIL_KEYS="$(grep -E '^AGENTMAIL_NAMEMARSHAL_KEY_[0-9]+=' $KEYS | cut -d= -f2- | tr '\n' ',' | sed 's/,$//')"
export TYPESAFE_API_KEY="$(grep -E '^TYPESAFE_API_KEY=' $KEYS | cut -d= -f2-)"
export FIRECRAWL_KEYS="$(grep -oE 'fc-[0-9a-f]{32}' "$HOME/Downloads/FIRECRAWL_KEYS_POOL_OCT27.json" | tr '\n' ',' | sed 's/,$//')"
export OWNER_EMAIL=slyvesterchiko1@gmail.com
export SEED_DIR="$HOME/projects/outreach-engine/seed"
set +a
exec "$@"
