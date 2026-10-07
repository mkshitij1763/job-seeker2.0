#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UV="$(command -v uv)"
mkdir -p "$ROOT/data/logs" "$HOME/Library/LaunchAgents"

install_agent() {
  local label="$1" dest="$HOME/Library/LaunchAgents/$1.plist"
  sed -e "s|__ROOT__|$ROOT|g" -e "s|__UV__|$UV|g" "$ROOT/scripts/$label.plist" > "$dest"
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$dest"
  echo "Installed $dest"
}

install_agent com.kshitij.jobseeker      # daily run at 11:15 (runs on wake if the Mac was asleep)
install_agent com.kshitij.jobseeker.web  # dashboard on 127.0.0.1:8000, kept running while logged in
echo "Run the daily job now with: launchctl kickstart gui/$(id -u)/com.kshitij.jobseeker"
echo "Phone access: tailscale serve --bg 8000"
