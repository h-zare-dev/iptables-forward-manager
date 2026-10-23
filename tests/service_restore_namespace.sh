#!/usr/bin/env bash
# CI ONLY: verify actual systemd unit enable/start/restart with nft in a network namespace.
# The host network namespace and installed production units are NEVER modified.
set -Eeuo pipefail
[[ "${CI_PORTFW_TEST:-}" == "1" && "${GITHUB_ACTIONS:-}" == "true" ]] || {
  echo "Safety guard: only an explicit GitHub Actions CI run may invoke this test" >&2
  exit 1
}
(( EUID == 0 )) || exit 1
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NS="pfboot$$"
TMP="$(mktemp -d)"
UNIT="portfw-ci-restore-$$.service"
UNITPATH="/run/systemd/system/$UNIT"
cleanup() {
  set +e
  systemctl disable --now "$UNIT" >/dev/null 2>&1 || true
  rm -f "$UNITPATH"
  systemctl daemon-reload >/dev/null 2>&1 || true
  ip netns del "$NS" 2>/dev/null || true
  rm -rf "$TMP"
}
trap cleanup EXIT

ip netns add "$NS"
ip -n "$NS" link set lo up
# Dummy interface gives primary_ipv4() a deterministic local default route.
ip -n "$NS" link add dev eth0 type dummy
ip -n "$NS" addr add 198.18.11.1/24 dev eth0
ip -n "$NS" link set eth0 up
ip -n "$NS" route add default dev eth0
mkdir -m 700 "$TMP/state"
printf '1|2010|198.18.12.2|3010|tcp\n' > "$TMP/state/rules.db"
chmod 600 "$TMP/state/rules.db"
# A disposable systemd unit uses the exact Type/RemainAfterExit/ExecStart semantics
# as portfw-nft.service, but executes the unmodified engine in a private netns.
IP="$(command -v ip)"
PYTHON="$(command -v python3)"
cat > "$UNITPATH" <<UNIT_CONTENT
[Unit]
Description=Isolated Port Forward Manager systemd smoke test
After=network-online.target
[Service]
Type=oneshot
ExecStart=$IP netns exec $NS /usr/bin/env PORTFW_STATE_DIR=$TMP/state PORTFW_LOCK=$TMP/lock $PYTHON $ROOT/portfw-nft apply
RemainAfterExit=yes
TimeoutStartSec=40s
[Install]
WantedBy=multi-user.target
UNIT_CONTENT

systemctl daemon-reload
systemctl enable "$UNIT" >/dev/null
[[ "$(systemctl is-enabled "$UNIT")" == enabled ]]
systemctl start "$UNIT"
[[ "$(systemctl is-active "$UNIT")" == active ]]
ip netns exec "$NS" nft list table ip ifm_portfw | grep -q '2010'
# Simulate empty kernel tables at boot and have systemd run the same restore command.
ip netns exec "$NS" nft delete table ip ifm_portfw
systemctl restart "$UNIT"
[[ "$(systemctl is-active "$UNIT")" == active ]]
ip netns exec "$NS" nft list map ip ifm_portfw tcp_dnat | grep -q '198.18.12.2'
# Idempotent service restart and no unexpected legacy engine start.
systemctl restart "$UNIT"
ip netns exec "$NS" nft list table ip ifm_portfw >/dev/null
echo "PASS: real systemd enable/start/restart restores native nftables in isolated namespace."
echo "NOTE: this tests boot-restore semantics, not a full VM power-cycle."
