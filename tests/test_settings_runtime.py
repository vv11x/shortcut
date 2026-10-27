"""Settings affect real Shortcut geometry and painting; OS side effects are mocked."""

import atexit
import copy
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@unittest.skipUnless(os.name == "nt", "Shortcut requires Windows")
class ShortcutSettingsRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        hook = sys.excepthook
        import shortcut_app.application as shortcut
        atexit.unregister(shortcut._restore_desktop_icons_safe)
        sys.excepthook = hook
        cls.module = shortcut
        cls.app = shortcut.QApplication.instance() or shortcut.QApplication([])

    def setUp(self):
        for name in ("save_config", "log", "trim_process_memory"):
            replacement = patch.object(self.module, name)
            replacement.start()
            self.addCleanup(replacement.stop)
        cfg = copy.deepcopy(self.module.DEFAULT_CONFIG)
        cfg.update(theme="light", running_dots=False, desktop_folder_mode=False)
        self.shortcut = self.module.Shortcut(cfg, preview=True)
        self.addCleanup(self.dispose_shortcut)

    def dispose_shortcut(self):
        for timer in (self.shortcut.timer, self.shortcut.geo_timer, self.shortcut.proc_timer, self.shortcut.blur_timer):
            timer.stop()
        self.shortcut.hide()
        self.shortcut.deleteLater()

    def enlarge_first_icon(self):
        self.shortcut.mouse_x = self.shortcut.rects[0][0]
        self.shortcut._recalc()
        self.shortcut.cur = list(self.shortcut.tgt)
        self.shortcut._layout()

    def test_fixed_bar_keeps_centers_and_glass_width_while_dynamic_mode_expands(self):
        self.shortcut.cfg["fixed_shortcut_bar"] = True
        self.shortcut._recalc(uniform=True)
        initial_centers = [rect[0] for rect in self.shortcut.rects]
        initial_width = self.shortcut.bar_rect_f().width()
        self.enlarge_first_icon()
        self.assertGreater(self.shortcut.rects[0][1], self.shortcut.icon_size)
        self.assertEqual([rect[0] for rect in self.shortcut.rects], initial_centers)
        self.assertEqual(self.shortcut.bar_rect_f().width(), initial_width)
        self.shortcut.cfg["fixed_shortcut_bar"] = False
        self.shortcut._layout()
        self.assertGreater(self.shortcut.bar_rect_f().width(), initial_width)
        self.assertNotEqual([rect[0] for rect in self.shortcut.rects], initial_centers)

    def test_magnification_can_be_disabled_and_levels_change_actual_widths(self):
        self.shortcut.cfg["magnify"] = False
        self.enlarge_first_icon()
        self.assertEqual(self.shortcut.rects[0][1], self.shortcut.icon_size)
        self.shortcut.cfg["magnify"] = True
        widths = []
        for level in ("low", "mid", "high"):
            self.shortcut.cfg["bump_level"] = level
            self.shortcut._recalc(uniform=True)
            self.enlarge_first_icon()
            widths.append(self.shortcut.rects[0][1])
        self.assertGreater(widths[0], self.shortcut.icon_size)
        self.assertLess(widths[0], widths[1])
        self.assertLess(widths[1], widths[2])

    def test_name_setting_changes_label_space(self):
        self.shortcut.cfg.update(position="bottom", show_name=True)
        self.shortcut.layout_position()
        with_names = self.shortcut.total_size().height()
        self.shortcut.cfg["show_name"] = False
        self.shortcut.layout_position()
        self.assertLess(self.shortcut.total_size().height(), with_names)

    def test_margin_and_custom_height_change_real_bar_position(self):
        for position in ("bottom", "top", "left", "right"):
            with self.subTest(position=position):
                self.shortcut.cfg.update(position=position, bottom_margin=6)
                start, _ = self.shortcut.layout_position()
                self.shortcut.cfg["bottom_margin"] = 26
                changed, _ = self.shortcut.layout_position()
                self.assertEqual(changed - start, 20 if position in ("top", "left") else -20)
        self.shortcut.cfg.update(position="custom", custom_bottom=100)
        start, _ = self.shortcut.layout_position()
        self.shortcut.cfg["custom_bottom"] = 140
        changed, _ = self.shortcut.layout_position()
        self.assertEqual(changed - start, -40)

    def test_bounce_switch_controls_new_animation_and_animation_changes_render(self):
        self.shortcut.cfg["launch_bounce"] = False
        self.shortcut.start_launch_bounce(0)
        self.assertEqual(self.shortcut.bounces[0], 0)
        self.shortcut.cfg["launch_bounce"] = True
        self.shortcut.start_launch_bounce(0)
        self.assertEqual(self.shortcut.bounces[0], 3)

        def snapshot(value):
            self.shortcut.bounces[0] = value
            pixmap = self.module.QPixmap(self.shortcut.size())
            pixmap.fill(self.module.Qt.transparent)
            self.shortcut.render(pixmap)
            return pixmap.toImage()

        self.assertNotEqual(snapshot(0), snapshot(2.5))

    def test_blur_refresh_modes_and_glass_switch_control_capture_timer(self):
        self.shortcut.preview = False
        self.shortcut._logged_once = True
        self.shortcut.backdrop_ok = True
        with patch.object(self.shortcut, "isVisible", return_value=True), \
                patch.object(self.shortcut, "refresh_backdrop") as refresh:
            for mode, interval in (("smart", 8000), ("off", 0), ("fast", 1000), ("normal", 3000), ("slow", 10000)):
                with self.subTest(mode=mode):
                    self.shortcut.cfg.update(glass=True, blur_mode=mode)
                    self.shortcut.start_backdrop()
                    self.assertEqual(self.shortcut.blur_timer.interval(), interval)
                    self.assertEqual(self.shortcut.blur_timer.isActive(), mode not in ("smart", "off"))
            refresh.reset_mock()
            self.shortcut.cfg["glass"] = False
            self.shortcut.start_backdrop()
            self.assertFalse(self.shortcut.blur_timer.isActive())
            self.assertIsNone(self.shortcut.backdrop)
            refresh.assert_not_called()

    def test_layer_setting_passes_correct_native_order_without_touching_desktop(self):
        self.shortcut.preview = False
        set_position = Mock()
        with patch.object(self.shortcut, "isVisible", return_value=True), \
                patch.object(self.module, "user32", SimpleNamespace(SetWindowPos=set_position)):
            for layer, expected in (("top", self.module.HWND_TOPMOST), ("bottom", self.module.HWND_BOTTOM)):
                self.shortcut.cfg["layer"] = layer
                self.shortcut.apply_layer()
                actual = set_position.call_args.args[1].value
                self.assertEqual(actual, self.module.wintypes.HWND(expected).value)

    def test_running_indicator_only_keeps_tracked_executables_and_obeys_toggle(self):
        self.shortcut.items[0]["exe"] = "example.exe"
        with patch.object(self.shortcut, "isVisible", return_value=True):
            self.shortcut.cfg["running_dots"] = True
            self.shortcut._apply_running({"example.exe", "unrelated.exe"})
            self.assertEqual(self.shortcut.running, {"example.exe"})
            self.shortcut.cfg["running_dots"] = False
            self.shortcut._apply_running({"example.exe"})
            self.assertEqual(self.shortcut.running, set())


class OrganizerSettingsRuntimeTests(unittest.TestCase):
    def setUp(self):
        from shortcut_app.organizer import default_state, normalize_path
        from shortcut_app.organizer_service import OrganizerService
        self.saved = Mock()
        self.service = OrganizerService(default_state(), self.saved, directories=[])
        self.addCleanup(self.service.stop)
        self.entries = [
            dict(path=normalize_path(name), name=os.path.basename(name), kind="documents", extension=".txt", target="")
            for name in ("alpha.txt", "beta.txt", "gamma.txt")
        ]
        self.service.entries = {entry["path"]: entry for entry in self.entries}

    def test_view_mode_is_saved_without_reindexing_or_changing_assignment(self):
        before = copy.deepcopy(self.service.groups())
        with patch.object(self.service, "_request_scan") as scan:
            self.service.set_view_mode("documents", "list")
        self.saved.assert_called_once_with()
        self.assertEqual(self.service.state["view_modes"]["documents"], "list")
        self.assertEqual(self.service.groups(), before)
        scan.assert_not_called()

    def test_item_order_updates_display_without_changing_file_identity(self):
        paths = [entry["path"] for entry in self.entries]
        self.service.reorder_paths("documents", [paths[-1]], before=paths[0])
        self.assertEqual([entry["path"] for entry in self.service.groups()["documents"]],
                         [paths[-1], paths[0], paths[1]])
        self.assertEqual(self.service.state["item_order"]["documents"], [paths[-1], paths[0], paths[1]])
        self.assertEqual(set(self.service.entries), set(paths))
        self.saved.assert_called_once_with()

    def test_category_priority_rules_and_separators_are_saved_together(self):
        categories = [
            dict(id="first", name="First", icon="documents", mode="all", rules=[
                dict(field="kind", value="documents"), dict(field="name", value="alpha")]),
            dict(id="fallback", name="Fallback", icon="other", mode="any", rules=[
                dict(field="extension", value="txt")]),
        ]
        self.service.update_categories(categories, ["first", "deleted-category"])
        self.assertEqual([entry["name"] for entry in self.service.groups()["first"]], ["alpha.txt"])
        self.assertEqual(len(self.service.groups()["fallback"]), 2)
        self.assertEqual(self.service.state["shortcut_separators"], ["first"])
        categories[0]["name"] = "unsaved caller change"
        self.assertEqual(self.service.state["categories"][0]["name"], "First")
        self.saved.assert_called_once_with()

    def test_automatic_toggle_controls_watches_without_disabling_explicit_rules(self):
        before = copy.deepcopy(self.service.groups())
        with patch.object(self.service, "_sync_watches") as watches, \
                patch.object(self.service, "_request_scan") as scan:
            self.service.set_automatic(False)
            self.assertFalse(self.service.state["automatic"])
            self.assertEqual(self.service.groups(), before)
            scan.assert_not_called()
            self.service.set_automatic(True)
            scan.assert_called_once_with(False)
            self.assertEqual(watches.call_count, 2)
        self.assertEqual(self.saved.call_count, 2)


if __name__ == "__main__":
    unittest.main()
