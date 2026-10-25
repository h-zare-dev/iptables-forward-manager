#!/usr/bin/env bash
# Runs ONLY in a disposable Debian container (never on a host with forwarding).
set -Eeuo pipefail
[[ -f /repo/install-native.sh ]] || { echo "Must run inside disposable Debian CI container" >&2; exit 1; }
[[ -f /.dockerenv ]] || { echo "Refusing installer smoke outside container" >&2; exit 1; }
[[ "$(id -u)" == 0 ]] || exit 1
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir "$TMP/bin"
cat > "$TMP/bin/curl" <<'MOCK_CURL'
#!/usr/bin/env bash
set -Eeuo pipefail
out=""
url=""
while (( $# )); do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
[[ -n "$url" && -n "$out" ]] || exit 2
[[ "$url" == https://raw.githubusercontent.com/h-zare-dev/iptables-forward-manager/main/* ]] || exit 2
src="/repo/${url##*/}"
[[ -f "$src" ]] || exit 2
cp "$src" "$out"
MOCK_CURL
cat > "$TMP/bin/systemctl" <<'MOCK_SYSTEMCTL'
#!/usr/bin/env bash
set -Eeuo pipefail
printf '%s\n' "$*" >> "$PORTFW_INSTALL_SMOKE_SYSTEMCTL"
[[ "$*" == "daemon-reload" ]] || { echo "Unexpected systemctl mutation: $*" >&2; exit 1; }
MOCK_SYSTEMCTL
chmod 700 "$TMP/bin/curl" "$TMP/bin/systemctl"
export PATH="$TMP/bin:$PATH"
export PORTFW_INSTALL_SMOKE_SYSTEMCTL="$TMP/service-commands"
# The actual installer is executed inside this disposable filesystem, with only
# downloads and systemd daemon-reload stubbed. No host services or rules are touched.
PORTFW_REF=main bash /repo/install-native.sh
cmp /repo/portfw-nft /usr/local/bin/portfw-nft
cmp /repo/portfw-migrate /usr/local/bin/portfw-migrate
cmp /repo/portfw-nft.service /etc/systemd/system/portfw-nft.service
cmp /repo/portfw-dns-refresh.timer /etc/systemd/system/portfw-dns-refresh.timer
cmp /repo/portfw-dns-refresh.service /etc/systemd/system/portfw-dns-refresh.service
[[ -x /usr/local/bin/portfw-nft && -x /usr/local/bin/portfw-migrate ]]
[[ "$(portfw-nft --version)" == 2.1.0-rc2 ]]
[[ "$(cat "$PORTFW_INSTALL_SMOKE_SYSTEMCTL")" == "daemon-reload" ]]
grep -Fxq 'WantedBy=multi-user.target' /etc/systemd/system/portfw-nft.service
grep -Fxq 'ExecStart=/usr/local/bin/portfw-nft apply' /etc/systemd/system/portfw-nft.service
# Simulate a second install; it must be idempotent and not activate systemd.
PORTFW_REF=main bash /repo/install-native.sh
[[ "$(cat "$PORTFW_INSTALL_SMOKE_SYSTEMCTL")" == $'daemon-reload\ndaemon-reload' ]]
echo "PASS: Debian installer, exact binaries, unit metadata, no auto-activation, idempotent reinstall."
