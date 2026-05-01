#!/bin/bash
# daily_run.sh — daily eBay Bowman 1st auto auction scan
set -euo pipefail

PYTHON="/Library/Frameworks/Python.framework/Versions/3.14/bin/python3"
PROJECT_DIR="/Users/brysonduhon/ebay-bowman-bid"
LOG="$PROJECT_DIR/scan.log"

cd "$PROJECT_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')]  $*" | tee -a "$LOG"; }

exec > >(tee -a "$LOG") 2>&1

log "========================================"
log "eBay Bowman scan starting"
log "========================================"

"$PYTHON" -m src.scan "$@"

log "Done."
