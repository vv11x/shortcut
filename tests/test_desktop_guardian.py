"""Crash-recovery marker and guardian logic; no real Explorer calls."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import shortcut_app.desktop_guardian as desktop_guardian
class MarkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.marker = str(Path(self.temp.name) / "desktop-hidden.json")

    def test_round_trip_and_token_specific_clear(self):
        desktop_guardian.write_marker(self.marker, "session-a", pid=42)
        marker = desktop_guardian.read_marker(self.marker)
        self.assertEqual(marker["token"], "session-a")
        self.assertEqual(marker["pid"], 42)
        self.assertFalse(desktop_guardian.clear_marker(self.marker, "session-b"))
        self.assertTrue(Path(self.marker).exists())
        self.assertTrue(desktop_guardian.clear_marker(self.marker, "session-a"))
        self.assertIsNone(desktop_guardian.read_marker(self.marker))

    def test_invalid_marker_is_reported_and_can_be_replaced(self):
        Path(self.marker).write_text(json.dumps({"token": 1}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "标记格式无效"):
            desktop_guardian.read_marker(self.marker)
        desktop_guardian.write_marker(self.marker, "session-a", pid=42)
        self.assertEqual(desktop_guardian.read_marker(self.marker)["token"], "session-a")


class HiddenStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.marker = str(Path(self.temp.name) / "desktop-hidden.json")

    def test_hide_writes_marker_before_hiding(self):
        events = []

        def visible(value):
            events.append(("visible", value))
            self.assertTrue(Path(self.marker).exists())

        with patch.object(desktop_guardian, "set_icons_visible", side_effect=visible):
            desktop_guardian.hide_desktop(self.marker, "session-a")
        self.assertEqual(events, [("visible", False)])
        self.assertEqual(desktop_guardian.read_marker(self.marker)["token"], "session-a")

    def test_failed_hide_keeps_marker_when_visibility_is_uncertain(self):
        with patch.object(desktop_guardian, "set_icons_visible",
                          side_effect=OSError("failed")), \
                patch.object(desktop_guardian, "icons_visible",
                             side_effect=OSError("unknown")):
            with self.assertRaises(OSError):
                desktop_guardian.hide_desktop(self.marker, "session-a")
        self.assertTrue(Path(self.marker).exists())

    def test_show_refuses_to_touch_another_sessions_state(self):
        desktop_guardian.write_marker(self.marker, "session-b", pid=2)
        with patch.object(desktop_guardian, "set_icons_visible") as visible:
            self.assertFalse(desktop_guardian.show_desktop(self.marker, "session-a"))
        visible.assert_not_called()
        self.assertEqual(desktop_guardian.read_marker(self.marker)["token"], "session-b")

    def test_show_clears_matching_marker(self):
        desktop_guardian.write_marker(self.marker, "session-a", pid=1)
        with patch.object(desktop_guardian, "set_icons_visible") as visible:
            self.assertTrue(desktop_guardian.show_desktop(self.marker, "session-a"))
        visible.assert_called_once_with(True)
        self.assertIsNone(desktop_guardian.read_marker(self.marker))

    def test_show_surfaces_windows_restore_errors(self):
        with patch.object(desktop_guardian, "set_icons_visible",
                          side_effect=OSError("Explorer unavailable")):
            with self.assertRaisesRegex(OSError, "Explorer unavailable"):
                desktop_guardian.show_desktop(self.marker)

    def test_stale_recovery_restores_and_clears_before_startup(self):
        desktop_guardian.write_marker(self.marker, "session-a", pid=1)
        with patch.object(desktop_guardian, "restore_stock_view") as restore:
            recovered, detail = desktop_guardian.recover_stale_desktop(self.marker)
        self.assertTrue(recovered)
        self.assertEqual(detail, "")
        restore.assert_called_once_with()
        self.assertIsNone(desktop_guardian.read_marker(self.marker))

    def test_failed_stale_recovery_keeps_marker_for_next_try(self):
        desktop_guardian.write_marker(self.marker, "session-a", pid=1)
        with patch.object(desktop_guardian, "restore_stock_view",
                          side_effect=OSError("Explorer busy")):
            recovered, detail = desktop_guardian.recover_stale_desktop(self.marker)
        self.assertFalse(recovered)
        self.assertIn("Explorer busy", detail)
        self.assertIsNotNone(desktop_guardian.read_marker(self.marker))

    def test_death_restore_ignores_newer_session_and_retries_transient_failure(self):
        desktop_guardian.write_marker(self.marker, "session-a", pid=1)
        with patch.object(desktop_guardian, "restore_stock_view") as restore:
            self.assertFalse(desktop_guardian._restore_after_death(
                self.marker, "session-b", attempts=1, delay=0))
        restore.assert_not_called()

        with patch.object(desktop_guardian, "restore_stock_view",
                          side_effect=[OSError("busy"), None]) as restore, \
                patch.object(desktop_guardian.time, "sleep"):
            self.assertTrue(desktop_guardian._restore_after_death(
                self.marker, "session-a", attempts=2, delay=0))
        self.assertEqual(restore.call_count, 2)
        self.assertIsNone(desktop_guardian.read_marker(self.marker))

    def test_exhausted_death_restore_records_the_underlying_error(self):
        desktop_guardian.write_marker(self.marker, "session-a", pid=1)
        with patch.object(desktop_guardian, "restore_stock_view",
                          side_effect=OSError("Explorer busy")), \
                patch.object(desktop_guardian, "_guardian_log") as log, \
                patch.object(desktop_guardian.time, "sleep"):
            self.assertFalse(desktop_guardian._restore_after_death(
                self.marker, "session-a", attempts=2, delay=0))
        self.assertEqual(log.call_count, 3)
        self.assertIn("Explorer busy", log.call_args_list[0].args[1])
        self.assertIn("标记保留", log.call_args_list[-1].args[1])


class GuardianCommandTests(unittest.TestCase):
    def test_source_command_includes_script_before_guard_flags(self):
        arguments = desktop_guardian.guardian_arguments(
            r"C:\app\shortcut.py", 123, r"C:\data\marker.json", "token",
            "stop-event", "ready-event", executable=r"C:\Python\python.exe",
            frozen=False)
        self.assertEqual(arguments[:2], [r"C:\Python\python.exe", r"C:\app\shortcut.py"])
        self.assertEqual(arguments[2:4], ["--desktop-guardian", "123"])
        self.assertEqual(arguments[-2:], ["stop-event", "ready-event"])

    def test_frozen_command_does_not_append_python_script(self):
        arguments = desktop_guardian.guardian_arguments(
            r"C:\app\shortcut.exe", 123, r"C:\data\marker.json", "token",
            "", "", executable=r"C:\app\shortcut.exe", frozen=True)
        self.assertEqual(arguments[:2], [r"C:\app\shortcut.exe",
                                         "--desktop-guardian"])
        self.assertEqual(len(arguments), 7)


if __name__ == "__main__":
    unittest.main()
