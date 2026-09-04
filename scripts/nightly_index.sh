#!/bin/bash
#
# Nightly full re-index of the home directory link map. Run via the
# local.lnmap.nightly-index LaunchAgent; see
# ~/Library/LaunchAgents/local.lnmap.nightly-index.plist.
#
# launchd truncates StandardOutPath/StandardErrorPath on each run rather
# than appending, so this script does its own append-logging instead.
set -euo pipefail

LOG_FILE="$HOME/.lnmap_nightly_index.log"

{
    echo "=== $(date) ==="
    /Users/richard/.venv/bin/lnmap index -q ~
    echo "--- done ---"
} >> "$LOG_FILE" 2>&1
