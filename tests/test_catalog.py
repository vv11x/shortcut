import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shortcut.catalog import DesktopCatalog
from shortcut.models import AppSettings, path_key


class DesktopCatalogTests(unittest.TestCase):
    def test_manual_assignment_overrides_rules_and_dismissed_paths_are_hidden(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            desktop = root / "user-desktop"
            public_desktop = root / "public" / "Desktop"
            desktop.mkdir()
            public_desktop.mkdir(parents=True)
            report = desktop / "report.pdf"
            report.touch()
            hidden = public_desktop / "hidden.txt"
            hidden.touch()
            fixed = root / "fixed-folder"
            fixed.mkdir()

            settings = AppSettings.defaults()
            settings.manual_assignments[path_key(report)] = "applications"
            settings.dismissed_paths.append(str(hidden))
            settings.fixed_paths.append(str(fixed))
            catalog = DesktopCatalog(settings)

            with patch("shortcut.catalog.QStandardPaths.writableLocation", return_value=str(desktop)):
                with patch.dict(os.environ, {"PUBLIC": str(root / "public")}):
                    catalog.refresh()

            self.assertIn(report, [entry.path for entry in catalog.entries_for(
                next(category for category in settings.categories if category.id == "applications")
            )])
            self.assertNotIn(hidden, [entry.path for entries in catalog.groups.values() for entry in entries])
            self.assertNotIn(hidden, [entry.path for entry in catalog.search("hidden")])
            self.assertIn(fixed, [entry.path for entry in catalog.entries])


if __name__ == "__main__":
    unittest.main()
