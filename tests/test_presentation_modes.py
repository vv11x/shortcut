"""Exercise actual mode switching and settings together, with OS effects replaced."""

import atexit
import copy
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


class PresentationModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        hook = sys.excepthook
        import shortcut_app.application as shortcut
        atexit.unregister(shortcut._restore_desktop_icons_safe)
        sys.excepthook = hook
        cls.module = shortcut
        cls.app = shortcut.QApplication.instance() or shortcut.QApplication([])

    def setUp(self):
        for name in ('save_config', 'log', 'trim_process_memory', 'set_icons_visible'):
            replacement = patch.object(self.module, name)
            replacement.start()
            self.addCleanup(replacement.stop)
        for name in ('apply_layer', 'start_backdrop', 'refresh_backdrop'):
            replacement = patch.object(self.module.Shortcut, name)
            replacement.start()
            self.addCleanup(replacement.stop)
        cfg = copy.deepcopy(self.module.DEFAULT_CONFIG)
        cfg.update(theme='light', running_dots=False, show_search=True)
        cfg['organizer']['automatic'] = False
        self.shortcut = self.module.Shortcut(cfg, preview=True)
        self.addCleanup(self.dispose)
        self.shortcut.setup_organizer(directories=[])
        self.shortcut.tray = self.module.ShortcutTray(self.shortcut)
        self.shortcut.category_panel.model.request_icon = Mock(return_value=None)

    def dispose(self):
        self.shortcut.shutdown_presentation()
        self.shortcut.organizer.stop()
        self.shortcut.search_bar.shutdown()
        self.shortcut.category_panel.model.shutdown()
        self.shortcut.category_panel.deleteLater()
        self.shortcut.desktop_folders.deleteLater()
        self.shortcut.tray.hide()
        self.shortcut.tray.deleteLater()
        self.shortcut.deleteLater()
        self.app.processEvents()

    def test_modes_are_mutually_exclusive_and_restore_search(self):
        self.shortcut.sync_presentation()
        self.assertTrue(self.shortcut.isVisible())
        self.assertTrue(self.shortcut.search_bar.isVisible())
        self.assertFalse(self.shortcut.desktop_folders.isVisible())
        self.assertTrue(self.shortcut.set_desktop_folder_mode(True))
        self.assertFalse(self.shortcut.isVisible())
        self.assertFalse(self.shortcut.search_bar.isVisible())
        self.assertTrue(self.shortcut.desktop_folders.isVisible())
        self.assertEqual(self.shortcut.cfg['folder_grid_size'], '4x4')
        self.assertTrue(self.shortcut.presentation_timer.isActive())
        self.assertFalse(self.shortcut.geo_timer.isActive())
        self.assertTrue(self.shortcut.set_desktop_folder_mode(False))
        self.assertTrue(self.shortcut.isVisible())
        self.assertTrue(self.shortcut.search_bar.isVisible())
        self.assertFalse(self.shortcut.desktop_folders.isVisible())
        self.assertFalse(self.shortcut.presentation_timer.isActive())

    def test_tray_reshow_keeps_desktop_mode(self):
        self.shortcut.set_desktop_folder_mode(True)
        self.shortcut.set_presentation_visible(False)
        self.assertFalse(self.shortcut.desktop_folders.isVisible())
        self.shortcut.tray._show_shortcut()
        self.assertTrue(self.shortcut.desktop_folders.isVisible())
        self.assertFalse(self.shortcut.isVisible())
        self.shortcut.tray.rebuild()
        labels = [action.text() for action in self.shortcut.tray.menu.actions()]
        self.assertIn('显示 / 隐藏桌面文件夹', labels)

    def test_tray_add_to_second_category_with_duplicate_name_uses_its_id(self):
        self.shortcut.cfg['desktop_folder_mode'] = True
        categories = self.shortcut.organizer.state['categories']
        categories[0]['name'] = categories[1]['name'] = 'Same name'

        def choose_second(_parent, _title, _label, labels, *_):
            self.assertNotEqual(labels[0], labels[1])
            return labels[1], True

        with patch.object(self.module.QFileDialog, 'getOpenFileNames', return_value=(['example.lnk'], '')), \
                patch.object(self.module.QInputDialog, 'getItem', side_effect=choose_second), \
                patch.object(self.shortcut.organizer, 'assign_paths') as assign, \
                patch.object(self.shortcut.tray, '_show_shortcut'):
            self.shortcut.tray.add_icons()
        assign.assert_called_once_with(['example.lnk'], categories[1]['id'])

    def test_tray_add_continues_with_selected_files_after_creating_first_category(self):
        self.shortcut.cfg['desktop_folder_mode'] = True
        self.shortcut.organizer.state['categories'] = []
        category = {'id': 'new', 'name': 'New category', 'icon': 'apps', 'rules': []}

        def create_category():
            self.shortcut.organizer.state['categories'] = [category]

        with patch.object(self.module.QFileDialog, 'getOpenFileNames', return_value=(['example.lnk'], '')), \
                patch.object(self.shortcut, 'manage_categories', side_effect=create_category), \
                patch.object(self.module.QInputDialog, 'getItem', side_effect=lambda *args: (args[3][0], True)), \
                patch.object(self.shortcut.organizer, 'assign_paths') as assign, \
                patch.object(self.shortcut.tray, '_show_shortcut'):
            self.shortcut.tray.add_icons()
        assign.assert_called_once_with(['example.lnk'], 'new')

    def test_pending_host_failure_preserves_mode_and_reports_error(self):
        boxes = self.shortcut.desktop_folders
        with patch.object(boxes, 'ensure_desktop_host', return_value=False):
            self.shortcut.set_desktop_folder_mode(True)
            self.assertTrue(boxes._reconnect.isActive())
            self.assertFalse(self.shortcut.isVisible())
        with patch.object(self.shortcut, 'organizer_message') as report:
            boxes.hostError.emit('test desktop unavailable')
            report.assert_called_once_with('桌面文件夹', 'test desktop unavailable')
        self.assertTrue(self.shortcut.cfg['desktop_folder_mode'])
        self.assertFalse(self.shortcut.isVisible())
        self.assertFalse(boxes.isVisible())

    def test_hiding_restores_icons_and_reshowing_reapplies_preference(self):
        manager = Mock()
        self.shortcut.desktop_manager = manager
        for folders in (False, True):
            for mode in ('managed', 'all', 'hidden'):
                with self.subTest(folders=folders, mode=mode):
                    self.shortcut.cfg['desktop_display'] = mode
                    self.shortcut.set_desktop_folder_mode(folders)
                    manager.set_mode.assert_called_with(mode)
                    self.shortcut.set_presentation_visible(False)
                    manager.set_mode.assert_called_with('all')
                    self.assertEqual(self.shortcut.cfg['desktop_display'], mode)
                    self.shortcut.set_presentation_visible(True)
                    manager.set_mode.assert_called_with(mode)

    def test_context_menu_hide_restores_desktop_and_updates_presentation_state(self):
        self.shortcut.desktop_manager = Mock()
        self.shortcut.sync_presentation()

        def choose_hide(menu, *_):
            action = next(action for action in menu.actions() if action.text() == '隐藏 Shortcut')
            action.trigger()
            return action

        with patch.object(self.module.ThemedMenu, 'exec_', choose_hide):
            self.shortcut.contextMenuEvent(SimpleNamespace(pos=lambda: self.module.QPoint(-1, -1)))
        self.assertFalse(self.shortcut._presentation_visible)
        self.assertFalse(self.shortcut.isVisible())
        self.shortcut.desktop_manager.set_mode.assert_called_with('all')

    def test_folder_collection_includes_uncategorized_but_shortcut_does_not(self):
        self.shortcut.desktop_manager = Mock()
        self.shortcut.set_desktop_folder_mode(True)
        categories = self.shortcut.desktop_manager.update.call_args.args[1]
        self.assertIn('__uncategorized__', [item['id'] for item in categories])
        self.shortcut.set_desktop_folder_mode(False)
        categories = self.shortcut.desktop_manager.update.call_args.args[1]
        self.assertNotIn('__uncategorized__', [item['id'] for item in categories])

    def test_shutdown_restores_desktop_once_and_stops_dismissal(self):
        self.shortcut.desktop_manager = Mock()
        self.shortcut.set_desktop_folder_mode(True)
        self.shortcut.open_category('apps', self.module.QRect(100, 100, 100, 100), shortcut_edge=None)
        self.shortcut.category_panel.hide()
        self.shortcut.shutdown_presentation()
        self.shortcut.shutdown_presentation()
        self.shortcut.desktop_manager.stop.assert_called_once_with()
        self.assertFalse(self.shortcut.category_panel._dismissal.isVisible())

    def test_folder_box_accepts_internal_virtual_assignment(self):
        self.shortcut.set_desktop_folder_mode(True)
        boxes = self.shortcut.desktop_folders
        card = boxes.folder_rects()[0][0].toRect()
        point = boxes._area.topLeft() + card.center()
        path = 'virtual-test-item.lnk'
        with patch.object(self.shortcut.organizer, 'assign_paths') as assign:
            self.assertEqual(self.shortcut._entry_drag_target([path], point, 'hover'), '归入桌面分类盒子')
            self.assertTrue(self.shortcut._entry_drag_target([path], point, 'drop'))
            assign.assert_called_once_with([path], boxes.folder_rects()[0][3]['id'])

    def test_preview_limit_does_not_limit_full_category_contents(self):
        entries = []
        for number in range(24):
            path = self.module.normalize_path('mode-test/app-%d.lnk' % number)
            entries.append({'path': path, 'name': 'App %d' % number, 'kind': 'apps',
                            'extension': '.lnk', 'target': ''})
        self.shortcut.organizer.entries = {item['path']: item for item in entries}
        self.shortcut.organizer._notify_changed()
        self.shortcut.set_desktop_folder_mode(True)
        box = next(item for item in self.shortcut.desktop_folders.folder_rects() if item[3]['id'] == 'apps')
        self.shortcut.open_category('apps', box[0].toAlignedRect(), shortcut_edge=None)
        self.assertEqual(self.shortcut.category_panel.model.rowCount(), 24)
        self.assertTrue(self.shortcut.category_panel.isVisible())
        self.assertFalse(self.shortcut.isVisible())

    def test_uncategorized_box_does_not_silently_remove_dragged_item(self):
        self.shortcut.set_desktop_folder_mode(True)
        boxes = self.shortcut.desktop_folders
        boxes._change_page(boxes._pages - 1)
        card = next(card[0].toRect() for card in boxes.folder_rects()
                    if card[3]['id'] == '__uncategorized__')
        point = card.center() + boxes._area.topLeft()
        with patch.object(self.shortcut.organizer, 'exclude_paths') as exclude:
            self.assertFalse(self.shortcut._entry_drag_target(['item.lnk'], point, 'drop'))
            exclude.assert_not_called()

    def test_search_disabled_releases_space_and_cannot_show_in_folder_mode(self):
        self.shortcut.sync_presentation()
        self.assertGreater(self.shortcut.search_extent(expanded=True), 0)
        self.shortcut.set_search_enabled(False)
        self.assertEqual(self.shortcut.search_extent(expanded=True), 0)
        self.assertFalse(self.shortcut.search_bar.isVisible())
        self.shortcut.set_desktop_folder_mode(True)
        self.shortcut.set_search_enabled(True)
        self.assertEqual(self.shortcut.search_extent(expanded=True), 0)
        self.assertFalse(self.shortcut.search_bar.isVisible())

    def test_real_preferences_switch_modes_and_synchronize_theme(self):
        self.shortcut.sync_presentation()
        self.shortcut.open_preferences_dialog()
        dialog = self.shortcut._pref_dialog
        dialog.controls['mode_folders'].setChecked(True)
        self.assertTrue(self.shortcut.desktop_folders.isVisible())
        self.assertFalse(dialog.controls['position'].isEnabled())
        self.assertTrue(dialog.controls['folder_grid_size'].isEnabled())
        self.shortcut.tray.set_theme('dark')
        self.assertFalse(self.shortcut.category_panel.light)
        self.assertFalse(self.shortcut.search_bar.light)
        self.assertIn('#1e222b', dialog.styleSheet())
        dialog.controls['mode_shortcut'].setChecked(True)
        self.assertTrue(self.shortcut.isVisible())
        self.assertTrue(dialog.controls['position'].isEnabled())

    def test_category_manager_is_owned_by_preferences_and_cannot_be_covered_by_reopening_settings(self):
        from PyQt5.QtCore import QTimer, Qt
        self.shortcut.open_preferences_dialog()
        preferences = self.shortcut._pref_dialog
        observations = []

        def inspect_dialog():
            manager = self.shortcut.category_manager
            observations.extend((manager.parentWidget() is preferences,
                                 manager.windowModality() == Qt.WindowModal,
                                 self.app.activeModalWidget() is manager))
            self.shortcut.open_preferences_dialog()
            observations.extend((self.shortcut._pref_dialog is preferences,
                                 self.app.activeModalWidget() is manager,
                                 not manager.windowIcon().isNull()))
            manager.reject()

        QTimer.singleShot(0, inspect_dialog)
        self.shortcut.manage_categories()
        self.assertEqual(observations, [True] * 6)
        self.assertIsNone(self.shortcut.category_manager)
        self.assertTrue(preferences.isVisible())

    def test_preferences_are_reused_and_windows_have_real_application_icons(self):
        self.shortcut.open_preferences_dialog()
        preferences = self.shortcut._pref_dialog
        self.shortcut.open_preferences_dialog()
        self.assertIs(self.shortcut._pref_dialog, preferences)
        self.assertFalse(self.shortcut.windowIcon().isNull())
        self.assertFalse(preferences.windowIcon().isNull())
        self.assertIn(self.module.QSize(32, 32), preferences.windowIcon().availableSizes())

    def test_open_preferences_follow_external_tray_changes_without_extra_saves(self):
        self.shortcut.open_preferences_dialog()
        preferences = self.shortcut._pref_dialog
        self.shortcut.tray.set_icon_size(76)
        self.shortcut.tray.set_flag('magnify', False)
        self.assertEqual(preferences.controls['icon_size'].value(), 76)
        self.assertFalse(preferences.controls['magnify'].isChecked())

    def test_config_round_trip_restores_mode_grid_and_positions(self):
        self.shortcut.cfg.update(desktop_folder_mode=True, folder_grid_size='4x4',
                             desktop_folder_positions={'apps': [50, 60]})
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'config.json')
            with patch.object(self.module, 'CONFIG_DIR', directory), \
                    patch.object(self.module, 'CONFIG_PATH', path), \
                    patch.object(self.module, 'save_config', wraps=self.real_save_config()):
                self.shortcut.save_preferences()
                restored = self.module.load_config()
            self.assertTrue(restored['desktop_folder_mode'])
            self.assertEqual(restored['folder_grid_size'], '4x4')
            self.assertEqual(restored['desktop_folder_positions'], {'apps': [50, 60]})
            self.shortcut.cfg.update(restored)
            self.shortcut.sync_presentation()
            self.assertFalse(self.shortcut.isVisible())
            self.assertTrue(self.shortcut.desktop_folders.isVisible())

    @staticmethod
    def real_save_config():
        # Use the real writer despite the fixture's OS-effect patch.
        import ast
        import json
        tree = ast.parse(Path(__file__).resolve().parents[1].joinpath('shortcut_app/application.py').read_text(encoding='utf-8-sig'))
        method = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'save_config')
        import shortcut_app.application as shortcut
        namespace = shortcut.__dict__.copy()
        exec(compile(ast.Module(body=[method], type_ignores=[]), 'shortcut.py', 'exec'), namespace)
        return namespace['save_config']

    def test_shutdown_hides_boxes_and_stops_mode_and_host_timers(self):
        self.shortcut.set_desktop_folder_mode(True)
        self.shortcut.shutdown_presentation()
        self.assertFalse(self.shortcut.desktop_folders.isVisible())
        self.assertTrue(self.shortcut.desktop_folders._closed)
        self.assertFalse(self.shortcut.presentation_timer.isActive())
        self.assertFalse(self.shortcut.desktop_folders._reconnect.isActive())

    def test_failed_autostart_and_invalid_custom_icon_do_not_persist_success(self):
        with patch.object(self.module, 'set_autostart', return_value=False):
            self.assertFalse(self.shortcut.set_autostart_enabled(True))
            self.assertFalse(self.shortcut.cfg['autostart'])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.exe'
            path.write_text('not an image', encoding='utf-8')
            self.assertFalse(self.shortcut.set_category_custom_icon('apps', str(path)))
            self.assertNotIn('apps', self.shortcut.cfg['category_custom_icons'])

    def test_never_shown_main_window_is_registered_for_stop_command(self):
        with patch.object(self.module.user32, 'SetPropW') as marker:
            hidden = self.module.Shortcut(copy.deepcopy(self.shortcut.cfg), preview=True)
            try:
                self.assertFalse(hidden.isVisible())
                marker.assert_called_with(int(hidden.winId()), self.module.MAIN_WINDOW_MARKER, 1)
            finally:
                hidden.shutdown_presentation()
                hidden.deleteLater()

    def test_failed_save_is_reported_instead_of_silently_succeeding(self):
        with patch.object(self.module, 'save_config', return_value=False):
            with self.assertRaises(OSError):
                self.shortcut.save_preferences()

    def test_shared_category_surface_consumes_glass_and_blur_settings(self):
        from test_desktop_folders import Screen
        screen = Screen()
        surface = self.shortcut.category_panel.surface
        self.shortcut.cfg.update(glass=True, blur_px=2)
        surface.capture(screen)
        before = surface.snapshot.width()
        self.shortcut.cfg['blur_px'] = 20
        surface.capture(screen)
        self.assertLess(surface.snapshot.width(), before)
        self.shortcut.cfg['glass'] = False
        surface.capture(screen)
        self.assertTrue(surface.snapshot.isNull())
        self.assertEqual(screen.grabs, 2)

    def test_runas_is_routed_from_panel_search_and_pinned_entry_menus(self):
        from PyQt5.QtCore import QPoint, Qt
        from shortcut_app.menu_ui import ThemedMenu
        path = self.module.normalize_path('right-click-test.lnk')
        entry = {'path': path, 'name': 'Test app.lnk', 'kind': 'apps', 'extension': '.lnk', 'target': ''}
        self.shortcut.organizer.entries = {path: entry}
        self.shortcut.organizer._notify_changed()
        invoke = Mock(return_value=True)
        self.shortcut.file_actions.shell = SimpleNamespace(invoke=invoke)

        def admin_action(menu, *args):
            return next(action for action in menu.actions() if action.text() == '以管理员身份运行')

        panel = self.shortcut.category_panel
        self.shortcut.open_category('apps', self.module.QRect(100, 100, 100, 100), shortcut_edge=None)
        position = panel.view.visualRect(panel.model.index(0, 0)).center()
        with patch.object(panel, '_exec_menu', side_effect=admin_action):
            panel._context_menu(position)
        invoke.assert_called_once_with(path, 'runas')
        invoke.reset_mock()

        search = self.shortcut.search_bar
        search.model.replace([dict(entry, label='Test app', category='apps', subtitle='apps')])
        search.view.resize(320, 120)
        position = search.view.visualRect(search.model.index(0, 0)).center()
        with patch.object(ThemedMenu, 'exec_', admin_action):
            search._result_context_menu(position)
        invoke.assert_called_once_with(path, 'runas')
        invoke.reset_mock()

        self.shortcut.cfg['items'] = [{'path': path, 'name': 'Test app'}]
        with patch.object(self.shortcut.icons, 'get', return_value=self.module.QPixmap(96, 96)), \
                patch.object(self.shortcut, '_exe_name', return_value='app.exe'):
            self.shortcut.reload()
        center, width, height, base, _ = self.shortcut.rects[0]
        position = self.shortcut.axis_transform().map(self.module.QPointF(center, base - height / 2)).toPoint()
        with patch.object(ThemedMenu, 'exec_', admin_action):
            self.shortcut.contextMenuEvent(SimpleNamespace(pos=lambda: position))
        invoke.assert_called_once_with(path, 'runas')

    def test_restart_waits_for_the_old_instance_and_handles_launch_failure(self):
        application = SimpleNamespace(quit=Mock())
        with patch.object(self.module.QApplication, 'instance', return_value=application), \
                patch.object(self.module.subprocess, 'Popen') as launch:
            self.assertTrue(self.shortcut.restart_shortcut())
            self.assertEqual(launch.call_args.args[0][-2:], ['--wait-for-exit', str(os.getpid())])
            application.quit.assert_called_once_with()
            application.quit.reset_mock()
            launch.side_effect = OSError('failed launch')
            self.assertFalse(self.shortcut.restart_shortcut())
            application.quit.assert_not_called()


if __name__ == '__main__':
    unittest.main()
