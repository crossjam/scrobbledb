#!/bin/sh
set -eu

PROJECT_DIR="/home/exedev/scrobbledb-exedev"
DATA_DIR="${XDG_DATA_HOME:-/home/exedev/.local/share}/dev.pirateninja.scrobbledb"
LOG_FILE="$DATA_DIR/scrobbledb-cron.log"

mkdir -p "$DATA_DIR"

{
    printf '\n===== scrobbledb daily run: %s =====\n' "$(date --iso-8601=seconds)"
    cd "$PROJECT_DIR"
    exec "$PROJECT_DIR/.venv/bin/scrobbledb" \
        --log-config "$DATA_DIR/loguru_config.toml" \
        ingest \
        --database "$DATA_DIR/scrobbledb.db" \
        --auth "$DATA_DIR/auth.json" \
        --verbose
} >>"$LOG_FILE" 2>&1
