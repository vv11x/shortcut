"""Regression checks that never change Explorer or start a native helper."""

import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]


def load_method(filename, class_name, method_name, namespace):
    # Importing shortcut registers global desktop-restoration hooks. Compile only
    # the real method under test so every Windows side effect stays isolated.
    source = ast.parse((ROOT / 'shortcut_app' / ('application.py' if filename == 'shortcut.py' else filename)).read_text(encoding="utf-8-sig"))
    owner = next(node for node in source.body
                 if isinstance(node, ast.ClassDef) and node.name == class_name)
    method = next(node for node in owner.body
                  if isinstance(node, ast.FunctionDef) and node.name == method_name)
    module = ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[]))
    exec(compile(module, filename, "exec"), namespace)
    return namespace[method_name]


class DesktopDisplayTests(unittest.TestCase):
    def setUp(self):
        self.visibility = Mock()
        self.save = Mock()
        self.apply_mode = load_method("shortcut.py", "Shortcut", "set_desktop_display", {
            "set_icons_visible": self.visibility,
            "save_config": self.save,
        })
        self.manager = SimpleNamespace(set_mode=Mock())
        self.owner = SimpleNamespace(
            cfg={}, desktop_manager=self.manager, desktop_folders=None, desktop_display_error=Mock(),
            organizer=SimpleNamespace(groups=Mock(return_value={"__uncategorized__": []})),
            _presentation_visible=True, _update_desktop_paths=Mock(),
        )
        sync = load_method("shortcut.py", "Shortcut", "_sync_desktop_collection", {})
        self.owner._sync_desktop_collection = lambda visible, mode=None: sync(self.owner, visible, mode)

    def test_empty_initial_index_still_starts_managed_mode(self):
        self.assertTrue(self.apply_mode(self.owner, "managed"))
        self.manager.set_mode.assert_called_once_with("managed")
        self.visibility.assert_not_called()
        self.assertEqual(self.owner.cfg["desktop_display"], "managed")

    def test_all_and_hidden_are_delegated_to_stop_native_collection(self):
        for mode in ("all", "hidden"):
            with self.subTest(mode=mode):
                self.assertTrue(self.apply_mode(self.owner, mode))
                self.manager.set_mode.assert_called_with(mode)
                self.assertEqual(self.owner.cfg["show_desktop_icons"], mode != "hidden")
        self.visibility.assert_not_called()

    def test_missing_manager_never_hides_without_a_guardian(self):
        self.owner.desktop_manager = None
        for mode in ("managed", "all"):
            with self.subTest(mode=mode):
                self.assertTrue(self.apply_mode(self.owner, mode))
                self.visibility.assert_called_with(mode != "hidden")
        self.visibility.reset_mock()
        before = dict(self.owner.cfg)
        self.assertFalse(self.apply_mode(self.owner, "hidden"))
        self.visibility.assert_not_called()
        self.assertEqual(self.owner.cfg, before)

    def test_failed_mode_change_does_not_persist_success(self):
        self.owner.cfg = {"desktop_display": "all", "show_desktop_icons": True}
        before = dict(self.owner.cfg)
        self.manager.set_mode.side_effect = OSError("mode switch failed")
        self.assertFalse(self.apply_mode(self.owner, "managed"))
        self.assertEqual(self.owner.cfg, before)
        self.save.assert_not_called()
        self.owner.desktop_display_error.assert_called_once_with("mode switch failed")

    def test_changing_preference_while_hidden_keeps_native_icons_visible(self):
        self.owner._presentation_visible = False
        self.assertTrue(self.apply_mode(self.owner, "hidden"))
        self.manager.set_mode.assert_called_once_with("all")
        self.assertEqual(self.owner.cfg['desktop_display'], 'hidden')

    def test_manager_stops_collection_before_restoring_all_or_hiding(self):
        for target in ("all", "hidden"):
            with self.subTest(mode=target):
                events = []
                begin = Mock(side_effect=lambda: events.append("begin_hidden"))
                manager = SimpleNamespace(
                    mode="managed", process=SimpleNamespace(state=lambda: 1),
                    guardian=None,
                    stop=lambda restore_hidden=True: events.append(("stop", restore_hidden)),
                    _begin_hidden=begin,
                )
                set_mode = load_method("desktop_manager.py", "DesktopManager", "set_mode", {
                    "QProcess": SimpleNamespace(NotRunning=0),
                    "set_icons_visible": lambda visible: events.append(("visible", visible)),
                })
                set_mode(manager, target)
                if target == "hidden":
                    self.assertEqual(events, [("stop", False), "begin_hidden"])
                    begin.assert_called_once_with()
                else:
                    self.assertEqual(events, [("stop", False), ("visible", True)])
                    begin.assert_not_called()
                self.assertEqual(manager.mode, target)


if __name__ == "__main__":
    unittest.main()
