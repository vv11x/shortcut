import unittest
from pathlib import Path

from shortcut.models import AppSettings, CategoryRule


class CategoryRuleTests(unittest.TestCase):
    def test_any_and_all_modes_match_case_insensitively(self):
        path = Path("Project.PDF")
        rule = CategoryRule(extensions=[".pdf"], name_terms=["project"], mode="all")
        self.assertTrue(rule.matches(path))
        self.assertFalse(CategoryRule(extensions=[".docx"], mode="any").matches(path))

    def test_unknown_rule_mode_is_reported(self):
        with self.assertRaisesRegex(ValueError, "Unsupported rule mode"):
            CategoryRule(mode="fallback").matches(Path("file.txt"))


class AppSettingsTests(unittest.TestCase):
    def test_default_settings_round_trip(self):
        settings = AppSettings.defaults()
        restored = AppSettings.from_dict(settings.to_dict())
        self.assertEqual(restored.to_dict(), settings.to_dict())
        self.assertEqual(restored.categories[-1].id, "other")

    def test_unknown_schema_is_reported(self):
        values = AppSettings.defaults().to_dict()
        values["schema_version"] = 99
        with self.assertRaisesRegex(ValueError, "Unsupported settings schema"):
            AppSettings.from_dict(values)


if __name__ == "__main__":
    unittest.main()
