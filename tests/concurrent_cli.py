#!/usr/bin/env python3
"""Concurrent state-writer contract test with stubbed system commands; no host firewall modifications."""
import concurrent.futures
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
FAKE = r'''#!/usr/bin/env python3
import os
from pathlib import Path
import sys
name = Path(sys.argv[0]).name
args = sys.argv[1:]
if name == "ip":
    print("1.1.1.1 via 198.18.11.254 dev eth0 src 198.18.11.1")
elif name == "iptables":
    sys.exit(1 if "-C" in args else 0)
elif name == "nft":
    if args[:2] == ["list", "table"]:
        sys.exit(1)
    if "-f" in args:
        sys.stdin.read()
        if os.environ.get("PORTFW_FAKE_NFT_FAIL"):
            sys.exit(1)
elif name == "systemctl":
    if args[0] == "is-enabled":
        print("disabled")
        sys.exit(1)
    if args[0] == "enable":
        with open(os.environ["PORTFW_TEST_SYSTEMCTL_LOG"], "a") as out:
            out.write("enable\n")
'''


def assert_run(command, env, should_pass=True):
    run = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=20)
    if (run.returncode == 0) != should_pass:
        raise AssertionError(f"Unexpected command exit: {command}\n{run.stdout}\n{run.stderr}")
    return run


def main():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)
        bin_dir = path / "fake-bin"
        state = path / "state"
        bin_dir.mkdir()
        state.mkdir()
        fake = bin_dir / "fake"
        fake.write_text(FAKE)
        fake.chmod(0o755)
        for cmd in ("ip", "iptables", "nft", "systemctl"):
            (bin_dir / cmd).symlink_to(fake)
        log = path / "systemctl.log"
        env = dict(os.environ)
        env.update(PORTFW_STATE_DIR=str(state), PORTFW_LOCK=str(path / "lock"),
                   PORTFW_TEST_SYSTEMCTL_LOG=str(log),
                   PATH=f"{bin_dir}:{os.environ.get('PATH', '')}")
        cmd = [sys.executable, str(ROOT / "portfw-nft"), "add"]
        # First rule is applied before enabling boot restore, never with --now.
        assert_run(cmd + ["2100", "192.0.2.10", "3100", "tcp"], env)
        if log.read_text().splitlines() != ["enable"]:
            raise AssertionError("First rule must enable boot persistence exactly once")
        # Concurrent real CLI processes share a single flock and must not lose updates.
        commands = [cmd + [str(2101 + i), "192.0.2.10", str(3101 + i), "tcp"] for i in range(12)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(assert_run, command, env) for command in commands]
            for future in futures:
                future.result()
        rules = (state / "rules.db").read_text().splitlines()
        if len(rules) != 13 or len({int(x.split("|")[1]) for x in rules}) != 13:
            raise AssertionError(f"Concurrent write lost or duplicated entries: {rules}")
        if log.read_text().splitlines() != ["enable"]:
            raise AssertionError("Subsequent additions unexpectedly re-enabled systemd")
        # Simulated nft failure must preserve both on-disk files.
        rules_before = (state / "rules.db").read_bytes()
        env_fail = {**env, "PORTFW_FAKE_NFT_FAIL": "1"}
        assert_run(cmd + ["2400", "192.0.2.10", "3400", "tcp"], env_fail, should_pass=False)
        if rules_before != (state / "rules.db").read_bytes():
            raise AssertionError("Failed kernel transaction modified persisted state")
        assert_run([sys.executable, str(ROOT / "portfw-nft"), "check"], env)
        print("PASS: concurrent writers serialized, first-rule persistence, rejected kernel transaction.")


if __name__ == "__main__":
    main()
