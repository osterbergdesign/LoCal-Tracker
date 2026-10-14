#!/usr/bin/env bash
# Installs or updates LoCal inside a Debian/Ubuntu machine or container.
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

SRC=/opt/local-tracker/src
DATA=/var/lib/local-tracker
ENV_FILE=/etc/local-tracker/local-tracker.env

export DEBIAN_FRONTEND=noninteractive
export PATH="$PATH:/usr/local/sbin:/usr/sbin:/sbin"  # pct exec may leave out the sbin folders
# The host's locale (e.g. en_US.UTF-8) usually isn't installed in a fresh container.
export LANG=C.UTF-8 LC_ALL=C.UTF-8
unset LANGUAGE

say() { echo " • $*"; }
trap 'echo " ✗ Stopped at line $LINENO: $BASH_COMMAND" >&2' ERR
[[ $EUID -eq 0 ]] || { echo " ✗ Run as root." >&2; exit 1; }
MIGRATED=0

# The app used to be called Matkoll. Move an existing Matkoll install over to the new names, once.
if [[ -f /etc/systemd/system/matkoll.service && ! -f /etc/systemd/system/local-tracker.service ]]; then
  say "Moving your Matkoll install over to LoCal (data and settings come along)"
  systemctl stop matkoll >/dev/null 2>&1 || true
  systemctl disable matkoll >/dev/null 2>&1 || true
  rm -f /etc/systemd/system/matkoll.service
  mkdir -p /var/lib/local-tracker /etc/local-tracker /opt/local-tracker
  if [[ -d /var/lib/matkoll ]]; then
    cp -a /var/lib/matkoll/. /var/lib/local-tracker/
    for suffix in "" -wal -shm; do
      if [[ -f /var/lib/local-tracker/matkoll.db$suffix ]]; then
        mv /var/lib/local-tracker/matkoll.db$suffix /var/lib/local-tracker/local-tracker.db$suffix
      fi
    done
    mv /var/lib/matkoll /var/lib/matkoll.before-rename
  fi
  if [[ -f /etc/matkoll/matkoll.env ]]; then
    sed 's#/var/lib/matkoll#/var/lib/local-tracker#' /etc/matkoll/matkoll.env >"$ENV_FILE"
  fi
  if [[ -f /etc/matkoll/source ]]; then
    cp /etc/matkoll/source /etc/local-tracker/source
  fi
  if [[ -s /opt/matkoll/zxing.min.js ]]; then
    cp /opt/matkoll/zxing.min.js /opt/local-tracker/zxing.min.js
  fi
  rm -rf /opt/matkoll /etc/matkoll /usr/local/bin/matkoll-backup /etc/cron.daily/matkoll-backup
  userdel matkoll >/dev/null 2>&1 || true
  # The old update command keeps working and points to the new one.
  cat >/usr/local/bin/matkoll-update <<'SHIM'
#!/bin/sh
echo "Matkoll is now called LoCal; next time, run local-tracker-update."
exec /usr/local/bin/local-tracker-update "$@"
SHIM
  chmod 755 /usr/local/bin/matkoll-update
  MIGRATED=1
fi

# Remember where the code comes from, so local-tracker-update uses the same place.
mkdir -p /etc/local-tracker
REPO=""; BRANCH=""
if [[ -f /etc/local-tracker/source ]]; then
  # shellcheck disable=SC1091
  . /etc/local-tracker/source
fi
REPO="${REPO_ARG:-${REPO:-$DEFAULT_REPO}}"
BRANCH="${BRANCH_ARG:-${BRANCH:-main}}"
printf 'REPO=%s\nBRANCH=%s\n' "$REPO" "$BRANCH" >/etc/local-tracker/source

FIRST_INSTALL=1
[[ -f /etc/systemd/system/local-tracker.service ]] && FIRST_INSTALL=0

if [[ $FIRST_INSTALL -eq 0 && -f $DATA/local-tracker.db && -x /usr/local/bin/local-tracker-backup ]]; then
  say "Backing up the database"
  /usr/local/bin/local-tracker-backup >/dev/null || echo " ! Backup failed, continuing"
fi

say "Installing system packages"
apt-get update -qq
apt-get install -y -qq python3 python3-venv git curl ca-certificates sqlite3 >/dev/null

id local-tracker >/dev/null 2>&1 || useradd --system --home-dir "$DATA" --shell /usr/sbin/nologin local-tracker
mkdir -p /opt/local-tracker "$DATA"

say "Getting the code from $REPO ($BRANCH)"
if [[ -d $SRC/.git ]]; then
  git -C "$SRC" remote set-url origin "$REPO"
  git -C "$SRC" fetch -q --depth 1 origin "$BRANCH"
  git -C "$SRC" reset -q --hard FETCH_HEAD
else
  # Older installs had the code copied in without git; keep the barcode decoder if it's there.
  if [[ -d $SRC ]]; then
    [[ -s $SRC/app/static/vendor/zxing.min.js ]] && cp "$SRC/app/static/vendor/zxing.min.js" /opt/local-tracker/zxing.min.js
    rm -rf "$SRC"
  fi
  git clone -q --depth 1 --branch "$BRANCH" "$REPO" "$SRC"
fi
VERSION="$(git -C "$SRC" log -1 --format='%cs %h')"

say "Installing Python packages"
[[ -x /opt/local-tracker/venv/bin/python ]] || python3 -m venv /opt/local-tracker/venv
/opt/local-tracker/venv/bin/pip install -q --upgrade pip
/opt/local-tracker/venv/bin/pip install -q -r "$SRC/requirements.txt"

# Barcode decoder for iPhone Safari and Firefox (Chrome on Android has one built in).
# It's kept outside the git checkout and linked in.
if [[ ! -s /opt/local-tracker/zxing.min.js ]]; then
  say "Downloading the barcode decoder"
  curl -fsSL --retry 3 -o /opt/local-tracker/zxing.min.js \
    https://cdn.jsdelivr.net/npm/@zxing/library@0.21.3/umd/index.min.js \
  || { rm -f /opt/local-tracker/zxing.min.js; echo " ! Couldn't download the barcode decoder. Live scanning on iPhone won't work; everything else will."; }
fi
mkdir -p "$SRC/app/static/vendor"
[[ -s /opt/local-tracker/zxing.min.js ]] && ln -sf /opt/local-tracker/zxing.min.js "$SRC/app/static/vendor/zxing.min.js"

if [[ "$OLLAMA" == "yes" ]]; then
  if ! command -v ollama >/dev/null; then
    say "Installing Ollama"
    apt-get install -y -qq zstd >/dev/null || true
    curl -fsSL https://ollama.com/install.sh | sh >/dev/null
  fi
  systemctl enable --now ollama >/dev/null 2>&1 || true
  OLLAMA_URL="http://127.0.0.1:11434"
  say "Downloading the vision model ($OLLAMA_MODEL) in the background"
  systemctl stop local-tracker-model-pull 2>/dev/null || true
  systemd-run --unit=local-tracker-model-pull --collect /bin/bash -c \
    "for i in \$(seq 30); do ollama list >/dev/null 2>&1 && break; sleep 2; done; ollama pull '$OLLAMA_MODEL'" >/dev/null
fi

if [[ ! -f $ENV_FILE ]]; then
  cat >"$ENV_FILE" <<ENV
# LoCal settings. Values saved in the app (You → Photo recognition) take priority over these.
# After editing: systemctl restart local-tracker
DATA_DIR=$DATA
PORT=$PORT
# Set to 1 once you serve LoCal over HTTPS.
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
chown root:local-tracker "$ENV_FILE"
chown -R local-tracker:local-tracker "$DATA"
PORT="$(sed -n 's/^PORT=//p' "$ENV_FILE")"; PORT="${PORT:-8080}"

cat >/etc/systemd/system/local-tracker.service <<'UNIT'
[Unit]
Description=LoCal meal planner and calorie tracker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=local-tracker
Group=local-tracker
EnvironmentFile=/etc/local-tracker/local-tracker.env
WorkingDirectory=/opt/local-tracker/src
ExecStart=/opt/local-tracker/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips=*
Restart=on-failure
RestartSec=3
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
UNIT

cat >/usr/local/bin/local-tracker-backup <<'BACKUP'
#!/usr/bin/env bash
# Writes a consistent copy of the database to /var/lib/local-tracker/backups/, keeping the last 14.
set -euo pipefail
dir=/var/lib/local-tracker/backups
mkdir -p "$dir"
out="$dir/local-tracker-$(date +%F-%H%M).db"
sqlite3 /var/lib/local-tracker/local-tracker.db ".backup '$out'"
chown -R local-tracker:local-tracker "$dir"
ls -1t "$dir"/local-tracker-*.db | tail -n +15 | xargs -r rm -f
echo "$out"
BACKUP
chmod 755 /usr/local/bin/local-tracker-backup

cat >/usr/local/bin/local-tracker-update <<'UPDATE'
#!/usr/bin/env bash
# Updates LoCal to the latest code on GitHub. Data and settings are kept.
set -euo pipefail
. /etc/local-tracker/source
raw="${REPO/github.com/raw.githubusercontent.com}/$BRANCH/lxc/install.sh"
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
curl -fsSL "$raw" -o "$tmp"
REPO="$REPO" BRANCH="$BRANCH" bash "$tmp"
UPDATE
chmod 755 /usr/local/bin/local-tracker-update

cat >/etc/cron.daily/local-tracker-backup <<'CRON'
#!/bin/sh
[ -f /var/lib/local-tracker/local-tracker.db ] && /usr/local/bin/local-tracker-backup >/dev/null
CRON
chmod 755 /etc/cron.daily/local-tracker-backup

systemctl daemon-reload
systemctl enable local-tracker >/dev/null 2>&1
systemctl restart local-tracker

for _ in $(seq 30); do
  if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    if [[ $MIGRATED -eq 1 ]]; then
      echo " ✓ Matkoll is now LoCal ($VERSION), running on port $PORT with your data. From now on update with: local-tracker-update"
      echo "   (A copy of the old data is in /var/lib/matkoll.before-rename; delete it when you're happy.)"
    elif [[ $FIRST_INSTALL -eq 1 ]]; then
      echo " ✓ LoCal ($VERSION) is installed and running on port $PORT"
    else
      echo " ✓ LoCal updated to $VERSION. Data and settings were kept."
    fi
    exit 0
  fi
  sleep 1
done
echo " ✗ LoCal didn't start. Last log lines:"
journalctl -u local-tracker -n 30 --no-pager
exit 1
