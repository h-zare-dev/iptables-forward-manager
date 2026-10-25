# Port Forward Manager

A lightweight terminal manager for **persistent IPv4 TCP/UDP port forwarding** on Linux, powered by native **nftables**. Includes a colorful menu, single/range/list port mappings, and support for primary and floating IPv4 addresses.

## Quick start — fresh server

For a **new Debian/Ubuntu server** that is **not already running the old Port Forward Manager**:

**1. Install dependencies** (skip if already installed):

```bash
sudo apt-get update
sudo apt-get install -y curl python3 nftables iptables iproute2 util-linux libc-bin
```

**2. Install Port Forward Manager:**

```bash
curl -fsSL https://raw.githubusercontent.com/h-zare-dev/iptables-forward-manager/main/install-native.sh | sudo PORTFW_REF=main bash
```

**3. Open the menu:**

```bash
sudo portfw-nft
```

**4. Add your first rule:** choose **[1] Add Forwarding**, then enter the source port, destination IPv4 (or domain), destination port, and protocol (`tcp`, `udp`, or `both`). **The rule is applied immediately, and the first successful add automatically enables `portfw-nft.service` for future boots.** You do not need to run `systemctl enable --now` manually.

That's it. Test connectivity from an external client, and open the menu any time with `sudo portfw-nft`. You can optionally check boot persistence with `systemctl is-enabled portfw-nft.service`. If automatic enable fails, the program warns you; the forwarding rule remains active, but persistence needs attention.

> **Already running the old `portfw` / iptables version?** Don't perform the fresh-install activation on top of it. Use the [upgrade and migration instructions](#moving-from-legacy-iptables-v110) near the end of this README.

## Menu and basic usage

```text
Port Forward Manager | Native nftables v2.1.0-rc1

[1] Add Forwarding       Create a new forwarding rule
[2] Edit Forwarding      Modify an existing rule
[3] Delete Forwarding    Remove one managed rule
[4] List Forwarding      Show all managed rules
[5] Delete All           Remove all managed forwarding rules
[6] Reload Rules         Reapply native maps and re-detect Primary IP
[7] DNS Auto Refresh     Configure background refresh timer
[8] Refresh DNS Now      Manually resolve domain destinations
[9] DNS Timed Balance    Rotate destination for new connections
[0] Exit                 Close the manager
```

The colored dashboard displays **hostname, interface, primary IPv4, secondary/floating IPv4, IPv6 (display only), and rule count**. Add/Edit let you keep existing values by pressing Enter; destructive menu operations require confirmation.

### Example: a single port

```text
Source port(s):       1015
Destination IPv4:     203.0.113.50
Destination port(s):  2096
Protocol:             both
```

This sends TCP+UDP arriving on local port **1015** to destination `203.0.113.50:2096`. The destination address above is for documentation; substitute your own reachable server.

### Port ranges and comma-separated lists

Source and destination ports are mapped **one-to-one, in the order entered**.

| Source port(s) | Destination port(s) | Mapping |
| --- | --- | --- |
| `1015` | `2096` | 1015 → 2096 |
| `2001-2005` | `3001-3005` | 2001 → 3001, …, 2005 → 3005 |
| `2020,2030,2040` | `3020,3030,3040` | 2020 → 3020; 2030 → 3030; 2040 → 3040 |
| `2001-2003,2010` | `3001-3003,8080` | 2001 → 3001; 2002 → 3002; 2003 → 3003; 2010 → 8080 |

The program rejects overlapping source ports for the same protocol, duplicate ports, malformed ranges, and unequal source/destination counts. For example, `2010-2020` (11 ports) cannot map to `2020-2040` (21 ports).

## Main features

- Native nftables **maps and sets** for DNAT, FORWARD and explicit SNAT; no per-packet DNS lookup.
- Single ports, inclusive ranges, comma-separated lists, or combinations of both.
- TCP, UDP or both, with up to **4,096 expanded ports per rule** and **10,000 protocol/port mappings** total.
- Destination **IPv4 or hostname with an IPv4 A record**.
- Incoming matching on any currently local IPv4 address, including **primary and floating/secondary IPs**. Forwarding configuration is independent of a Floating IP manager.
- Persistent systemd restore; a **Reload** action detects the current primary IPv4 for SNAT.
- Managed `ip ifm_portfw` table; no global nftables or conntrack flush. Configuration updates are validated and committed as a batch for the owned table.
- Optional independent DNS refresh timer with configurable intervals.

Only **IPv4** is forwarded; IPv6 is shown in the menu for server information.

## Command-line usage

The interactive menu is the easiest route. For automation:

```bash
portfw-nft --version
portfw-nft check
portfw-nft list

sudo portfw-nft add '2001-2003,2010' 203.0.113.50 '3001-3003,8080' both
sudo portfw-nft edit 1 '2001-2005' 203.0.113.50 '3001-3005' tcp
sudo portfw-nft delete 1
sudo portfw-nft reload
sudo portfw-nft apply
sudo systemctl reload portfw-nft.service
```

To remove **all managed forwarding entries**: `sudo portfw-nft clear` (or menu option 5). Be careful on a busy server.

`portfw-nft render` is for **preview/dry-run only**, with an illustrative SNAT IPv4. **Don't load its rendered output directly into the live firewall.** Replace the example destination addresses in CLI samples with actual reachable hosts.

## Domain destinations and optional DNS refresh

A hostname can be used in place of a destination IPv4:

```bash
sudo portfw-nft add '1010' edge.example.net '2096' both
```

- Adding a domain resolves its IPv4 **A record** and caches the selected IPv4; an invalid or unresolvable domain is rejected.
- **Default (unchanged):** when a hostname has multiple A records, use the numerically lowest eligible IP; no balancing until explicitly enabled.
- **Opt-in timed backend rotation:** for a domain rule, alternate the selected A-record IP every configured interval (default 5 min) when the DNS timer next runs. This is **time-slot distribution of new flows, not equal bandwidth distribution**.
- Proxied DNS services may return a proxy IP rather than an origin.
- AAAA-only/IPv6 destinations aren't supported.
- Existing conntrack sessions aren't moved to a newly resolved destination.
- DNS lookups run outside the packet path; an unchanged or failed lookup doesn't replace the current valid mapping.

Refresh manually:

```bash
sudo portfw-nft dns-refresh
```

Or optionally enable the independent systemd timer (installed **disabled**, default **5 minutes**):

```bash
sudo portfw-nft timer --minutes 5 --enable
sudo portfw-nft timer --minutes 30
sudo portfw-nft timer --disable
```

Menu options **7** and **8** provide the same timer configuration/manual refresh. Available intervals in minutes: **1, 2, 3, 5, 10, 15, 20, 30, 45, 60**. Timing is approximate rather than aligned to the clock minute.

### Five-minute DNS backend rotation (opt-in, new in v2.1)

When two A records point to different servers, you can choose **time-based backend rotation** instead of the legacy numerically lowest-IP behavior. For example:

```text
edge.example.net   A   198.51.100.10
edge.example.net   A   198.51.100.20
```

Choose **[9] DNS Timed Balance**, then select the *domain Rule ID*, and choose 5 minutes. Or use the CLI:

```bash
# Example only: replace ID with the domain rule's ID
sudo portfw-nft balance --enable 1 --minutes 5

# Poll DNS at least once per minute for ~5-minute backend rotations:
sudo portfw-nft timer --minutes 1 --enable

# Read-only selected destination / next rotation info:
portfw-nft balance

# Stop automatic switching, retaining the current target until the next
# normal DNS refresh; future refreshes revert to the default lowest IP:
sudo portfw-nft balance --disable 1
```

At the first successful enable, the current cached destination is retained for five minutes. Then each DNS poll after the due time moves **new connections only** to the next IPv4 in sorted order. With exactly two stable A records and a five-minute interval, the destination will alternate A → B → A → B. A shared hostname used by multiple forwarding rules rotates together.

**The rotation interval is NOT DNS TTL.** TTL controls caching by recursive resolvers; `getent ahostsv4` returns the system resolver's current view and might lag behind recent changes. The DNS refresh timer controls how often the host checks; set it to **one minute** for five-minute rotation, allowing normal systemd scheduling jitter. You can verify the current target with `portfw-nft balance` or `nft list map ip ifm_portfw tcp_dnat`.

**Connection safety:** nftables stateful NAT generally selects the destination on the first packet of each conntrack flow; existing tracked flows continue to use their NAT binding after destination changes. The manager does not flush conntrack. Still, resetting conntrack externally, expiring UDP state, reboots, or policy/firewall changes can interrupt traffic. If a backend disappears from the DNS answers, a usable remaining IP is selected immediately on the next poll; this is not a health check. A backend can still be unhealthy while its A record is present.

**Traffic balance:** alternating time windows does not guarantee 50/50 bytes, bandwidth, sessions, or per-backend health. Long-running connections may stay on one server for hours. If actual per-flow 50/50 is required instead, a distinct kernel per-connection `numgen` design would be needed.

This is a release-candidate feature: **test against two controlled downstream targets and compare packet loss/retransmission/jitter before production rollout**. This code does not deploy anything to existing servers automatically.

> **Testing note:** public DNS propagation and high-throughput stability under live destination-IP rotation have not yet been fully end-to-end validated. Keep the timer disabled until you've confirmed behavior with your own DNS records.

## Service, persistence, and troubleshooting

The native service `portfw-nft.service` restores the managed rules at boot, after network-online. State is stored in `/etc/iptables-forward-manager/rules.db`; domain cache in `/etc/iptables-forward-manager/dns-cache.db`; opt-in timed backend state in `/etc/iptables-forward-manager/dns-balance.db` (mode 0600).

For a fresh native installation, the installer deliberately **doesn't start or enable** the service. After the **first successful Add Forwarding**, the program enables boot restoration automatically using `systemctl enable portfw-nft.service` (without reapplying the active kernel rules). If this step fails, it prints a warning; check `systemctl is-enabled portfw-nft.service` and the service permissions. If the **primary IPv4 changes**, run `sudo portfw-nft reload` to update the SNAT source. Secondary/floating IPv4s are matched when the kernel considers them local.

Read-only checks:

```bash
portfw-nft check
portfw-nft list
nft list table ip ifm_portfw
nft list map ip ifm_portfw tcp_dnat
nft list map ip ifm_portfw udp_dnat
systemctl is-active portfw-nft.service
systemctl is-enabled portfw-dns-refresh.timer || true
journalctl -u portfw-nft.service -n 50 --no-pager
```

The service can report `active (exited)`: this is normal for its `oneshot`/persistent configuration. A matching rule in the nftables map proves the configuration is present, **not** end-to-end connectivity. Test the actual TCP/UDP service, destination listeners, provider firewall and routing. Existing Docker/UFW/other base chains can still drop traffic; one nftables `accept` doesn't override another chain's `drop`.

## Development and testing

This repository uses **`development` as the default branch**. The normal flow is `feature/*` → PR to `development` → CI/manual test → owner-reviewed PR to `main`.

GitHub Actions **Quality** and **Shell syntax** cover parsing and invalid cases, UI, migration ordering, DNS-cache behavior, nftables dry runs, and real TCP/UDP forwarding + SNAT in isolated network namespaces. Manual `test-de` testing included migration, native maps, range/list creation and validation. These do **not** certify every firewall setup, low jitter under all loads, or zero-packet-loss cutovers.

For required pre-merge checks, supported runner environments, branch-protection setup and manual release qualifications, see [CI & Release Qualification Gate](docs/CI_RELEASE_GATE.md).

For implementation and compatibility details, see [Native engine technical reference](docs/NATIVE_NFT_CANDIDATE.md).

## Updating an existing native installation

If you're **already using `portfw-nft`**, the same installer updates the installed binary and systemd units **without restarting or reconfiguring the active forwarding rules**:

```bash
curl -fsSL https://raw.githubusercontent.com/h-zare-dev/iptables-forward-manager/main/install-native.sh | sudo PORTFW_REF=main bash
portfw-nft --version
portfw-nft list
```

Do not run the legacy installer or commands as part of a native update. A code update does not automatically change the currently loaded nftables table; schedule reapplication separately if needed and verify connectivity. For `development` feature testing, choose the matching `PORTFW_REF` and installer branch on a test host only.

## Moving from legacy iptables (v1.1.0)

If your server already uses the old `portfw` (iptables) engine, **don't enable the native service directly**. The two engines share the same database and overlapping NAT hooks can break forwarding. The legacy service's stop action also does not remove its old jumps.

Install the native files side by side using the Quick Start installer, then use **`portfw-migrate`** during a low-traffic maintenance window. Have a second SSH session or provider console available. Full steps and limitations: [Safe migration and rollback guide](docs/SAFE_NATIVE_CUTOVER.md).

```bash
sudo portfw-migrate preflight  # only checks; no changes
sudo portfw-migrate status

sudo portfw-migrate switch     # arms independent 10-minute automatic rollback
sudo portfw-migrate status

# Test external TCP and UDP connections through the forwarded ports first:
sudo portfw-migrate confirm    # only if tested and successful within 10 minutes

# If something fails:
sudo portfw-migrate rollback
```

The migration backs up the current state and detaches only the legacy managed jumps, retaining rollback capability. The automatic rescue timer is **not a guarantee** of uninterrupted service. **Never run `portfw-migrate switch` again on an already-migrated native host.** After `confirm`, use only `portfw-nft`, never legacy `portfw --reload`. Manual rollback later restores the rules saved **at cutover time** (newer changes may be lost).

## Native versus legacy — reference

| | Native nftables v2.0.0-rc3 | Legacy iptables v1.1.0 |
| --- | --- | --- |
| Command | `portfw-nft` | `portfw` |
| Installer | `install-native.sh` | `install.sh` |
| Engine | Dedicated `ip ifm_portfw` nftables table | iptables / iptables-nft `IFM_*` chains |
| Single ports | Yes | Yes |
| Port ranges / comma-separated lists | Yes | No |
| Destination domain (IPv4 A) | Yes | No |
| Independent DNS timer | Yes (opt-in) | No |
| Primary + floating IPv4 | Yes | Yes |
| Persistent service | `portfw-nft.service` | `iptables-forward-manager.service` |

Legacy installs for legacy-only servers:

```bash
curl -fsSL https://raw.githubusercontent.com/h-zare-dev/iptables-forward-manager/main/install.sh | sudo bash
sudo portfw
```

On legacy-only servers, `portfw --list`, `portfw --apply`, and `portfw --reload` remain available. **Never run these on servers already migrated to native nftables.**

## License

MIT
