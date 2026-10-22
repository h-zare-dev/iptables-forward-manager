# Native nftables candidate (v2.0.0-rc1)

**Status: opt-in / staging only.** The stable `portfw` (iptables-nft) and its systemd service are intentionally unchanged. The candidate lives at `portfw-nft` and must NOT automatically be activated on production servers.

## Why a separate candidate?

A direct in-place upgrade would be unsafe on active high-throughput forwarding servers. The legacy application installs `IFM_DNAT`, `IFM_SNAT` and `IFM_FORWARD` chains. Running new native NAT rules in parallel with the legacy jumps can create double-NAT, rule ordering ambiguity, and dropped connections. The candidate explicitly **refuses to modify nftables while it sees the legacy `IFM_DNAT` jump active**.

Both tools currently refer to the same `/etc/iptables-forward-manager/rules.db`. Only ONE engine may own and modify this state. The installer does not change or stop the existing engine. For staging, the original file can be read without modification. Use a dedicated maintenance window for any switch.

## Supported inputs

Each rule retains one ID and five pipe-separated columns in `rules.db`:

`ID|source_ports|destination_ip_or_domain|destination_ports|protocol`

For example:

```text
1|2001|192.0.2.50|3001|tcp
2|2001-2003,2010|edge.example.net|3001-3003,8080|udp
3|7000,7003|203.0.113.9|8000,8005|both
```

- Single ports, inclusive ranges and comma-separated lists can be mixed.
- Ports map **positionally**, 1:1; counts must match exactly.
- Duplicate ports, malformed ranges, protocol overlaps and conflicting source mappings are rejected before nftables changes.
- At most 4,096 ports per rule and 10,000 protocol/port mappings total.
- Both `tcp` and `udp`, or `both`.
- IPv4 destination or canonical A-record hostname; no AAAA-only destinations in this IPv4 release.
- A hostname with multiple A records resolves to the numerically lowest eligible IPv4. This is deterministic but **not load balancing**. For Cloudflare Proxied records, the DNS IP is usually the proxy, not the origin.
- Traffic destined to currently LOCAL IPv4 addresses is eligible, retaining Primary/Floating behavior.
- The native engine uses named maps for DNAT and named sets for FORWARD and precise SNAT. No per-packet DNS requests.
- Existing conntrack sessions are not flushed when rules change. Established connections are *not migrated* to a new DNS target.

## Installation on a test server only

```bash
curl -fsSL https://raw.githubusercontent.com/h-zare-dev/iptables-forward-manager/feature/native-nft-range-dns/install-native.sh | sudo PORTFW_REF=feature/native-nft-range-dns bash
```

Prerequisites: Python 3, `nft`, `ip`, `getent`, systemd, and root privileges for mutation. On Debian/Ubuntu, install missing requirements with:

```bash
sudo apt-get install -y python3 nftables iproute2 libc-bin
```

Installation puts `/usr/local/bin/portfw-nft` alongside the old `/usr/local/bin/portfw` and installs **disabled** candidate units:

- `portfw-nft.service` — persistent native rules at boot (enable only after explicit cutover).
- `portfw-dns-refresh.service` — oneshot DNS re-resolution, separate from forwarding data plane.
- `portfw-dns-refresh.timer` — default 5 minutes, install-disabled.

No legacy service is stopped, no iptables chains are removed, no native rules are activated, and no DNS timer is enabled by the installer.

Read-only inspection:

```bash
portfw-nft check
portfw-nft list
portfw-nft render
```

To run a genuinely isolated rendering/test case without touching the live state:

```bash
tmp="$(mktemp -d)"
printf '1|2001-2003|192.0.2.50|3001-3003|both\n' > "$tmp/rules.db"
PORTFW_STATE_DIR="$tmp" portfw-nft render > "$tmp/example.nft"
sudo nft -c -f "$tmp/example.nft"
rm -rf "$tmp"
```

**Cutover caveat:** Removing the legacy PREROUTING, POSTROUTING and FORWARD jumps and enabling the new native hooks is not a single atomic operation across the two engines. Do not perform it during high traffic or assume uninterrupted zero-loss migration. First review the old and new rules on the actual test server, back up `rules.db`, record old nft/iptables rules, verify Docker/UFW policies, and agree on a maintenance window and rollback steps. The new `portfw-nft apply` explicitly fails closed while the old PREROUTING IFM jump is active. After a controlled cutover, enable `portfw-nft.service` only after native rules have been validated. Do **not** flush the entire nftables ruleset or conntrack table.

## CLI (after cutover, when old jumps are inactive)

```bash
sudo portfw-nft                   # interactive menu
sudo portfw-nft add '2001-2003,2010' edge.example.net '3001-3003,8080' both
sudo portfw-nft edit 1 '2001,2002' 192.0.2.50 '3001,3002' tcp
sudo portfw-nft delete 1
sudo portfw-nft list
sudo portfw-nft apply
sudo portfw-nft reload
sudo portfw-nft dns-refresh
sudo portfw-nft timer --minutes 5 --enable
sudo portfw-nft timer --minutes 30
sudo portfw-nft timer --disable
```

Available timer intervals: **1, 2, 3, 5 (default), 10, 15, 20, 30, 45 and 60 minutes**. The timer uses `OnUnitInactiveSec` and `AccuracySec=30s`: it does not have to run at exact wall-clock minute boundaries. No continuously-running DNS daemon.

### DNS update behavior

1. The timer wakes the oneshot process; it reads the domain list.
2. All DNS lookups occur in user space, outside the firewall update lock, with a bounded per-query timeout.
3. Unchanged results do **not** invoke `nft`; DNS failures retain the last valid cached IP.
4. On change, the writer lock is held, updated nft rules are checked using `nft -c -f`, then submitted as **one nftables batch transaction**. This deletes and recreates only the tool-owned `ip ifm_portfw` table (never `flush ruleset` or third-party tables). The DNS cache is persisted after successful nft commit.
5. The Linux conntrack table is not flushed. Old sessions generally continue using their original mapping while the previous destination is reachable. The new destination applies to new connections only.

### Firewall compatibility boundaries

- nftables `accept` in our base chain does **not** override a later `drop` from UFW, Docker, or another base chain. Check relevant FORWARD policy on the test host before activating.
- Matching the same listener ports in a different NAT service is unsupported; activation requires verifying no overlap.
- This feature doesn't make the native engine independent of Linux Netfilter: the DNS service is independently scheduled, but a changed destination still requires an nft transaction.
- Do not infer zero packet loss or lower jitter simply from using native nftables. Run repeatable A/B tests on the test host before production.

## Quality and acceptance

`quality` is run on feature pushes and pull requests targeting `development` or `main`. The gate includes:

- Bash and Python syntax checks.
- Unit tests for positional mappings, ranges, mixed lists, duplicates/conflicts, legacy state parsing, invalid IP/domain input, persistence, no-op DNS, DNS failure and rollback on failed apply.
- A privileged **`nft -c` dry-run**, rendering a mixed range/list and a cached domain to detect nftables expression errors without changing kernel rules.

What CI does **not** establish: production live NAT behavior, interoperability with arbitrary firewall default-drop policies, throughput, jitter or zero-disruption cutover. These require explicit test-server staging with observed forwarding traffic, established TCP/UDP sessions, DNS changes and a rollback drill.

Release procedure: `feature/native-nft-range-dns` → PR to `development` → **manual test on test-de** → subsequent PR `development` → `main` with human-controlled merge.
