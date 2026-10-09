#!/usr/bin/env bash
# One-time, idempotent server setup for Ubuntu 24.04 (aarch64). Run as root from the Mac:
#   ssh jobseeker 'sudo BASE_URL=https://<sub>.duckdns.org OWNER_EMAIL=<email> BRANCH=multi-user bash -s' \
#     < scripts/server/bootstrap.sh
# Re-run it after adding the deploy key, after filling /etc/duckdns.env and .env, and after the data move.
set -euo pipefail

[[ -n ${BASE_URL:-} ]] || { echo "BASE_URL is required (https://<sub>.duckdns.org)" >&2; exit 1; }
[[ -n ${OWNER_EMAIL:-} ]] || { echo "OWNER_EMAIL is required" >&2; exit 1; }
[[ -n ${BRANCH:-} ]] || { echo "BRANCH is required (the branch to deploy, e.g. multi-user)" >&2; exit 1; }
[[ $BASE_URL == https://* ]] || { echo "BASE_URL must start with https://" >&2; exit 1; }
[[ $EUID -eq 0 ]] || { echo "Run as root (sudo)" >&2; exit 1; }

REPO=${REPO:-git@github.com:mkshitij1763/job-seeker2.0.git}
HOME_DIR=${HOME_DIR:-/srv/jobseeker}
DOMAIN=${BASE_URL#https://}
DOMAIN=${DOMAIN%%/*}
export DOMAIN OWNER_EMAIL HOME_DIR
CHANGED=0

put_file() {  # put_file DEST MODE < content  -- writes only when different, reports changes
  local dest=$1 mode=$2 tmp
  tmp=$(mktemp)
  cat > "$tmp"
  if [[ -f $dest ]] && cmp -s "$tmp" "$dest"; then
    rm -f "$tmp"
    return 1
  fi
  install -D -m "$mode" "$tmp" "$dest"
  rm -f "$tmp"
  echo "changed: $dest"
  CHANGED=1
}

render() { envsubst '${DOMAIN} ${OWNER_EMAIL} ${HOME_DIR}' < "$HOME_DIR/app/scripts/server/templates/$1"; }

as_js() { sudo -u jobseeker -H bash -c "$1"; }

open_port() {  # open_port iptables|ip6tables PORT  -- insert above Oracle's REJECT rule, once
  local ipt=$1 port=$2 pos
  local rule=(-p tcp -m state --state NEW --dport "$port" -j ACCEPT)
  "$ipt" -C INPUT "${rule[@]}" 2>/dev/null && return 0
  pos=$("$ipt" -L INPUT --line-numbers -n | awk '$2 == "REJECT" { print $1; exit }')
  if [[ -n $pos ]]; then "$ipt" -I INPUT "$pos" "${rule[@]}"; else "$ipt" -A INPUT "${rule[@]}"; fi
  echo "changed: $ipt INPUT accepts tcp/$port"
  CHANGED=1
}

# ---- Phase A: the system ----
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq sqlite3 git curl gettext-base iptables-persistent netfilter-persistent \
  unattended-upgrades debian-keyring debian-archive-keyring apt-transport-https gnupg >/dev/null
if [[ ! -f /etc/apt/sources.list.d/caddy-stable.list ]]; then  # (verify) against caddyserver.com/docs/install
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq
  CHANGED=1
fi
apt-get install -y -qq caddy >/dev/null

if ! id jobseeker >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "$HOME_DIR" --shell /usr/sbin/nologin jobseeker
  CHANGED=1
fi
install -d -o jobseeker -g jobseeker -m 750 "$HOME_DIR" "$HOME_DIR/data" "$HOME_DIR/data/backups" "$HOME_DIR/config"
install -d -o jobseeker -g jobseeker -m 700 "$HOME_DIR/.ssh"

open_port iptables 80
open_port iptables 443
if ip -6 addr show scope global | grep -q inet6; then
  open_port ip6tables 80
  open_port ip6tables 443
fi
netfilter-persistent save >/dev/null 2>&1

if [[ ! -s $HOME_DIR/.ssh/id_ed25519 ]]; then
  as_js "ssh-keygen -q -t ed25519 -N '' -C jobseeker-deploy -f $HOME_DIR/.ssh/id_ed25519"
  as_js "ssh-keyscan -t ed25519 github.com >> $HOME_DIR/.ssh/known_hosts 2>/dev/null"  # (verify) fingerprint vs docs.github.com
  CHANGED=1
fi
if ! as_js "git ls-remote -q $REPO HEAD" >/dev/null 2>&1; then
  echo
  echo "Add this public key as a READ-ONLY deploy key (GitHub repo -> Settings -> Deploy keys), then re-run:"
  cat "$HOME_DIR/.ssh/id_ed25519.pub"
  exit 0
fi

# ---- Phase B: the app ----
if [[ ! -x $HOME_DIR/.local/bin/uv ]]; then
  as_js 'curl -LsSf https://astral.sh/uv/install.sh | sh' >/dev/null
  CHANGED=1
fi
as_js "$HOME_DIR/.local/bin/uv python install 3.13" >/dev/null
if [[ ! -d $HOME_DIR/app/.git ]]; then  # first time only: later checkouts belong to deploy.sh
  as_js "git clone -q $REPO $HOME_DIR/app && cd $HOME_DIR/app && git checkout -q --detach origin/$BRANCH"
  CHANGED=1
fi
as_js "cd $HOME_DIR/app && $HOME_DIR/.local/bin/uv sync --frozen" >/dev/null  # stops here if a wheel is missing

if [[ ! -f $HOME_DIR/.env ]]; then
  install -o jobseeker -g jobseeker -m 600 "$HOME_DIR/app/scripts/server/env.example" "$HOME_DIR/.env"
  echo "created: $HOME_DIR/.env (empty values; fill it with: sudo -u jobseeker nano $HOME_DIR/.env)"
  CHANGED=1
fi

# put_file reads from process substitution, not a pipe: a pipe would run it in a subshell and lose CHANGED.
for unit in jobseeker-web.service jobseeker-tick.service jobseeker-tick.timer duckdns.service duckdns.timer; do
  put_file "/etc/systemd/system/$unit" 644 < <(render "$unit") || true
done
if put_file /etc/caddy/Caddyfile 644 < <(render Caddyfile); then systemctl reload caddy || true; fi
put_file /etc/apt/apt.conf.d/52jobseeker-upgrades 644 < <(render 52jobseeker-upgrades) || true
if put_file /etc/systemd/journald.conf.d/jobseeker.conf 644 < <(render journald-jobseeker.conf); then
  systemctl restart systemd-journald
fi
# --- sshd hardening ---
# sshd keeps the FIRST value it reads, so the drop-in must sort before cloud-init's 50-/60- files.
rm -f /etc/ssh/sshd_config.d/jobseeker.conf  # the pre-review name, which sorted after them
if put_file /etc/ssh/sshd_config.d/00-jobseeker.conf 644 < <(render sshd-jobseeker.conf); then
  if ! sshd -t; then
    rm -f /etc/ssh/sshd_config.d/00-jobseeker.conf
    echo "sshd -t rejected the hardening drop-in; removed it and left sshd as it was. Fix it, then re-run." >&2
    exit 1
  fi
  systemctl reload ssh
fi
# --- end sshd hardening ---
if [[ ! -f /etc/duckdns.env ]]; then
  put_file /etc/duckdns.env 600 < <(printf 'DUCKDNS_DOMAIN=%s\nDUCKDNS_TOKEN=\n' "${DOMAIN%%.*}") || true
  echo "Put your DuckDNS token in /etc/duckdns.env (sudo nano /etc/duckdns.env), then re-run."
fi
systemctl daemon-reload
systemctl enable --now caddy >/dev/null 2>&1
if grep -Eq '^DUCKDNS_TOKEN=.+' /etc/duckdns.env; then
  systemctl enable --now duckdns.timer >/dev/null 2>&1
fi

if "$HOME_DIR/app/scripts/server/ready.sh" "$HOME_DIR"; then
  systemctl enable --now jobseeker-web.service jobseeker-tick.timer >/dev/null 2>&1
else
  echo "jobseeker-web and the tick timer stay disabled until the items above are done."
fi

echo
echo "---- status ----"
for unit in caddy duckdns.timer jobseeker-web jobseeker-tick.timer; do
  printf '%-22s %s\n' "$unit" "$(systemctl is-active "$unit" 2>/dev/null || true)"
done
journalctl -u caddy -n 5 --no-pager 2>/dev/null || true
[[ $CHANGED == 1 ]] || echo "No changes."
