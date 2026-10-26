#!/usr/bin/env bash
# Safe side-by-side native installer. NEVER enables native NAT automatically.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo "Run with sudo/root" >&2; exit 1; }
REF="${PORTFW_REF:-main}"
case "$REF" in
  main|development|feature/*) ;;
  *) echo "Unsupported branch ref: $REF" >&2; exit 1 ;;
esac
RAW="https://raw.githubusercontent.com/h-zare-dev/iptables-forward-manager/$REF"
for cmd in curl python3 nft ip getent flock systemctl; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Missing command: $cmd" >&2
    echo "Install prerequisites (Debian/Ubuntu): apt-get install curl python3 nftables iproute2 util-linux libc-bin" >&2
    exit 1
  fi
done
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
for filename in portfw-nft portfw-migrate portfw-nft.service portfw-dns-refresh.service portfw-dns-refresh.timer; do
  curl -fsSL "$RAW/$filename" -o "$tmp/$filename"
  test -s "$tmp/$filename" || { echo "Empty: $filename" >&2; exit 1; }
done
python3 -m py_compile "$tmp/portfw-nft" "$tmp/portfw-migrate"
install -m 0755 "$tmp/portfw-nft" /usr/local/bin/portfw-nft
install -m 0755 "$tmp/portfw-migrate" /usr/local/bin/portfw-migrate
for unit in portfw-nft.service portfw-dns-refresh.service portfw-dns-refresh.timer; do
  install -m 0644 "$tmp/$unit" "/etc/systemd/system/$unit"
done
systemctl daemon-reload
echo "Native Port Forward Manager files installed SIDE BY SIDE (not activated)."
echo "Legacy iptables-forward-manager.service and portfw remain unchanged."
echo "Inspect: portfw-nft check && portfw-nft render && portfw-migrate preflight"
echo "Do NOT enable portfw-nft.service while legacy IFM NAT hooks are active."
