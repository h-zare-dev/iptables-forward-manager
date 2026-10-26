#!/usr/bin/env python3
"""Unit/contract tests. No firewall or root access required."""
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parent.parent / "portfw-nft"
loader = importlib.machinery.SourceFileLoader("portfw_nft", str(SOURCE))
spec = importlib.util.spec_from_loader(loader.name, loader)
fw = importlib.util.module_from_spec(spec)
loader.exec_module(fw)


class ParseTests(unittest.TestCase):
    def test_single_port_and_backward_compatible_record(self):
        self.assertEqual(fw.ports("2001"), [2001])
        self.assertEqual(fw.make_rule("1", "2001", "192.0.2.7", "3001", "both"),
                         (1, "2001", "192.0.2.7", "3001", "both"))

    def test_range_inclusive_and_ordered_mixed_list(self):
        self.assertEqual(fw.ports("2001-2003, 2008, 2020-2021"), [2001,2002,2003,2008,2020,2021])
        self.assertEqual(fw.ports("3001, 3005, 3010"), [3001,3005,3010])

    def test_mismatched_source_destination_counts_fail(self):
        with self.assertRaisesRegex(fw.PortfwError, "Counts must match"):
            fw.make_rule("1", "2001-2010", "192.0.2.7", "3001-3005", "tcp")

    def test_bad_port_specs(self):
        bad = ["0", "65536", "2010-2001", "2001,,2002", "2001,", "2001-",
               "2001-2002-2003", "2001,2001", "2001-2003,2002", "-3", "",
               "1;2", "1\n2"]
        for item in bad:
            with self.subTest(item=item), self.assertRaises(fw.PortfwError):
                fw.ports(item)

    def test_limit(self):
        with self.assertRaisesRegex(fw.PortfwError, "More than"):
            fw.ports("1-4097")

    def test_protocol_conflicts(self):
        one = fw.make_rule(1, "2001-2003", "192.0.2.7", "3001-3003", "both")
        two = fw.make_rule(2, "2003,2010", "198.51.100.9", "4000,4001", "udp")
        with self.assertRaisesRegex(fw.PortfwError, "conflict"):
            fw.validate_rules([one, two])
        a = fw.make_rule(1, "2003", "192.0.2.7", "3001", "tcp")
        b = fw.make_rule(2, "2003", "192.0.2.8", "3002", "udp")
        self.assertEqual(len(fw.validate_rules([a, b])), 2)

    def test_host_safety(self):
        self.assertEqual(fw.destination("Node.Example.COM"), "node.example.com")
        for host in ("127.0.0.1", "0.0.0.0", "239.1.2.3", "$(echo BAD)", "-x.example.org", "example.com:80"):
            with self.subTest(host=host), self.assertRaises(fw.PortfwError):
                fw.destination(host)


class RenderTests(unittest.TestCase):
    def test_map_preserves_positional_mapping_and_both_protocols(self):
        r = fw.make_rule(1, "2001-2003,2010", "192.0.2.50", "3001-3003,8080", "both")
        data = fw.nft_config([r], {}, "198.51.100.10")
        self.assertIn("2001 : 192.0.2.50 . 3001", data)
        self.assertIn("2002 : 192.0.2.50 . 3002", data)
        self.assertIn("2003 : 192.0.2.50 . 3003", data)
        self.assertIn("2010 : 192.0.2.50 . 8080", data)
        self.assertIn("tcp_dnat", data)
        self.assertIn("udp_dnat", data)
        self.assertIn("fib daddr type local", data)
        self.assertIn("ct original proto-dst @tcp_snat snat to 198.51.100.10", data)
        self.assertNotIn("flush ruleset", data)
        self.assertNotIn("IFM_DNAT", data)

    def test_dns_cache_and_table_replacement(self):
        r = fw.make_rule(3, "80", "node.example.com", "8080", "tcp")
        with self.assertRaisesRegex(fw.PortfwError, "No DNS cache"):
            fw.nft_config([r], {}, "198.51.100.10")
        data = fw.nft_config([r], {"node.example.com": "203.0.113.7"}, "198.51.100.10", existing=True)
        self.assertTrue(data.startswith("delete table ip ifm_portfw\nadd table ip ifm_portfw"))
        self.assertIn("80 : 203.0.113.7 . 8080", data)

    def test_does_not_affect_external_tables(self):
        script = fw.nft_config([], {}, "192.0.2.1", existing=True)
        self.assertNotIn("flush ruleset", script)
        self.assertNotIn("delete table ip filter", script)
        self.assertNotIn("iptables", script)
        self.assertIn("delete table ip ifm_portfw", script)


class StorageAndRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / "state"
        self.state.mkdir()
        self.p1 = patch.object(fw, "STATE_DIR", self.state)
        self.p2 = patch.object(fw, "RULES", self.state / "rules.db")
        self.p3 = patch.object(fw, "CACHE", self.state / "dns-cache.db")
        self.p4 = patch.object(fw, "LOCK", self.root / "portfw.lock")
        for p in (self.p1, self.p2, self.p3, self.p4):
            p.start()
            self.addCleanup(p.stop)

    def test_legacy_state_read_without_migration(self):
        fw.RULES.write_text("1|1008|179.237.79.116|1008|both\n")
        self.assertEqual(fw.read_rules()[0][3], "1008")

    def test_unchanged_dns_never_rewrites_firewall(self):
        fw.save_rules([fw.make_rule(1, "2001", "edge.example.net", "3001", "tcp")])
        fw.save_cache({"edge.example.net": "192.0.2.50"})
        with patch.object(fw, "resolve_all", return_value=["192.0.2.50"]), patch.object(fw, "apply") as apply:
            fw.refresh_dns()
            apply.assert_not_called()

    def test_dns_changed_committed_and_old_ip_retained_on_error(self):
        fw.save_rules([fw.make_rule(1, "2001", "edge.example.net", "3001", "tcp")])
        fw.save_cache({"edge.example.net": "192.0.2.50"})
        with patch.object(fw, "resolve_all", return_value=["198.51.100.22"]), patch.object(fw, "apply") as apply:
            fw.refresh_dns()
            apply.assert_called_once()
            self.assertEqual(fw.read_cache()["edge.example.net"], "198.51.100.22")
        with patch.object(fw, "resolve_all", side_effect=fw.PortfwError("timeout")), patch.object(fw, "apply") as apply:
            fw.refresh_dns()
            apply.assert_not_called()
            self.assertEqual(fw.read_cache()["edge.example.net"], "198.51.100.22")

    def test_failed_commit_keeps_previous_cache(self):
        fw.save_rules([fw.make_rule(1, "2001", "edge.example.net", "3001", "tcp")])
        fw.save_cache({"edge.example.net": "192.0.2.50"})
        with patch.object(fw, "resolve_all", return_value=["198.51.100.22"]), \
             patch.object(fw, "apply", side_effect=fw.PortfwError("nft failed")):
            with self.assertRaises(fw.PortfwError):
                fw.refresh_dns()
        self.assertEqual(fw.read_cache()["edge.example.net"], "192.0.2.50")

    def test_failed_add_keeps_rules(self):
        import argparse
        fw.save_rules([fw.make_rule(1, "2001", "192.0.2.50", "3001", "tcp")])
        args = argparse.Namespace(source="2002", target="198.51.100.22", dest="3002", protocol="tcp")
        with patch.object(fw, "apply", side_effect=fw.PortfwError("preflight failed")):
            with self.assertRaises(fw.PortfwError):
                fw.change("add", args)
        self.assertEqual(len(fw.read_rules()), 1)

    def test_first_successful_add_enables_boot_persistence_without_restart(self):
        import argparse
        import subprocess
        args = argparse.Namespace(source="2001", target="192.0.2.50", dest="3001", protocol="tcp")
        def fake_run(command, **kwargs):
            if command[:2] == ["systemctl", "is-enabled"]:
                return subprocess.CompletedProcess(command, 1, stdout="disabled\n", stderr="")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        with patch.object(fw, "apply") as apply, patch.object(fw, "run", side_effect=fake_run) as run:
            fw.change("add", args)
            apply.assert_called_once()
            calls = [call.args[0] for call in run.call_args_list]
        self.assertIn(["systemctl", "enable", "portfw-nft.service"], calls)
        self.assertNotIn(["systemctl", "enable", "--now", "portfw-nft.service"], calls)
        self.assertNotIn(["systemctl", "restart", "portfw-nft.service"], calls)
        self.assertEqual(len(fw.read_rules()), 1)

    def test_subsequent_add_does_not_override_manual_service_disable(self):
        import argparse
        fw.save_rules([fw.make_rule(1, "2001", "192.0.2.50", "3001", "tcp")])
        args = argparse.Namespace(source="2002", target="192.0.2.50", dest="3002", protocol="tcp")
        with patch.object(fw, "apply"), patch.object(fw, "run") as run:
            fw.change("add", args)
            run.assert_not_called()

    def test_failed_first_add_does_not_enable_service(self):
        import argparse
        args = argparse.Namespace(source="2001", target="192.0.2.50", dest="3001", protocol="tcp")
        with patch.object(fw, "apply", side_effect=fw.PortfwError("nft failed")), \
             patch.object(fw, "run") as run:
            with self.assertRaisesRegex(fw.PortfwError, "nft failed"):
                fw.change("add", args)
            run.assert_not_called()
        self.assertEqual(fw.read_rules(), [])

    def test_enable_failure_keeps_successful_forwarding_and_warns(self):
        import argparse
        import subprocess
        import io
        from contextlib import redirect_stderr
        args = argparse.Namespace(source="2001", target="192.0.2.50", dest="3001", protocol="tcp")
        def fake_run(command, **kwargs):
            if command[:2] == ["systemctl", "is-enabled"]:
                return subprocess.CompletedProcess(command, 1, stdout="disabled\n", stderr="")
            raise fw.PortfwError("systemctl enable failed")
        errors = io.StringIO()
        with patch.object(fw, "apply"), patch.object(fw, "run", side_effect=fake_run), redirect_stderr(errors):
            fw.change("add", args)
        self.assertIn("automatic boot restore could not be enabled", errors.getvalue())
        self.assertEqual(len(fw.read_rules()), 1)

    def test_file_permission(self):
        fw.save_cache({"edge.example.net": "192.0.2.50"})
        self.assertEqual(fw.CACHE.stat().st_mode & 0o777, 0o600)

    def test_all_dns_fail_keeps_old_ip(self):
        fw.save_rules([fw.make_rule(1, "2001", "edge.example.net", "3001", "tcp")])
        fw.save_cache({"edge.example.net": "192.0.2.50"})
        with patch.object(fw, "resolve_all", side_effect=fw.PortfwError("DNS failed")):
            fw.refresh_dns()
        self.assertEqual(fw.read_cache()["edge.example.net"], "192.0.2.50")


if __name__ == "__main__":
    unittest.main(verbosity=2)
