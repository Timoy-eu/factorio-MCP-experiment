#!/usr/bin/env bash
# Starts a Factorio headless server with RCON (Linux).
# Adjust: FACTORIO_DIR, SAVE, RCON_PASSWORD.
set -euo pipefail
FACTORIO_DIR="${FACTORIO_DIR:-$HOME/factorio}"
SAVE="${SAVE:-$FACTORIO_DIR/saves/agent.zip}"
RCON_PORT="${RCON_PORT:-27015}"
RCON_PASSWORD="${RCON_PASSWORD:-secret}"

cd "$FACTORIO_DIR"
[ -f "$SAVE" ] || ./bin/x64/factorio --create "$SAVE"
exec ./bin/x64/factorio --start-server "$SAVE" \
  --server-settings "$FACTORIO_DIR/server-settings.json" \
  --rcon-port "$RCON_PORT" --rcon-password "$RCON_PASSWORD"
