# Changelog

## 2.1.0 — 2026-10-26

Stable native nftables release of the tested 2.1.0 release candidates.

### Added and changed

- Rule-first Add/Edit workflow with DNS A-record detection, per-rule OFF, Timed Rotation and Per-Connection Round Robin settings.
- One automatically managed systemd DNS scheduler (1-minute tick) with independent per-rule polling intervals.
- Timed rotation of destinations for **new** connections and native kernel `numgen inc mod N` per-connection RR across available backend A records.
- Per-rule DNS persistence in `dns-rules.json`; compatibility with existing legacy DNS databases and existing non-DNS forwarding records.
- Diagnostic DNS menu, safe scheduler repair, and reduced unnecessary nftables updates for unchanged DNS.

### Compatibility and operator notes

- Native executable: `portfw-nft` **2.1.0**; the separate legacy iptables executable `portfw` stays **1.1.0**.
- The native installer is side-by-side and **does not migrate, start services, restart nftables or interrupt forwarding**. A first successful native Add enables boot restore; Add/Edit with a domain enables the DNS timer.
- Native and legacy forwarding engines must not own overlapping NAT hooks. Follow the [safe cutover instructions](docs/SAFE_NATIVE_CUTOVER.md) for preexisting legacy hosts.
- Earlier DNS balance state stays readable; explicitly editing a domain rule transitions it to modern per-rule scheduling.
- There is no active backend health check and no guarantee of equal bandwidth, zero packet loss, jitter, or line-rate performance. Validate the individual backend network paths as well as the forwarding host.

### Quality evidence

- Automated unit, syntax, CI and isolated kernel namespace checks; manual TCP staging on `ip-tun05` with a three-backend domain confirmed Timed and Per-Connection RR behavior and SYN-ACK responses from all three IPs.
- External probe: 60/60 TCP connection attempts successful. One backend path showed a ~1.16s worst-case TCP handshake delay in the sample; investigate separately from release packaging.

### Release process

Changes reach `main` only via an approved `development` → `main` PR after its checks pass. A GitHub version tag/release should be created only after the final merge, never from the staging branch.
