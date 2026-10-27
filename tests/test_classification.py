"""Path identity regressions; synthetic entries never access the user's desktop."""

import os
import unittest

from shortcut_app.organizer import (UNCATEGORIZED, classify, default_state, normalize_path,
                       reconcile_entries, matches_category)


def entry(directory, name="report.txt", kind="documents", target=""):
    path = normalize_path(os.path.join("classification-test-data", directory, name))
    return {"path": path, "name": name, "kind": kind,
            "extension": os.path.splitext(name)[1], "target": target}


def paths(group):
    return {item["path"] for item in group}


class ClassificationIdentityTests(unittest.TestCase):
    def setUp(self):
        self.state = default_state()
        self.first = entry("one")
        self.second = entry("two")

    def test_same_named_files_in_distinct_directories_are_both_kept(self):
        groups = classify([self.first, self.second], self.state)
        self.assertEqual(paths(groups["documents"]),
                         {self.first["path"], self.second["path"]})

    def test_shortcuts_to_same_target_remain_independent_entries(self):
        target = normalize_path(os.path.join("classification-test-data", "app.exe"))
        user = entry("user-desktop", "App.lnk", "apps", target)
        public = entry("public-desktop", "App.lnk", "apps", target)
        self.state["manual"][public["path"]] = "images"
        groups = classify([user, public], self.state)
        self.assertEqual(paths(groups["apps"]), {user["path"]})
        self.assertEqual(paths(groups["images"]), {public["path"]})

    def test_repeated_normalized_path_only_appears_once(self):
        duplicate = dict(self.first)
        duplicate["path"] = os.path.join(os.path.dirname(self.first["path"]),
                                         "unused", "..", self.first["name"])
        groups = classify([self.first, duplicate], self.state)
        self.assertEqual(groups["documents"], [self.first])

    def test_manual_assignment_only_applies_to_exact_path(self):
        self.state["manual"][self.first["path"]] = "images"
        groups = classify([self.first, self.second], self.state)
        self.assertEqual(paths(groups["images"]), {self.first["path"]})
        self.assertEqual(paths(groups["documents"]), {self.second["path"]})

    def test_absent_same_named_manual_entry_cannot_assign_another_file(self):
        self.state["manual"][self.first["path"]] = "images"
        groups = classify([self.second], self.state)
        self.assertEqual(groups["images"], [])
        self.assertEqual(groups["documents"], [self.second])

    def test_exclusion_only_removes_exact_path(self):
        self.state["excluded"] = [self.first["path"]]
        groups = classify([self.first, self.second], self.state)
        self.assertEqual(groups["documents"], [self.second])

    def test_first_matching_rule_wins_and_unknown_types_remain_uncategorized(self):
        self.state["categories"].insert(0, {
            "id": "reports", "rules": [{"field": "name", "value": "report"}]})
        unknown = entry("one", "unknown.bin", "other")
        groups = classify([self.first, unknown], self.state)
        self.assertEqual(groups["reports"], [self.first])
        self.assertEqual(groups["documents"], [])
        self.assertEqual(groups[UNCATEGORIZED], [unknown])

    def test_file_identity_rename_still_preserves_manual_assignment(self):
        old = dict(self.first, identity="volume:42", birth_ns=123)
        renamed = dict(entry("one", "renamed.txt"), identity="volume:42", birth_ns=123)
        self.state["manual"][old["path"]] = "images"
        reconcile_entries([old], [renamed], self.state)
        groups = classify([renamed], self.state)
        self.assertNotIn(old["path"], self.state["manual"])
        self.assertEqual(groups["images"], [renamed])

    def test_selected_exact_paths_preserve_commas_and_only_match_selected_files(self):
        selected = entry("one", "report,final.txt")
        other = entry("one", "report.txt")
        category = {"rules": [{"field": "exact", "value": [selected["path"]]}]}
        self.assertTrue(matches_category(selected, category))
        self.assertFalse(matches_category(other, category))

    def test_compound_extension_matches_target_file_but_not_folder(self):
        archive = entry("one", "backup.tar.gz", "archives")
        shortcut = dict(entry("two", "Backup.lnk", "archives"),
                        extension=".gz", target=archive["path"])
        category = {"rules": [{"field": "extension", "value": "*.tar.gz"}]}
        self.assertTrue(matches_category(archive, category))
        self.assertTrue(matches_category(shortcut, category))
        folder = dict(archive, kind="folders", extension="")
        self.assertFalse(matches_category(folder, category))


if __name__ == "__main__":
    unittest.main()
