#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UV="$(command -v uv)"
LABEL="com.kshitij.jobseeker"
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p "$ROOT/data/logs" "$HOME/Library/LaunchAgents"
sed -e "s|__ROOT__|$ROOT|g" -e "s|__UV__|$UV|g" "$ROOT/scripts/$LABEL.plist" > "$DEST"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$DEST"
echo "Installed $DEST (daily 07:30; runs on wake if the Mac was asleep)."
echo "Run it now with: launchctl kickstart gui/$(id -u)/$LABEL"
