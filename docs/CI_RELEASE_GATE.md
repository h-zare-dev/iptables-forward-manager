# CI / Release Qualification Gate

This repository uses `development` for integration and `main` for published code.
Every pull request targeting either branch must pass these **stable check names**:

- `quality` — aggregate release gate (fails if any required subjob fails, is skipped or is cancelled).
- `bash-syntax` — independent syntax/entrypoint check.

## Mandatory CI coverage

| Gate | Environment | What it establishes |
| --- | --- | --- |
| ShellCheck, actionlint, Python security scanning (Bandit medium/high) | Ubuntu 24.04 | Static defects / workflow correctness / common high-risk Python constructs |
| Unit and contract tests | Ubuntu 22.04 and 24.04, Debian 12 (bookworm) and 13 (trixie) | Inputs, ranges/lists, collisions, cache/error paths, UI, migration ordering, first-add service logic |
| Actual Linux Netfilter packet path | Ubuntu 22.04 and 24.04 | Real TCP+UDP packets, positional mapping, DNAT, SNAT, post-reload forwarding in isolated namespaces |
| DNS A-record rotation and balancing | Ubuntu 22.04 and 24.04 | A-record changes, per-rule OFF/Timed/Per-Connection RR, kernel forwarding for selected backends, no-op updates and resolver-failure retention |
| Native nftables replace | Ubuntu 22.04 and 24.04 | nftables dry run and single-transaction replacement inside a temporary network namespace |
| Concurrent CLI writers | Ubuntu 22.04 and 24.04 | Multiple real processes honor flock, don't lose rules; failed simulated apply doesn't corrupt disk |
| Installer smoke | Disposable Debian 12/13 Docker filesystems | Installation and reinstallation of exact binaries/units, no unintended systemd activation; daemon-reload stubbed |
| systemd boot-restore semantics | Ubuntu 22.04 and 24.04 | A disposable real systemd unit enables, starts and restarts the unmodified native engine into an isolated kernel network namespace |
| Shell syntax | Ubuntu 24.04 | Independent required check `bash-syntax` |

**Isolation:** Runtime tests create and delete only temporary Linux network namespaces, veth pairs, state files and (for restore testing) a disposable uniquely named systemd unit on GitHub-hosted runners. They never flush the host firewall, alter production servers, or reach production endpoints.

**Known limits:** A real VM reboot, true multi-Gbps/long-duration packet loss or jitter measurement, every VPS provider firewall combination, end-to-end live Legacy→Native migration with a timed rollback, and real public-DNS propagation **cannot be proven by GitHub-hosted CI alone**. Migration ordering and fallback logic have automated mocked checks and have been manually tested on `test-de`. A real DNS A-record rotation is simulated with a controlled resolver returning two distinct destination IPv4 addresses in an isolated network, rather than altering an external authoritative DNS zone. Follow the manual release checklist below before treating a new platform-wide change as production-certified.

## Required branch settings (maintained by repository owner)

Go to **Settings → Rules → Rulesets** and create **active** protections for `development` and `main`.

- Require a pull request; 0 required approvals is practical for a single-human-maintainer repository.
- Require **`quality` and `bash-syntax` status checks**, including up-to-date branches if offered.
- Require conversation resolution.
- Prohibit force pushes and deletion.
- Avoid unnecessary owner/bot bypass rules.
- Keep `development` the default branch, and merge feature branches there first.

GitHub Actions being green without active Required Status Checks **does not prevent merging a failing PR**.

## Release process

1. Create `feature/*` branch from `development`, propose changes via PR.
2. Wait until both `quality` and `bash-syntax` are green; inspect failed subjobs and repair before review.
3. Have the owner merge to `development` (no automated release deployments).
4. Verify both checks on the resulting `development` commit.
5. For risky networking, migration, DNS-refresh or systemd changes, perform controlled extra manual tests on a dedicated test server with recent backups and console access; verify real external connectivity for the protocols actually in use (TCP and/or UDP), without requiring irrelevant protocol tests for a local deployment.
6. Prepare owner-reviewed PR `development → main`. **The PR must have its own green checks** before owner merge.
7. Promotion of code does not automatically restart services or change existing kernel firewall state.

For the native upgrade process consult [SAFE_NATIVE_CUTOVER.md](SAFE_NATIVE_CUTOVER.md); for installation and routine commands consult the root [README](../README.md).

**Security note:** A successful CI run is not a guarantee that software has zero vulnerabilities, outages, packet loss, jitter or regressions. It is a reproducible set of essential automatic gates plus explicit manual qualification for production network changes.
