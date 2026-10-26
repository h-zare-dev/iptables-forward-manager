# Controlled migration: Legacy iptables-nft to Native nftables

## Status and boundaries

This procedure is **only for an already working legacy installation** on a Debian/Ubuntu host with `iptables -V` showing `(nf_tables)`. It was first exercised on `test-de` with two forwarding entries: TCP+UDP source ports 1015 and 1020. This server has already completed cutover, so **do not run `switch` there a second time**. It does **not** configure per-rule DNS balancing or refresh, edit destinations, or change the database schema. Configure automatic DNS updates later using **Edit Forwarding** on the native manager; the installer itself never activates DNS.

**Expect a brief interruption of new TCP/UDP flows during the cutover.** No tool can guarantee packet-loss-free cross-engine migration. Existing conntrack mappings are never flushed, but their targets must remain reachable. Plan a low-traffic maintenance window, have an independent SSH session or provider console available, and test both forwarded ports externally before confirming.

## Install migration helper

The native installer from `main` installs the migration helper alongside the legacy and native binaries, without activating either engine:

```bash
curl -fsSL https://raw.githubusercontent.com/h-zare-dev/iptables-forward-manager/main/install-native.sh | sudo PORTFW_REF=main bash
```

For development-only testing, use the intended `feature/*` branch as both the installer URL ref and `PORTFW_REF` value, and verify the exact commit on a non-production host. The current stable native release is `v2.1.0` (after its release PR is merged into `main`).

Check:

```bash
portfw-migrate preflight
portfw-migrate status
```

Preflight verifies old service active/enabled, EXACTLY one jump for each of `IFM_DNAT`, `IFM_SNAT`, `IFM_FORWARD`, native service and table inactive, DNS timer inactive, valid rules and syntactically valid native rendering. It **does not** mutate the firewall.

## The actual cutover

**Do not add/edit rules during the transition.**

```bash
sudo portfw-migrate switch
sudo portfw-migrate status
```

The helper:

1. Takes timestamped backups of `rules.db`, `iptables-save`, and the full native nftables ruleset under `/var/lib/portfw-native-migrate/backup-*` (root-only).
2. Creates an independent **10-minute systemd rescue timer**, before changing a single firewall rule. If the SSH session drops, the timer still fires.
3. Stops **and disables** the old oneshot service. This alone does NOT remove legacy rules, since its unit has no ExecStop.
4. Detaches only three managed legacy jumps, preserving all other iptables/Docker/UFW rules and preserving the old IFM chain contents for emergency restoration.
5. Invokes `portfw-nft apply` (which refuses overlap if the old PREROUTING hook remains).
6. Enables and starts the native oneshot service for boot persistence.
7. Checks native table/service and absence of all three old jumps.

**On any failure** the helper attempts immediate restoration; the watchdog remains available if recovery fails.

After the switch, use an **external client** to confirm connectivity over each actually configured source port and protocol (TCP and/or UDP) and every intended destination, including any Primary/Floating IP in use. The original `test-de` exercise used source ports 1015/1020; do not assume those are the ports on a different host. Compare connection errors, drop counters, latency and RTT variation before/after. SSH to the host itself is not a sufficient validation.

Only when these end-to-end checks pass, and **within ten minutes**, run:

```bash
sudo portfw-migrate confirm
sudo portfw-migrate status
```

Confirmation cancels the rescue timer and persists native as the sole active engine. The migration helper does not activate DNS refresh; the native Add/Edit flow automatically enables the shared DNS timer when domain rules are configured.

To deliberately revert, even after confirmation, run:

```bash
sudo portfw-migrate rollback
```

This restores the original `rules.db` and all three old jumps, removes **only** the owned `ip ifm_portfw` table, disables native service, and enables/starts legacy. Never run a blanket `nft flush ruleset` or `iptables-restore` against Docker while live.

## Operational caveats

- If the machine reboots before the watchdog fires, a transient systemd timer is not preserved; use the provider console if needed.
- As with any fail-safe procedure, rollback itself may briefly disrupt newly established flows.
- Native `portfw-nft` and legacy `portfw` share `rules.db`; **never** run legacy add/edit/reload after cutover.
- The existing legacy chains are intentionally left allocated but **detached**; do not reattach them unless rolling back.
- A local active service and native table do not guarantee end-to-end reachability. The human operator must perform external functional checks before confirmation.
- Before adding Range/List or Domain rules, verify the plain 1015/1020 legacy equivalents migrated correctly.
- Adding or editing a domain destination in `portfw-nft` automatically manages the DNS timer and per-rule polling; stage a DNS change and failure test before applying such edits to busy production rules.
- Native nftables avoids rebuilding iptables chains for new config changes, but an engine cutover is not entirely atomic between old and new engines. Do not claim a zero-loss cutover.

## CI coverage

`tests/test_migrate.py` checks watchdog-before-detach ordering, reattach-before-native-delete fallback, safe refusal of unsupported backend and confirmation safety. Existing `quality` tests still exercise real TCP/UDP translation inside isolated namespaces. Manual on-host testing remains mandatory.

## Already migrated to native?

After `confirm`, the native `portfw-nft.service` is enabled and the legacy service is disabled. For routine edits/reload use `sudo portfw-nft`, `sudo portfw-nft list`, and `sudo portfw-nft reload`; **do not run `portfw-migrate switch` again** or use the legacy `portfw --reload` on that host. The root [README](../README.md) is the current operator manual for v2.1.0.

A manual `portfw-migrate rollback` restores the rules database **as saved at the original cutover**; any later additions/edits would be lost unless backed up separately. Domain DNS refresh is automatically managed on Add/Edit; it is not turned on merely by installing the binaries. Review automatic DNS behavior separately before editing live domain rules.
