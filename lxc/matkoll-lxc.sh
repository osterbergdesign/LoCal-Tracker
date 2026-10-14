#!/usr/bin/env bash
# Matkoll — Proxmox VE helper script
#
# Run on the Proxmox host as root:
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/osterbergdesign/LoCal-Tracker/main/lxc/matkoll-lxc.sh)"
#
# Or with a saved copy:
#   bash matkoll-lxc.sh              create a new container (asks a few questions)
#   bash matkoll-lxc.sh -y           create one with the defaults, no questions
#   bash matkoll-lxc.sh update 123   update Matkoll in container 123 from GitHub, keeping its data
#
# Settings can also be given as environment variables, for example:
#   CTID=150 RAM=2048 NET=192.168.1.50/24 GATEWAY=192.168.1.1 bash matkoll-lxc.sh -y
#
# The container gets its code from GitHub and keeps it up to date with
# `matkoll-update` (run inside it) or `bash matkoll-lxc.sh update <id>` on the host.

set -Eeuo pipefail

APP="Matkoll"
REPO="${REPO:-https://github.com/osterbergdesign/LoCal-Tracker}"
BRANCH="${BRANCH:-main}"
RAW="${REPO/github.com/raw.githubusercontent.com}/$BRANCH"

# ---------------------------------------------------------------- defaults (override with env vars)
CTID="${CTID:-}"
CT_HOSTNAME="${CT_HOSTNAME:-matkoll}"
CORES="${CORES:-2}"
RAM="${RAM:-1024}"            # MiB
DISK="${DISK:-4}"             # GiB
BRIDGE="${BRIDGE:-vmbr0}"
NET="${NET:-dhcp}"            # "dhcp" or a CIDR like 192.168.1.50/24
GATEWAY="${GATEWAY:-}"
VLAN="${VLAN:-}"
STORAGE="${STORAGE:-}"        # rootfs storage, picked automatically if empty
TEMPLATE_STORAGE="${TEMPLATE_STORAGE:-}"
UNPRIVILEGED="${UNPRIVILEGED:-1}"
PORT="${PORT:-8080}"
OLLAMA="${OLLAMA:-no}"        # "yes" installs Ollama inside the container (CPU)
OLLAMA_MODEL="${OLLAMA_MODEL:-qwen2.5vl:7b}"
OLLAMA_URL="${OLLAMA_URL:-}"  # an Ollama server you already run elsewhere
ROOT_PASSWORD="${ROOT_PASSWORD:-}"
SSH_KEY_FILE="${SSH_KEY_FILE:-}"

# ---------------------------------------------------------------- output helpers
if [[ -t 1 ]]; then
  BL=$'\e[36m'; GN=$'\e[32m'; RD=$'\e[31m'; YW=$'\e[33m'; BD=$'\e[1m'; CL=$'\e[0m'
else
  BL=""; GN=""; RD=""; YW=""; BD=""; CL=""
fi
msg()  { printf ' %s•%s %s\n' "$BL" "$CL" "$*"; }
ok()   { printf ' %s✓%s %s\n' "$GN" "$CL" "$*"; }
warn() { printf ' %s!%s %s\n' "$YW" "$CL" "$*"; }
die()  { printf ' %s✗ %s%s\n' "$RD" "$*" "$CL" >&2; exit 1; }
trap 'die "Stopped at line $LINENO: $BASH_COMMAND"' ERR

header() {
  cat <<EOF
${BD}${BL}
   __  __       _   _          _ _
  |  \/  | __ _| |_| | _____  | | |
  | |\/| |/ _\` | __| |/ / _ \ | | |
  | |  | | (_| | |_|   < (_) || | |
  |_|  |_|\__,_|\__|_|\_\___/ |_|_|
${CL}  Household meal planner and calorie tracker

EOF
}

# ---------------------------------------------------------------- host checks
check_host() {
  [[ $EUID -eq 0 ]] || die "Run this as root on the Proxmox host."
  command -v pct >/dev/null && command -v pveam >/dev/null || die "This doesn't look like a Proxmox VE host (pct not found)."
  [[ "$(uname -m)" == "x86_64" || "$(uname -m)" == "aarch64" ]] || die "Unsupported CPU architecture: $(uname -m)"
}

# ---------------------------------------------------------------- install inside the container
# The real installer lives in the repo (lxc/install.sh), so it's always current.
run_installer() {
  local ctid="$1"
  pct exec "$ctid" -- env LANG=C.UTF-8 LC_ALL=C.UTF-8 DEBIAN_FRONTEND=noninteractive bash -c \
    "command -v curl >/dev/null || { apt-get update -qq && apt-get install -y -qq curl ca-certificates >/dev/null; }"
  pct exec "$ctid" -- env LANG=C.UTF-8 LC_ALL=C.UTF-8 \
    PORT="$PORT" OLLAMA="$OLLAMA" OLLAMA_MODEL="$OLLAMA_MODEL" OLLAMA_URL="$OLLAMA_URL" \
    REPO="$REPO" BRANCH="$BRANCH" \
    bash -c "curl -fsSL '$RAW/lxc/install.sh' -o /tmp/matkoll-install.sh && bash /tmp/matkoll-install.sh; rc=\$?; rm -f /tmp/matkoll-install.sh; exit \$rc"
}

# ---------------------------------------------------------------- questions
YES=0
ask() { # ask <var> <title> <prompt>  — keeps the current value as default
  local var="$1" title="$2" prompt="$3" val
  [[ $YES -eq 1 ]] && return 0
  val=$(whiptail --backtitle "Matkoll LXC" --title "$title" --inputbox "$prompt" 10 64 "${!var}" 3>&1 1>&2 2>&3) || die "Cancelled."
  printf -v "$var" '%s' "$val"
}

pick_storage() { # pick_storage <content> <var> <title>
  local content="$1" var="$2" title="$3" list=() line name type free n=0
  [[ -n "${!var}" ]] && return 0
  while read -r name type _ _ _ free _; do
    [[ "$name" == "Name" || -z "$name" ]] && continue
    list+=("$name" "$type, $((free / 1024 / 1024)) GiB free")
    n=$((n + 1))
  done < <(pvesm status -content "$content" 2>/dev/null)
  [[ $n -gt 0 ]] || die "No storage on this host can hold $content."
  if [[ $n -eq 1 || $YES -eq 1 ]]; then
    printf -v "$var" '%s' "${list[0]}"
  else
    local choice
    choice=$(whiptail --backtitle "Matkoll LXC" --title "$title" --menu "Where should it go?" 16 64 6 "${list[@]}" 3>&1 1>&2 2>&3) || die "Cancelled."
    printf -v "$var" '%s' "$choice"
  fi
}

questions() {
  [[ -n "$CTID" ]] || CTID="$(pvesh get /cluster/nextid)"
  if [[ $YES -eq 0 ]]; then
    command -v whiptail >/dev/null || die "whiptail is missing. Run with -y to use the defaults."
    if whiptail --backtitle "Matkoll LXC" --title "$APP" --yesno \
      "Create a new Matkoll container with these settings?\n\n  ID ${CTID} · ${CORES} cores · ${RAM} MiB RAM · ${DISK} GiB disk\n  Network: ${NET} on ${BRIDGE}\n  Port ${PORT}\n\nChoose No to change them." 15 64; then
      YES=1
    fi
  fi
  ask CTID "Container ID" "Container ID"
  ask CT_HOSTNAME "Hostname" "Hostname"
  ask CORES "CPU" "CPU cores"
  ask RAM "Memory" "RAM in MiB (8192 or more if you'll run Ollama inside it)"
  ask DISK "Disk" "Disk size in GiB (20 or more if you'll run Ollama inside it)"
  ask BRIDGE "Network" "Network bridge"
  ask NET "Network" "IPv4: dhcp, or an address with prefix like 192.168.1.50/24"
  if [[ "$NET" != "dhcp" ]]; then
    ask GATEWAY "Network" "Gateway, for example 192.168.1.1"
  fi
  ask VLAN "Network" "VLAN tag (empty for none)"
  ask PORT "Port" "Port Matkoll listens on"
  if [[ $YES -eq 0 ]]; then
    local choice
    choice=$(whiptail --backtitle "Matkoll LXC" --title "Photo recognition" --menu \
      "Photos can be recognised by a vision model. Cloud API keys (Claude, OpenAI) can be added later in the app." 17 74 3 \
      "later"    "Set it up later in the app" \
      "existing" "Use an Ollama server I already run" \
      "install"  "Install Ollama in this container (CPU only, slow)" 3>&1 1>&2 2>&3) || die "Cancelled."
    case "$choice" in
      existing) OLLAMA_URL="${OLLAMA_URL:-http://192.168.1.10:11434}"; ask OLLAMA_URL "Ollama" "Address of your Ollama server"
                ask OLLAMA_MODEL "Ollama" "Vision model on that server" ;;
      install)  OLLAMA="yes"; ask OLLAMA_MODEL "Ollama" "Vision model to download (qwen2.5vl:3b is lighter, qwen2.5vl:7b is better)"
                if [[ $RAM -lt 8192 ]]; then RAM=8192; warn "Raised RAM to 8192 MiB for the model."; fi
                if [[ $DISK -lt 20 ]]; then DISK=20; warn "Raised disk to 20 GiB for the model."; fi ;;
    esac
  elif [[ "$OLLAMA" == "yes" ]]; then
    if [[ $RAM -lt 8192 ]]; then RAM=8192; fi
    if [[ $DISK -lt 20 ]]; then DISK=20; fi
  fi

  [[ "$CTID" =~ ^[0-9]+$ ]] || die "Container ID must be a number."
  if pct status "$CTID" >/dev/null 2>&1 || qm status "$CTID" >/dev/null 2>&1; then
    die "ID $CTID is already in use."
  fi
  [[ "$NET" == "dhcp" || "$NET" =~ ^[0-9.]+/[0-9]+$ ]] || die "Network must be dhcp or an address like 192.168.1.50/24."
  pick_storage rootdir STORAGE "Container storage"
  pick_storage vztmpl TEMPLATE_STORAGE "Template storage"
}

# ---------------------------------------------------------------- container
get_template() {
  msg "Finding the newest Debian template"
  pveam update >/dev/null 2>&1 || warn "Couldn't refresh the template list; using what's cached."
  # Proxmox VE 8 can only run Debian 12 containers; 9 and later also take Debian 13+.
  local pve_major pattern tpl
  pve_major="$(pveversion 2>/dev/null | sed -n 's#^pve-manager/\([0-9]*\).*#\1#p')"
  if [[ "${pve_major:-8}" -ge 9 ]]; then pattern='debian-1[2-9]'; else pattern='debian-12'; fi
  tpl=$(pveam available --section system 2>/dev/null | awk '{print $2}' | grep -E "^${pattern}-standard_.*_(amd64|arm64)\.tar\.(zst|gz|xz)$" | sort -V | tail -n1)
  [[ -n "$tpl" ]] || die "No Debian 12+ template found. Check the host's internet connection."
  if ! pveam list "$TEMPLATE_STORAGE" 2>/dev/null | grep -q "$tpl"; then
    msg "Downloading $tpl"
    pveam download "$TEMPLATE_STORAGE" "$tpl" >/dev/null
  fi
  TEMPLATE="$TEMPLATE_STORAGE:vztmpl/$tpl"
  ok "Template $tpl"
}

create_container() {
  local net="name=eth0,bridge=$BRIDGE"
  if [[ "$NET" == "dhcp" ]]; then
    net+=",ip=dhcp"
  else
    net+=",ip=$NET"
    if [[ -n "$GATEWAY" ]]; then net+=",gw=$GATEWAY"; fi
  fi
  if [[ -n "$VLAN" ]]; then net+=",tag=$VLAN"; fi
  local args=(
    --hostname "$CT_HOSTNAME" --cores "$CORES" --memory "$RAM" --swap 512
    --rootfs "$STORAGE:$DISK" --net0 "$net" --ostype debian
    --unprivileged "$UNPRIVILEGED" --features nesting=1 --onboot 1
    --timezone host --tags "matkoll" --description "Matkoll — http://<ip>:${PORT}"
  )
  if [[ -n "$ROOT_PASSWORD" ]]; then args+=(--password "$ROOT_PASSWORD"); fi
  if [[ -n "$SSH_KEY_FILE" ]]; then args+=(--ssh-public-keys "$SSH_KEY_FILE"); fi
  msg "Creating container $CTID"
  pct create "$CTID" "$TEMPLATE" "${args[@]}" >/dev/null
  ok "Container $CTID created"
  pct start "$CTID"
  msg "Waiting for the network"
  local i
  for i in $(seq 60); do
    if pct exec "$CTID" -- getent hosts deb.debian.org >/dev/null 2>&1; then ok "Network is up"; return 0; fi
    sleep 1
  done
  die "Container $CTID has no internet access. Check the bridge, VLAN and DHCP."
}

container_ip() {
  pct exec "$1" -- sh -c "hostname -I 2>/dev/null | awk '{print \$1}'" 2>/dev/null || true
}

# ---------------------------------------------------------------- commands
cmd_create() {
  header
  check_host
  questions
  get_template
  create_container
  msg "Installing Matkoll (takes a minute or two)"
  run_installer "$CTID"
  local ip; ip="$(container_ip "$CTID")"
  pct set "$CTID" --description "Matkoll — http://${ip:-<ip>}:${PORT}" >/dev/null 2>&1 || true
  echo
  ok "${BD}Matkoll is ready at http://${ip:-<container-ip>}:${PORT}${CL}"
  cat <<EOF

  1. Open that address and create the first account. It becomes the admin.
  2. The Swedish food database downloads in the background on first start.
  3. The live barcode scanner needs HTTPS. The quickest way is Tailscale inside
     the container, or point your reverse proxy at ${ip:-<container-ip>}:${PORT}.
     Then set SECURE_COOKIE=1 in /etc/matkoll/matkoll.env.
EOF
  if [[ "$OLLAMA" == "yes" ]]; then
    cat <<EOF
  4. The vision model is downloading inside the container. Follow it with:
       pct exec $CTID -- journalctl -fu matkoll-model-pull
     Photo logging works once it finishes.
EOF
  fi
  cat <<EOF

  Update later:  pct exec $CTID -- matkoll-update
  Settings:      pct exec $CTID -- nano /etc/matkoll/matkoll.env
  Logs:          pct exec $CTID -- journalctl -fu matkoll
  Backups:       daily database copies in /var/lib/matkoll/backups inside the container

EOF
}

cmd_update() {
  header
  check_host
  local ctid="${1:-}"
  [[ "$ctid" =~ ^[0-9]+$ ]] || die "Usage: bash matkoll-lxc.sh update <container id>"
  pct status "$ctid" >/dev/null 2>&1 || die "Container $ctid doesn't exist."
  if ! pct status "$ctid" | grep -q running; then pct start "$ctid"; sleep 3; fi
  pct exec "$ctid" -- test -f /etc/systemd/system/matkoll.service || die "Container $ctid doesn't have Matkoll installed."
  msg "Updating Matkoll in container $ctid from $REPO ($BRANCH)"
  # Works for both GitHub-based installs and older bundled ones (it converts those).
  OLLAMA="no"
  run_installer "$ctid"
}

main() {
  case "${1:-}" in
    update) shift; cmd_update "$@" ;;
    -y|--yes) YES=1; cmd_create ;;
    -h|--help) echo "Usage: bash matkoll-lxc.sh [-y | update <container id>]" ;;
    "") cmd_create ;;
    *) die "Unknown option: $1 (try --help)" ;;
  esac
}

main "$@"
