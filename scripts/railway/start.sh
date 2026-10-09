#!/bin/bash
# The Railway container's entrypoint (Dockerfile CMD): migrate, then the web and a 5-minute tick loop side by side.
# On a VM, systemd does this job (scripts/server/templates); here one process supervises both.
#
# It never exits on a missing database or a failed migrate: Railway would restart it in a loop and burn credit.
# It parks instead, so the data can be restored (or the problem fixed) over `railway ssh`, then the service restarted.
set -u

export JOBSEEKER_HOME="${JOBSEEKER_HOME:-/data}"

# Railway mounts the volume root-owned. Start as root, hand the volume to `app`, then re-run this script as `app`.
if [ "$(id -u)" = 0 ]; then
    mkdir -p "$JOBSEEKER_HOME"
    chown -R app:app "$JOBSEEKER_HOME"
    exec setpriv --reuid=app --regid=app --init-groups -- "$0" "$@"
fi

export HOME="$JOBSEEKER_HOME"
export BACKUP_DIR="${BACKUP_DIR:-$JOBSEEKER_HOME/backups}"
TICK_INTERVAL="${TICK_INTERVAL:-300}"
DB="$JOBSEEKER_HOME/data/jobseeker.db"

log() { echo "start.sh: $*"; }

# Stay up, serving nothing, until Railway stops the container; repeat the reason every PARK_LOG_INTERVAL seconds
# so the state is obvious in the logs at any time. Deliberately no "start empty" switch: if the volume ever fails
# to mount, a blank app would let the first Google sign-in claim ownership.
park() {
    trap 'kill "$!" 2>/dev/null; exit 0' TERM INT
    while :; do
        log "PARKED: $1"
        sleep "${PARK_LOG_INTERVAL:-300}" &
        wait "$!"
    done
}

if [ ! -f "$DB" ]; then
    park "waiting for restore at $JOBSEEKER_HOME ($DB is missing). Nothing is served. Restore over 'railway ssh' (hosting plan, Railway runbook), then restart the service."
fi
if ! jobseeker migrate; then
    park "migrate failed (see the first lines of this deployment's log). Nothing is served. Fix it over 'railway ssh', then restart the service."
fi

# The container's peak memory so far (cgroup v2), for sizing; logged after each tick.
memory_peak() {
    if [ -r /sys/fs/cgroup/memory.peak ]; then
        log "container memory peak so far: $(( $(cat /sys/fs/cgroup/memory.peak) / 1048576 )) MB"
    fi
}

# What the systemd timer does on a VM: a tick every TICK_INTERVAL seconds, each capped at 3h and at nice 10 (the
# unit's Nice=10), so the web keeps the CPU when a tick is busy. A failed tick is logged and the loop goes on.
# SIGTERM stops the running tick (or sleep) and ends the loop.
tick_loop() {
    child=""
    trap 'if [ -n "$child" ]; then kill "$child" 2>/dev/null; fi; exit 0' TERM
    while :; do
        timeout 3h nice -n 10 jobseeker tick &
        child=$!
        wait "$child"
        code=$?
        child=""
        if [ "$code" = 124 ]; then
            log "tick failed (exit 124): it hit the 3h cap and was stopped"
        elif [ "$code" != 0 ]; then
            log "tick failed (exit $code)"
        fi
        memory_peak
        sleep "$TICK_INTERVAL" &
        child=$!
        wait "$child"
        child=""
    done
}

# One uvicorn worker. Railway's proxy sets X-Forwarded-*; FORWARDED_ALLOW_IPS=* (a Railway variable) trusts it.
jobseeker serve --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers &
SERVE_PID=$!
tick_loop &
LOOP_PID=$!

# Not `exec serve`: that would drop this trap, and the tick loop with it. No wait-for-any either: macOS's test bash is 3.2.
stop() {
    kill "$SERVE_PID" "$LOOP_PID" 2>/dev/null
    wait "$SERVE_PID" "$LOOP_PID" 2>/dev/null
    exit 0
}
trap stop TERM INT

wait "$SERVE_PID"
code=$?
log "serve exited (exit $code); stopping the tick loop so Railway restarts the container"
kill "$LOOP_PID" 2>/dev/null
wait "$LOOP_PID" 2>/dev/null
if [ "$code" = 0 ]; then
    exit 1
fi
exit "$code"
