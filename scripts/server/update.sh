#!/usr/bin/env bash
# Server half of scripts/deploy.sh; runs as root:  bash -s -- <SHA|--rollback> < update.sh
# DRY_RUN=1 prints commands instead of running them (tests use DRY_* knobs, see tests/test_deploy.py).
set -euo pipefail
HOME_DIR=${HOME_DIR:-/srv/jobseeker}
APP=$HOME_DIR/app
LOG=$HOME_DIR/data/deploy.log
DB=$HOME_DIR/data/jobseeker.db
JS=$APP/scripts/server/js
DRY_RUN=${DRY_RUN:-0}
target=${1:?usage: update.sh <sha>|--rollback}

run() {
  if [[ $DRY_RUN == 1 ]]; then
    echo "+ $*"
    if [[ -n ${DRY_FAIL:-} && "$*" == *"$DRY_FAIL"* ]]; then return 1; fi
    return 0
  fi
  "$@"
}
as_app() { run sudo -u jobseeker -H bash -c "cd $APP && $1"; }
tick_running() {
  if [[ $DRY_RUN == 1 ]]; then
    echo "+ systemctl is-active --quiet jobseeker-tick.service"
    [[ ${DRY_TICK_RUNNING:-0} == 1 ]]
  else
    systemctl is-active --quiet jobseeker-tick.service
  fi
}
user_version() {  # user_version before|after
  if [[ $DRY_RUN == 1 ]]; then
    if [[ $1 == before ]]; then echo "${DRY_UV_BEFORE:-5}"; else echo "${DRY_UV_AFTER:-${DRY_UV_BEFORE:-5}}"; fi
  else
    sqlite3 "$DB" 'PRAGMA user_version'
  fi
}
current_sha() { if [[ $DRY_RUN == 1 ]]; then echo "${DRY_OLD:-old0000}"; else git -C "$APP" rev-parse HEAD; fi; }
previous_sha() {
  if [[ $DRY_RUN == 1 ]]; then echo "${DRY_PREV-prev0000}"; return; fi
  [[ -f $LOG ]] && awk 'END { print $2 }' "$LOG"
}
base_url() {
  if [[ $DRY_RUN == 1 ]]; then echo "https://example.duckdns.org"; else grep -E '^BASE_URL=' "$HOME_DIR/.env" | cut -d= -f2-; fi
}
healthy() {
  local url i
  url="$(base_url)/healthz"
  for i in $(seq 1 15); do
    if run curl -fsS -o /dev/null "$url"; then return 0; fi
    [[ $DRY_RUN == 1 ]] && return 1
    sleep 2
  done
  return 1
}
restart_old_code() {
  as_app "git checkout -q --detach $old" || true
  as_app "$HOME_DIR/.local/bin/uv sync --frozen" || true
  run systemctl start jobseeker-web || true
  run systemctl start jobseeker-tick.timer || true
  run journalctl -u jobseeker-web -n 30 --no-pager || true
}

if [[ $target == --rollback ]]; then
  target=$(previous_sha || true)
  if [[ -z $target ]]; then echo "No previous deploy recorded in $LOG" >&2; exit 1; fi
fi

if tick_running; then
  since=$(systemctl show -p ActiveEnterTimestamp --value jobseeker-tick.service 2>/dev/null || echo "unknown")
  echo "A run is in progress since $since; try again later. Nothing was changed." >&2
  exit 2
fi

old=$(current_sha)
run systemctl stop jobseeker-tick.timer
as_app "git fetch -q origin && git checkout -q --detach $target"
as_app "$HOME_DIR/.local/bin/uv sync --frozen"

uv_before=$(user_version before)
run systemctl stop jobseeker-web
if ! run "$JS" migrate; then
  if [[ $(user_version after) == "$uv_before" ]]; then
    restart_old_code
    echo "migrate failed; schema unchanged, rolled back to $old" >&2
  else
    echo "migrate failed after changing the schema; restore data/backups/pre-migrate-v$uv_before-* by hand" >&2
  fi
  exit 1
fi
uv_after=$(user_version after)
run bash -c "echo \"$(date -u +%FT%TZ) $old -> $target user_version=$uv_before->$uv_after\" >> $LOG"

run systemctl start jobseeker-web
if ! healthy; then
  if [[ $uv_after == "$uv_before" ]]; then
    restart_old_code
    echo "/healthz failed after deploying $target; rolled back to $old" >&2
  else
    run systemctl stop jobseeker-web || true
    {
      echo "/healthz failed and the schema changed (user_version $uv_before -> $uv_after)."
      echo "The old code can't run on the new schema, so the web service stays stopped. To restore:"
      echo "  1. sudo cp $HOME_DIR/data/backups/pre-migrate-v$uv_before-<timestamp>.db $DB"
      echo "  2. scripts/deploy.sh --sha $old"
    } >&2
  fi
  exit 1
fi
run systemctl start jobseeker-tick.timer
echo "Deployed $target"
