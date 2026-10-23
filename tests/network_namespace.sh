#!/usr/bin/env bash
# Real TCP/UDP data-plane validation, entirely inside temporary netns/veth pairs.
# Does not modify host firewall, NIC, routing, conntrack, services or rules.db.
set -Eeuo pipefail

if (( EUID != 0 )); then
  echo "ERROR: run as root" >&2
  exit 1
fi
for cmd in ip nft python3 sysctl iptables; do
  command -v "$cmd" >/dev/null || { echo "ERROR: missing $cmd" >&2; exit 1; }
done

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENGINE="${1:-$ROOT/portfw-nft}"
[[ -f "$ENGINE" ]] || { echo "ERROR: engine file not found: $ENGINE" >&2; exit 1; }
TMP="$(mktemp -d)"
chmod 700 "$TMP"
NSC="pfclient$$"
NSR="pfrouter$$"
NSD="pfserver$$"
VC="pfvc$$"
VR="pfvr$$"
VRO="pfvo$$"
VD="pfvd$$"
SERVER_PID=""

cleanup() {
  set +e
  if [[ -n "$SERVER_PID" ]]; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  for ns in "$NSC" "$NSR" "$NSD"; do
    ip netns del "$ns" 2>/dev/null || true
  done
  rm -rf "$TMP"
}
trap cleanup EXIT

echo "Creating isolated namespaces: $NSC, $NSR, $NSD"
ip netns add "$NSC"
ip netns add "$NSR"
ip netns add "$NSD"

ip link add "$VC" type veth peer name "$VR"
ip link set "$VC" netns "$NSC"
ip link set "$VR" netns "$NSR"
ip link add "$VRO" type veth peer name "$VD"
ip link set "$VRO" netns "$NSR"
ip link set "$VD" netns "$NSD"

ip -n "$NSC" link set "$VC" name eth0
ip -n "$NSR" link set "$VR" name eth0
ip -n "$NSR" link set "$VRO" name eth1
ip -n "$NSD" link set "$VD" name eth0
for ns in "$NSC" "$NSR" "$NSD"; do ip -n "$ns" link set lo up; done

ip -n "$NSC" address add 198.18.11.2/24 dev eth0
ip -n "$NSR" address add 198.18.11.1/24 dev eth0
ip -n "$NSR" address add 198.18.11.3/24 dev eth0 # secondary/floating-style local IPv4
ip -n "$NSR" address add 198.18.12.1/24 dev eth1
ip -n "$NSD" address add 198.18.12.2/24 dev eth0
ip -n "$NSC" link set eth0 up
ip -n "$NSR" link set eth0 up
ip -n "$NSR" link set eth1 up
ip -n "$NSD" link set eth0 up
ip -n "$NSC" route add default via 198.18.11.1
ip -n "$NSR" route add default via 198.18.12.2
ip -n "$NSD" route add default via 198.18.12.1

STATE="$TMP/state"
install -d -m 0700 "$STATE"
cat > "$STATE/rules.db" <<'RULES'
1|2001-2003,2010|198.18.12.2|3001-3003,8080|both
2|5001|edge.example.net|6001|tcp
RULES
echo 'edge.example.net|198.18.12.2' > "$STATE/dns-cache.db"
chmod 600 "$STATE/rules.db" "$STATE/dns-cache.db"

ip netns exec "$NSD" python3 "$ROOT/tests/echo_probe.py" server "$TMP/ready" >"$TMP/server.log" 2>&1 &
SERVER_PID="$!"
for _ in {1..50}; do
  [[ -f "$TMP/ready" ]] && break
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    cat "$TMP/server.log" >&2; exit 1
  fi
  sleep 0.1
done
[[ -f "$TMP/ready" ]] || { echo "ERROR: echo probes failed to start" >&2; cat "$TMP/server.log"; exit 1; }

echo "Applying the actual native engine ONLY inside $NSR"
ip netns exec "$NSR" env PORTFW_STATE_DIR="$STATE" PORTFW_LOCK="$TMP/.lock" python3 "$ENGINE" check
ip netns exec "$NSR" env PORTFW_STATE_DIR="$STATE" PORTFW_LOCK="$TMP/.lock" python3 "$ENGINE" apply
ip netns exec "$NSR" nft list table ip ifm_portfw > "$TMP/native-rule-list.txt"

for proto in tcp udp; do
  for mapping in 2001:3001 2002:3002 2003:3003 2010:8080; do
    source_port="${mapping%%:*}"
    target_port="${mapping##*:}"
    ip netns exec "$NSC" python3 "$ROOT/tests/echo_probe.py" probe "$proto" "$source_port" "$target_port"
  done
done
ip netns exec "$NSC" python3 "$ROOT/tests/echo_probe.py" probe tcp 5001 6001

echo "Forwarding must accept packets to the secondary/floating local IPv4"
ip netns exec "$NSC" env PORTFW_PROBE_SERVER_IP=198.18.11.3 python3 "$ROOT/tests/echo_probe.py" probe tcp 2001 3001
ip netns exec "$NSC" env PORTFW_PROBE_SERVER_IP=198.18.11.3 python3 "$ROOT/tests/echo_probe.py" probe udp 2010 8080

echo "Reapply idempotence and verify traffic continues"
ip netns exec "$NSR" env PORTFW_STATE_DIR="$STATE" PORTFW_LOCK="$TMP/.lock" python3 "$ENGINE" reload
ip netns exec "$NSC" python3 "$ROOT/tests/echo_probe.py" probe tcp 2001 3001
ip netns exec "$NSC" python3 "$ROOT/tests/echo_probe.py" probe udp 2010 8080

echo "Invalid one-to-one cardinality MUST fail without changing rules"
cp "$STATE/rules.db" "$TMP/before.db"
if ip netns exec "$NSR" env PORTFW_STATE_DIR="$STATE" PORTFW_LOCK="$TMP/.lock" python3 "$ENGINE" add "2200-2204" "198.18.12.2" "3300-3302" "tcp"; then
  echo "ERROR: unequal source/destination port counts were accepted" >&2
  exit 1
fi
cmp "$TMP/before.db" "$STATE/rules.db"
ip netns exec "$NSC" python3 "$ROOT/tests/echo_probe.py" probe tcp 2001 3001

echo "SUCCESS: isolated TCP/UDP forwarding, positional ranges/lists, domain cache, SNAT and reload."
echo "Host firewall and existing service were not touched."
