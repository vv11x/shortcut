"""Shell operations are recorded, never elevated, launched or shown in these tests."""

import ctypes as C
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtCore import QPoint
from PyQt5.QtWidgets import QApplication, QWidget

from shortcut_app.file_actions import FileActions
from shortcut_app.menu_ui import ThemedMenu
from shortcut_app.shell_actions import WindowsShell, _ExecuteInfo, native_menu_selection, native_point


class ShellActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.owner = QWidget()
        self.owner.organizer_message = Mock()
        self.owner.category_panel = SimpleNamespace(hide=Mock())
        self.owner.search_bar = SimpleNamespace(collapse=Mock())
        self.owner.recycle_bin = None
        with patch('shortcut_app.file_actions.installed_tools', return_value={}):
            self.actions = FileActions(self.owner)
        self.addCleanup(self.owner.deleteLater)

    def shell_with_api(self, execute):
        shell = WindowsShell(self.owner)
        shell._initialize = Mock()
        shell._shell = SimpleNamespace(ShellExecuteExW=execute)
        return shell

    def test_runas_passes_original_shortcut_without_overriding_saved_arguments(self):
        records = []

        def execute(pointer):
            info = C.cast(pointer, C.POINTER(_ExecuteInfo)).contents
            records.append((info.lpFile, info.lpVerb, info.lpParameters, info.lpDirectory, info.fMask))
            return True

        shell = self.shell_with_api(execute)
        path = os.path.abspath('test shortcut 中文.lnk')
        self.assertTrue(shell.invoke(path, 'runas'))
        self.assertEqual(records[0][:4], (path, 'runas', None, None))
        self.assertEqual(records[0][4] & 0xc, 0xc)
        self.assertFalse(records[0][4] & 0x00800000)  # Never disable zone checks.

    def test_properties_uses_original_entry_and_context_handler_flag(self):
        records = []

        def execute(pointer):
            info = C.cast(pointer, C.POINTER(_ExecuteInfo)).contents
            records.append((info.lpVerb, info.lpFile, info.fMask))
            return True

        path = os.path.abspath('properties-entry.lnk')
        self.shell_with_api(execute).invoke(path, 'properties')
        self.assertEqual(records[0][:2], ('properties', path))
        self.assertEqual(records[0][2] & 0xc, 0xc)

    def test_uac_cancellation_is_not_reported_as_failure_or_retried(self):
        execute = Mock(return_value=False)
        with patch('shortcut_app.shell_actions.C.get_last_error', return_value=1223):
            self.assertFalse(self.shell_with_api(execute).invoke('app.exe', 'runas'))
        execute.assert_called_once()

    def test_other_shell_errors_are_reported(self):
        with patch('shortcut_app.shell_actions.C.get_last_error', return_value=2):
            with self.assertRaises(OSError):
                self.shell_with_api(Mock(return_value=False)).invoke('missing.exe', 'runas')

    def test_shared_menus_have_windows_actions_with_valid_selection_rules(self):
        for paths, can_admin, can_native in ((['app.lnk'], True, True), (['notes.txt'], False, True),
                                             (['one/a.lnk', 'two/b.lnk'], False, False),
                                             (['one/a.lnk', 'one/b.lnk'], False, True)):
            with self.subTest(paths=paths):
                menu = ThemedMenu()
                commands = self.actions.add_menu(menu, paths)
                by_command = {command: action for action, command in commands.items()}
                self.assertEqual(by_command['runas'].isEnabled(), can_admin)
                self.assertEqual(by_command['native_menu'].isEnabled(), can_native)
                self.assertEqual(by_command['properties'].isEnabled(), len(paths) == 1)
                menu.deleteLater()

    def test_document_shortcut_does_not_offer_a_program_elevation_action(self):
        from shortcut_app.organizer import normalize_path
        self.owner.organizer = SimpleNamespace(entries={normalize_path('document.lnk'): {'kind': 'documents'}})
        menu = ThemedMenu()
        commands = self.actions.add_menu(menu, ['document.lnk'])
        action = next(action for action, command in commands.items() if command == 'runas')
        self.assertFalse(action.isEnabled())
        menu.deleteLater()

    def test_file_action_hides_both_popups_and_invokes_explicit_runas(self):
        self.actions.shell = SimpleNamespace(invoke=Mock(return_value=True))
        self.assertTrue(self.actions.perform('runas', ['app.lnk']))
        self.actions.shell.invoke.assert_called_once_with(os.path.abspath('app.lnk'), 'runas')
        self.owner.category_panel.hide.assert_called_once()
        self.owner.search_bar.collapse.assert_called_once_with(animate=False)

    def test_cancelled_runas_has_no_error_notification(self):
        self.actions.shell = SimpleNamespace(invoke=Mock(return_value=False))
        self.assertFalse(self.actions.perform('runas', ['app.lnk']))
        self.owner.organizer_message.assert_not_called()

    def test_cross_folder_native_selection_does_not_silently_use_first_item(self):
        self.actions.shell = SimpleNamespace(context_menu=Mock())
        self.assertFalse(self.actions.perform('native_menu', ['one/app.lnk', 'two/app.lnk']))
        self.actions.shell.context_menu.assert_not_called()
        self.owner.organizer_message.assert_called_once()

    def test_native_menu_payload_uses_utf16_length_for_non_bmp_paths(self):
        shell = self.shell_with_api(Mock())
        records = []

        def show(owner, buffer, characters, x, y):
            records.append(C.string_at(buffer, characters * 2).decode('utf-16-le'))
            return 1  # Menu cancelled.

        shell._native = SimpleNamespace(ShowShellContextMenu=show)
        paths = [os.path.abspath('menu-😀.lnk')]
        with patch('shortcut_app.shell_actions.native_point', return_value=QPoint(10, 20)):
            self.assertFalse(shell.context_menu(paths, QPoint(10, 20)))
        self.assertEqual(records, [paths[0] + '\0\0'])

    def test_reveal_selects_original_shortcut_and_releases_pidl(self):
        parse = Mock(side_effect=lambda path, unused, result, flags, attributes:
                     setattr(C.cast(result, C.POINTER(C.c_void_p)).contents, 'value', 123) or 0)
        select = Mock(return_value=0)
        shell = self.shell_with_api(Mock())
        shell._ole = SimpleNamespace(CoTaskMemFree=Mock())
        api = SimpleNamespace(SHParseDisplayName=parse, SHOpenFolderAndSelectItems=select)
        with patch('shortcut_app.shell_actions.C.WinDLL', return_value=api):
            self.assertTrue(shell.reveal('original.lnk'))
        self.assertEqual(parse.call_args.args[0], os.path.abspath('original.lnk'))
        self.assertEqual(select.call_args.args[0].value, 123)
        self.assertEqual(select.call_args.args[1:], (0, None, 0))
        shell._ole.CoTaskMemFree.assert_called_once()
        shell._ole = None

    def test_mixed_parent_rules_and_native_popup_coordinates(self):
        self.assertTrue(native_menu_selection(['folder/a.lnk', 'folder/b.lnk']))
        self.assertFalse(native_menu_selection(['folder/a.lnk', 'other/b.lnk']))
        screen = SimpleNamespace(geometry=lambda: self.owner.rect().translated(-1920, 0),
                                 devicePixelRatio=lambda: 2)
        with patch('shortcut_app.shell_actions.QApplication.screenAt', return_value=screen):
            self.assertEqual(native_point(QPoint(-1880, 40)), QPoint(-1840, 80))


if __name__ == '__main__':
    unittest.main()
