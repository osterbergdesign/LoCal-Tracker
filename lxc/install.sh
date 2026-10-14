#!/usr/bin/env bash
# Installs or updates Matkoll inside a Debian/Ubuntu machine or container.
# Safe to run again: it updates the code from GitHub and keeps data and settings.
#
#   curl -fsSL https://raw.githubusercontent.com/osterbergdesign/LoCal-Tracker/main/lxc/install.sh -o install.sh && bash install.sh
#
# Optional environment variables (used on first install):
#   PORT=8080  OLLAMA=yes|no  OLLAMA_MODEL=qwen2.5vl:7b  OLLAMA_URL=http://host:11434
#   REPO=https://github.com/osterbergdesign/LoCal-Tracker  BRANCH=main
set -Eeuo pipefail

DEFAULT_REPO="https://github.com/osterbergdesign/LoCal-Tracker"
REPO_ARG="${REPO:-}"
BRANCH_ARG="${BRANCH:-}"
PORT="${PORT:-8080}"
OLLAMA="${OLLAMA:-no}"
OLLAMA_MODEL="${OLLAMA_MODEL:-qwen2.5vl:7b}"
OLLAMA_URL="${OLLAMA_URL:-}"

SRC=/opt/matkoll/src
DATA=/var/lib/matkoll
ENV_FILE=/etc/matkoll/matkoll.env

export DEBIAN_FRONTEND=noninteractive
# The host's locale (e.g. en_US.UTF-8) usually isn't installed in a fresh container.
export LANG=C.UTF-8 LC_ALL=C.UTF-8
unset LANGUAGE

say() { echo " • $*"; }
trap 'echo " ✗ Stopped at line $LINENO: $BASH_COMMAND" >&2' ERR
[[ $EUID -eq 0 ]] || { echo " ✗ Run as root." >&2; exit 1; }

# Remember where the code comes from, so matkoll-update uses the same place.
mkdir -p /etc/matkoll
REPO=""; BRANCH=""
if [[ -f /etc/matkoll/source ]]; then
  # shellcheck disable=SC1091
  . /etc/matkoll/source
fi
REPO="${REPO_ARG:-${REPO:-$DEFAULT_REPO}}"
BRANCH="${BRANCH_ARG:-${BRANCH:-main}}"
printf 'REPO=%s\nBRANCH=%s\n' "$REPO" "$BRANCH" >/etc/matkoll/source

FIRST_INSTALL=1
[[ -f /etc/systemd/system/matkoll.service ]] && FIRST_INSTALL=0

if [[ $FIRST_INSTALL -eq 0 && -f $DATA/matkoll.db && -x /usr/local/bin/matkoll-backup ]]; then
  say "Backing up the database"
  /usr/local/bin/matkoll-backup >/dev/null || echo " ! Backup failed, continuing"
fi

say "Installing system packages"
apt-get update -qq
apt-get install -y -qq python3 python3-venv git curl ca-certificates sqlite3 >/dev/null

id matkoll >/dev/null 2>&1 || useradd --system --home-dir "$DATA" --shell /usr/sbin/nologin matkoll
mkdir -p /opt/matkoll "$DATA"

say "Getting the code from $REPO ($BRANCH)"
if [[ -d $SRC/.git ]]; then
  git -C "$SRC" remote set-url origin "$REPO"
  git -C "$SRC" fetch -q --depth 1 origin "$BRANCH"
  git -C "$SRC" reset -q --hard FETCH_HEAD
else
  # Older installs had the code copied in without git; keep the barcode decoder if it's there.
  if [[ -d $SRC ]]; then
    [[ -s $SRC/app/static/vendor/zxing.min.js ]] && cp "$SRC/app/static/vendor/zxing.min.js" /opt/matkoll/zxing.min.js
    rm -rf "$SRC"
  fi
  git clone -q --depth 1 --branch "$BRANCH" "$REPO" "$SRC"
fi
VERSION="$(git -C "$SRC" log -1 --format='%cs %h')"

say "Installing Python packages"
[[ -x /opt/matkoll/venv/bin/python ]] || python3 -m venv /opt/matkoll/venv
/opt/matkoll/venv/bin/pip install -q --upgrade pip
/opt/matkoll/venv/bin/pip install -q -r "$SRC/requirements.txt"

# Barcode decoder for iPhone Safari and Firefox (Chrome on Android has one built in).
# It's kept outside the git checkout and linked in.
if [[ ! -s /opt/matkoll/zxing.min.js ]]; then
  say "Downloading the barcode decoder"
  curl -fsSL --retry 3 -o /opt/matkoll/zxing.min.js \
    https://cdn.jsdelivr.net/npm/@zxing/library@0.21.3/umd/index.min.js \
  || { rm -f /opt/matkoll/zxing.min.js; echo " ! Couldn't download the barcode decoder. Live scanning on iPhone won't work; everything else will."; }
fi
mkdir -p "$SRC/app/static/vendor"
[[ -s /opt/matkoll/zxing.min.js ]] && ln -sf /opt/matkoll/zxing.min.js "$SRC/app/static/vendor/zxing.min.js"

if [[ "$OLLAMA" == "yes" ]]; then
  if ! command -v ollama >/dev/null; then
    say "Installing Ollama"
    apt-get install -y -qq zstd >/dev/null || true
    curl -fsSL https://ollama.com/install.sh | sh >/dev/null
  fi
  systemctl enable --now ollama >/dev/null 2>&1 || true
  OLLAMA_URL="http://127.0.0.1:11434"
  say "Downloading the vision model ($OLLAMA_MODEL) in the background"
  systemctl stop matkoll-model-pull 2>/dev/null || true
  systemd-run --unit=matkoll-model-pull --collect /bin/bash -c \
    "for i in \$(seq 30); do ollama list >/dev/null 2>&1 && break; sleep 2; done; ollama pull '$OLLAMA_MODEL'" >/dev/null
fi

if [[ ! -f $ENV_FILE ]]; then
  cat >"$ENV_FILE" <<ENV
# Matkoll settings. Values saved in the app (You → Photo recognition) take priority over these.
# After editing: systemctl restart matkoll
DATA_DIR=$DATA
PORT=$PORT
# Set to 1 once you serve Matkoll over HTTPS.
SECURE_COOKIE=0
AUTO_IMPORT_SLV=1
AI_DEFAULT_PROVIDER=ollama
OLLAMA_URL=$OLLAMA_URL
OLLAMA_MODEL=$OLLAMA_MODEL
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-sonnet-5-5
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4.1-mini
OPENAI_BASE_URL=https://api.openai.com/v1
USDA_API_KEY=
ENV
elif [[ "$OLLAMA" == "yes" ]]; then
  sed -i "s|^OLLAMA_URL=.*|OLLAMA_URL=$OLLAMA_URL|; s|^OLLAMA_MODEL=.*|OLLAMA_MODEL=$OLLAMA_MODEL|" "$ENV_FILE"
fi
chmod 640 "$ENV_FILE"
chown root:matkoll "$ENV_FILE"
chown -R matkoll:matkoll "$DATA"
PORT="$(sed -n 's/^PORT=//p' "$ENV_FILE")"; PORT="${PORT:-8080}"

cat >/etc/systemd/system/matkoll.service <<'UNIT'
[Unit]
Description=Matkoll meal planner and calorie tracker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=matkoll
Group=matkoll
EnvironmentFile=/etc/matkoll/matkoll.env
WorkingDirectory=/opt/matkoll/src
ExecStart=/opt/matkoll/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips=*
Restart=on-failure
RestartSec=3
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
UNIT

cat >/usr/local/bin/matkoll-backup <<'BACKUP'
#!/usr/bin/env bash
# Writes a consistent copy of the database to /var/lib/matkoll/backups/, keeping the last 14.
set -euo pipefail
dir=/var/lib/matkoll/backups
mkdir -p "$dir"
out="$dir/matkoll-$(date +%F-%H%M).db"
sqlite3 /var/lib/matkoll/matkoll.db ".backup '$out'"
chown -R matkoll:matkoll "$dir"
ls -1t "$dir"/matkoll-*.db | tail -n +15 | xargs -r rm -f
echo "$out"
BACKUP
chmod 755 /usr/local/bin/matkoll-backup

cat >/usr/local/bin/matkoll-update <<'UPDATE'
#!/usr/bin/env bash
# Updates Matkoll to the latest code on GitHub. Data and settings are kept.
set -euo pipefail
. /etc/matkoll/source
raw="${REPO/github.com/raw.githubusercontent.com}/$BRANCH/lxc/install.sh"
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
curl -fsSL "$raw" -o "$tmp"
REPO="$REPO" BRANCH="$BRANCH" bash "$tmp"
UPDATE
chmod 755 /usr/local/bin/matkoll-update

cat >/etc/cron.daily/matkoll-backup <<'CRON'
#!/bin/sh
[ -f /var/lib/matkoll/matkoll.db ] && /usr/local/bin/matkoll-backup >/dev/null
CRON
chmod 755 /etc/cron.daily/matkoll-backup

systemctl daemon-reload
systemctl enable matkoll >/dev/null 2>&1
systemctl restart matkoll

for _ in $(seq 30); do
  if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    if [[ $FIRST_INSTALL -eq 1 ]]; then
      echo " ✓ Matkoll ($VERSION) is installed and running on port $PORT"
    else
      echo " ✓ Matkoll updated to $VERSION. Data and settings were kept."
    fi
    exit 0
  fi
  sleep 1
done
echo " ✗ Matkoll didn't start. Last log lines:"
journalctl -u matkoll -n 30 --no-pager
exit 1
