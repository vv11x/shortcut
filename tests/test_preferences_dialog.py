"""All preference controls use test doubles, without changing Windows settings."""

import ast
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import sip
from PyQt5.QtCore import QCoreApplication, QEvent, QObject, Qt, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QApplication, QLabel, QPushButton, QScrollArea

from shortcut_app.preferences_dialog import PreferencesDialog


class _Organizer(QObject):
    changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.state = {"automatic": True, "categories": [
            {"id": "first", "name": "First category", "icon": "apps"},
            {"id": "second", "name": "Second category", "icon": "documents"},
        ]}
        self.scans = 0

    def set_automatic(self, value):
        self.state["automatic"] = value
        self.changed.emit()

    def request_scan(self):
        self.scans += 1


class _Tray:
    def __init__(self, shortcut):
        self.shortcut = shortcut

    def _set(self, key, value):
        self.shortcut.cfg[key] = value
        self.shortcut.save_preferences()

    def set_transparency(self, value): self._set("transparency", value)
    def set_blur(self, value): self._set("blur_px", value)
    def set_theme(self, value): self._set("theme", value)
    def set_icon_size(self, value): self._set("icon_size", value)
    def set_layer(self, value): self._set("layer", value)

    def set_flag(self, key, value, **kwargs):
        self.shortcut.calls.append(("flag", key, value, kwargs))
        self._set(key, value)


class _Shortcut:
    def __init__(self):
        self.cfg = {"desktop_folder_mode": False, "glass": True, "transparency": 40,
                    "blur_px": 6, "theme": "auto", "position": "bottom", "magnify": True}
        self.calls = []
        self.saves = 0
        self.autostart_ok = self.mode_ok = self.desktop_ok = self.icon_ok = True
        self.tray = _Tray(self)
        self.organizer = _Organizer()
        self.category_panel = SimpleNamespace(set_single_click=lambda value: self.calls.append(("single", value)))

    def save_preferences(self): self.saves += 1
    def is_light(self): return self.cfg.get("theme") == "light"
    def refresh_geometry(self): self.calls.append(("geometry",))
    def start_backdrop(self): self.calls.append(("backdrop",))
    def set_position(self, value): self.cfg["position"] = value; self.save_preferences()
    def set_screen(self, index, name): self.calls.append(("screen", index, name)); self.save_preferences()
    def set_search_enabled(self, value): self.cfg["show_search"] = value; self.save_preferences()
    def set_folder_grid_size(self, value): self.cfg["folder_grid_size"] = value; self.save_preferences()
    def set_language(self, value): self.cfg["lang"] = value; self.save_preferences()
    def open_config_directory(self): self.calls.append(("config_directory",))
    def trim_memory(self): self.calls.append(("trim",)); return True
    def manage_categories(self): self.calls.append(("manage",))

    def set_desktop_folder_mode(self, value):
        if self.mode_ok:
            self.cfg["desktop_folder_mode"] = value
            self.save_preferences()
        return self.mode_ok

    def set_desktop_display(self, value):
        if self.desktop_ok:
            self.cfg["desktop_display"] = value
            self.save_preferences()
        return self.desktop_ok

    def set_autostart_enabled(self, value):
        if self.autostart_ok:
            self.cfg["autostart"] = value
            self.save_preferences()
        return self.autostart_ok

    def _category_artwork(self, category):
        artwork = QPixmap(36, 36)
        artwork.fill(Qt.blue)
        return artwork

    def set_category_custom_icon(self, cid, path):
        if not self.icon_ok:
            return False
        self.calls.append(("icon", cid, path))
        custom = self.cfg.setdefault("category_custom_icons", {})
        if path:
            custom[cid] = path
        else:
            custom.pop(cid, None)
        self.save_preferences()
        return True


class PreferencesDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.shortcut = _Shortcut()
        self.dialog = PreferencesDialog(self.shortcut)
        self.dialog.show()
        self.app.processEvents()

    def tearDown(self):
        self.dialog.close()
        self.dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def choose(self, key, value):
        control = self.dialog.controls[key]
        index = control.findData(value)
        self.assertGreaterEqual(index, 0, key)
        control.setCurrentIndex(index)

    def test_initialization_does_not_save_or_import_entry_point(self):
        self.assertEqual(self.shortcut.saves, 0)
        tree = ast.parse((Path(__file__).parents[1] / "shortcut_app/preferences_dialog.py").read_text(encoding="utf-8-sig"))
        self.assertFalse(any(isinstance(node, ast.ImportFrom) and node.module == "shortcut" for node in ast.walk(tree)))
        self.assertEqual(self.dialog.pages.count(), 6)
        self.assertEqual(self.dialog.controls["screen"].currentIndex(), 0)
        self.assertEqual(self.dialog.controls["screen"].currentData(), (-1, ""))
        for index in range(6):
            self.assertIsInstance(self.dialog.pages.widget(index), QScrollArea)

    def test_modes_are_mutually_exclusive_and_controls_match_mode(self):
        controls = self.dialog.controls
        self.assertTrue(controls["mode_shortcut"].isChecked())
        self.assertEqual(controls["folder_grid_size"].currentData(), "4x4")
        self.assertFalse(controls["folder_grid_size"].isEnabled())
        controls["mode_folders"].setChecked(True)
        self.assertTrue(self.shortcut.cfg["desktop_folder_mode"])
        self.assertFalse(controls["mode_shortcut"].isChecked())
        self.assertTrue(controls["folder_grid_size"].isEnabled())
        self.assertTrue(controls["screen"].isEnabled())
        for key in ("position", "icon_size", "layer", "launch_bounce", "magnify", "show_name",
                    "running_dots", "reorder", "show_search", "fixed_shortcut_bar", "sep_split", "blur_mode"):
            self.assertFalse(controls[key].isEnabled(), key)
            self.assertTrue(controls[key].toolTip(), key)
        for key in ("glass", "theme", "transparency", "blur_px", "single_click_launch", "desktop_display"):
            self.assertTrue(controls[key].isEnabled(), key)
        for grid in ("3x3", "2x2", "4x4"):
            self.choose("folder_grid_size", grid)
            self.assertEqual(self.shortcut.cfg["folder_grid_size"], grid)

    def test_failed_mode_switch_restores_selection(self):
        self.shortcut.mode_ok = False
        self.dialog.controls["mode_folders"].setChecked(True)
        self.assertFalse(self.shortcut.cfg["desktop_folder_mode"])
        self.assertTrue(self.dialog.controls["mode_shortcut"].isChecked())
        self.assertFalse(self.dialog.controls["mode_folders"].isChecked())

    def test_sliders_and_every_boolean_setting_persist(self):
        for key, value in (("transparency", 0), ("blur_px", 12), ("icon_size", 72)):
            self.dialog.controls[key].setValue(value)
            self.assertEqual(self.shortcut.cfg[key], value)
        for key in ("single_click_launch", "launch_bounce", "magnify", "show_name", "running_dots",
                    "reorder", "show_search", "fixed_shortcut_bar", "sep_split", "glass"):
            control = self.dialog.controls[key]
            target = not control.isChecked()
            control.setChecked(target)
            self.assertEqual(self.shortcut.cfg[key], target, key)
        self.assertIn(("single", False), self.shortcut.calls)
        self.assertFalse(self.dialog.controls["blur_px"].isEnabled())
        self.assertFalse(self.dialog.controls["bump_level"].isEnabled())
        self.assertIn(("flag", "show_name", False, {"geometry": True}), self.shortcut.calls)
        self.assertGreater(self.shortcut.saves, 10)

    def test_value_choices_screen_and_custom_position_update(self):
        for key, value in (("blur_mode", "fast"), ("bump_level", "high"), ("layer", "top"), ("lang", "en")):
            self.choose(key, value)
            self.assertEqual(self.shortcut.cfg[key], value)
        self.assertIn(("backdrop",), self.shortcut.calls)
        self.choose("position", "custom")
        self.assertTrue(self.dialog.controls["custom_bottom"].isEnabled())
        self.assertFalse(self.dialog.controls["bottom_margin"].isEnabled())
        self.dialog.controls["custom_bottom"].setValue(250)
        self.assertEqual(self.shortcut.cfg["custom_bottom"], 250)
        self.choose("position", "left")
        self.dialog.controls["bottom_margin"].setValue(12)
        self.assertEqual(self.shortcut.cfg["bottom_margin"], 12)
        self.assertTrue(self.dialog.controls["bottom_margin"].isEnabled())
        self.assertFalse(self.dialog.controls["custom_bottom"].isEnabled())
        if self.dialog.controls["screen"].count() > 1:
            value = self.dialog.controls["screen"].itemData(1)
            self.choose("screen", value)
            self.assertIn(("screen", *value), self.shortcut.calls)

    def test_theme_refresh_is_immediate_and_external_mode_refresh_works(self):
        old_style = self.dialog.styleSheet()
        self.choose("theme", "light")
        self.assertNotEqual(self.dialog.styleSheet(), old_style)
        self.shortcut.cfg["desktop_folder_mode"] = True
        self.dialog.refresh_mode()
        self.assertTrue(self.dialog.controls["mode_folders"].isChecked())
        self.assertFalse(self.dialog.controls["position"].isEnabled())

    def test_autostart_failure_does_not_persist_success(self):
        control = self.dialog.controls["autostart"]
        self.shortcut.autostart_ok = False
        control.setChecked(True)
        self.assertFalse(control.isChecked())
        self.assertFalse(self.shortcut.cfg.get("autostart", False))
        self.assertEqual(self.shortcut.saves, 0)
        self.shortcut.autostart_ok = True
        control.setChecked(True)
        self.assertTrue(self.shortcut.cfg["autostart"])

    def test_icon_picker_binds_name_and_releases_old_page(self):
        old_page = self.dialog.pages.widget(4)
        button = old_page.findChild(QPushButton, "pick_icon_first")
        with patch("shortcut_app.preferences_dialog.QFileDialog.getOpenFileName", return_value=("test-icon.png", "")) as picker:
            button.click()
            self.assertIn("First category", picker.call_args.args[1])
            self.assertNotIn("*.exe", picker.call_args.args[3])
        self.assertIn(("icon", "first", "test-icon.png"), self.shortcut.calls)
        self.assertEqual(self.dialog.pages.count(), 6)
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertTrue(sip.isdeleted(old_page))
        self.dialog.pages.widget(4).findChild(QPushButton, "reset_icon_first").click()
        self.assertNotIn("first", self.shortcut.cfg["category_custom_icons"])

    def test_invalid_icon_and_desktop_mode_keep_previous_values(self):
        self.shortcut.icon_ok = False
        self.dialog._set_icon("first", "bad.exe")
        self.assertNotIn("category_custom_icons", self.shortcut.cfg)
        self.assertIn("ICO", self.dialog.message.text())
        self.shortcut.desktop_ok = False
        self.choose("desktop_display", "hidden")
        self.assertEqual(self.dialog.controls["desktop_display"].currentData(), "managed")

    def test_management_system_actions_and_error_reporting(self):
        page = self.dialog.pages.widget(4)
        page.findChild(QPushButton, "scan_desktop").click()
        self.assertEqual(self.shortcut.organizer.scans, 1)
        page.findChild(QPushButton, "manage_categories").click()
        self.assertIn(("manage",), self.shortcut.calls)
        automatic = page.findChild(QObject, "automatic")
        automatic.setChecked(False)
        self.assertFalse(self.shortcut.organizer.state["automatic"])
        system = self.dialog.pages.widget(5)
        system.findChild(QPushButton, "trim_memory").click()
        self.assertIn(("trim",), self.shortcut.calls)
        self.assertIn("请求", self.dialog.message.text())
        system.findChild(QPushButton, "open_config_directory").click()
        self.assertIn(("config_directory",), self.shortcut.calls)
        with patch.object(self.shortcut, "open_config_directory", side_effect=OSError("test failure")):
            with self.assertRaisesRegex(OSError, "test failure"):
                self.dialog._invoke(self.shortcut.open_config_directory)
        self.assertIn("test failure", self.dialog.message.text())
        self.assertFalse(any("4.4" in label.text() for label in self.dialog.findChildren(QLabel)))

    def test_reopening_synchronizes_external_settings_without_saving(self):
        self.dialog.hide()
        self.shortcut.cfg.update(position="left", theme="light", glass=False,
                                 transparency=73, icon_size=80, magnify=False,
                                 desktop_display="all", desktop_folder_mode=True)
        saved = self.shortcut.saves
        self.dialog.show()
        self.app.processEvents()
        controls = self.dialog.controls
        self.assertEqual(controls["position"].currentData(), "left")
        self.assertEqual(controls["theme"].currentData(), "light")
        self.assertEqual(controls["desktop_display"].currentData(), "all")
        self.assertEqual(controls["icon_size"].value(), 80)
        self.assertFalse(controls["glass"].isChecked())
        self.assertFalse(controls["magnify"].isChecked())
        self.assertTrue(controls["mode_folders"].isChecked())
        self.assertIn("73", self.dialog._slider_labels["transparency"][0].text())
        self.assertEqual(self.shortcut.saves, saved)

    def test_category_refresh_keeps_scroll_and_management_is_before_icons(self):
        self.shortcut.organizer.state["categories"] = [
            {"id": str(index), "name": f"Category {index}", "icon": "apps"} for index in range(25)]
        self.shortcut.organizer.changed.emit()
        self.dialog.nav.setCurrentRow(4)
        self.app.processEvents()
        old = self.dialog.pages.widget(4)
        manage = old.findChild(QPushButton, "manage_categories")
        pick = old.findChild(QPushButton, "pick_icon_0")
        self.assertLess(manage.mapTo(old.widget(), manage.rect().topLeft()).y(),
                        pick.mapTo(old.widget(), pick.rect().topLeft()).y())
        old.verticalScrollBar().setValue(450)
        self.dialog._set_icon("15", "test-icon.png")
        self.app.processEvents()
        self.assertEqual(self.dialog.pages.widget(4).verticalScrollBar().value(), 450)
        self.assertEqual(self.dialog.pages.currentIndex(), 4)

    def test_autostart_exception_preserves_specific_error(self):
        with patch.object(self.shortcut, "set_autostart_enabled", side_effect=OSError("registry error 5")):
            with self.assertRaisesRegex(OSError, "registry error 5"):
                self.dialog._set_autostart(True)
        self.assertIn("registry error 5", self.dialog.message.text())
        self.assertFalse(self.dialog.controls["autostart"].isChecked())

    def test_long_pages_remain_scrollable_in_small_window(self):
        self.dialog.resize(580, 380)
        for index in (0, 1, 2, 3, 4, 5):
            self.dialog.nav.setCurrentRow(index)
            self.app.processEvents()
            scroll = self.dialog.pages.widget(index)
            self.assertIsNotNone(scroll.widget().layout())
        self.dialog.nav.setCurrentRow(1)
        self.app.processEvents()
        self.assertGreater(self.dialog.pages.widget(1).verticalScrollBar().maximum(), 0)


if __name__ == "__main__":
    unittest.main()
