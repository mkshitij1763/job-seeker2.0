#!/usr/bin/env bash
# Server half of scripts/deploy.sh; runs as root:  bash -s -- <SHA|--rollback> < update.sh
# DRY_RUN=1 prints commands instead of running them (tests use DRY_* knobs, see tests/test_deploy.py).
set -Eeuo pipefail  # -E: the ERR trap below must also fire for failures inside as_app/run
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
old_code_healthy() {  # DRY_ROLLBACK_HEALTHY=1 makes the post-rollback check pass in a dry run
  if [[ $DRY_RUN == 1 && ${DRY_ROLLBACK_HEALTHY:-0} == 1 ]]; then echo "+ curl -fsS -o /dev/null $(base_url)/healthz"; return 0; fi
  healthy
}
restart_old_code() {  # $1 = what went wrong. Restart (not start): the web may already be running the new code.
  as_app "git checkout -q --detach $old" || true
  as_app "$HOME_DIR/.local/bin/uv sync --frozen" || true
  run systemctl restart jobseeker-web || true
  run systemctl start jobseeker-tick.timer || true
  if old_code_healthy; then
    echo "$1; rolled back to $old and /healthz is OK" >&2
  else
    echo "$1; rolled back to $old, but /healthz still fails. Last web log lines:" >&2
    run journalctl -u jobseeker-web -n 30 --no-pager || true
  fi
}
restore_steps() {  # $1 = user_version before the migration. Services must be stopped before the WAL files go.
  echo "  1. sudo systemctl stop jobseeker-web jobseeker-tick.timer"
  echo "  2. sudo rm -f $DB-wal $DB-shm"
  echo "  3. sudo cp $HOME_DIR/data/backups/pre-migrate-v$1-<timestamp>.db $DB"
  echo "  4. scripts/deploy.sh --sha $old"
}

if [[ $target == --rollback ]]; then
  target=$(previous_sha || true)
  if [[ -z $target ]]; then echo "No previous deploy recorded in $LOG" >&2; exit 1; fi
fi

# Stop the timer FIRST, then look: a tick can't start between the check and the stop.
run systemctl stop jobseeker-tick.timer
if tick_running; then
  since=$(systemctl show -p ActiveEnterTimestamp --value jobseeker-tick.service 2>/dev/null || echo "unknown")
  run systemctl start jobseeker-tick.timer
  echo "A run is in progress since $since; try again later. Nothing was changed." >&2
  exit 2
fi

old=$(current_sha)
before_migrate_failed() {
  trap - ERR
  restart_old_code "deploying $target failed before migrating"
  exit 1
}
trap before_migrate_failed ERR  # a failed fetch/checkout/sync must not leave the timer stopped or the code half-moved
as_app "git fetch -q origin && git checkout -q --detach $target"
as_app "$HOME_DIR/.local/bin/uv sync --frozen"
uv_before=$(user_version before)
trap - ERR

run systemctl stop jobseeker-web
if ! run "$JS" migrate; then
  if [[ $(user_version after) == "$uv_before" ]]; then
    restart_old_code "migrate failed; schema unchanged"
  else
    {
      echo "migrate failed after changing the schema. To restore:"
      restore_steps "$uv_before"
    } >&2
  fi
  exit 1
fi
uv_after=$(user_version after)
run bash -c "echo \"$(date -u +%FT%TZ) $old -> $target user_version=$uv_before->$uv_after\" >> $LOG"

run systemctl start jobseeker-web
if ! healthy; then
  if [[ $uv_after == "$uv_before" ]]; then
    restart_old_code "/healthz failed after deploying $target"
  else
    run systemctl stop jobseeker-web || true
    {
      echo "/healthz failed and the schema changed (user_version $uv_before -> $uv_after)."
      echo "The old code can't run on the new schema, so the web service stays stopped. To restore:"
      restore_steps "$uv_before"
    } >&2
  fi
  exit 1
fi
run systemctl start jobseeker-tick.timer
echo "Deployed $target"
