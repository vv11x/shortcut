import os
os.environ['QT_QPA_PLATFORM'] = 'windows'
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import tempfile
OUTPUT = Path(tempfile.gettempdir()) / 'shortcut-validation'
OUTPUT.mkdir(parents=True, exist_ok=True)
import atexit
import copy
import json
from unittest.mock import patch
from PyQt5.QtCore import Qt, QRect, QAbstractAnimation
from PyQt5.QtWidgets import QApplication
from PyQt5.QtTest import QTest

hook = sys.excepthook
import shortcut_app.application as shortcut
atexit.unregister(shortcut._restore_desktop_icons_safe)
sys.excepthook = hook
from shortcut_app.desktop_visibility import desktop_snapshot, icons_visible
from shortcut_app.desktop_manager import DesktopManager

shortcut.configure_display_scaling()
app = QApplication([])
app.setQuitOnLastWindowClosed(False)
before = desktop_snapshot()
paths = [p for p in before['positions'] if p.endswith('.lnk')][:2]
assert len(paths) == 2
cfg = copy.deepcopy(shortcut.DEFAULT_CONFIG)
cfg.update(theme='light', running_dots=False, desktop_display='all', glass=False)
cfg['organizer']['automatic'] = False
errors, checks = [], []

def wait_for(condition, name, timeout=15000):
    elapsed = 0
    while not condition() and elapsed < timeout and not errors:
        QTest.qWait(30)
        elapsed += 30
    assert not errors, errors
    assert condition(), name
    checks.append(name)
    print('PASS', name, flush=True)

def wait_collected(path, name):
    wait_for(lambda: manager.socket is not None and not manager._startup.isActive(), name + '_service_ready')
    QTest.qWait(200)
    assert path not in desktop_snapshot()['positions'], name
    checks.append(name)
    print('PASS', name, flush=True)

with patch.object(shortcut, 'save_config', return_value=True):
    window = shortcut.Shortcut(cfg, preview=True)
    window.setup_organizer(directories=[])
    manager = window.desktop_manager = DesktopManager(shortcut.SCRIPT_PATH, window,
        marker_path=str((OUTPUT / 'smoke-hidden.json')))
    manager.error.connect(errors.append)
    window.desktop_folders.hostError.connect(errors.append)
    try:
        window.organizer.entries = {p: {'path': p, 'name': Path(p).name, 'kind': 'apps',
                                        'extension': '.lnk', 'target': ''} for p in paths}
        window.organizer.state['manual'][paths[1]] = '__uncategorized__'
        window.organizer._notify_changed()
        window.sync_presentation()
        assert window.set_desktop_display('managed')
        wait_collected(paths[0], 'shortcut_collects_shortcut')
        window.set_presentation_visible(False)
        wait_for(lambda: paths[0] in desktop_snapshot()['positions'], 'hide_restores_shortcut')
        window.set_presentation_visible(True)
        wait_collected(paths[0], 'reshow_collects_shortcut')
        window.set_desktop_folder_mode(True)
        wait_for(lambda: window.desktop_folders.isVisible() and window.desktop_folders._host_backend.alive(),
                 'native_desktop_boxes_attached')
        wait_collected(paths[1], 'folder_collects_uncategorized')
        boxes = window.desktop_folders
        QTest.qWait(300)
        box = next(c[0].toAlignedRect() for c in boxes.folder_rects() if c[3]['id'] == 'apps')
        QTest.mousePress(boxes, Qt.LeftButton, Qt.NoModifier, box.center())
        QTest.qWait(100)
        assert boxes._feedback_levels['apps'][1] > .9
        boxes.grab().save(str((OUTPUT / 'native-boxes-pressed.png')))
        QTest.mouseRelease(boxes, Qt.LeftButton, Qt.NoModifier, box.center())
        panel = window.category_panel
        wait_for(lambda: panel.isVisible() and panel._appear.state() == QAbstractAnimation.Stopped,
                 'panel_opens_from_native_box')
        panel.grab().save(str((OUTPUT / 'native-panel.png')))
        assert panel.pos() == panel._target_pos
        QTest.keyClick(panel, Qt.Key_Escape)
        assert not panel.isVisible()
        assert panel._dismissal.isVisible(), 'native dismissal ghost was hidden with its owner'
        assert not panel._dismissal.frame.isNull()
        panel._dismissal.grab().save(str((OUTPUT / 'native-dismissal.png')))
        wait_for(lambda: not panel._dismissal.isVisible(), 'escape_finishes_dismissal')
        for index in range(4):
            window.open_category('apps', QRect(150 + index * 60, 400, 160, 160), shortcut_edge=None)
            QTest.qWait(45)
            panel.hide()
        window.open_category('apps', QRect(400, 400, 160, 160), shortcut_edge=None)
        assert not panel._dismissal.isVisible()
        window.set_presentation_visible(False)
        wait_for(lambda: all(p in desktop_snapshot()['positions'] for p in paths), 'folder_hide_restores_icons')
        assert not panel._dismissal.isVisible()
        window.set_presentation_visible(True)
        wait_collected(paths[0], 'folder_reshow_collects_icons')
        window.set_desktop_folder_mode(False)
        QTest.qWait(200)
        assert paths[1] in desktop_snapshot()['positions']
        assert paths[0] not in desktop_snapshot()['positions']
        checks.append('shortcut_mode_returns_uncategorized_to_desktop')
        assert window.set_desktop_display('hidden')
        assert not icons_visible()
        window.set_presentation_visible(False)
        assert icons_visible()
        assert window.cfg['desktop_display'] == 'hidden'
        window.set_presentation_visible(True)
        assert not icons_visible()
        checks.append('hide_all_preference_restores_and_reapplies')
        window.shutdown_presentation()
        wait_for(lambda: all(p in desktop_snapshot()['positions'] for p in paths), 'exit_restores_icons')
        after = desktop_snapshot()
        assert after['positions'] == before['positions'], 'desktop item positions changed'
        assert after['flags'] == before['flags'], 'desktop flags changed'
        checks.append('original_shortcut_positions_and_flags_preserved')
    finally:
        window.shutdown_presentation()
        manager.stop()
        window.organizer.stop()
        window.search_bar.shutdown()
        window.category_panel.hide_immediately()
        window.category_panel.model.shutdown()
        window.category_panel.close()
        window.desktop_folders.shutdown()
        window.close()
        app.processEvents()
(OUTPUT / 'native-transition-report.json').write_text(
    json.dumps({'checks': checks, 'errors': errors}, ensure_ascii=False, indent=2), encoding='utf-8')
print('ALL NATIVE CHECKS PASSED', flush=True)
