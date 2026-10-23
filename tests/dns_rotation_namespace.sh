#!/usr/bin/env bash
# DNS failover data-plane test in throwaway namespaces, never on host firewall.
set -Eeuo pipefail
(( EUID == 0 )) || { echo "Requires root" >&2; exit 1; }
for cmd in ip nft python3 iptables sysctl; do command -v "$cmd" >/dev/null || exit 1; done
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
NSC="pfdc$$"; NSR="pfdr$$"; NSD="pfds$$"
VC="pfdvc$$"; VR="pfdvr$$"; VRO="pfdvo$$"; VD="pfdvd$$"
SERVER_PID=""
cleanup() {
  set +e
  if [[ -n "$SERVER_PID" ]]; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  for ns in "$NSC" "$NSR" "$NSD"; do ip netns del "$ns" 2>/dev/null || true; done
  rm -rf "$TMP"
}
trap cleanup EXIT
ip netns add "$NSC"; ip netns add "$NSR"; ip netns add "$NSD"
ip link add "$VC" type veth peer name "$VR"
ip link set "$VC" netns "$NSC"; ip link set "$VR" netns "$NSR"
ip link add "$VRO" type veth peer name "$VD"
ip link set "$VRO" netns "$NSR"; ip link set "$VD" netns "$NSD"
ip -n "$NSC" link set "$VC" name eth0
ip -n "$NSR" link set "$VR" name eth0
ip -n "$NSR" link set "$VRO" name eth1
ip -n "$NSD" link set "$VD" name eth0
for ns in "$NSC" "$NSR" "$NSD"; do ip -n "$ns" link set lo up; done
ip -n "$NSC" addr add 198.18.11.2/24 dev eth0
ip -n "$NSR" addr add 198.18.11.1/24 dev eth0
ip -n "$NSR" addr add 198.18.12.1/24 dev eth1
ip -n "$NSD" addr add 198.18.12.2/24 dev eth0
ip -n "$NSD" addr add 198.18.12.3/24 dev eth0
ip -n "$NSC" link set eth0 up
ip -n "$NSR" link set eth0 up
ip -n "$NSR" link set eth1 up
ip -n "$NSD" link set eth0 up
ip -n "$NSC" route add default via 198.18.11.1
ip -n "$NSR" route add default via 198.18.12.2
ip -n "$NSD" route add default via 198.18.12.1

mkdir -m 700 "$TMP/state" "$TMP/bin"
printf '1|5001|edge.example.net|6001|tcp\n' > "$TMP/state/rules.db"
printf 'edge.example.net|198.18.12.2\n' > "$TMP/state/dns-cache.db"
printf '198.18.12.2\n' > "$TMP/dns-record"
chmod 600 "$TMP/state/"*.db
# Resolver stub is local to this test process and never affects host DNS.
cat > "$TMP/bin/getent" <<'GETENT'
#!/usr/bin/env bash
[[ "${1:-}" == "ahostsv4" && "${2:-}" == "edge.example.net" ]] || exit 2
[[ -f "$PORTFW_TEST_DNS_RECORD" ]] || exit 2
value="$(cat "$PORTFW_TEST_DNS_RECORD")"
[[ "$value" == "FAIL" ]] && exit 2
printf '%s STREAM edge.example.net\n' "$value"
GETENT
chmod 700 "$TMP/bin/getent"

ip netns exec "$NSD" python3 "$ROOT/tests/dns_probe.py" server "$TMP/ready" > "$TMP/server.log" 2>&1 &
SERVER_PID="$!"
for i in {1..50}; do
  [[ -f "$TMP/ready" ]] && break
  kill -0 "$SERVER_PID" 2>/dev/null || { cat "$TMP/server.log"; exit 1; }
  sleep .1
done
[[ -f "$TMP/ready" ]] || { cat "$TMP/server.log"; exit 1; }

ip netns exec "$NSR" env PORTFW_STATE_DIR="$TMP/state" PORTFW_LOCK="$TMP/lock" \
  python3 "$ROOT/portfw-nft" apply
ip netns exec "$NSC" python3 "$ROOT/tests/dns_probe.py" probe 198.18.12.2

before="$(ip netns exec "$NSR" nft -a list table ip ifm_portfw)"
ip netns exec "$NSR" env PATH="$TMP/bin:$PATH" PORTFW_TEST_DNS_RECORD="$TMP/dns-record" \
  PORTFW_STATE_DIR="$TMP/state" PORTFW_LOCK="$TMP/lock" python3 "$ROOT/portfw-nft" dns-refresh
after="$(ip netns exec "$NSR" nft -a list table ip ifm_portfw)"
[[ "$before" == "$after" ]] || { echo "Unchanged DNS unexpectedly altered nftables" >&2; exit 1; }

printf '198.18.12.3\n' > "$TMP/dns-record"
ip netns exec "$NSR" env PATH="$TMP/bin:$PATH" PORTFW_TEST_DNS_RECORD="$TMP/dns-record" \
  PORTFW_STATE_DIR="$TMP/state" PORTFW_LOCK="$TMP/lock" python3 "$ROOT/portfw-nft" dns-refresh
grep -Fxq 'edge.example.net|198.18.12.3' "$TMP/state/dns-cache.db"
ip netns exec "$NSR" nft list map ip ifm_portfw tcp_dnat | grep -q '198.18.12.3'
ip netns exec "$NSC" python3 "$ROOT/tests/dns_probe.py" probe 198.18.12.3

printf 'FAIL\n' > "$TMP/dns-record"
before="$(ip netns exec "$NSR" nft -a list table ip ifm_portfw)"
ip netns exec "$NSR" env PATH="$TMP/bin:$PATH" PORTFW_TEST_DNS_RECORD="$TMP/dns-record" \
  PORTFW_STATE_DIR="$TMP/state" PORTFW_LOCK="$TMP/lock" python3 "$ROOT/portfw-nft" dns-refresh
after="$(ip netns exec "$NSR" nft -a list table ip ifm_portfw)"
[[ "$before" == "$after" ]] || { echo "Failed DNS unexpectedly altered nftables" >&2; exit 1; }
grep -Fxq 'edge.example.net|198.18.12.3' "$TMP/state/dns-cache.db"
ip netns exec "$NSC" python3 "$ROOT/tests/dns_probe.py" probe 198.18.12.3

echo "PASS: real DNS A-record rotation, unchanged-no-op, failure fallback, TCP delivery and SNAT."
