#!/usr/bin/env python3
"""UI regression tests. No actual firewall changes or root access required."""
import contextlib
import importlib.machinery
import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parent.parent / "portfw-nft"
loader = importlib.machinery.SourceFileLoader("native_ui", str(SOURCE))
spec = importlib.util.spec_from_loader(loader.name, loader)
ui = importlib.util.module_from_spec(spec)
loader.exec_module(ui)


class NativeMenuTests(unittest.TestCase):
    def setUp(self):
        self.sample = [
            ui.make_rule(1, "1015", "57.131.133.117", "2096", "both"),
            ui.make_rule(2, "2001-2003,2010", "edge.example.net", "3001-3003,8080", "tcp"),
        ]

    def test_server_dashboard_matches_legacy_fields(self):
        def ip_lookup(*args):
            if args[:3] == ("-4", "route", "show"):
                return "default via 172.31.1.1 dev eth0 proto static\n"
            if args[:2] == ("-4", "-o"):
                return ("2: eth0 inet 91.107.254.25/32 scope global eth0\n"
                        "2: eth0 inet 91.98.99.74/32 scope global eth0\n")
            if args[:2] == ("-6", "-o"):
                return "2: eth0 inet6 2a01:4f8:1c1b:31f::1/64 scope global eth0\n"
            return ""
        with patch.object(ui, "_ip_command", side_effect=ip_lookup), \
             patch.object(ui, "primary_ipv4", return_value="91.107.254.25"), \
             patch.object(ui.socket, "gethostname", return_value="test-de"), \
             patch.dict(os.environ, {"TERM": "dumb"}):
            result = io.StringIO()
            with contextlib.redirect_stdout(result):
                ui.print_header(self.sample)
        contents = result.getvalue()
        for term in ("Port Forward Manager", "nftables v2.1.0",
                     "Host:", "test-de", "Interface:", "eth0",
                     "Primary IPv4:", "91.107.254.25",
                     "Other IPv4:", "91.98.99.74",
                     "IPv6:", "2a01:4f8:1c1b:31f::1",
                     "Managed rules:", "2", "┌", "└"):
            with self.subTest(term=term):
                self.assertIn(term, contents)
        self.assertNotIn("\x1b", contents)

    def test_multiport_rows_wrap_without_truncating(self):
        r = ui.make_rule(5, "2001-2003,2010,2020-2022,3000-3010",
                         "a-subdomain.example.net", "3001-3003,8080,4000-4002,6000-6010", "both")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            ui.list_rules([r])
        data = out.getvalue()
        self.assertIn("2001-2003", data)
        self.assertIn("3010", data)
        self.assertIn("6000-6010", data)
        self.assertIn("a-subdomain.example.net", data)
        self.assertIn("TCP+UDP", data)

    def test_show_main_menu_without_touching_firewall(self):
        with patch.object(ui, "read_rules", return_value=self.sample), \
             patch.object(ui, "_server_info", return_value={
                 "host": "test-de", "interface": "eth0", "primary": "91.107.254.25",
                 "other_ipv4": "91.98.99.74", "ipv6": "2001:db8::1", "count": 2,
             }), \
             patch.object(ui, "apply") as apply, \
             patch("builtins.input", return_value="0"), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            ui.interactive()
        self.assertIn("DNS Settings", out.getvalue())
        self.assertNotIn("[9] DNS Load Balancing", out.getvalue())
        self.assertIn("Reload Rules", out.getvalue())
        self.assertIn("Delete All", out.getvalue())
        apply.assert_not_called()

    def test_edit_defaults_preserve_current_values(self):
        existing = ("2001-2003", "edge.example.net", "3001-3003", "both")
        with patch("builtins.input", side_effect=["", "", "", ""]), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ui._entry(existing), existing)

    def test_invalid_port_and_protocol_are_reprompted(self):
        entries = ["2001,,2002", "2001,2002", "192.0.2.50", "3001,3002", "bad", "tcp"]
        with patch("builtins.input", side_effect=entries), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ui._entry(), ("2001,2002", "192.0.2.50", "3001,3002", "tcp"))

    def test_invalid_one_to_one_never_changes_state(self):
        with patch("builtins.input", side_effect=["2001-2003", "192.0.2.50", "3001-3002", "both"]), \
             patch.object(ui, "change") as change, \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ui.PortfwError, "Counts must match"):
                ui._add()
        change.assert_not_called()

    def test_delete_requires_explicit_confirmation(self):
        with patch.object(ui, "read_rules", return_value=self.sample), \
             patch("builtins.input", side_effect=["1", "n"]), \
             patch.object(ui, "change") as change, \
             contextlib.redirect_stdout(io.StringIO()):
            ui._delete()
        change.assert_not_called()

    def test_dns_disabled_by_default_and_interval_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(ui.Path, "read_text", side_effect=OSError):
                self.assertEqual(ui._dns_configured_minutes(), 5)
            fake = "[Timer]\nOnUnitInactiveSec=\nOnUnitInactiveSec=30min\n"
            with patch.object(ui.Path, "read_text", return_value=fake):
                self.assertEqual(ui._dns_configured_minutes(), 30)
        with patch.object(ui, "run") as run:
            run.return_value.stdout = "disabled\n"
            self.assertFalse(ui._dns_is_enabled())



if __name__ == "__main__":
    unittest.main(verbosity=2)
