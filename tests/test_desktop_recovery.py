"""Exercise the real recovery function without changing the Windows desktop."""

from contextlib import contextmanager
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import shortcut_app.desktop_visibility as desktop_visibility
class DesktopRecoveryTests(unittest.TestCase):
    def test_recovery_unhides_and_refreshes_before_showing_the_view(self):
        events = []

        @contextmanager
        def desktop():
            yield "view"

        @contextmanager
        def interface(view, iid):
            self.assertEqual(view, "view")
            self.assertEqual(iid, "000214E3-0000-0000-C000-000000000046")
            yield "shell"

        def method(view, slot):
            self.assertEqual((view, slot), ("shell", 8))
            return lambda value: events.append("refresh") or 0

        show = Mock(side_effect=lambda hwnd, mode: events.append("show"))
        user = SimpleNamespace(ShowWindow=show)
        with patch.multiple(desktop_visibility,
                            set_icons_visible=lambda visible: events.append(("visible", visible)),
                            _desktop_view=desktop, shell_interface=interface, _method=method,
                            desktop_snapshot=lambda: {"icons": 42}), \
                patch.object(desktop_visibility.ctypes, "WinDLL", return_value=user):
            desktop_visibility.restore_stock_view()
        self.assertEqual(events, [("visible", True), "refresh", "show"])
        show.assert_called_once_with(42, 5)

    def test_failed_refresh_is_reported(self):
        @contextmanager
        def pointer(*args):
            yield 1

        with patch.multiple(desktop_visibility, set_icons_visible=Mock(),
                            _desktop_view=pointer, shell_interface=pointer,
                            _method=lambda *args: lambda view: -2147467259):
            with self.assertRaises(OSError):
                desktop_visibility.restore_stock_view()


if __name__ == "__main__":
    unittest.main()
