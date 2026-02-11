#!/usr/bin/env bash
# Run the full hashtag-trends-to-ads pipeline.
# Designed for cron — logs to a file, exits non-zero only if ALL stages fail.
#
# crontab example (every 6 hours):
#   0 */6 * * * /opt/sharkey_hashtag_trends_ads/run_pipeline.sh
#
# Or every 8 hours (3x/day at 00:00, 08:00, 16:00):
#   0 0,8,16 * * * /opt/sharkey_hashtag_trends_ads/run_pipeline.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PY="${SCRIPT_DIR}/.venv/bin/python"
LOGDIR="${SCRIPT_DIR}/logs"
mkdir -p "$LOGDIR"
LOGFILE="${LOGDIR}/run_$(date +%Y%m%d_%H%M%S).log"

# How many tags to auto-select (override with SELECT_N env var)
SELECT_N="${SELECT_N:-10}"

# Keep last 30 log files
find "$LOGDIR" -name 'run_*.log' -type f | sort | head -n -30 | xargs -r rm -f

failures=0

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

{
    log "=== pipeline start ==="

    log "stage 1: bubble trends"
    if "$PY" -m sharkey_ads.bubble_trends --select "$SELECT_N"; then
        log "stage 1: ok"
    else
        log "stage 1: FAILED (exit $?)"
        ((failures++))
    fi

    log "stage 2: image uploads"
    if "$PY" -m sharkey_ads.ads_stage_uploads; then
        log "stage 2: ok"
    else
        log "stage 2: FAILED (exit $?)"
        ((failures++))
    fi

    log "stage 3: ad create/update"
    if "$PY" -m sharkey_ads.ad_stage_create_ad; then
        log "stage 3: ok"
    else
        log "stage 3: FAILED (exit $?)"
        ((failures++))
    fi

    if [ "$failures" -eq 0 ]; then
        log "=== pipeline finished: all stages ok ==="
    elif [ "$failures" -lt 3 ]; then
        log "=== pipeline finished: $failures stage(s) had errors (partial success) ==="
    else
        log "=== pipeline finished: all stages failed ==="
    fi

} 2>&1 | tee "$LOGFILE"

# Exit non-zero only if all 3 stages failed
[ "$failures" -lt 3 ]
