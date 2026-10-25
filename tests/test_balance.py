#!/usr/bin/env python3
"""Timed DNS rotation contract tests; no root or firewall access required."""
import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parent.parent / "portfw-nft"
loader = importlib.machinery.SourceFileLoader("portfw_balance", str(SOURCE))
spec = importlib.util.spec_from_loader(loader.name, loader)
fw = importlib.util.module_from_spec(spec)
loader.exec_module(fw)

HOST = "edge.example.net"
A = "198.51.100.10"
B = "198.51.100.20"
C = "198.51.100.30"


class TimedBalancingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        state = root / "state"
        state.mkdir()
        for key, value in (
            ("STATE_DIR", state), ("RULES", state / "rules.db"),
            ("CACHE", state / "dns-cache.db"), ("BALANCE", state / "dns-balance.db"),
            ("BACKENDS", state / "dns-backends.db"),
            ("LOCK", root / "lock"),
        ):
            p = patch.object(fw, key, value)
            p.start()
            self.addCleanup(p.stop)
        self.rule = fw.make_rule(1, "2020", HOST, "2020", "both")
        fw.save_rules([self.rule])
        fw.save_cache({HOST: A})
        p = patch.object(fw, "_dns_is_enabled", return_value=True)
        p.start()
        self.addCleanup(p.stop)

    def enable(self, now=1000, minutes=5, addresses=None):
        if addresses is None:
            addresses = [A, B]
        with patch.object(fw, "resolve_all", return_value=addresses), \
             patch.object(fw.time, "time", return_value=now):
            fw.configure_balance(1, True, minutes)

    def refresh(self, now, addresses=None, failed=False):
        if addresses is None:
            addresses = [A, B]
        with patch.object(fw, "resolve_all",
                          side_effect=fw.PortfwError("DNS outage") if failed else None,
                          return_value=addresses), \
             patch.object(fw.time, "time", return_value=now), \
             patch.object(fw, "apply") as apply:
            fw.refresh_dns()
            return apply.call_count

    def test_resolver_deduplicates_and_orders_all_a_records(self):
        import subprocess
        response = subprocess.CompletedProcess([], 0, stdout=(
            f"{B} STREAM edge.example.net\n{A} DGRAM edge.example.net\n"
            f"{B} RAW edge.example.net\n{C} STREAM edge.example.net\n"), stderr="")
        with patch.object(fw, "run", return_value=response):
            self.assertEqual(fw.resolve_all(HOST), [A, B, C])
            self.assertEqual(fw.resolve(HOST), A)

    def test_rotation_is_opt_in_and_no_early_swap(self):
        self.enable()
        self.assertEqual(self.refresh(1299), 0)
        self.assertEqual(fw.read_cache()[HOST], A)
        self.assertEqual(fw.read_balance()[HOST], (5, A, 1000))

    def test_after_five_minutes_exactly_one_backend_switches(self):
        self.enable()
        self.assertEqual(self.refresh(1300), 1)
        self.assertEqual(fw.read_cache()[HOST], B)
        self.assertEqual(fw.read_balance()[HOST], (5, B, 1300))
        self.assertEqual(self.refresh(1305), 0)
        self.assertEqual(self.refresh(1599), 0)
        self.assertEqual(self.refresh(1600), 1)
        self.assertEqual(fw.read_cache()[HOST], A)

    def test_three_backends_rotate_in_numeric_order(self):
        self.enable(addresses=[A, B, C])
        for now, expected in [(1300, B), (1600, C), (1900, A)]:
            self.assertEqual(self.refresh(now, addresses=[C, A, B]), 1)
            self.assertEqual(fw.read_cache()[HOST], expected)

    def test_no_timer_refresh_is_no_rotation(self):
        self.enable()
        self.assertEqual(fw.read_balance()[HOST], (5, A, 1000))
        self.assertEqual(fw.read_cache()[HOST], A)

    def test_resolver_outage_keeps_previous_backend_and_clock(self):
        self.enable()
        self.assertEqual(self.refresh(1300, failed=True), 0)
        self.assertEqual(fw.read_cache()[HOST], A)
        self.assertEqual(fw.read_balance()[HOST], (5, A, 1000))

    def test_current_backend_removed_from_dns_switches_immediately(self):
        self.enable()
        self.assertEqual(self.refresh(1001, addresses=[B, C]), 1)
        self.assertEqual(fw.read_cache()[HOST], B)

    def test_only_one_a_answer_keeps_current_ip_without_switch(self):
        self.enable()
        self.assertEqual(self.refresh(1600, addresses=[A]), 0)
        self.assertEqual(fw.read_balance()[HOST], (5, A, 1000))

    def test_after_restart_state_is_read_from_disk(self):
        self.enable()
        self.assertEqual(self.refresh(1300), 1)
        reloaded = fw.read_balance()
        self.assertEqual(reloaded[HOST], (5, B, 1300))
        self.assertEqual(self.refresh(1590), 0)

    def test_failed_kernel_validation_does_not_advance_selection(self):
        self.enable()
        with patch.object(fw, "resolve_all", return_value=[A, B]), \
             patch.object(fw.time, "time", return_value=1300), \
             patch.object(fw, "apply", side_effect=fw.PortfwError("nft failed")):
            with self.assertRaisesRegex(fw.PortfwError, "nft failed"):
                fw.refresh_dns()
        self.assertEqual(fw.read_cache()[HOST], A)
        self.assertEqual(fw.read_balance()[HOST], (5, A, 1000))

    def test_disabled_rule_reverts_to_stable_lowest_on_next_dns_refresh(self):
        self.enable()
        self.assertEqual(self.refresh(1300), 1)
        fw.configure_balance(1, False)
        self.assertEqual(fw.read_balance(), {})
        with patch.object(fw, "resolve", return_value=A), \
             patch.object(fw, "apply") as apply:
            fw.refresh_dns()
            apply.assert_called_once()
        self.assertEqual(fw.read_cache()[HOST], A)

    def test_non_domain_rule_must_not_enable_balancing(self):
        fw.save_rules([fw.make_rule(1, "2020", A, "2020", "both")])
        with self.assertRaisesRegex(fw.PortfwError, "domain"):
            fw.configure_balance(1, True)
        self.assertFalse(fw.BALANCE.exists())

    def test_one_a_record_cannot_enable(self):
        with patch.object(fw, "resolve_all", return_value=[A]), \
             self.assertRaisesRegex(fw.PortfwError, "at least two"):
            fw.configure_balance(1, True)
        self.assertFalse(fw.BALANCE.exists())

    def test_balance_file_validation(self):
        fw.BALANCE.write_text(f"{HOST}|61|{A}|1000\n")
        with self.assertRaises(fw.PortfwError):
            fw.read_balance()
        fw.BALANCE.write_text(f"{HOST}|5|{A}|1000\n{HOST}|5|{A}|1001\n")
        with self.assertRaises(fw.PortfwError):
            fw.read_balance()

    def test_clear_prunes_balancer_and_no_kernel_on_other_host(self):
        import argparse
        self.enable()
        with patch.object(fw, "apply"):
            fw.change("clear", argparse.Namespace())
        self.assertEqual(fw.read_balance(), {})
        self.assertEqual(fw.read_rules(), [])

    def test_edit_domain_to_another_cleans_old_balancer(self):
        import argparse
        self.enable()
        with patch.object(fw, "apply"), \
             patch.object(fw, "resolve", return_value=C):
            fw.change("edit", argparse.Namespace(id=1, source="2020",
                    target="other.example.net", dest="2020", protocol="both"))
        self.assertEqual(fw.read_balance(), {})
        self.assertEqual(fw.read_cache(), {"other.example.net": C})

    def test_shared_domain_rules_rotate_together(self):
        self.enable()
        fw.save_rules([self.rule, fw.make_rule(2, "2030", HOST, "2030", "tcp")])
        self.assertEqual(self.refresh(1300), 1)
        self.assertEqual(fw.read_cache()[HOST], B)

    def test_per_connection_requires_at_least_two_records(self):
        with patch.object(fw, "resolve_all", return_value=[A]), \
             self.assertRaisesRegex(fw.PortfwError, "at least two"):
            fw.configure_balance(1, True, mode="round-robin")

    def test_per_connection_mode_persists_and_installs_kernel_once(self):
        with patch.object(fw, "resolve_all", return_value=[A, B]), \
             patch.object(fw, "apply") as apply:
            fw.configure_balance(1, True, mode="round-robin")
        apply.assert_called_once()
        self.assertEqual(fw.read_balance()[HOST][0], 0)
        self.assertEqual(fw.read_backends()[HOST], [A, B])

    def test_per_connection_polls_without_replacing_unchanged_nft(self):
        with patch.object(fw, "resolve_all", return_value=[A, B]), \
             patch.object(fw, "apply"):
            fw.configure_balance(1, True, mode="round-robin")
        self.assertEqual(self.refresh(999999, addresses=[A, B]), 0)
        self.assertEqual(fw.read_backends()[HOST], [A, B])

    def test_per_connection_dns_change_updates_kernel_destinations(self):
        with patch.object(fw, "resolve_all", return_value=[A, B]), \
             patch.object(fw, "apply"):
            fw.configure_balance(1, True, mode="round-robin")
        self.assertEqual(self.refresh(10000, addresses=[B, C]), 1)
        self.assertEqual(fw.read_backends()[HOST], [B, C])
        self.assertEqual(fw.read_balance()[HOST][0], 0)

    def test_per_connection_dns_failure_keeps_last_good_backends(self):
        with patch.object(fw, "resolve_all", return_value=[A, B]), \
             patch.object(fw, "apply"):
            fw.configure_balance(1, True, mode="round-robin")
        self.assertEqual(self.refresh(10000, failed=True), 0)
        self.assertEqual(fw.read_backends()[HOST], [A, B])

    def test_per_connection_kernel_apply_failure_leaves_mode_off(self):
        with patch.object(fw, "resolve_all", return_value=[A, B]), \
             patch.object(fw, "apply", side_effect=fw.PortfwError("nft rejected")):
            with self.assertRaisesRegex(fw.PortfwError, "nft rejected"):
                fw.configure_balance(1, True, mode="round-robin")
        self.assertFalse(fw.BALANCE.exists())
        self.assertFalse(fw.BACKENDS.exists())

    def test_per_connection_disabling_restores_static_nft(self):
        with patch.object(fw, "resolve_all", return_value=[A, B]), \
             patch.object(fw, "apply"):
            fw.configure_balance(1, True, mode="round-robin")
        with patch.object(fw, "apply") as apply:
            fw.configure_balance(1, False)
        apply.assert_called_once()
        self.assertEqual(fw.read_balance(), {})
        self.assertEqual(fw.read_backends(), {})

    def test_static_and_rr_uses_shared_postrouting_and_explicit_tcp_udp(self):
        r2 = fw.make_rule(2, "2030", "198.51.100.77", "3030", "both")
        self.assertEqual(fw.read_cache()[HOST], A)
        script = fw.nft_config([self.rule, r2], {HOST: A}, "198.51.100.80",
            balance={HOST: (0, A, 1000)}, backends={HOST: [A, B]})
        self.assertIn("numgen inc mod 2", script)
        self.assertIn("tcp_rr2", script)
        self.assertIn("udp_rr2", script)
        self.assertIn("2020 . 0 : 198.51.100.10 . 2020", script)
        self.assertIn("2020 . 1 : 198.51.100.20 . 2020", script)
        self.assertIn("2030 : 198.51.100.77 . 3030", script)
        self.assertIn("198.51.100.20 . 2020 . 2020", script)

    def test_rr_mode_limit_rejects_mapping_explosion(self):
        src = ",".join(str(x) for x in range(1001, 1002))
        rec = fw.make_rule(1, src, HOST, "2020", "both")
        with patch.object(fw, "MAX_RR_MAPPINGS", 1), self.assertRaisesRegex(fw.PortfwError, "Too many"):
            fw.nft_config([rec], {HOST: A}, A, balance={HOST:(0,A,100)},
                          backends={HOST:[A,B]})

    def test_new_domain_config_defaults_to_off(self):
        self.assertEqual(self.refresh(1800), 0)
        self.assertFalse(fw.BALANCE.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
