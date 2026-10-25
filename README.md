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
Port Forward Manager | Native nftables v2.1.0-rc2

[1] Add Forwarding       Create a new forwarding rule
[2] Edit Forwarding      Modify an existing rule
[3] Delete Forwarding    Remove one managed rule
[4] List Forwarding      Show all managed rules
[5] Delete All           Remove all managed forwarding rules
[6] Reload Rules         Reapply native maps and re-detect Primary IP
[7] DNS Auto Refresh     Configure background refresh timer
[8] Refresh DNS Now      Manually resolve domain destinations
[9] DNS Load Balancing   OFF / Timed / Per-Connection RR
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
- **Opt-in three-mode DNS load balancing** per domain: OFF (default), Timed Rotation (5-minute IP slots), or Per-Connection Round Robin (native kernel numgen).

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

### DNS Balancing - three modes, 100% terminal menu (v2.1.0-rc2)

Choose **[9] DNS Load Balancing** from the original colorful terminal UI. Each domain has a dedicated framed status panel: its Rule ID(s), current mode, selected IP or backend list, DNS timer state, and (for timed mode) the approximate next switch. Select **Configure Rule Mode**, pick an existing domain Rule ID, then:

| Mode | Behavior | DNS timer needed? |
|---|---|---|
| **OFF (default)** | One stable selected IPv4; existing behavior, no balancing | Only if you want dynamic DNS updates |
| **TIMED ROTATION** | Every configured N minutes, change the destination for **new connections only**: IP A → B → C → A | **Yes**; poll timer should be shorter than switch interval |
| **PER-CONNECTION ROUND ROBIN** | Each **new TCP/UDP conntrack flow** alternates across all currently discovered IPv4 addresses using nftables kernel `numgen inc` | No for packet distribution; **yes** to periodically discover A-record changes |

**Your two IPs:** with 5-minute Timed Rotation, all new flows use `57.131.133.117` for one slot, then `57.131.144.149` for the next. With Per-Connection RR, new connections alternate between both backends on the same public forwarding port, without waiting for a 5-minute boundary. **With 10 stable A records**, Timed rotates through all 10 in about 50 minutes; Per-Connection RR cycles through all 10 as new flows arrive. Some DNS resolvers return only subsets of published A records; the manager balances only what `getent ahostsv4` currently returns.

The colored terminal menu has **full status/selection/confirmation flows**, not CLI-only switches. CLI remains available for automation:

```bash
# Timed rotation: advance selected IP every ~5 minutes
sudo portfw-nft balance --enable 1 --mode timed --minutes 5

# Alternative: native per-connection Round Robin (no timer wait per packet)
sudo portfw-nft balance --enable 1 --mode round-robin

# Restore legacy stable behavior
sudo portfw-nft balance --disable 1

# View per-domain mode and destination(s)
sudo portfw-nft balance

# The one timer checks A records and drives timed rotation; 1-minute polling
# is recommended to detect an expired five-minute slot promptly.
sudo portfw-nft timer --minutes 1 --enable
```

**Timer versus Cloudflare TTL:** TTL sets recursive DNS caching, not balancing interval. The timer runs `portfw-nft dns-refresh` at its configured cadence. For Timed, it advances the target **only when the timed slot expires**; for Per-Connection RR, forwarding and selection happen entirely in the kernel on each new flow, while DNS polls only update the destination list if it changes. Unchanged and failed DNS responses leave the kernel map and existing connections untouched.

**Safety & persistence:** nftables NAT normally evaluates the translation on the first packet of a tracked flow; established TCP connections retain their destination on a map change, as confirmed in real isolated kernel tests. No conntrack flush, other firewall table flush, packet-processing Python loop, service restart, or coupling to a Floating IP manager. Mode and last selected IP are persisted in `dns-balance.db`; for Per-Connection mode the backend snapshot is persisted in `dns-backends.db` for DNS-independent boot restore. Both are root-only (0600), and any `nft -c` rejection aborts a change before persistence. Domain rules sharing the same hostname share mode and selection.

**Operational limits:** time-slot rotation **does not** guarantee 50/50 byte volume; Per-Connection RR distributes new conntrack sessions more evenly, but also cannot ensure equal bandwidth when flows vary in size. DNS A records are **not health checks**: an unhealthy backend still receives flows while published. Timed slots are approximate due to systemd timer scheduling and resolver caching; an RR kernel sequence can restart on explicit ruleset rebuild or DNS backend changes. Active UDP mappings survive only as long as their conntrack entries remain valid. Cap of **64 distinct A records** and **50,000 expanded RR endpoint mappings** to prevent excessive kernel resources. Always test packet drops, jitter and long-lived flows on staging before production.

> **Rollout:** This release-candidate feature is opt-in and does not automatically deploy or activate on existing servers. No direct changes to `main`, `development`, GRE or Ansible hosts until owner approves.

## Service, persistence, and troubleshooting

The native service `portfw-nft.service` restores the managed rules at boot, after network-online. State is stored in `/etc/iptables-forward-manager/rules.db`; domain cache in `/etc/iptables-forward-manager/dns-cache.db`; opt-in balancing state in `/etc/iptables-forward-manager/dns-balance.db`, and the per-connection backend snapshot in `/etc/iptables-forward-manager/dns-backends.db` (both mode 0600).

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
