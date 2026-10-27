"""Shortcut launch regressions with every external action replaced by a mock."""

import ast
import ntpath
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call


ROOT = Path(__file__).resolve().parents[1]


class ShortcutLaunchIdentityTests(unittest.TestCase):
    def setUp(self):
        self.user_link = r"C:\Users\Current\Desktop\Editor.lnk"
        self.public_link = r"C:\Users\Public\Desktop\Editor.lnk"
        self.other_link = r"C:\Tools\Editor.lnk"
        self.links = {
            self.user_link: (r"C:\Apps\UserEditor.exe", "--profile user", r"C:\UserWork"),
            self.public_link: (r"C:\Apps\PublicEditor.exe", "--profile public", r"C:\PublicWork"),
            self.other_link: (r"C:\Apps\OtherEditor.exe", "--profile other", r"C:\OtherWork"),
        }
        self.path = Mock(wraps=ntpath)
        self.path.isdir.return_value = False
        self.path.exists.return_value = True
        self.path.expanduser.return_value = r"C:\Users\Current"
        self.resolve = Mock(side_effect=self.links.get)
        self.shortcut_target = Mock(side_effect=lambda path: self.links.get(path, ("",))[0])
        self.shell_execute = Mock(return_value=33)
        self.startfile = Mock()
        self.popen = Mock()
        self.fix_path = Mock(side_effect=lambda path: path)
        self.original_invoke = Mock(side_effect=OSError('simulate original link failure'))
        self.owner = SimpleNamespace(file_actions=SimpleNamespace(shell=SimpleNamespace(invoke=self.original_invoke)))
        namespace = {
            "os": SimpleNamespace(path=self.path, startfile=self.startfile),
            "subprocess": SimpleNamespace(Popen=self.popen),
            "ctypes": SimpleNamespace(windll=SimpleNamespace(
                shell32=SimpleNamespace(ShellExecuteW=self.shell_execute))),
            "fix_user_path": self.fix_path,
            "normalize_path": lambda path: ntpath.normcase(ntpath.normpath(path)),
            "shortcut_target": self.shortcut_target,
            "resolve_shortcut_info": self.resolve,
            "log": Mock(),
            "traceback": SimpleNamespace(format_exc=lambda: "mock launch failure"),
        }
        # Avoid importing shortcut and its global desktop-restoration hook.
        tree = ast.parse((ROOT / "shortcut_app/application.py").read_text(encoding="utf-8-sig"))
        owner = next(node for node in tree.body
                     if isinstance(node, ast.ClassDef) and node.name == "Shortcut")
        launch = next(node for node in owner.body
                      if isinstance(node, ast.FunctionDef) and node.name == "launch")
        exec(compile(ast.Module(body=[launch], type_ignores=[]), "shortcut.py", "exec"), namespace)
        self.launch = namespace["launch"]

    def test_same_named_links_each_use_their_own_target_arguments_and_working_directory(self):
        for path in (self.public_link, self.other_link, self.user_link):
            self.launch(self.owner, path)
        self.assertEqual(self.resolve.call_args_list,
                         [call(self.public_link), call(self.other_link), call(self.user_link)])
        self.assertEqual(self.shell_execute.call_args_list, [
            call(None, "open", *self.links[path], 1)
            for path in (self.public_link, self.other_link, self.user_link)])
        self.startfile.assert_not_called()
        self.popen.assert_not_called()

    def test_broken_link_does_not_launch_a_valid_same_named_user_link(self):
        missing_target = r"C:\Missing\Editor.exe"
        self.links[self.public_link] = (missing_target, "--profile broken", "")
        self.path.exists.side_effect = lambda path: path != missing_target
        self.launch(self.owner, self.public_link)
        self.resolve.assert_called_once_with(self.public_link)
        self.shell_execute.assert_called_once_with(None, "open", self.public_link, None, None, 1)

    def test_unresolvable_link_still_uses_original_path_for_shell_fallback(self):
        self.links.pop(self.public_link)
        self.launch(self.owner, self.public_link)
        self.resolve.assert_called_once_with(self.public_link)
        self.shell_execute.assert_called_once_with(None, "open", self.public_link, None, None, 1)

    def test_startfile_fallback_preserves_the_requested_link(self):
        self.links.pop(self.other_link)
        self.shell_execute.return_value = 2
        self.launch(self.owner, self.other_link)
        self.startfile.assert_called_once_with(self.other_link)
        self.resolve.assert_called_once_with(self.other_link)

    def test_explicit_user_path_correction_is_still_applied_before_resolving(self):
        old_path = r"C:\Users\Previous\Desktop\Editor.lnk"
        self.fix_path.side_effect = lambda path: self.user_link if path == old_path else path
        self.launch(self.owner, old_path)
        self.fix_path.assert_called_once_with(old_path)
        self.resolve.assert_called_once_with(self.user_link)
        self.shell_execute.assert_called_once_with(None, "open", *self.links[self.user_link], 1)

    def test_original_link_executes_before_resolving_to_preserve_saved_shell_flags(self):
        self.original_invoke.side_effect = None
        self.original_invoke.return_value = True
        for path in (self.public_link, self.other_link, self.user_link):
            self.launch(self.owner, path)
        self.assertEqual(self.original_invoke.call_args_list,
                         [call(path, 'open') for path in (self.public_link, self.other_link, self.user_link)])
        self.resolve.assert_not_called()
        self.shell_execute.assert_not_called()

    def test_cancelled_uac_does_not_fall_back_to_normal_launch(self):
        self.original_invoke.side_effect = None
        self.original_invoke.return_value = False
        self.launch(self.owner, self.public_link)
        self.resolve.assert_not_called()
        self.shell_execute.assert_not_called()
        self.startfile.assert_not_called()


if __name__ == "__main__":
    unittest.main()
