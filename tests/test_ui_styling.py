import unittest
from pathlib import Path
from PySide6.QtCore import Qt, QPoint, QSize
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QDialog, QListWidgetItem

from shortcut.catalog import DesktopCatalog
from shortcut.dock_window import CategoryButton, ShortcutDock
from shortcut.models import AppSettings, Category, ShortcutEntry
from shortcut.panels import EntryPanel, SearchPopup
from shortcut.settings_dialog import SettingsDialog
from shortcut.theme import DARK_TOKENS, LIGHT_TOKENS, get_dock_qss, get_menu_qss, get_panel_qss, get_search_popup_qss, get_settings_qss
from shortcut.windows_desktop import DesktopIconController


class DummyCatalog:
    def __init__(self, entries_map=None):
        self.entries_map = entries_map or {}
        self.settings = None

    def entries_for(self, category):
        return self.entries_map.get(category.id, [
            ShortcutEntry(Path("C:/Windows/System32/notepad.exe")),
            ShortcutEntry(Path("C:/Windows/explorer.exe")),
        ])

    def refresh(self):
        pass

    def search(self, query):
        if query == "test":
            return [ShortcutEntry(Path("C:/Windows/System32/cmd.exe"))]
        return []


class UIStylingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_theme_tokens_and_generators(self):
        for theme in ("dark", "light"):
            dock_qss = get_dock_qss(theme)
            self.assertIn("#dock", dock_qss)
            self.assertIn("rgba", dock_qss)

            panel_qss = get_panel_qss(theme)
            self.assertIn("#entry_panel", panel_qss)
            self.assertIn("#empty_hint", panel_qss)

            search_qss = get_search_popup_qss(theme)
            self.assertIn("#search_popup", search_qss)
            self.assertIn("#search_empty_hint", search_qss)

            settings_qss = get_settings_qss(theme)
            self.assertIn("#settings_dialog", settings_qss)
            self.assertIn("#primary_button", settings_qss)

            menu_qss = get_menu_qss(theme)
            self.assertIn("QMenu", menu_qss)

    def test_dock_horizontal_and_vertical_four_edges(self):
        settings = AppSettings.defaults()
        # Add long category title to test readability
        settings.categories.append(Category("industrial", "工业自动化与设备调试", "industrial"))
        catalog = DummyCatalog()

        for edge in ("bottom", "top", "left", "right"):
            settings.dock_edge = edge
            dock = ShortcutDock(settings, catalog, DesktopIconController())
            is_vertical = edge in ("left", "right")

            # Check that button styles match edge
            for cat in settings.categories:
                btn = dock.category_buttons.get(cat.id)
                self.assertIsNotNone(btn)
                if is_vertical:
                    self.assertEqual(btn.toolButtonStyle(), Qt.ToolButtonTextBesideIcon)
                else:
                    self.assertEqual(btn.toolButtonStyle(), Qt.ToolButtonTextUnderIcon)
                self.assertEqual(btn.text(), cat.title)
                self.assertIn(cat.title, btn.toolTip())

            dock.close()
            dock.search_popup.close()

    def test_dock_dark_and_light_themes(self):
        catalog = DummyCatalog()
        for theme in ("dark", "light"):
            settings = AppSettings.defaults()
            settings.theme = theme
            dock = ShortcutDock(settings, catalog, DesktopIconController())
            expected_bg = DARK_TOKENS.dock_bg if theme == "dark" else LIGHT_TOKENS.dock_bg
            self.assertIn(expected_bg, dock.styleSheet())
            dock.close()
            dock.search_popup.close()

    def test_category_button_paint_and_drag_properties(self):
        cat = Category("app", "测试长分类名称应用", "apps")
        btn = CategoryButton(cat, lambda *args: None, None, is_vertical=False, count=12)
        btn.resize(80, 80)
        pixmap = btn.grab()
        self.assertFalse(pixmap.isNull())
        self.assertGreater(pixmap.width(), 0)

        # Test drag property toggle
        btn.setProperty("drag_active", True)
        self.assertTrue(btn.property("drag_active"))
        btn.setProperty("drag_active", False)
        self.assertFalse(btn.property("drag_active"))

    def test_entry_panel_empty_and_populated_states(self):
        cat = Category("doc", "办公文档", "documents")
        settings = AppSettings.defaults()

        # Populated panel
        panel = EntryPanel(
            cat,
            [ShortcutEntry(Path("C:/test.txt"))],
            settings.categories,
            settings,
            lambda *args: None,
            lambda *args: None,
            lambda *args: None,
            lambda *args: None,
            lambda *args: None,
            lambda *args: None,
            lambda *args: None,
        )
        self.assertTrue(panel.empty_hint.isHidden())
        self.assertFalse(panel.items.isHidden())
        self.assertEqual(panel.count_label.text(), "1")

        # Empty panel
        panel.set_entries([])
        self.assertFalse(panel.empty_hint.isHidden())
        self.assertTrue(panel.items.isHidden())
        self.assertEqual(panel.count_label.text(), "0")

        # View modes
        panel.set_view_mode("icons")
        self.assertEqual(panel.items.iconSize(), QSize(64, 64))
        panel.set_view_mode("list")
        self.assertEqual(panel.items.iconSize(), QSize(24, 24))
        panel.close()

    def test_search_popup_matches_and_empty_state(self):
        popup = SearchPopup()
        for theme in ("dark", "light"):
            popup.apply_theme(theme)
            self.assertIn("search_popup", popup.styleSheet())

        # With entries
        entries = [ShortcutEntry(Path("C:/Windows/notepad.exe"))]
        popup.set_entries(entries)
        self.assertFalse(popup.items.isHidden())
        self.assertTrue(popup.empty_hint.isHidden())
        self.assertEqual(popup.items.count(), 1)
        item_text = popup.items.item(0).text()
        self.assertIn("notepad", item_text)
        self.assertIn("Windows", item_text)

        # Empty entries
        popup.set_entries([])
        self.assertTrue(popup.items.isHidden())
        self.assertFalse(popup.empty_hint.isHidden())
        popup.close()

    def test_settings_dialog_structure_and_theme_toggle(self):
        settings = AppSettings.defaults()
        dialog = SettingsDialog(settings)
        self.assertEqual(dialog.objectName(), "settings_dialog")

        # Check group boxes exist
        group_boxes = dialog.findChildren(SettingsDialog.__init__.__annotations__.get("QGroupBox", object))
        # Check that card grouping widgets exist
        self.assertIsNotNone(dialog.findChild(object, "brand_header"))
        self.assertIsNotNone(dialog.findChild(object, "primary_button"))

        # Verify theme switching dynamically updates stylesheet
        dialog.theme_combo.setCurrentIndex(dialog.theme_combo.findData("light"))
        self.assertIn("rgba(242, 245, 252", dialog.styleSheet())

        dialog.theme_combo.setCurrentIndex(dialog.theme_combo.findData("dark"))
        self.assertIn("rgba(32, 38, 54", dialog.styleSheet())
        dialog.close()

    def test_dock_paints_glass_background(self):
        settings = AppSettings.defaults()
        catalog = DummyCatalog()
        dock = ShortcutDock(settings, catalog, DesktopIconController())
        dock.show()
        self.app.processEvents()
        img = dock.grab().toImage()
        # Ensure that within the dock container, the glass background is actually drawn (non-zero alpha)
        center_color = img.pixelColor(dock.width() // 2, dock.height() // 2)
        self.assertGreater(center_color.alpha(), 100)
        dock.close()
        dock.search_popup.close()

    def test_dock_position_and_size_stable_on_refresh(self):
        settings = AppSettings.defaults()
        catalog = DummyCatalog()
        dock = ShortcutDock(settings, catalog, DesktopIconController())
        dock.show()
        self.app.processEvents()
        initial_pos = dock.pos()
        initial_size = dock.size()

        # Simulate clicking the refresh button
        dock.refresh_catalog()
        self.app.processEvents()
        self.assertEqual(dock.pos(), initial_pos)
        self.assertEqual(dock.size(), initial_size)

        # Re-trigger refresh to ensure multiple refreshes remain stable
        dock.refresh_catalog()
        self.app.processEvents()
        self.assertEqual(dock.pos(), initial_pos)
        self.assertEqual(dock.size(), initial_size)
        dock.close()
        dock.search_popup.close()

    def test_category_button_set_count(self):
        cat = Category("app", "应用", "apps")
        btn = CategoryButton(cat, lambda *args: None, None, is_vertical=False, count=5)
        self.assertEqual(btn.count, 5)
        self.assertIn("5 项", btn.toolTip())
        btn.set_count(12)
        self.assertEqual(btn.count, 12)
        self.assertIn("12 项", btn.toolTip())

    def test_dock_position_stable_with_category_mutations(self):
        settings = AppSettings.defaults()
        catalog = DummyCatalog()
        dock = ShortcutDock(settings, catalog, DesktopIconController())
        dock.show()
        self.app.processEvents()

        # Add a new category to trigger rebuild branch
        new_cat = Category.create("新自定义分类", "other")
        settings.categories.append(new_cat)
        dock.refresh_catalog()
        self.app.processEvents()
        pos_after_add = dock.pos()
        size_after_add = dock.size()

        # Subsequent refresh calls must be completely stable
        for _ in range(3):
            dock.refresh_catalog()
            self.app.processEvents()
            self.assertEqual(dock.pos(), pos_after_add)
            self.assertEqual(dock.size(), size_after_add)

        dock.close()
        dock.search_popup.close()

    def test_category_button_badge_anchoring(self):
        cat_short = Category("app", "应用", "apps")
        cat_long = Category("app_long", "超长名称分类测试项目列表", "apps")

        # Horizontal buttons
        btn_short = CategoryButton(cat_short, lambda *args: None, None, is_vertical=False, count=8)
        btn_short.setIconSize(QSize(48, 48))
        btn_short.resize(76, 84)

        btn_long = CategoryButton(cat_long, lambda *args: None, None, is_vertical=False, count=8)
        btn_long.setIconSize(QSize(48, 48))
        btn_long.resize(160, 84)

        # Grabbing and painting them should succeed without any error
        pix_short = btn_short.grab()
        pix_long = btn_long.grab()
        self.assertFalse(pix_short.isNull())
        self.assertFalse(pix_long.isNull())

        # Vertical button
        btn_vert = CategoryButton(cat_short, lambda *args: None, None, is_vertical=True, count=15)
        btn_vert.setIconSize(QSize(36, 36))
        btn_vert.resize(140, 48)
        pix_vert = btn_vert.grab()
        self.assertFalse(pix_vert.isNull())

    def test_catalog_entries_for_safety(self):
        settings = AppSettings.defaults()
        real_catalog = DesktopCatalog(settings)
        # Calling entries_for before refresh should safely return [] instead of KeyError
        unrefreshed_cat = settings.categories[0]
        self.assertEqual(real_catalog.entries_for(unrefreshed_cat), [])

        # Calling entries_for for an unregistered category should also return []
        random_cat = Category.create("未收录分类", "other")
        self.assertEqual(real_catalog.entries_for(random_cat), [])

    def test_dock_sizing_upgraded(self):
        settings = AppSettings.defaults()
        catalog = DummyCatalog()
        dock = ShortcutDock(settings, catalog, DesktopIconController())

        # Horizontal mode check
        first_btn = list(dock.category_buttons.values())[0]
        self.assertEqual(first_btn.iconSize(), QSize(48, 48))
        self.assertGreaterEqual(first_btn.minimumHeight(), 80)
        self.assertGreaterEqual(dock.search_box.minimumHeight(), 26)
        self.assertGreaterEqual(dock.refresh_button.minimumHeight(), 26)

        dock.close()
        dock.search_popup.close()


if __name__ == "__main__":
    unittest.main()
