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
- Automatically detects the primary IPv4 source address and uses explicit `SNAT`, avoiding the wrong-source-IP behavior that `MASQUERADE` can cause on multi-IP/Floating-IP servers.
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

For each managed forward, the tool creates the required DNAT, FORWARD, and SNAT behavior. The SNAT address is detected from the host's default IPv4 route at apply time.

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

## Non-interactive commands

```bash
sudo portfw --list
sudo portfw --apply
sudo portfw --help
```

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
