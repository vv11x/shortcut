"""Windows 实机窗口检查；不读取或修改用户配置。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'windows'
import atexit
import copy
import ctypes
from pathlib import Path
import sys
import tempfile
import traceback
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
original_hook = sys.excepthook
import shortcut_app.application as shortcut
atexit.unregister(shortcut._restore_desktop_icons_safe)
sys.excepthook = original_hook
from shortcut_app.branding import configure_application
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtTest import QTest

shortcut.configure_display_scaling()
app = shortcut.QApplication([])
configure_application(app)
app.setQuitOnLastWindowClosed(False)
user = ctypes.WinDLL('user32', use_last_error=True)
user.GetWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
user.GetWindow.restype = ctypes.c_void_p
user.IsWindowEnabled.argtypes = [ctypes.c_void_p]
user.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
user.SendMessageW.restype = ctypes.c_ssize_t
cfg = copy.deepcopy(shortcut.DEFAULT_CONFIG)
cfg.update(theme='light', glass=False, running_dots=False)
cfg['organizer']['automatic'] = False
errors = []
output = Path(tempfile.gettempdir()) / 'shortcut-validation' / 'settings-pages'
output.mkdir(parents=True, exist_ok=True)

with patch.object(shortcut, 'save_config', return_value=True):
    window = shortcut.Shortcut(cfg, preview=True)
    window.setup_organizer(directories=[])
    window.tray = shortcut.ShortcutTray(window)
    try:
        window.open_preferences_dialog()
        preferences = window._pref_dialog
        assert preferences.controls['screen'].currentIndex() == 0, 'primary screen choice is blank'
        for index in range(6):
            preferences.nav.setCurrentRow(index)
            QTest.qWait(50)
            assert preferences.pages.currentIndex() == index
            assert preferences.grab().save(str(output / ('page-%d.png' % (index + 1))))
        preferences.nav.setCurrentRow(4)
        QTest.qWait(100)
        assert user.SendMessageW(int(preferences.winId()), 0x7f, 1, 0), 'preferences native icon missing'
        window.tray.set_icon_size(76)
        assert preferences.controls['icon_size'].value() == 76
        print('PASS all six settings pages render and tray changes synchronize')
        original_categories = copy.deepcopy(window.organizer.state['categories'])

        def inspect():
            manager = window.category_manager
            try:
                assert manager.parentWidget() is preferences
                assert manager.windowModality() == Qt.WindowModal
                assert user.GetWindow(int(manager.winId()), 4) == int(preferences.winId()), 'wrong native owner'
                assert not user.IsWindowEnabled(int(preferences.winId())), 'preferences still accepts input'
                assert user.SendMessageW(int(manager.winId()), 0x7f, 1, 0), 'manager native icon missing'
                window.open_preferences_dialog()
                assert window._pref_dialog is preferences
                assert app.activeModalWidget() is manager
                assert manager.grab().save(str(output / 'category-manager.png'))
                manager.name.clear()
                manager._save()
                assert app.activeModalWidget() is manager, 'invalid draft was saved'
                assert '分类名称' in manager.status.text()
                manager.name.setText('Unsaved draft')
                manager._append_rule({'field': 'extension', 'value': ''})
                manager.list.setCurrentRow(1)
                manager.list.setCurrentRow(0)
                assert manager.rule_rows[-1].value()['value'] == '', 'draft rule lost'
                manager._remove_rule(manager.rule_rows[-1])
                selected_file = output / 'selected,example.txt'
                selected_file.write_text('example', encoding='utf-8')
                manager._append_rule({'field': 'exact', 'value': [str(selected_file)]})
                before_failure = copy.deepcopy(cfg)
                with patch.object(window.organizer, '_save_callback', side_effect=OSError('test disk full')):
                    try:
                        manager._save()
                    except OSError as error:
                        assert str(error) == 'test disk full'
                    else:
                        raise AssertionError('save error was hidden')
                assert cfg == before_failure, 'failed save published the draft'
                assert 'test disk full' in manager.status.text()
                assert app.activeModalWidget() is manager, 'failed save closed the dialog'
                assert manager.rule_rows[-1].value()['value'] == [str(selected_file)]
                QTest.qWait(50)
                assert manager.grab().save(str(output / 'category-save-error.png'))
                print('PASS save failure exposes original error, keeps draft and leaves active config unchanged')
                print('PASS native dialog owner, modal input, settings focus and window icons')
            except Exception:
                errors.append(traceback.format_exc())
            finally:
                manager.reject()

        QTimer.singleShot(100, inspect)
        window.manage_categories()
        app.processEvents()
        assert not errors, '\n'.join(errors)
        assert user.IsWindowEnabled(int(preferences.winId()))
        assert window.category_manager is None
        assert window.organizer.state['categories'] == original_categories, 'cancel changed categories'
        print('PASS preferences restored after closing category manager')
        print('Screenshots: ' + str(output))
    finally:
        window.shutdown_presentation()
        window.organizer.stop()
        window.search_bar.shutdown()
        window.category_panel.model.shutdown()
        window.category_panel.deleteLater()
        window.desktop_folders.deleteLater()
        window.tray.deleteLater()
        window.deleteLater()
        app.processEvents()
