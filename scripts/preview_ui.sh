#!/usr/bin/env bash
# Preview the ui-redesign branch on :8001 (Tailscale :8443) against the real data.
# Usage: scripts/preview_ui.sh install | remove
set -euo pipefail
WORKTREE="$(cd "$(dirname "$0")/.." && pwd)"
MAIN="$(cd "$WORKTREE/../job-seeker2.0" && pwd)"
UV="$(command -v uv)"
LABEL=com.kshitij.jobseeker.uipreview
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
TS=/Applications/Tailscale.app/Contents/MacOS/Tailscale

case "${1:-}" in
  install)
    sed -e "s|__UV__|$UV|g" -e "s|__WORKTREE__|$WORKTREE|g" -e "s|__MAIN__|$MAIN|g" \
      "$WORKTREE/scripts/$LABEL.plist" > "$DEST"
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$DEST"
    "$TS" serve --bg --https=8443 http://127.0.0.1:8001
    echo "Preview: https://delulu.tail1c97dd.ts.net:8443" ;;
  remove)
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    rm -f "$DEST"
    "$TS" serve --https=8443 off || true
    echo "Preview stopped. Remove the worktree with: git -C \"$MAIN\" worktree remove \"$WORKTREE\"" ;;
  *) echo "usage: $0 install|remove" >&2; exit 2 ;;
esac
