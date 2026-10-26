import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QDialog

from shortcut.dock_window import ShortcutDock
from shortcut.models import AppSettings
from shortcut.windows_desktop import DesktopIconController


class EmptyCatalog:
    def __init__(self):
        self.settings = None

    def entries_for(self, category):
        return []

    def refresh(self):
        return None


class RejectedSettingsDialog:
    def __init__(self, settings, parent):
        self.settings = settings

    def exec_(self):
        return QDialog.DialogCode.Rejected


class AcceptedSettingsDialog:
    def __init__(self, settings):
        self.settings = settings

    def exec_(self):
        return QDialog.DialogCode.Accepted


class SettingsDialogFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_cancelled_dialog_returns_without_error(self):
        settings = AppSettings.defaults()
        catalog = EmptyCatalog()
        dock = ShortcutDock(settings, catalog, DesktopIconController())
        with patch("shortcut.dock_window.SettingsDialog", RejectedSettingsDialog):
            dock.open_settings()
        self.assertIs(dock.settings, settings)
        dock.close()
        dock.search_popup.close()

    def test_accepted_dialog_updates_settings_and_persists_them(self):
        settings = AppSettings.defaults()
        updated_settings = AppSettings.defaults()
        catalog = EmptyCatalog()
        dock = ShortcutDock(settings, catalog, DesktopIconController())
        dialog = AcceptedSettingsDialog(updated_settings)
        with patch("shortcut.dock_window.SettingsDialog", return_value=dialog):
            with patch("shortcut.dock_window.save_settings") as save_settings:
                dock.open_settings()

        self.assertIs(dock.settings, updated_settings)
        self.assertIs(catalog.settings, updated_settings)
        save_settings.assert_called_once_with(updated_settings)
        dock.close()
        dock.search_popup.close()


if __name__ == "__main__":
    unittest.main()
