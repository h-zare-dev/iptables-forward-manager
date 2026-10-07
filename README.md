# iptables-forward-manager

A small interactive manager for persistent IPv4 port forwarding with `iptables`.

The goal is simple: users manage **ports and destination IPs**, not raw firewall commands.

## Features

- Add forwarding rules with a simple form.
- Edit an existing rule without opening an editor or exposing raw `iptables` syntax.
- Delete one rule or all rules managed by this tool.
- Friendly list view with source port, destination IP, destination port, and protocol.
- TCP, UDP, or TCP+UDP rules.
- Persistent restore after reboot with `systemd`.
- Idempotent rebuilds: repeated apply/restart does not create duplicate managed rules.
- Uses dedicated `iptables` chains and does **not** flush unrelated Docker/firewall rules.
- Supports forwarding on **all IPv4 addresses currently local to the server** (primary plus floating/secondary IPs) without hardcoding those addresses.
- Automatically detects the current primary IPv4 source address whenever rules are applied/reloaded and uses explicit `SNAT`, avoiding the wrong-source-IP behavior that `MASQUERADE` can cause on multi-IP/Floating-IP servers.
- Provides a manual reload action in both the CLI and interactive menu for rebuilding rules after network changes.
- State changes are transactional: if applying a change fails, the previous state is restored.

## Supported systems

The manager itself is Bash and uses standard Linux networking tools. The installer currently supports automatic dependency installation on Debian/Ubuntu systems with `systemd`.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/h-zare-dev/iptables-forward-manager/main/install.sh | sudo bash
```

Then run:

```bash
sudo portfw
```

## Menu

```text
iptables Forward Manager

[1] Add Forwarding
[2] Edit Forwarding
[3] Delete Forwarding
[4] List Forwarding
[5] Delete All
[6] Reload Rules
[0] Exit
```

### Add example

```text
Source port: 1010
Destination IP: 51.195.233.176
Destination port: 1008
Protocol (tcp/udp/both) [both]:
```

### List example

```text
ID   Source Port  Destination IP    Destination Port  Protocol
1    1008         179.237.79.116   1008              TCP+UDP
2    1010         51.195.233.176   1008              TCP+UDP
```

### Edit example

```text
Select rule ID to edit: 2

Edit Rule 2
Press Enter to keep the current value.
Source port [1010]:
Destination IP [51.195.233.176]:
Destination port [1008]:
Protocol (tcp/udp/both) [both]:
```

No raw `iptables` rule is shown in the interactive UI.

## How it works

Managed configuration is stored in:

```text
/etc/iptables-forward-manager/rules.db
```

The tool owns only these chains:

```text
IFM_DNAT
IFM_SNAT
IFM_FORWARD
```

On each apply it flushes and rebuilds **only those chains** from the saved state. Other `iptables` rules are left alone.

For each managed forward, the tool creates the required DNAT, FORWARD, and SNAT behavior.

Incoming DNAT rules use `-m addrtype --dst-type LOCAL`. That means a forwarding rule is eligible on any IPv4 address that the kernel currently considers local to the server, including the current primary IPv4 and any floating/secondary IPv4 addresses. Those incoming addresses are not stored or hardcoded in the forwarding rule.

The SNAT address is detected dynamically from the host's default IPv4 route whenever rules are applied or reloaded. If the primary IPv4 changes while the server is running, use `portfw --reload` (or menu option **Reload Rules**) so the explicit SNAT rule is rebuilt with the new primary source address.

This project has no dependency on any floating-IP management tool. Floating/secondary addresses may be configured manually, by Netplan, by a provider agent, or by another independent tool.

## Persistence

The installer enables:

```text
iptables-forward-manager.service
```

At boot, after the network is online and after common firewall managers such as Docker/UFW/netfilter-persistent, the service runs:

```bash
portfw --apply
```

You can also re-apply manually:

```bash
sudo portfw --apply
```

Or use the reload alias:

```bash
sudo portfw --reload
```

With systemd you can reload the managed rules without rebooting:

```bash
sudo systemctl reload iptables-forward-manager
```

All three rebuild the managed chains from the saved state and re-detect the current primary IPv4 source address.

## Non-interactive commands

```bash
sudo portfw --list
sudo portfw --apply
sudo portfw --reload
sudo portfw --help
```

## Multi-IP behavior

The same forwarding rule can receive traffic on the server's current primary IPv4 and on any floating/secondary IPv4 that is local to the host.

For example, if the server currently owns:

```text
Primary:   62.238.5.238
Floating:  95.216.178.75
Floating:  65.109.254.122
```

and source port `1008` is forwarded, traffic to `1008` on any of those local addresses can match the managed DNAT rule.

If a floating IP is added or removed, the `LOCAL` destination match follows the kernel's live address/routing state; no IP address is hardcoded into the forwarding rule.

If the **primary IPv4 itself changes**, run:

```bash
sudo portfw --reload
```

so the explicit SNAT source is re-detected and rebuilt.

## Safety boundaries

`Delete All` deletes only forwarding rules managed by this project. It does not flush the host firewall, Docker chains, UFW rules, or unrelated NAT rules.

This project manages IPv4 forwarding only in the first release.

## Development-branch testing

Before a change is merged, the installer can be pointed at a branch:

```bash
curl -fsSL https://raw.githubusercontent.com/h-zare-dev/iptables-forward-manager/feature/mvp-forward-manager/install.sh \
  | sudo PORTFW_REF=feature/mvp-forward-manager bash
```

## License

MIT
