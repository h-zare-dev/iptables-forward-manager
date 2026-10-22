# Port Forward Manager

A terminal-based, persistent **IPv4 TCP/UDP port-forwarding manager for Linux** with a colorful interactive menu, native **nftables** maps/sets, and safe rule management.

**Current native version: v2.0.0-rc2**. The original iptables-based **v1.1.0** remains available for compatibility, but the native and legacy engines must **not** be operated simultaneously.

| | Native v2 | Legacy v1 |
| --- | --- | --- |
| Command | \`portfw-nft\` | \`portfw\` |
| Engine | Native nftables (table \`ip ifm_portfw\`) | iptables / iptables-nft (\`IFM_*\` chains) |
| Single ports | ✅ | ✅ |
| Inclusive ranges and comma-separated lists | ✅ | — |
| Destination IPv4 or domain (A record) | ✅ | IPv4 only |
| Independent DNS refresh timer | ✅ (opt-in) | — |
| Primary + floating/secondary IPv4 | ✅ | ✅ |
| Persistent systemd restore | \`portfw-nft.service\` | \`iptables-forward-manager.service\` |
| Installer | \`install-native.sh\` | \`install.sh\` |

> [!IMPORTANT]
> **On a server migrated to native nftables, use only \`portfw-nft\`.** Do not run the old \`portfw\` menu, \`portfw --reload\`, or \`iptables-forward-manager.service\`: they can reattach legacy NAT hooks and conflict with the native rules. The two engines share the same rules database. Merely installing the native binaries does **not** migrate the running firewall.

## Features

- **Interactive, color-coded terminal UI** with hostname, network interface, primary IPv4, other/floating IPv4, global IPv6 addresses (display only), and managed rule count.
- Create, edit, list, and delete one or all managed rules; reload native maps without rebooting.
- Single ports: \`1015\`; inclusive ranges: \`2001-2010\`; comma lists: \`2020,2030,2040\`; mixed specifications: \`2001-2003,2010,2020-2022\`.
- **Ordered 1:1 mapping** between source and destination ports. Rejects mismatched counts, duplicates, malformed port specs, and overlapping source ports for the same protocol.
- \`tcp\`, \`udp\`, or \`both\`. Up to **4,096 expanded source ports per rule** and **10,000 protocol/port mappings** across all rules.
- IPv4 destination or hostname resolved to an IPv4 **A record**, with a cached destination and a separately scheduled, optional DNS refresh.
- Forwarding to all **currently local IPv4 addresses** on the host (primary and floating/secondary), without binding a rule to a specific incoming IPv4 address.
- Explicit SNAT to the **current primary IPv4 source address**, re-detected when applying/reloading rules. No dependency on a separate Floating IP manager.
- Owned nftables table, DNAT maps, FORWARD/SNAT sets, serialized writes, validation, and a single nftables batch to replace **only** that table. No global firewall flush and no conntrack flush.
- \`systemd\` startup restore, independent DNS oneshot service/timer, and a guarded migration helper with backup and a **10-minute auto-rollback window**.

The project currently **forwards IPv4 traffic only**; the IPv6 address shown in the menu is informational.

## Requirements

- Linux with kernel nftables/NAT support, a working IPv4 network stack and \`systemd\`.
- Python 3, \`nft\`, \`iptables\` (for migration/legacy overlap detection), \`ip\`, \`getent\`, \`flock\`, and \`curl\`.
- Root privileges for rule changes and service management.
- Debian/Ubuntu are the intended installation targets. Other distributions may work if all prerequisites and systemd semantics match, but have not been validated here.
- The destination must be reachable and the required traffic permitted by the provider firewall and any existing UFW/Docker/other filter rules.

Example for Debian/Ubuntu **if dependencies are missing**:

\`\`\`bash
sudo apt-get update
sudo apt-get install -y curl python3 nftables iptables iproute2 util-linux libc-bin
\`\`\`

## Install native nftables

For the **current reviewed code on \`main\`**:

\`\`\`bash
curl -fsSL https://raw.githubusercontent.com/h-zare-dev/iptables-forward-manager/main/install-native.sh \
  | sudo PORTFW_REF=main bash
\`\`\`

The native installer is **side-by-side and intentionally non-activating**. It:

1. Installs \`/usr/local/bin/portfw-nft\` and \`/usr/local/bin/portfw-migrate\`.
2. Installs the native restore and DNS systemd units, then reloads systemd unit definitions.
3. **Does not** enable/disable either forwarding engine, enable the DNS timer, remove old rules, flush nftables, or start a migration.

Inspect without modifying your active firewall:

\`\`\`bash
portfw-nft --version
portfw-nft check
portfw-nft list
systemctl is-enabled portfw-nft.service || true
systemctl is-enabled portfw-dns-refresh.timer || true
\`\`\`

On a fresh host with no legacy forwarding rules, establish and verify the intended rules and firewall policies **before** explicitly activating \`portfw-nft.service\`. Do not simply enable both legacy and native services.

**Already using the original \`portfw\`?** Follow [Controlled legacy-to-native migration](docs/SAFE_NATIVE_CUTOVER.md) instead of enabling the native service directly.

**Already running native nftables?** Re-running the installer from the intended branch refreshes the installed code/units without restarting your running forwarding service. Check the new binary version; don't start a legacy service.

## Interactive menu

Run (after native activation/migration):

\`\`\`bash
sudo portfw-nft
\`\`\`

The colored UI includes Host, Interface, Primary IPv4, Other IPv4, IPv6 (display only), and Managed rules. Options:

\`\`\`text
Port Forward Manager | Native nftables v2.0.0-rc2

[1] Add Forwarding       Create a new forwarding rule
[2] Edit Forwarding      Modify an existing rule
[3] Delete Forwarding    Remove one managed rule
[4] List Forwarding      Show all managed rules
[5] Delete All           Remove all managed forwarding rules
[6] Reload Rules         Reapply native maps and re-detect Primary IP
[7] DNS Auto Refresh     Configure background refresh timer
[8] Refresh DNS Now      Manually resolve domain destinations
[0] Exit                 Close the manager
\`\`\`

Add/Edit prompt for source ports, destination IPv4/domain, destination ports, and protocol (defaults to \`both\`). Editing allows Enter to keep the displayed existing value. Destructive menu actions request confirmation.

### Port mapping examples

Each item expands **in the order written**, and source item #N maps to destination item #N.

| Source port(s) | Destination port(s) | Result |
| --- | --- | --- |
| \`1015\` | \`2096\` | 1015 → 2096 |
| \`2001-2005\` | \`3001-3005\` | 2001 → 3001, …, 2005 → 3005 |
| \`2020,2030,2040\` | \`3020,3030,3040\` | 2020 → 3020; 2030 → 3030; 2040 → 3040 |
| \`2001-2003,2010\` | \`3001-3003,8080\` | 2001 → 3001; 2002 → 3002; 2003 → 3003; 2010 → 8080 |

An unequal range such as \`2010-2020\` (11 ports) → \`2020-2040\` (21 ports) is rejected, as is an overlapping TCP source port already present in another \`tcp\` or \`both\` rule.

Example native CLI addition:

\`\`\`bash
sudo portfw-nft add '2001-2003,2010' 203.0.113.50 '3001-3003,8080' both
sudo portfw-nft add '2020,2030,2040' 203.0.113.50 '3020,3030,3040' tcp
\`\`\`

These use **documentation/example IPs**. Substitute a reachable real destination before use. The destination must actually listen on its selected ports for traffic to work.

## Native CLI reference

\`\`\`bash
portfw-nft --version
portfw-nft check
portfw-nft list
portfw-nft render                            # preview only: illustrative SNAT IP
sudo portfw-nft                             # interactive menu
sudo portfw-nft add SOURCE TARGET DESTPORTS tcp|udp|both
sudo portfw-nft edit ID SOURCE TARGET DESTPORTS tcp|udp|both
sudo portfw-nft delete ID
sudo portfw-nft clear                       # deletes managed rules
sudo portfw-nft reload                      # reapply the native table; detect primary IP
sudo portfw-nft apply                       # same native reapplication
sudo systemctl reload portfw-nft.service
\`\`\`

Examples:

\`\`\`bash
sudo portfw-nft edit 3 '2001-2005' 203.0.113.50 '3001-3005' both
sudo portfw-nft delete 3
\`\`\`

**Careful:** \`render\` uses an **illustrative SNAT IPv4** for validation; its output is **not** intended to be directly loaded as a live ruleset. Applying/reloading can briefly affect new connections, so avoid unnecessary changes during peak traffic.

## Domain destinations and DNS refresh (optional)

A domain may replace a destination IPv4:

\`\`\`bash
sudo portfw-nft add '1010' edge.example.net '2096' both
\`\`\`

This performs an **initial IPv4 A-record lookup**. A failed lookup or invalid destination rejects the new rule. Domain traffic is forwarded to the **resolved IPv4**, not to a DNS name in the kernel; DNS resolution **does not occur per packet**.

- **IPv4 A records only**; AAAA-only destinations are unsupported.
- If multiple IPv4 A records exist, the current resolver chooses the numerically lowest eligible address. This is **not** DNS-based balancing or health checking.
- A proxied hostname (e.g. Cloudflare orange-cloud) may resolve to a CDN proxy rather than the origin; only use a hostname/port combination whose returned IP accepts the intended forwarding protocol.
- The cached IPv4 stays in use if a later DNS check fails; successful DNS changes affect **new connections**, not already established conntrack mappings.
- Changing a domain's DNS does not automatically change the kernel mapping unless the refresh action/timer is run.

Manual refresh:

\`\`\`bash
sudo portfw-nft dns-refresh
\`\`\`

Independent \`systemd\` timer (installed **disabled**, default **5 minutes**):

\`\`\`bash
sudo portfw-nft timer --minutes 5 --enable
sudo portfw-nft timer --minutes 30
sudo portfw-nft timer --disable
systemctl status portfw-dns-refresh.timer --no-pager
\`\`\`

Available intervals (minutes): **1, 2, 3, 5, 10, 15, 20, 30, 45, 60**. The schedule uses \`OnUnitInactiveSec\` and \`AccuracySec=30s\`, so it isn't tied to exact wall-clock boundaries. Menu option **7** offers the same settings, and option **8** triggers a manual refresh.

The DNS service performs lookups outside the packet path. If the result doesn't change, **no nftables update is made**. When it changes, the engine validates and submits a batch updating only its own table; unrelated rules and conntrack are not flushed.

> [!WARNING]
> A live domain A-record change, DNS failure/recovery, and high-throughput stability have **not yet been end-to-end validated on the production traffic path**. Leave auto-refresh disabled until you have tested your own DNS records and can verify reachability/rollback.

## Migration from legacy iptables (v1.1.0)

The legacy program \`portfw\` is retained. Do **not** try to migrate by simply stopping its systemd service: it has no \`ExecStop\`, so old NAT jumps can remain attached.

Use the separate migration utility and the full [safe cutover and rollback guide](docs/SAFE_NATIVE_CUTOVER.md). Summary:

\`\`\`bash
sudo portfw-migrate preflight        # read-only prerequisite check
sudo portfw-migrate status           # current engines / rollback state

# Planned maintenance window + second SSH/provider-console access:
sudo portfw-migrate switch           # arms a 10-minute fallback; changes the active engine
sudo portfw-migrate status

# FIRST test real TCP and UDP access via your forwarded IPs and ports.
sudo portfw-migrate confirm          # only if checks passed, within the rollback window

# If cutover failed or you decide to revert:
sudo portfw-migrate rollback
\`\`\`

The helper backs up \`rules.db\`, \`iptables-save\`, and \`nft list ruleset\`; preserves the managed legacy chains while detaching their three jump rules; and arms a **10-minute systemd rescue timer** before the cutover. The watchdog is not a guarantee of zero interruption or successful restoration under all failure conditions.

**Do not run \`preflight\`/\`switch\` a second time on an already migrated native host.** The native service and table should now be active and the legacy DNAT jump detached. A migration rollback restores the saved database from **cutover time**: rules created later would be lost unless separately backed up.

## Persistence, routing, and firewall boundaries

- Stored state: \`/etc/iptables-forward-manager/rules.db\`; DNS cache: \`/etc/iptables-forward-manager/dns-cache.db\`.
- On an **activated native** host, \`portfw-nft.service\` restores the native rules after network-online at boot; it is a oneshot with \`RemainAfterExit=yes\`.
- Engine-owned kernel rules live in table **\`ip ifm_portfw\`**, with DNAT maps and FORWARD/SNAT sets for TCP and UDP.
- An inbound rule can match any IPv4 address Linux considers **local**, including primary/floating addresses. The primary IPv4 used for outbound SNAT is determined from the current IPv4 route at apply/reload time.
- If the primary IPv4 changes, run \`sudo portfw-nft reload\` so the new SNAT source is detected. A floating-IP address becoming local is handled by the kernel's local-address match.
- The manager **does not manage an external Floating IP service** and is intentionally independent of any such tool.
- It doesn't flush unrelated nftables tables, iptables, Docker/UFW, or the conntrack table. **An \`accept\` in the managed nftables filter chain cannot override a \`drop\` from another base chain**: verify the full forwarding policy of your system.
- \`clear\` and menu "Delete All" remove only this tool's managed forwarding entries; do not use them to troubleshoot an unrelated firewall.

### Diagnostics (read-only)

\`\`\`bash
portfw-nft check
portfw-nft list
nft list table ip ifm_portfw
nft list map ip ifm_portfw tcp_dnat
nft list map ip ifm_portfw udp_dnat
systemctl is-active portfw-nft.service
systemctl is-enabled portfw-dns-refresh.timer || true
journalctl -u portfw-nft.service -n 50 --no-pager
\`\`\`

A saved rule and a matching kernel map entry confirm the **configuration**, not successful delivery to the target. Validate end-to-end with real TCP/UDP clients and check destination listeners, routing and external firewalls. Native nftables itself is **not** a proven fix for network jitter or upstream congestion.

## Quality assurance and known limits

GitHub Actions runs **Quality** and **Shell syntax** on feature pushes and PRs. Quality covers Python/unit tests, rule parsing/validation, DNS cache updates/fallback, UI, migration order/rollback mocks, a native \`nft -c\` dry-run, table replacement in an isolated network namespace, and actual TCP+UDP forwarding/SNAT using temporary client/router/server network namespaces.

Manual \`test-de\` validation covered the native cutover, displayed native maps, source range/list creation, conflict rejection, unequal-count rejection, UI v2.0.0-rc2, and removal of test rules. **It does not certify** live DNS refresh/failover, every provider firewall combination, sustained multi-Gbps throughput, or zero-packet-loss upgrades.

### Repository workflow

\`development\` is the default branch. Changes start in \`feature/*\`, are PR'd to \`development\`, validated by CI and on a test server, then promoted via an owner-reviewed PR from \`development\` to \`main\`. Don't deploy development experiments automatically to production.

For a reviewed native install from the stable branch use \`PORTFW_REF=main\`; for testing a specific feature, use that \`PORTFW_REF\` **only on a test server**.

## Legacy compatibility (v1.1.0)

The original Bash/iptables engine remains available when needed:

\`\`\`bash
curl -fsSL https://raw.githubusercontent.com/h-zare-dev/iptables-forward-manager/main/install.sh | sudo bash
sudo portfw
\`\`\`

On a legacy-only server its CLI is \`portfw --list\`, \`portfw --apply\`, and \`portfw --reload\`. **Do not execute those commands on servers already migrated to native nftables.** Legacy does not support native range/list/domain functionality.

## License

MIT
