"""Control-plane migration tests (mocks only; no host firewall changes)."""
import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

FILE = Path(__file__).resolve().parent.parent / "portfw-migrate"
loader = importlib.machinery.SourceFileLoader("portfw_migrate", str(FILE))
spec = importlib.util.spec_from_loader(loader.name, loader)
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)


class CutoverTests(unittest.TestCase):
    def test_preflight_rejects_non_iptables_nft(self):
        with tempfile.TemporaryDirectory() as tmp:
            rules = Path(tmp) / "rules.db"
            rules.write_text("1|1015|192.0.2.50|2096|both\\n")
            with patch.object(m.shutil, "which", return_value="/bin/true"), \
                 patch.object(m, "RULES", rules), \
                 patch.object(m, "run") as run:
                run.return_value.stdout = "iptables v1.8.11 (legacy)"
                with self.assertRaisesRegex(m.CutoverError, "iptables-nft"):
                    m.preflight()

    def test_preflight_rejects_missing_native_tool(self):
        with patch.object(m.shutil, "which", side_effect=lambda cmd: None if cmd == "portfw-nft" else "/bin/true"):
            with self.assertRaisesRegex(m.CutoverError, "Missing executable"):
                m.preflight()

    def test_switch_arms_rescue_before_detaching_hooks(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            events = []
            def record_run(*args, **kwargs):
                events.append(" ".join(args))
                return type("Process", (), {"stdout": "", "returncode": 0})()
            with patch.object(m, "preflight"), patch.object(m, "backup", return_value=folder), \
                 patch.object(m, "run", side_effect=record_run), \
                 patch.object(m, "ok", return_value=True), \
                 patch.object(m, "detach", side_effect=lambda *a: events.append("detach")), \
                 patch.object(m, "connected", return_value=False), \
                 patch.object(m, "native_exists", return_value=True):
                m.switch()
            self.assertTrue((folder / "pending").exists())
            self.assertLess(next(i for i, e in enumerate(events) if "systemd-run" in e),
                            next(i for i, e in enumerate(events) if "disable --now" in e))
            self.assertLess(next(i for i, e in enumerate(events) if "disable --now" in e),
                            events.index("detach"))
            self.assertLess(events.index("detach"),
                            next(i for i, e in enumerate(events) if "portfw-nft apply" in e))

    def test_rollback_reattaches_old_before_deleting_native(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "rules.db").write_text("1|1015|192.0.2.50|2096|both\n")
            (folder / "pending").touch()
            events = []
            def record_run(*args, **kwargs):
                events.append(" ".join(args))
                return type("Process", (), {"stdout": "", "returncode": 0})()
            # This unit test must never touch /etc/iptables-forward-manager.
            with patch.object(m, "get_session", return_value=folder), \
                 patch.object(m, "run", side_effect=record_run), \
                 patch.object(m, "native_exists", return_value=True), \
                 patch.object(m, "attach", side_effect=lambda *a: events.append("attach")), \
                 patch.object(m, "cancel_rescue"), patch.object(m.shutil, "copy2"):
                m.rollback()
            self.assertEqual(events.count("attach"), 3)
            self.assertLess(events.index("attach"),
                            next(i for i, e in enumerate(events) if e.startswith("nft delete table")))

    def test_confirm_rejects_no_external_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "pending").touch()
            with patch.object(m, "get_session", return_value=folder), \
                 patch.object(m, "ok", return_value=False):
                with self.assertRaisesRegex(m.CutoverError, "not active"):
                    m.confirm()
            self.assertTrue((folder / "pending").exists())


if __name__ == "__main__":
    unittest.main()
