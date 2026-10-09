#!/bin/bash
# Sets the Railway service's secret variables from YOUR Terminal (hosting plan, Railway runbook R1 step 4).
# Run it from a checkout that `railway link` points at the project:  bash scripts/railway/set-secrets.sh
#
# - SECRET_KEY, TOKEN_KEY, BACKUP_KEY and the VAPID pair are generated here, but only when the service doesn't
#   have them yet: a new TOKEN_KEY or BACKUP_KEY would orphan every stored Gmail token and every B2 backup.
# - The others are asked for with hidden input. Press Enter to skip one (or to keep a value that's already set).
# - Each value goes to `railway variable set --stdin --skip-deploys`: never on a command line, never printed.
#   Nothing redeploys; restart or deploy the service afterwards.
set -u

SERVICE="${RAILWAY_SERVICE:-job-seeker2.0}"
ENVIRONMENT="${RAILWAY_ENVIRONMENT:-production}"
GENERATED="SECRET_KEY TOKEN_KEY BACKUP_KEY"
ASKED="GOOGLE_CLIENT_SECRET BACKUP_S3_KEY_ID BACKUP_S3_SECRET GROQ_API_KEY TAVILY_API_KEY GEMINI_API_KEY
CLOUDFLARE_API_TOKEN APIFY_API_TOKEN HUNTER_API_KEY HEALTHCHECK_PING_URL"

die() { echo "set-secrets.sh: $*" >&2; exit 1; }

jobseeker_cli() {
    if command -v jobseeker >/dev/null 2>&1; then jobseeker "$@"; else uv run --quiet jobseeker "$@"; fi
}

railway status >/dev/null 2>&1 || die "this directory isn't linked to a Railway project. Run 'railway link' here first."

# Names only: the JSON carries raw values, so it never reaches the screen.
existing=$(railway variable list --service "$SERVICE" --environment "$ENVIRONMENT" --json 2>/dev/null |
    python3 -c '
import json, sys
d = json.load(sys.stdin)
names = d.keys() if isinstance(d, dict) else [v.get("name") for v in d]
print(" ".join(n for n in names if n))
') || die "couldn't list the variables of service '$SERVICE' ($ENVIRONMENT)."

has() { case " $existing " in *" $1 "*) return 0 ;; esac; return 1; }

failed=""
put() {  # put NAME VALUE
    if printf '%s' "$2" | railway variable set "$1" --stdin --skip-deploys \
            --service "$SERVICE" --environment "$ENVIRONMENT" >/dev/null; then
        echo "  $1 set"
    else
        echo "set-secrets.sh: setting $1 failed" >&2
        failed="$failed $1"
    fi
}

if has VAPID_PRIVATE_KEY && ! has VAPID_PUBLIC_KEY || has VAPID_PUBLIC_KEY && ! has VAPID_PRIVATE_KEY; then
    die "only half of the VAPID pair is set. Delete VAPID_PRIVATE_KEY and VAPID_PUBLIC_KEY in the dashboard, then rerun."
fi

echo "Generated keys (service $SERVICE, $ENVIRONMENT):"
made=""
for name in $GENERATED; do
    if has "$name"; then
        echo "  $name already set, kept"
    else
        put "$name" "$(jobseeker_cli gen-key)"
        made="$made $name"
    fi
done
if has VAPID_PRIVATE_KEY; then
    echo "  VAPID pair already set, kept"
else
    pair=$(jobseeker_cli vapid-keys) || die "jobseeker vapid-keys failed"
    put VAPID_PRIVATE_KEY "$(printf '%s\n' "$pair" | sed -n 's/^VAPID_PRIVATE_KEY=//p')"
    put VAPID_PUBLIC_KEY "$(printf '%s\n' "$pair" | sed -n 's/^VAPID_PUBLIC_KEY=//p')"
    unset pair
fi

echo
echo "Secrets from your accounts (input is hidden; Enter skips):"
for name in $ASKED; do
    if has "$name"; then hint=" (already set; Enter keeps it)"; else hint=""; fi
    IFS= read -r -s -p "  $name$hint: " value
    echo >&2
    if [ -n "$value" ]; then put "$name" "$value"; fi
done
unset value

echo
echo "Save BACKUP_KEY and TOKEN_KEY in your password manager now (Railway dashboard → $SERVICE → Variables)."
echo "Without BACKUP_KEY no B2 backup can be decrypted, and both must move with the data when the trial ends."
case "$made" in *KEY*) echo "New this run:$made" ;; esac
echo "Nothing was redeployed. Restart the service when you're done."

[ -z "$failed" ] || die "these were NOT set:$failed"
