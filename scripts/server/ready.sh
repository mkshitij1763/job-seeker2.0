#!/usr/bin/env bash
# Prints what is still missing before jobseeker-web and the tick timer may be enabled. Never prints values.
# Usage: ready.sh /srv/jobseeker   (exit 0 = ready)
set -euo pipefail
home=${1:?usage: ready.sh HOME_DIR}
missing=0
for name in SECRET_KEY OWNER_EMAIL BASE_URL GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET TOKEN_KEY; do
  if ! grep -Eq "^${name}=.+" "$home/.env" 2>/dev/null; then
    echo "missing: $name"
    missing=1
  fi
done
for file in data/jobseeker.db config/app.yaml; do
  if [[ ! -f $home/$file ]]; then
    echo "missing: $file"
    missing=1
  fi
done
exit "$missing"
