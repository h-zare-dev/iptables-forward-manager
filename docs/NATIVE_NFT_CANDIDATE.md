# Native nftables v2.1.0 — technical reference

**Status:** Version **2.1.0** is the final native nftables release to be published from `main` after owner approval. This guide describes its runtime design. The historical filename `NATIVE_NFT_CANDIDATE.md` is retained for existing links. The native installer is **side-by-side and non-activating**: it does not restart live NAT, migrate a legacy service or change firewall rules.

## Runtime ownership and safety

- The supported standalone native command is `portfw-nft` (Python 3), and the legacy tool remains `portfw` (iptables 1.1.0).
- Both use `/etc/iptables-forward-manager/rules.db`; run **only one engine** against this state and the NAT hooks. Native `apply` refuses to overlap an active legacy `IFM_DNAT` PREROUTING jump.
- Native writes only its managed `table ip ifm_portfw`; it never flushes all nftables tables or the conntrack table. A rules update is syntax-checked using `nft -c -f` then submitted as an nftables batch, affecting new connections. Established NAT mappings normally persist in conntrack while their destination remains reachable.
- Native `apply` enables `net.ipv4.ip_forward=1` at runtime and detects the primary IPv4 for SNAT. `reload` reapplies the owned table and re-detects the current primary IP. Incoming destination IPv4 must be considered local by the kernel, including a configured secondary/floating IPv4. The Floating IP manager is an independent project.
- A rule in nftables is not proof of end-to-end reachability: provider firewalls, UFW/Docker rules, return routing and destination health still matter. Do not infer zero packet loss or jitter from using native nftables.

## Rule format and limits

The compatible `rules.db` format remains:

```text
ID|source_ports|destination_ip_or_domain|destination_ports|protocol
1|2001|192.0.2.50|3001|tcp
2|2001-2003,2010|edge.example.net|3001-3003,8080|both
3|7000,7003|203.0.113.9|8000,8005|udp
```

Source and destination port lists and inclusive ranges are matched **positionally, one-to-one**. Duplicate, conflicting or malformed mappings fail validation. Protocols are `tcp`, `udp` and `both`. Each rule supports at most 4,096 expanded ports; the total limit is 10,000 protocol/port mappings. RR expansion is capped at 50,000 backend endpoints and at most 64 resolved IPv4 addresses. Only IPv4 A records are supported; AAAA-only DNS destinations and IPv6 packet forwarding are not.

## Add/Edit: per-rule DNS policy

**All normal DNS configuration happens in the same Add/Edit menu flow**. An IPv4 destination needs no DNS settings. A domain is resolved using `getent ahostsv4` and shows the available A records. One eligible IPv4 forces OFF; for two or more A records the operator chooses:

| Mode | Default DNS polling | Data-plane behavior |
| --- | --- | --- |
| **Single IP (OFF)** (default) | 5 min | One stable selected A record; it changes only when no longer published |
| **Timed Rotation** | 1 min | Rotate the selected destination for **new** flows after a configured interval (default 5 min) |
| **Per-Connection RR** | 5 min | Kernel selects a backend for each **new** conntrack flow using `numgen inc mod N` |

The operator can customize per-rule DNS polling (1/2/3/5/10/15/20/30/45/60 minutes). Timed Rotation has a separate interval from DNS polling. Add/Edit reviews all fields before applying them; a timer or persistence error triggers best-effort transaction rollback. Existing sessions are **not** migrated to a newly selected backend.

The native state file `/etc/iptables-forward-manager/dns-rules.json` uses schema 1 with per-rule `mode`, `poll`, `rotate`, `selected`, `backends`, `last` and `checked`. Files written by the manager are root-only mode 0600. Existing `dns-cache.db`, `dns-balance.db`, and `dns-backends.db` are preserved for backward compatibility with legacy DNS policies until the corresponding domain rule is explicitly edited.

OFF and Timed modes use `tcp_dnat` / `udp_dnat` maps for a single destination. In RR mode, the kernel uses `tcp_rr_dispatch` / `udp_rr_dispatch`, per-rule `tcp_rr_<ID>` / `udp_rr_<ID>` chains, `numgen`, and port-remap maps; therefore `tcp_dnat` may legitimately be empty for an RR-only configuration. DNAT/FORWARD/SNAT entries are scoped to the selected backend(s) and destination port(s).

## DNS scheduling, updates and limitations

- A single `portfw-dns-refresh.timer` executes `portfw-nft dns-refresh`. The installed base timer unit has a 5-minute default, but **Add/Edit with domain rules configures a managed 1-minute systemd override and automatically enables/starts it**. The scheduler itself ticks every minute; each modern rule is resolved only when its own `poll` interval is due.
- Timed rotation uses the last known-good A-record list and can rotate between DNS polls. If an interval expires between timer ticks, the rotation occurs on the next tick, not at an exact wall-clock instant.
- `portfw-nft dns-refresh` and menu option [8] run the worker immediately, but **do not force an early DNS lookup** for modern rules whose `poll` interval has not elapsed.
- If an A record changes, nftables is updated as needed with a checked batch. Unchanged DNS or a non-due rotation does not reload the firewall. DNS failures retain the known-good addresses.
- If all domain rules are removed, the manager disables the DNS timer only when it was auto-enabled by the manager, preserving a preexisting user-managed timer. Menu [7] is for diagnostic status and **Repair Scheduler**, not initial DNS setup. While any domain rule exists, manually disabling the timer or setting its shared tick other than 1 minute through the CLI is rejected.
- DNS TTL and local resolver caching can delay observed DNS changes. **There are no active backend health checks or automatic failover from an A record that remains published but unreachable.** RR distributes new connection *counts*, not guaranteed equal bytes or throughput.

## Installation, updating and compatibility

**Fresh Debian/Ubuntu server** (not already running legacy NAT):

```bash
sudo apt-get update
sudo apt-get install -y curl python3 nftables iptables iproute2 util-linux libc-bin
curl -fsSL https://raw.githubusercontent.com/h-zare-dev/iptables-forward-manager/main/install-native.sh | sudo PORTFW_REF=main bash
sudo portfw-nft
```

The installer writes the native binary, migration helper and systemd units **without starting or enabling** either engine. After the first successful Add, the manager enables `portfw-nft.service` for boot-time rule restore; it does not restart the active firewall. Domain Add/Edit also automatically manages the DNS scheduler. An update using the installer replaces files **without applying/reloading live rules**. State, selected modes and existing nftables entries remain untouched until an explicit operation or service run.

**Legacy iptables 1.1.0 installation:** do **not** start native alongside legacy hooks. Use `portfw-migrate preflight` and the maintained [controlled cutover/rollback guide](SAFE_NATIVE_CUTOVER.md) with an independent console and low-traffic maintenance window.

**Upgrading an earlier native release candidate:** legacy DNS state is readable; editing each legacy domain rule in the v2.1.0 UI upgrades that rule to independent per-rule policy. Installing the binary alone does not perform this state conversion or silently change active nftables.

## CLI and safe checks

```bash
portfw-nft --version
portfw-nft check
portfw-nft list
sudo portfw-nft
sudo portfw-nft add '2001-2003,2010' edge.example.net '3001-3003,8080' both
sudo portfw-nft edit 1 '2001,2002' 192.0.2.50 '3001,3002' tcp
sudo portfw-nft delete 1
sudo portfw-nft apply
sudo portfw-nft reload
sudo portfw-nft dns-refresh
sudo portfw-nft balance             # advanced/legacy summary
sudo nft list table ip ifm_portfw
systemctl is-enabled portfw-nft.service
systemctl list-timers --all portfw-dns-refresh.timer
```

Advanced `portfw-nft balance --enable ID --mode round-robin`, `--mode timed --minutes N` and `balance --disable ID` remain for compatibility. On a modern rule they invoke the same Edit transaction; the interactive Add/Edit flow is recommended. The `portfw-nft timer` CLI is for diagnostics/legacy settings; active domain rules require a managed 1-minute tick and cannot be manually disabled.

`portfw-nft render` is a **dry-run preview** with illustrative SNAT source `192.0.2.1`, not output to blindly apply to a live host. Always validate the intended state and real client-to-backend reachability. Do not activate `portfw` legacy rules or run `portfw-migrate switch` again on a previously migrated native host.

## Quality, observed staging and release flow

GitHub `quality` and `bash-syntax` gates exercise unit/contract validation, input limits, per-rule DNS and RR behavior, nftables syntax, isolated Linux-kernel TCP/UDP forwarding, systemd restore, concurrency and Debian compatibility. See [CI release gate](CI_RELEASE_GATE.md).

Manual staging on `ip-tun05` confirmed timed DNS rotation, automatic timer, Edit → RR, kernel `numgen inc mod 3`, outbound TCP SYN distribution and replies from all three backends; a 60-connection test from `reycloud-ir02` succeeded 60/60. A direct TCP probe showed ~1.16s outliers on one backend path. Interface RX drops were 20 in a 20-second sample among 262,212 RX packets; **this is not an end-to-end packet-loss measurement**. The three backends did not respond to ICMP, so 100% ICMP loss did not prove TCP loss. None of these spot checks certifies long-running multi-Gbps performance or zero jitter.

Workflow: `feature/*` → owner-reviewed PR and CI on `development` → final release PR and CI on `main` → **owner-controlled merge**. Version labels and documentation do not deploy to servers automatically. See [README](../README.md) and [CHANGELOG](../CHANGELOG.md).
