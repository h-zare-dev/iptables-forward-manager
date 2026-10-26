#!/usr/bin/env python3
"""Rule-first DNS UX, per-rule scheduler and migration contract tests."""
import argparse
import contextlib
import importlib.machinery
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parent.parent / "portfw-nft"
loader = importlib.machinery.SourceFileLoader("native_rule_dns", str(SOURCE))
spec = importlib.util.spec_from_loader(loader.name, loader)
fw = importlib.util.module_from_spec(spec)
loader.exec_module(fw)

HOST = "edge.example.net"
A, B, C = "198.51.100.10", "198.51.100.20", "198.51.100.30"


def args(target=HOST, mode=None, poll=5, rotate=5, addresses=None, rid=None, source="2020", protocol="both"):
    return argparse.Namespace(id=rid, source=source, target=target, dest=source,
          protocol=protocol, dns_mode=mode, dns_poll=poll, dns_rotate=rotate,
          dns_addresses=addresses)


class RuleFirstDNSTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        state = root / "state"
        state.mkdir()
        for field, value in (
            ("STATE_DIR", state), ("RULES", state/"rules.db"),
            ("CACHE", state/"dns-cache.db"), ("BALANCE", state/"dns-balance.db"),
            ("BACKENDS", state/"dns-backends.db"), ("RULE_DNS", state/"dns-rules.json"),
            ("TIMER_MANAGED", state/"dns-timer-managed"), ("LOCK", root/"lock")
        ):
            p = patch.object(fw, field, value)
            p.start()
            self.addCleanup(p.stop)
        for field, value in (("apply", None), ("_sync_dns_timer", None),
                              ("_enable_persistence_after_first_add", None)):
            p = patch.object(fw, field)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(fw, "resolve_all", return_value=[A, B])
        p.start()
        self.addCleanup(p.stop)
        p = patch.object(fw.time, "time", return_value=1000)
        p.start()
        self.addCleanup(p.stop)

    def add(self, mode="off", poll=5, rotate=5, source="2020", host=HOST):
        fw.change("add", args(target=host, mode=mode, poll=poll,
                              rotate=rotate, addresses=[A, B], source=source))

    def test_add_default_off_still_has_automatic_dns_refresh(self):
        self.add()
        policy = fw.read_rule_dns()[1]
        self.assertEqual((policy["mode"], policy["poll"], policy["selected"]), ("off", 5, A))
        fw._sync_dns_timer.assert_called_once()
        self.assertEqual(fw.read_rules()[0][2], HOST)
        self.assertEqual(fw.RULE_DNS.stat().st_mode & 0o777, 0o600)

    def test_add_ip_has_no_dns_policy_or_timer(self):
        fw.change("add", args(target="192.0.2.9", source="2020"))
        self.assertEqual(fw.read_rule_dns(), {})
        fw._sync_dns_timer.assert_called_once_with(fw.read_rules())
        # _sync sees that only an IP rule exists and no DNS timer is required.
        self.assertEqual(fw.read_rules()[0][2], "192.0.2.9")

    def test_independent_modes_on_same_domain(self):
        self.add(mode="timed", poll=1, rotate=5)
        self.add(mode="rr", source="3030")
        config = fw.read_rule_dns()
        self.assertEqual(config[1]["mode"], "timed")
        self.assertEqual(config[2]["mode"], "rr")
        script = fw.nft_config(fw.read_rules(), fw.read_cache(), A,
                                policies=config)
        self.assertIn("2020 : 198.51.100.10 . 2020", script)
        self.assertIn("3030 : jump tcp_rr_2", script)
        self.assertIn("3030 : jump udp_rr_2", script)
        self.assertNotIn("2020 : jump tcp_rr_1", script)

    def test_rr_with_only_one_backend_is_rejected_before_kernel(self):
        with self.assertRaisesRegex(fw.PortfwError, "two or more"):
            fw.change("add", args(mode="rr", addresses=[A]))
        self.assertEqual(fw.read_rules(), [])

    def test_timed_rotation_runs_without_forcing_dns_lookup_every_minute(self):
        self.add(mode="timed", poll=5, rotate=1)
        with patch.object(fw.time, "time", return_value=1059):
            fw.refresh_dns()
        self.assertEqual(fw.read_rule_dns()[1]["selected"], A)
        fw.resolve_all.assert_called_once()  # only the original Add call
        with patch.object(fw.time, "time", return_value=1060):
            fw.refresh_dns()
        self.assertEqual(fw.read_rule_dns()[1]["selected"], B)
        fw.resolve_all.assert_called_once()

    def test_off_mode_dns_updates_when_selected_ip_is_removed(self):
        self.add()
        with patch.object(fw.time, "time", return_value=1100):
            fw.refresh_dns()
        self.assertEqual(fw.read_rule_dns()[1]["selected"], A)
        with patch.object(fw.time, "time", return_value=1310), \
             patch.object(fw, "resolve_all", return_value=[B, C]):
            fw.refresh_dns()
        self.assertEqual(fw.read_rule_dns()[1]["selected"], B)

    def test_off_mode_preserves_stable_ip_if_a_record_still_present(self):
        self.add()
        with patch.object(fw.time, "time", return_value=1310), \
             patch.object(fw, "resolve_all", return_value=[A, B, C]):
            fw.refresh_dns()
        self.assertEqual(fw.read_rule_dns()[1]["selected"], A)

    def test_rr_polls_without_replacing_kernel_for_unchanged_dns(self):
        self.add(mode="rr", poll=1)
        fw.apply.reset_mock()
        with patch.object(fw.time, "time", return_value=1061):
            fw.refresh_dns()
        fw.apply.assert_not_called()
        self.assertEqual(fw.read_rule_dns()[1]["checked"], 1061)

    def test_rr_dns_change_updates_only_its_own_backend_state(self):
        self.add(mode="rr", poll=1)
        self.add(mode="off", source="3030")
        with patch.object(fw.time, "time", return_value=1061), \
             patch.object(fw, "resolve_all", return_value=[B, C]):
            fw.refresh_dns()
        self.assertEqual(fw.read_rule_dns()[1]["backends"], [B, C])
        self.assertEqual(fw.read_rule_dns()[2]["mode"], "off")
        fw.apply.assert_called()

    def test_edit_mode_in_one_flow(self):
        self.add()
        fw.change("edit", args(target=HOST, mode="rr", poll=3, addresses=[A,B], rid=1))
        self.assertEqual(fw.read_rule_dns()[1]["mode"], "rr")
        self.assertEqual(fw.read_rule_dns()[1]["poll"], 3)
        self.assertIn("2020 : jump tcp_rr_1",
                      fw.nft_config(fw.read_rules(), fw.read_cache(), A,
                                    policies=fw.read_rule_dns()))

    def test_delete_prunes_policy_and_automatic_timer(self):
        self.add()
        fw.change("delete", argparse.Namespace(id=1))
        self.assertEqual(fw.read_rule_dns(), {})
        self.assertEqual(fw.read_rules(), [])
        fw._sync_dns_timer.assert_called_with([])

    def test_failed_timer_activation_is_not_reported_as_success(self):
        fw._sync_dns_timer.side_effect = fw.PortfwError("timer start failed")
        with self.assertRaisesRegex(fw.PortfwError, "timer start failed"):
            self.add()
        self.assertEqual(fw.read_rules(), [])
        self.assertEqual(fw.read_rule_dns(), {})
        self.assertEqual(fw.apply.call_count, 2)

    def test_failed_kernel_preflight_never_updates_rule_or_dns(self):
        fw.apply.side_effect = fw.PortfwError("nft check failed")
        with self.assertRaisesRegex(fw.PortfwError, "nft check failed"):
            self.add(mode="rr")
        self.assertFalse(fw.RULES.exists())
        self.assertFalse(fw.RULE_DNS.exists())

    def test_legacy_per_domain_round_robin_read_and_upgrade(self):
        fw.save_rules([fw.make_rule(1, "2020", HOST, "2020", "both")])
        fw.save_cache({HOST: A})
        fw.save_balance({HOST: (0, A, 999)})
        fw.save_backends({HOST: [A, B]})
        # Existing data plane is preserved until edited.
        script = fw.nft_config(fw.read_rules(), fw.read_cache(), A,
                        balance=fw.read_balance(), backends=fw.read_backends())
        self.assertIn("2020 : jump tcp_rr_1", script)
        with patch.object(fw, "resolve_all", return_value=[A, B]):
            fw.change("edit", args(mode="rr", poll=5, addresses=[A,B], rid=1))
        self.assertEqual(fw.read_rule_dns()[1]["mode"], "rr")
        self.assertIn("2020 : jump tcp_rr_1",
             fw.nft_config(fw.read_rules(), fw.read_cache(), A,
                            policies=fw.read_rule_dns(),
                            balance=fw.read_balance(), backends=fw.read_backends()))

    def test_invalid_persisted_policy_rejected(self):
        fw.RULE_DNS.write_text('{"schema":1,"rules":{"1":{"mode":"bad"}}}')
        with self.assertRaisesRegex(fw.PortfwError, "Invalid DNS rule mode"):
            fw.read_rule_dns()


class ColorfulMenuTests(unittest.TestCase):
    def test_single_ip_skips_mode_menu(self):
        with patch.object(fw, "resolve_all", return_value=[A]), \
             patch.object(fw, "_prompt", side_effect=["N"]), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            result = fw._rule_dns_form(None, HOST)
        self.assertEqual(result["dns_mode"], "off")
        self.assertEqual(result["dns_poll"], 5)
        self.assertNotIn("Per-Connection RR", out.getvalue())

    def test_multi_a_off_and_custom_refresh(self):
        with patch.object(fw, "resolve_all", return_value=[A,B,C]), \
             patch.object(fw, "_prompt", side_effect=["1", "y", "10"]), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            result = fw._rule_dns_form(None, HOST)
        self.assertEqual((result["dns_mode"], result["dns_poll"]), ("off", 10))
        for label in ("IPv4 A records", "Single IP", "Timed Rotation",
                      "Per-Connection RR", "DNS Updates: AUTO", "┌"):
            self.assertIn(label, out.getvalue())

    def test_timed_default_poll_and_rotation(self):
        with patch.object(fw, "resolve_all", return_value=[A,B]), \
             patch.object(fw, "_prompt", side_effect=["2", "5", "N"]), \
             contextlib.redirect_stdout(io.StringIO()):
            result = fw._rule_dns_form(None, HOST)
        self.assertEqual((result["dns_mode"], result["dns_poll"], result["dns_rotate"]),
                         ("timed", 1, 5))

    def test_rr_default_poll_and_no_rotation_question(self):
        with patch.object(fw, "resolve_all", return_value=[A,B]), \
             patch.object(fw, "_prompt", side_effect=["3", "N"]) as ask, \
             contextlib.redirect_stdout(io.StringIO()):
            result = fw._rule_dns_form(None, HOST)
        self.assertEqual((result["dns_mode"], result["dns_poll"]), ("rr", 5))
        self.assertEqual(ask.call_count, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
