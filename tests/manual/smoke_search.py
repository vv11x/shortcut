"""检查四边停靠的搜索锚点和真实点击；不操作原生桌面图标或用户配置。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'windows'
import atexit
import copy
from pathlib import Path
import sys
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
original_hook = sys.excepthook
import shortcut_app.application as shortcut
atexit.unregister(shortcut._restore_desktop_icons_safe)
sys.excepthook = original_hook
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest

shortcut.configure_display_scaling()
app = shortcut.QApplication([])
app.setQuitOnLastWindowClosed(False)
cfg = copy.deepcopy(shortcut.DEFAULT_CONFIG)
cfg.update(show_search=True, theme='light', running_dots=False, glass=False)
cfg['organizer']['automatic'] = False
with patch.object(shortcut, 'save_config', return_value=True):
    window = shortcut.Shortcut(cfg, preview=True)
    window.setup_organizer(directories=[])
    try:
        for position in ('left', 'right', 'top', 'bottom'):
            window.set_position(position)
            window.show()
            window.sync_search_geometry()
            QTest.qWait(50)
            bar = window.window_rect(window.bar_rect_f()).toAlignedRect().translated(window.pos())
            anchor = window.search_bar._anchor
            gap = round(8 * window.ui_mult)
            if position in ('left', 'right'):
                assert abs(anchor.center().x() - bar.center().x()) <= 1
                assert bar.top() - anchor.bottom() - 1 == gap
            else:
                assert abs(anchor.center().y() - bar.center().y()) <= 1
                distance = (anchor.left() - bar.right() - 1 if anchor.left() > bar.right()
                            else bar.left() - anchor.right() - 1)
                assert distance == gap, (position, bar, anchor, gap)
            before = window.geometry()
            QTest.mouseClick(window.search_bar.button, Qt.LeftButton)
            QTest.qWait(280)
            assert window.search_bar.expanded, 'search did not stay open: ' + position
            assert window.geometry() == before, 'opening search moved the bar: ' + position
            QTest.keyClick(window.search_bar.edit, Qt.Key_Escape)
            QTest.qWait(220)
            assert not window.search_bar.expanded
            print('PASS', position, 'anchor, click, expansion and Escape;',
                  'physical gap:', gap * window.devicePixelRatioF())
    finally:
        window.shutdown_presentation()
        window.organizer.stop()
        window.search_bar.shutdown()
        window.category_panel.model.shutdown()
        window.category_panel.deleteLater()
        window.desktop_folders.deleteLater()
        window.deleteLater()
        app.processEvents()
