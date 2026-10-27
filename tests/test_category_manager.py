"""Exercise category drafts and saving without indexing or changing the desktop."""

import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QCoreApplication, QEvent, Qt
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QApplication, QDialog

from shortcut_app.category_manager import CategoryManager, _RuleRow
from shortcut_app.organizer import default_state, normalize_path
from shortcut_app.organizer import classify, describe_path
from shortcut_app.organizer_service import OrganizerService


class CategoryManagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        path = Path(self.temp.name) / "custom.png"
        image = QPixmap(128, 128)
        image.fill(Qt.red)
        self.assertTrue(image.save(str(path)))
        self.state = default_state()
        self.cfg = {"organizer": self.state, "sep_split": False,
                    "category_custom_icons": {"apps": str(path), "removed": str(path)}}
        self.persist = Mock()
        self.service = OrganizerService(self.state, self.persist, directories=[])
        self.dialogs = []

    def tearDown(self):
        for dialog in self.dialogs:
            dialog.close()
            dialog.deleteLater()
        self.service.stop()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def manager(self):
        dialog = CategoryManager(self.service, shortcut_config=self.cfg)
        self.dialogs.append(dialog)
        return dialog

    def test_cancel_preserves_all_config_and_draft_icon(self):
        original = copy.deepcopy(self.cfg)
        dialog = self.manager()
        self.assertEqual(dialog.current_id, "apps")
        self.assertIn("custom.png", dialog.icon_hint.text())
        dialog.name.setText("Edited")
        dialog._select_icon("documents")
        dialog.split_background.setChecked(True)
        dialog.reject()
        self.assertEqual(self.cfg, original)
        self.persist.assert_not_called()

    def test_selecting_same_preset_replaces_custom_image_only_when_saved(self):
        dialog = self.manager()
        dialog._select_icon(dialog.icon.currentData())
        self.assertNotIn("apps", dialog.custom_icons)
        self.assertIn("apps", self.cfg["category_custom_icons"])
        dialog._save()
        self.assertNotIn("apps", self.cfg["category_custom_icons"])
        self.assertNotIn("removed", self.cfg["category_custom_icons"])
        self.persist.assert_called_once_with()
        self.assertEqual(dialog.result(), QDialog.Accepted)

    def test_empty_rule_survives_switching_and_prevents_saving(self):
        dialog = self.manager()
        dialog._append_rule({"field": "name", "value": ""})
        count = len(dialog.rule_rows)
        dialog.list.setCurrentRow(1)
        dialog.list.setCurrentRow(0)
        self.assertEqual(len(dialog.rule_rows), count)
        self.assertEqual(dialog.rule_rows[-1].value()["value"], "")
        dialog._save()
        self.persist.assert_not_called()
        self.assertIn("规则内容", dialog.status.text())
        dialog.rule_rows[-1].text.setText("Example")
        dialog._save()
        self.persist.assert_called_once_with()

    def test_empty_category_name_is_not_silently_replaced(self):
        dialog = self.manager()
        dialog.name.setText("  ")
        dialog._save()
        self.persist.assert_not_called()
        self.assertIn("分类名称", dialog.status.text())
        self.assertEqual(dialog.name.text().strip(), "")

    def test_saving_rules_and_restoring_exclusions_emits_once(self):
        excluded = normalize_path("excluded.txt")
        self.state["excluded"] = [excluded]
        self.service.changed.connect(changed := Mock())
        dialog = self.manager()
        dialog.restore_excluded.setChecked(True)
        dialog.name.setText("Applications")
        dialog._save()
        self.assertEqual(self.state["excluded"], [])
        self.assertEqual(self.state["categories"][0]["name"], "Applications")
        self.persist.assert_called_once_with()
        changed.assert_called_once_with()

    def test_switching_rule_fields_preserves_separate_drafts_and_valid_kind(self):
        row = _RuleRow({"field": "extension", "value": "pdf"})
        self.addCleanup(row.deleteLater)
        row.field.setCurrentIndex(row.field.findData("kind"))
        self.assertEqual(row.value(), {"field": "kind", "value": "documents"})
        row.field.setCurrentIndex(row.field.findData("name"))
        self.assertEqual(row.text.text(), "")
        row.text.setText("report")
        row.field.setCurrentIndex(row.field.findData("extension"))
        self.assertEqual(row.text.text(), "pdf")
        row.field.setCurrentIndex(row.field.findData("name"))
        self.assertEqual(row.text.text(), "report")

    def test_save_failure_is_exposed_and_does_not_accept_dialog(self):
        original = copy.deepcopy(self.cfg)
        dialog = self.manager()
        dialog.name.setText("Failed draft")
        dialog._select_icon("images")
        dialog.split_background.setChecked(True)
        self.persist.side_effect = OSError("disk full")
        with self.assertRaisesRegex(OSError, "disk full"):
            dialog._save()
        self.assertNotEqual(dialog.result(), QDialog.Accepted)
        self.assertIn("disk full", dialog.status.text())
        self.assertEqual(self.cfg, original)
        self.assertEqual(dialog.name.text(), "Failed draft")
        dialog.reject()
        self.assertEqual(self.cfg, original)

    def test_false_save_result_does_not_accept_dialog(self):
        dialog = self.manager()
        self.persist.return_value = False
        with self.assertRaisesRegex(OSError, "无法保存分类设置"):
            dialog._save()
        self.assertNotEqual(dialog.result(), QDialog.Accepted)

    def test_separator_only_rule_is_invalid(self):
        dialog = self.manager()
        dialog._append_rule({"field": "extension", "value": ", ，"})
        dialog._save()
        self.persist.assert_not_called()
        self.assertIn("规则内容", dialog.status.text())

    def test_selected_files_keep_exact_paths_through_field_and_category_switching(self):
        dialog = self.manager()
        paths = [str(Path(self.temp.name) / "report,final.txt"),
                 str(Path(self.temp.name) / "资料，终稿.txt")]
        for path in paths:
            Path(path).write_text("example", encoding="utf-8")
        saved_config = Path(self.temp.name) / "settings.json"
        self.persist.side_effect = lambda: saved_config.write_text(json.dumps(self.cfg), encoding="utf-8")
        dialog._append_rule({"field": "exact", "value": ""})
        row = dialog.rule_rows[-1]
        with patch("shortcut_app.category_manager.QFileDialog.getOpenFileNames", return_value=(paths, "")):
            row._choose()
        self.assertEqual(row.value()["value"], paths)
        row.field.setCurrentIndex(row.field.findData("name"))
        row.field.setCurrentIndex(row.field.findData("exact"))
        self.assertEqual(row.value()["value"], paths)
        dialog.list.setCurrentRow(2)
        dialog.list.setCurrentRow(0)
        self.assertEqual(dialog.rule_rows[-1].value()["value"], paths)
        dialog._save()
        self.assertEqual(self.state["categories"][0]["rules"][-1]["value"], paths)
        restored = json.loads(saved_config.read_text(encoding="utf-8"))
        groups = classify([describe_path(path) for path in paths], restored["organizer"])
        self.assertEqual({entry["path"] for entry in groups["apps"]}, {normalize_path(path) for path in paths})


if __name__ == "__main__":
    unittest.main()
