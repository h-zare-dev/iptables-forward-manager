#!/usr/bin/env bash
set -Eeuo pipefail

REPO_OWNER="h-zare-dev"
REPO_NAME="iptables-forward-manager"
REF="${PORTFW_REF:-main}"
RAW_BASE="https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/${REF}"

BIN_PATH="/usr/local/bin/portfw"
SERVICE_PATH="/etc/systemd/system/iptables-forward-manager.service"
STATE_DIR="/etc/iptables-forward-manager"

if [[ ${EUID} -ne 0 ]]; then
  echo "ERROR: run the installer as root (or with sudo)." >&2
  exit 1
fi

install_dependencies() {
  local missing=0 cmd
  for cmd in curl ip iptables flock sysctl; do
    command -v "$cmd" >/dev/null 2>&1 || missing=1
  done

  (( missing == 0 )) && return 0

  if ! command -v apt-get >/dev/null 2>&1; then
    echo "ERROR: missing required commands. Automatic dependency installation currently supports Debian/Ubuntu only." >&2
    exit 1
  fi

  echo "Installing required packages..."
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    curl iproute2 iptables util-linux procps
}

download_file() {
  local url="$1" destination="$2" mode="$3" tmp
  tmp="$(mktemp)"
  trap 'rm -f "$tmp"' RETURN

  curl -fsSL "$url" -o "$tmp"
  [[ -s "$tmp" ]] || { echo "ERROR: downloaded file is empty: $url" >&2; return 1; }
  install -m "$mode" "$tmp" "$destination"
}

install_dependencies
install -d -m 0700 "$STATE_DIR"
[[ -e "$STATE_DIR/rules.db" ]] || install -m 0600 /dev/null "$STATE_DIR/rules.db"

download_file "$RAW_BASE/portfw" "$BIN_PATH" 0755
download_file "$RAW_BASE/iptables-forward-manager.service" "$SERVICE_PATH" 0644

systemctl daemon-reload
systemctl enable --now iptables-forward-manager.service >/dev/null

echo
echo "iptables-forward-manager installed successfully."
echo "Run: portfw"
