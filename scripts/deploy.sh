#!/usr/bin/env bash
# Deploy from the Mac:  scripts/deploy.sh [--branch multi-user] [--host jobseeker] [--sha SHA] [--dry-run] [--rollback]
set -euo pipefail
cd "$(dirname "$0")/.."
BRANCH=multi-user
HOST=jobseeker
SHA=""
DRY=0
MODE=deploy
while (($#)); do
  case $1 in
    --branch) BRANCH=$2; shift 2 ;;
    --host) HOST=$2; shift 2 ;;
    --sha) SHA=$2; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    --rollback) MODE=rollback; shift ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

if [[ $MODE == rollback ]]; then
  target=--rollback
else
  if [[ -z $SHA ]]; then
    git fetch -q origin
    SHA=$(git rev-parse "origin/$BRANCH")
  fi
  if [[ $(git rev-parse HEAD 2>/dev/null) != "$SHA" ]]; then
    echo "Note: local HEAD differs from $SHA; unpushed commits are not deployed." >&2
  fi
  target=$SHA
fi

dry_env=""
if [[ $DRY == 1 ]]; then
  for name in DRY_FAIL DRY_TICK_RUNNING DRY_UV_BEFORE DRY_UV_AFTER DRY_PREV DRY_OLD; do
    if [[ -n ${!name+x} ]]; then dry_env+=" $name=$(printf '%q' "${!name}")"; fi
  done
fi
ssh "$HOST" "sudo DRY_RUN=$DRY$dry_env bash -s -- $target" < scripts/server/update.sh
