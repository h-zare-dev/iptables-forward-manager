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

install_dependencies

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

curl -fsSL "$RAW_BASE/portfw" -o "$TMP_DIR/portfw"
curl -fsSL "$RAW_BASE/iptables-forward-manager.service" -o "$TMP_DIR/iptables-forward-manager.service"

[[ -s "$TMP_DIR/portfw" ]] || { echo "ERROR: downloaded portfw is empty." >&2; exit 1; }
[[ -s "$TMP_DIR/iptables-forward-manager.service" ]] || { echo "ERROR: downloaded service file is empty." >&2; exit 1; }
bash -n "$TMP_DIR/portfw"

install -d -m 0700 "$STATE_DIR"
[[ -e "$STATE_DIR/rules.db" ]] || install -m 0600 /dev/null "$STATE_DIR/rules.db"

install -m 0755 "$TMP_DIR/portfw" "$BIN_PATH"
install -m 0644 "$TMP_DIR/iptables-forward-manager.service" "$SERVICE_PATH"

systemctl daemon-reload
systemctl enable --now iptables-forward-manager.service >/dev/null

echo
echo "iptables-forward-manager installed successfully."
echo "Run: portfw"
