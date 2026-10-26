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

**4. Add your first rule:** choose **[1] Add Forwarding**, then enter the source port, destination IPv4 (or domain), destination port, and protocol (`tcp`, `udp`, or `both`). **For a domain**, the *same Add form* resolves the A records, offers OFF / Timed Rotation / Per-Connection RR when multiple IPs exist, and shows **DNS Updates: AUTO** (5-minute default for OFF or RR, 1-minute default for Timed). You can customize the interval in the same form. No manual DNS timer setup or separate balancing screen is required. Review and confirm to save. The first successful add enables `portfw-nft.service` for future boots.

That's it. Test connectivity from an external client, and open the menu any time with `sudo portfw-nft`. You can optionally check boot persistence with `systemctl is-enabled portfw-nft.service`. If boot restore enable fails, the program warns you; the forwarding rule remains active, but persistence needs attention. DNS timer activation is different: on new domain rule creation, a DNS timer failure is treated as an unsuccessful transaction, with best-effort rollback.

> **Already running the old `portfw` / iptables version?** Don't perform the fresh-install activation on top of it. Use the [upgrade and migration instructions](#moving-from-legacy-iptables-v110) near the end of this README.

## Menu and basic usage

```text
Port Forward Manager | Native nftables v2.1.0-rc3

[1] Add Forwarding       Create a new forwarding rule
[2] Edit Forwarding      Modify an existing rule
[3] Delete Forwarding    Remove one managed rule
[4] List Forwarding      Show all managed rules
[5] Delete All           Remove all managed forwarding rules
[6] Reload Rules         Reapply native maps and re-detect Primary IP
[7] DNS Settings         Advanced scheduler status and repair
[8] Refresh DNS Now      Check the DNS of existing domain rules
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
- A single self-managed systemd DNS scheduler, with **independent per-rule DNS intervals** and safe time-window rotation.
- **Three load distribution modes in Add/Edit**, per forwarding rule: OFF (default), Timed Rotation, or Per-Connection Round Robin (kernel numgen).

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

## Rule-first DNS updates and balancing (v2.1.0-rc3)

All routine configuration lives inside **[1] Add Forwarding** and **[2] Edit Forwarding**. No one needs to activate a separate balancing menu or remember to enable a timer.

**Adding an IPv4 address:** only the ordinary source port, destination, protocol and final confirmation are shown; no DNS questions.

**Adding a hostname with one A record:** choose the destination as usual. The form displays the resolved IPv4, automatically selects **Single IP (OFF)** and **DNS Updates: AUTO / 5 minutes**. You may optionally customize that interval. OFF does **not** disable DNS updates. If the selected IP disappears from DNS, the scheduler chooses a remaining valid address and applies it.

**Adding a hostname with multiple A records:** the same form displays how many backend addresses were found, then offers:

| Distribution | DNS Updates default | How it works |
|---|---|---|
| **[1] Single IP (OFF)** | AUTO / **5 minutes** | One selected backend, no balancing. The IP is followed on DNS changes. |
| **[2] Timed Rotation** | AUTO / **1 minute** | Change the destination for *new* connections every N minutes (default **5**). |
| **[3] Per-Connection RR** | AUTO / **5 minutes** | Select the next backend for every new TCP/UDP conntrack flow in the nftables kernel. |

The screen also offers **Customize DNS refresh? [y/N]**. Press Enter to accept the sensible default without filling out another settings page. Timed Rotation separately asks for rotation interval; polling interval and rotation interval are distinct settings.

A final colored, boxed **Review Forwarding Rule** page shows ports, destination, protocol, balancing mode, and automatic DNS interval. Nothing is committed until **Save and apply** is confirmed. If nftables validation or required DNS scheduler activation fails, the Add/Edit operation reports failure and attempts to restore the previous configuration.

**Edit** shows the same form, retaining the Rule's existing distribution and DNS update interval as defaults. Different rules pointing to **the same hostname** can use independent OFF, Timed, or RR modes and independent refresh settings.

**DNS engine:** one `portfw-dns-refresh.timer` schedules `portfw-nft dns-refresh` every minute. The program enables and starts this timer automatically when domain rules exist; individual domain rules are only resolved after their *own* saved polling interval. Timed rotation can use the last known good backend list between DNS polls. If all domains are deleted, it disables the timer **only if that timer was originally auto-enabled by the manager**, rather than overriding an existing user-managed timer. DNS failures preserve the previous known-good backend.

**DNS TTL** is different from the refresh period: DNS resolver caches can make Cloudflare changes visible later. There is no health check or downtime failover; a published but unreachable A record still receives traffic. OFF, Timed and RR do **not** guarantee equal bandwidth. Existing conntrack TCP connections retain their established NAT mappings during a change; UDP state has a finite lifetime.

**Safety:** only IPv4 A records are used; AAAA-only destinations are unsupported. At most 64 resolved IPv4 addresses and 50,000 expanded RR endpoints can be loaded. All state files use root-only 0600 permissions. Changing or adding a domain requires successful resolution; the timer never performs DNS lookups inside the packet path. Unchanged addresses and time slots do not replace nftables rules.

### Advanced controls

**[7] DNS Settings** now shows per-rule modes, intervals, shared scheduler status and a repair action. It is not a second mandatory setup screen. **[8] Refresh DNS Now** manually checks due domain updates; existing CLI commands remain for advanced automation:

```bash
sudo portfw-nft dns-refresh
sudo portfw-nft balance
sudo portfw-nft balance --enable 1 --mode round-robin
sudo portfw-nft balance --enable 1 --mode timed --minutes 5
sudo portfw-nft balance --disable 1
```

A one-minute timer tick is required for independent per-rule schedules. Do **not** manually disable the DNS timer while domain rules are active. The manager's Add/Edit flow automatically repairs activation; after a manual change to timer state, use [7] → Repair Scheduler.

### Upgrade from rc2

Existing `rules.db`, `dns-cache.db`, `dns-balance.db` and `dns-backends.db` remain readable without destructive migration. Older domain balancing rules continue to use their original settings until explicitly edited. The **first Add/Edit in the new UI** creates per-rule state in `dns-rules.json`; editing an existing domain pre-fills its legacy mode and preserves its current target where possible. Deleting unused rules prunes their new state. No automatic activation of existing DNS rules occurs solely by installing the newer binary; open the existing Rule in **Edit** (review and save) to opt into fully automatic per-rule scheduling.

> **Release candidate:** test in staging, including long-lived sessions, DNS failures, packet loss, latency and throughput, before making changes to live traffic. Merge only after the repository owner approves.

## Service, persistence, and troubleshooting

The native service `portfw-nft.service` restores the managed rules at boot, after network-online. State is stored in `/etc/iptables-forward-manager/rules.db`; domain cache in `/etc/iptables-forward-manager/dns-cache.db`; new per-rule DNS policy in `/etc/iptables-forward-manager/dns-rules.json` (0600). Legacy `dns-balance.db` and `dns-backends.db` remain readable for safe upgrades.

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
