#!/bin/bash
#
# Nightly full re-index of the home directory link map. Run via the
# local.lnmap.nightly-index LaunchAgent; see
# ~/Library/LaunchAgents/local.lnmap.nightly-index.plist.
#
# launchd truncates StandardOutPath/StandardErrorPath on each run rather
# than appending, so this script does its own append-logging instead.
#
# lnmap index can occasionally hang indefinitely -- e.g. a macOS permission
# prompt with nobody there to answer it. TIMEOUT_SECONDS bounds the whole
# run so one stuck night doesn't block every night after it. If it fires,
# run `lnmap check ~` to see where indexing got stuck.
set -euo pipefail

LOG_FILE="$HOME/.lnmap_nightly_index.log"
TIMEOUT_SECONDS=3600

{
    echo "=== $(date) ==="

    /Users/richard/.venv/bin/lnmap index -q ~ &
    pid=$!

    ( sleep "$TIMEOUT_SECONDS"; kill -9 "$pid" 2>/dev/null ) &
    watchdog=$!

    if wait "$pid"; then
        echo "--- done ---"
    else
        echo "--- lnmap index did not finish within ${TIMEOUT_SECONDS}s and was killed; run 'lnmap check ~' to see where it got stuck ---"
    fi

    kill "$watchdog" 2>/dev/null || true
    wait "$watchdog" 2>/dev/null || true
} >> "$LOG_FILE" 2>&1
