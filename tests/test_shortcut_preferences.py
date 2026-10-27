"""Preference regressions using temporary config and an offscreen Shortcut."""

import ast
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class TransparencyTests(unittest.TestCase):
    def test_config_replace_failure_keeps_old_file_and_exposes_original_error(self):
        tree = ast.parse((ROOT / "shortcut_app/application.py").read_text(encoding="utf-8-sig"))
        writer = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "save_config")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"saved": true}', encoding="utf-8")
            namespace = {"os": os, "json": json, "CONFIG_DIR": directory, "CONFIG_PATH": str(path)}
            exec(compile(ast.Module(body=[writer], type_ignores=[]), "application.py", "exec"), namespace)
            with patch.object(os, "replace", side_effect=PermissionError("replace denied")):
                with self.assertRaisesRegex(PermissionError, "replace denied"):
                    namespace["save_config"]({"saved": False})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"saved": True})

    def test_transparency_round_trip_and_invalid_values(self):
        # Read the real loader without installing shortcut's global desktop hooks.
        tree = ast.parse((ROOT / "shortcut_app/application.py").read_text(encoding="utf-8-sig"))
        loader = next(node for node in tree.body
                      if isinstance(node, ast.FunctionDef) and node.name == "load_config")
        namespace = {
            "copy": copy, "json": json, "os": os,
            "__package__": "shortcut_app", "__name__": "shortcut_app.application",
            "default_state": lambda: {},
            "DEFAULT_CONFIG": {"items": [], "organizer": {}, "transparency": 40},
        }
        exec(compile(ast.Module(body=[loader], type_ignores=[]), "shortcut.py", "exec"), namespace)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            namespace["CONFIG_PATH"] = str(path)
            for saved, expected in ((0, 0), (100, 100), ("0", 0), (-1, 0),
                                    (101, 100), (None, 40), ("invalid", 40)):
                with self.subTest(saved=saved):
                    path.write_text(json.dumps({"transparency": saved}), encoding="utf-8")
                    self.assertEqual(namespace["load_config"]()["transparency"], expected)
            path.write_text("{}", encoding="utf-8")
            self.assertEqual(namespace["load_config"]()["transparency"], 40)


@unittest.skipUnless(os.name == "nt", "Shortcut requires Windows")
class SearchVisibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import atexit
        import sys

        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        hook = sys.excepthook
        import shortcut_app.application as shortcut
        atexit.unregister(shortcut._restore_desktop_icons_safe)
        sys.excepthook = hook
        cls.module = shortcut
        cls.app = shortcut.QApplication.instance() or shortcut.QApplication([])

    def setUp(self):
        self.patches = [
            patch.object(self.module, "save_config"),
            patch.object(self.module, "log"),
            patch.object(self.module, "trim_process_memory"),
            patch.object(self.module.Shortcut, "apply_layer"),
            patch.object(self.module.Shortcut, "refresh_backdrop"),
            patch.object(self.module.Shortcut, "start_backdrop"),
        ]
        for active_patch in self.patches:
            active_patch.start()
            self.addCleanup(active_patch.stop)
        cfg = copy.deepcopy(self.module.DEFAULT_CONFIG)
        cfg.update(show_search=False, theme="light", running_dots=False)
        cfg["organizer"]["automatic"] = False
        self.shortcut = self.module.Shortcut(cfg, preview=True)
        self.addCleanup(self.dispose_shortcut)

    def dispose_shortcut(self):
        self.shortcut.hide()
        if self.shortcut.organizer:
            self.shortcut.organizer.stop()
        if self.shortcut.search_bar:
            self.shortcut.search_bar.shutdown()
        if self.shortcut.category_panel:
            self.shortcut.category_panel.model.shutdown()
            self.shortcut.category_panel.deleteLater()
        if self.shortcut.desktop_folders:
            self.shortcut.desktop_folders.shutdown()
            self.shortcut.desktop_folders.deleteLater()
        self.shortcut.deleteLater()
        self.app.processEvents()

    def setup_organizer(self):
        self.shortcut.setup_organizer(directories=[])
        self.app.processEvents()

    def test_disabled_search_stays_hidden_on_show_and_reshow(self):
        self.setup_organizer()
        for _ in range(2):
            self.shortcut.show()
            self.app.processEvents()
            self.assertFalse(self.shortcut.search_bar.isVisible())
            self.shortcut.hide()

    def test_organizer_setup_on_visible_shortcut_respects_disabled_search(self):
        self.shortcut.show()
        self.setup_organizer()
        self.assertFalse(self.shortcut.search_bar.isVisible())

    def test_search_stays_next_to_visible_bar_on_all_edges_and_does_not_move_bar_when_opened(self):
        self.setup_organizer()
        self.shortcut.cfg['show_search'] = True
        for position in ('left', 'right', 'top', 'bottom'):
            for names in (True, False):
                with self.subTest(position=position, names=names):
                    self.shortcut.cfg['show_name'] = names
                    self.shortcut.set_position(position)
                    self.shortcut.show()
                    self.shortcut.sync_search_geometry()
                    bar = self.shortcut.window_rect(self.shortcut.bar_rect_f()).toAlignedRect()
                    bar.translate(self.shortcut.pos())
                    anchor = self.shortcut.search_bar._anchor
                    gap = round(8 * self.shortcut.ui_mult)
                    if position in ('left', 'right'):
                        self.assertLessEqual(abs(anchor.center().x() - bar.center().x()), 1)
                        self.assertEqual(bar.top() - anchor.bottom() - 1, gap)
                    else:
                        self.assertLessEqual(abs(anchor.center().y() - bar.center().y()), 1)
                        self.assertEqual(anchor.left() - bar.right() - 1, gap)
                    before = self.shortcut.geometry()
                    self.shortcut.search_bar.expand()
                    self.shortcut.search_bar._motion.setCurrentTime(self.shortcut.search_bar._motion.duration())
                    self.assertEqual(self.shortcut.geometry(), before)
                    self.shortcut.search_bar.collapse(animate=False)

    def test_search_follows_native_window_move_without_waiting_for_position_timer(self):
        from PyQt5.QtCore import QPoint
        self.setup_organizer()
        self.shortcut.cfg['show_search'] = True
        self.shortcut.show()
        self.shortcut.sync_search_geometry()
        before = self.shortcut.search_bar._anchor
        self.shortcut.move(self.shortcut.pos() + QPoint(-13, 7))
        self.assertEqual(self.shortcut.search_bar._anchor, before.translated(-13, 7))

    def test_toggle_search_and_keep_it_hidden_with_shortcut(self):
        self.setup_organizer()
        self.shortcut.show()
        self.shortcut.cfg["show_search"] = True
        self.shortcut.sync_search_geometry()
        self.assertTrue(self.shortcut.search_bar.isVisible())
        self.assertFalse(self.shortcut.search_bar._anchor.isEmpty())
        self.shortcut.cfg["show_search"] = False
        self.shortcut.sync_search_geometry()
        self.assertFalse(self.shortcut.search_bar.isVisible())
        self.shortcut.hide()
        self.shortcut.cfg["show_search"] = True
        self.shortcut.sync_search_geometry()
        self.assertFalse(self.shortcut.search_bar.isVisible())
        self.shortcut.show()
        self.assertTrue(self.shortcut.search_bar.isVisible())


if __name__ == "__main__":
    unittest.main()
