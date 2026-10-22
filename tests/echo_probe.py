#!/usr/bin/env python3
"""TCP/UDP echo probes for the *isolated* network-namespace data-plane test."""
import socket
import sys
import threading
import time
from pathlib import Path

SERVER_IP = "198.18.12.2"
EXPECTED_SNAT = "198.18.12.1"
ROUTER_CLIENT_IP = "198.18.11.1"
PORTS = (3001, 3002, 3003, 8080, 6001)


def serve_tcp(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((SERVER_IP, port))
        sock.listen(32)
        while True:
            connection, peer = sock.accept()
            with connection:
                data = connection.recv(1024)
                connection.sendall(f"ACK|{port}|{peer[0]}|".encode() + data)


def serve_udp(port):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind((SERVER_IP, port))
        while True:
            data, peer = sock.recvfrom(1024)
            sock.sendto(f"ACK|{port}|{peer[0]}|".encode() + data, peer)


def server(flag):
    for port in PORTS:
        for callback in (serve_tcp, serve_udp):
            threading.Thread(target=callback, args=(port,), daemon=True).start()
    time.sleep(0.5)
    Path(flag).touch()
    while True:
        time.sleep(1)


def probe(protocol, source_port, destination_port):
    payload = f"probe-{protocol}-{source_port}".encode()
    expected = f"ACK|{destination_port}|{EXPECTED_SNAT}|".encode() + payload
    kind = socket.SOCK_STREAM if protocol == "tcp" else socket.SOCK_DGRAM
    with socket.socket(socket.AF_INET, kind) as sock:
        sock.settimeout(4)
        if protocol == "tcp":
            sock.connect((ROUTER_CLIENT_IP, source_port))
            sock.sendall(payload)
            answer = sock.recv(1024)
        else:
            sock.sendto(payload, (ROUTER_CLIENT_IP, source_port))
            answer, _ = sock.recvfrom(1024)
    if answer != expected:
        raise RuntimeError(f"{protocol}/{source_port}: expected {expected!r}, got {answer!r}")
    print(f"PASS {protocol}/{source_port} -> {SERVER_IP}:{destination_port}, SNAT={EXPECTED_SNAT}")


if __name__ == "__main__":
    if sys.argv[1] == "server":
        server(sys.argv[2])
    elif sys.argv[1] == "probe":
        probe(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]))
    else:
        raise SystemExit("Usage: echo_probe.py server FLAG | probe tcp|udp SOURCE DEST")
