#!/usr/bin/env python3
"""Isolated TCP receiver that proves which DNS-selected IP received forwarded packets."""
import socket
import sys
import threading
import time
from pathlib import Path

IPS = ("198.18.12.2", "198.18.12.3")
ROUTER = "198.18.11.1"
SNAT = "198.18.12.1"
PORT = 6001


def receiver(ip):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((ip, PORT))
        sock.listen(16)
        while True:
            connection, peer = sock.accept()
            with connection:
                connection.settimeout(8)
                while True:
                    try:
                        data = connection.recv(128)
                    except socket.timeout:
                        break
                    if not data:
                        break
                    connection.sendall(f"ACK|{ip}|{peer[0]}|".encode() + data)


def server(flag):
    for ip in IPS:
        threading.Thread(target=receiver, args=(ip,), daemon=True).start()
    time.sleep(0.4)
    Path(flag).touch()
    while True:
        time.sleep(1)


def probe(ip):
    with socket.create_connection((ROUTER, 5001), timeout=4) as sock:
        sock.sendall(b"DNS-ROTATION")
        got = sock.recv(128)
    expected = f"ACK|{ip}|{SNAT}|DNS-ROTATION".encode()
    if got != expected:
        raise RuntimeError(f"Expected {expected!r}; received {got!r}")
    print(f"PASS: forwarded TCP reached {ip}:{PORT} with expected SNAT")


def hold(ip, ready, continue_flag):
    """Keep the same TCP socket open during nftables destination rotation."""
    with socket.create_connection((ROUTER, 5001), timeout=4) as sock:
        def exchange(payload):
            sock.sendall(payload)
            got = sock.recv(128)
            expected = f"ACK|{ip}|{SNAT}|".encode() + payload
            if got != expected:
                raise RuntimeError(f"Established flow changed destination: {got!r} != {expected!r}")
        exchange(b"BEFORE")
        Path(ready).touch()
        for _ in range(100):
            if Path(continue_flag).exists():
                break
            time.sleep(0.05)
        else:
            raise RuntimeError("Timeout awaiting DNS rotation from test harness")
        exchange(b"AFTER")
    print(f"PASS: existing TCP connection stayed on {ip} across destination rotation")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "server":
        server(sys.argv[2])
    elif len(sys.argv) == 3 and sys.argv[1] == "probe":
        probe(sys.argv[2])
    elif len(sys.argv) == 5 and sys.argv[1] == "hold":
        hold(sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        sys.exit("Usage: dns_probe.py server READY_FILE | probe DEST_IP | hold DEST_IP READY CONTINUE")
