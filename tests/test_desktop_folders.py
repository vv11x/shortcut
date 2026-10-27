"""Desktop box layout, preview and interaction without Explorer or real files."""

import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtCore import QObject, QPoint, QPointF, QRect, Qt, QEvent, QMimeData, QUrl, pyqtSignal
from PyQt5.QtGui import QColor, QDropEvent, QIcon, QImage, QLinearGradient, QMouseEvent, QPainter, QPixmap
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from shortcut_app.desktop_folders import DesktopFoldersWidget, _DesktopHost
from shortcut_app.organizer import normalize_path


class Screen:
    def __init__(self, area=QRect(0, 0, 1280, 800), ratio=1):
        self.area, self.ratio, self.grabs = area, ratio, 0

    def availableGeometry(self):
        return self.area

    def geometry(self):
        return self.area

    def devicePixelRatio(self):
        return self.ratio

    def grabWindow(self, *args):
        self.grabs += 1
        result = QPixmap(self.area.size())
        painter = QPainter(result)
        gradient = QLinearGradient(0, 0, result.width(), result.height())
        gradient.setColorAt(0, QColor('#274366'))
        gradient.setColorAt(.55, QColor('#6478a4'))
        gradient.setColorAt(1, QColor('#be7990'))
        painter.fillRect(result.rect(), gradient)
        painter.end()
        return result


class IconModel(QObject):
    iconReady = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.icons = {}
        self.requests = []
        fallback = QPixmap(40, 40)
        fallback.fill(QColor('#6a97cd'))
        self.fallback = QIcon(fallback)

    def request_icon(self, path):
        self.requests.append(path)
        return self.icons.get(normalize_path(path))


def make_shortcut(screen=None, count=24, category_count=6):
    screen = screen or Screen()
    model = IconModel()
    titles = ['开发工具', '办公文档', '游戏娱乐', '创意设计', '影音媒体', '系统工具']
    categories, groups = [], {}
    for index in range(category_count):
        cid = 'category-%d' % index
        categories.append({'id': cid, 'name': titles[index % len(titles)], 'icon': 'apps'})
        groups[cid] = []
        for item in range(count):
            path = normalize_path('box-test/%s/app-%d.lnk' % (cid, item))
            groups[cid].append({'path': path, 'name': '应用 %d' % item, 'kind': 'apps'})
            pixmap = QPixmap(48, 48)
            pixmap.fill(QColor.fromHsv((index * 52 + item * 23) % 360, 145, 220))
            painter = QPainter(pixmap)
            painter.setPen(Qt.white)
            painter.drawText(pixmap.rect(), Qt.AlignCenter, str(item + 1))
            painter.end()
            model.icons[path] = QIcon(pixmap)
    organizer = SimpleNamespace(state={'categories': categories}, groups=lambda: groups,
                                assign_paths=Mock())
    cfg = {'desktop_folder_mode': True, 'folder_grid_size': '4x4', 'desktop_display': 'all',
           'desktop_folder_positions': {}, 'desktop_folder_cols': 4,
           'desktop_folders_pos': [80, 80], 'glass': True, 'transparency': 40, 'blur_px': 6}
    shortcut = SimpleNamespace(organizer=organizer, category_panel=SimpleNamespace(model=model),
                           target_screen=lambda: screen, is_light=lambda: False,
                           open_category=Mock(), open_preferences_dialog=Mock(),
                           set_desktop_folder_mode=Mock(), _presentation_visible=True)
    return shortcut, cfg


class DesktopFolderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.shortcut, self.cfg = make_shortcut()
        self.widget = DesktopFoldersWidget(self.shortcut, self.cfg)
        self.addCleanup(self.dispose)

    def dispose(self):
        self.widget.shutdown()
        self.widget.deleteLater()
        self.app.processEvents()

    def test_four_by_four_requests_sixteen_preview_icons_per_category(self):
        self.assertEqual(self.widget._grid_side(), 4)
        self.assertEqual(len(self.shortcut.category_panel.model.requests), 6 * 16)
        self.cfg['folder_grid_size'] = '3x3'
        self.shortcut.category_panel.model.requests.clear()
        self.widget.refresh()
        self.assertEqual(len(self.shortcut.category_panel.model.requests), 6 * 9)

    def test_mini_grid_retains_physical_pixels_at_fractional_screen_density(self):
        for ratio in (1.25, 1.5, 2.0):
            with self.subTest(ratio=ratio):
                self.widget._screen.ratio = ratio
                self.widget.refresh()
                grid = self.widget._grids['category-0']
                import math
                self.assertEqual(grid.width(), math.ceil(self.widget.tile_size * ratio))
                self.assertEqual(grid.devicePixelRatioF(), ratio)

    def test_paint_only_uses_cached_icons_and_background(self):
        self.widget._capture_backdrop()
        with patch.object(self.shortcut.category_panel.model, 'request_icon', side_effect=AssertionError('paint queried icons')), \
                patch.object(self.widget._screen, 'grabWindow', side_effect=AssertionError('paint captured screen')):
            rendered = QPixmap(self.widget.size())
            self.widget.render(rendered)
            self.assertFalse(rendered.isNull())

    def test_click_opens_full_category_at_box_anchor(self):
        self.widget.show()
        card = self.widget.folder_rects()[0][0].toAlignedRect()
        QTest.mouseClick(self.widget, Qt.LeftButton, Qt.NoModifier, card.center())
        self.shortcut.open_category.assert_called_once_with('category-0', anchor=card, shortcut_edge=None)

    def test_drag_saves_one_box_without_opening_or_moving_files(self):
        self.widget.show()
        card = self.widget.folder_rects()[0][0].toRect()
        origin = card.center()
        moved = origin + QPoint(27, 23)
        changes = []
        self.widget.positionChanged.connect(lambda: changes.append(True))
        QTest.mousePress(self.widget, Qt.LeftButton, Qt.NoModifier, origin)
        event = QMouseEvent(QEvent.MouseMove, QPointF(moved), QPointF(self.widget.mapToGlobal(moved)),
                            Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(self.widget, event)
        QTest.mouseRelease(self.widget, Qt.LeftButton, Qt.NoModifier, moved)
        self.assertEqual(self.cfg['desktop_folder_positions']['category-0'],
                         [card.x() + 27, card.y() + 23])
        self.assertEqual(changes, [True])
        self.shortcut.open_category.assert_not_called()
        self.shortcut.organizer.assign_paths.assert_not_called()

    def test_press_and_release_feedback_settles_without_recapturing_or_requesting_icons(self):
        from PyQt5.QtCore import QAbstractAnimation
        self.widget.show()
        self.widget._reveal.setCurrentTime(self.widget._reveal.duration())
        card = self.widget.folder_rects()[0][0].toRect()
        with patch.object(self.widget._screen, 'grabWindow', side_effect=AssertionError('animation captured screen')), \
                patch.object(self.shortcut.category_panel.model, 'request_icon', side_effect=AssertionError('animation requested icon')):
            QTest.mousePress(self.widget, Qt.LeftButton, Qt.NoModifier, card.center())
            self.widget._feedback.setCurrentTime(self.widget._feedback.duration())
            self.assertEqual(self.widget._feedback_levels['category-0'][1], 1.0)
            QTest.mouseRelease(self.widget, Qt.LeftButton, Qt.NoModifier, card.center())
            self.widget._feedback.setCurrentTime(self.widget._feedback.duration())
            self.assertEqual(self.widget._feedback_levels['category-0'][1], 0.0)
            self.widget.grab()
        self.assertEqual(self.widget._feedback.state(), QAbstractAnimation.Stopped)
        self.assertEqual(self.widget._reveal.state(), QAbstractAnimation.Stopped)

    def test_positions_are_clamped_and_blank_desktop_is_not_in_mask(self):
        self.cfg['desktop_folder_positions']['category-0'] = [90000, -90000]
        self.widget.refresh()
        for card, tile, label, category in self.widget.folder_rects():
            self.assertTrue(QRect(self.widget.rect()).contains(card.toRect()))
        self.assertFalse(self.widget.mask().contains(QPoint(0, 799)))

    def test_category_hit_uses_virtual_desktop_coordinates(self):
        screen = Screen(QRect(-1280, 0, 1280, 800))
        self.shortcut.target_screen = lambda: screen
        self.widget.refresh()
        self.widget.show()
        card = self.widget.folder_rects()[0][0].toRect()
        point = card.center() + screen.area.topLeft()
        self.assertEqual(self.widget.category_at(point), 'category-0')
        self.assertTrue(self.widget.contains_global(point))

    def test_small_work_area_pages_keep_every_category_accessible(self):
        self.shortcut.target_screen = lambda: Screen(QRect(0, 0, 360, 420))
        self.widget.refresh()
        seen = set()
        for _ in range(self.widget._pages):
            seen.update(card[3]['id'] for card in self.widget.folder_rects())
            self.widget._change_page(1)
        self.assertEqual(seen, {category['id'] for category in self.shortcut.organizer.state['categories']})

    def test_changing_monitor_reflows_outside_positions_instead_of_stacking_boxes(self):
        self.cfg['desktop_folder_positions'] = {'category-%d' % i: [80 + i * 20, 80] for i in range(6)}
        self.shortcut.target_screen = lambda: Screen(QRect(-1280, 0, 1280, 800))
        self.widget.refresh()
        points = {(card.x(), card.y()) for card, _, _, _ in self.widget.folder_rects()}
        self.assertEqual(len(points), 6)

    def test_blur_change_reuses_source_and_changes_actual_snapshot(self):
        self.widget._capture_backdrop()
        before = self.widget._backdrop.width()
        self.cfg['blur_px'] = 20
        self.widget.refresh()
        self.assertLess(self.widget._backdrop.width(), before)
        self.assertEqual(self.widget._screen.grabs, 1)

    def test_transparency_changes_box_pixels(self):
        self.cfg['glass'] = False
        images = []
        for value in (0, 100):
            self.cfg['transparency'] = value
            pixmap = QPixmap(self.widget.size())
            pixmap.fill(Qt.transparent)
            self.widget.render(pixmap)
            images.append(pixmap.toImage())
        self.assertNotEqual(images[0], images[1])

    def test_host_recovery_is_bounded_and_does_not_override_hidden_state(self):
        errors = []
        self.widget.hostError.connect(errors.append)
        with patch.object(self.widget, 'ensure_desktop_host', return_value=False):
            for _ in range(12):
                self.widget._retry_host()
        self.assertEqual(len(errors), 1)
        self.shortcut._presentation_visible = False
        with patch.object(self.widget, 'ensure_desktop_host', return_value=True):
            self.widget._retry_host()
        self.assertFalse(self.widget.isVisible())

    def test_native_rectangle_respects_negative_origin_and_scale(self):
        screen = Screen(QRect(-1920, 0, 1920, 1080), ratio=2)
        self.assertEqual(_DesktopHost.native_rectangle(screen, QRect(-1880, 40, 300, 400)),
                         QRect(-1840, 80, 600, 800))

    def test_external_drop_assigns_original_path_without_moving_it(self):
        self.widget.show()
        card = self.widget.folder_rects()[0][0].toRect()
        mime = QMimeData()
        path = normalize_path('external-original.lnk')
        mime.setUrls([QUrl.fromLocalFile(path)])
        event = QDropEvent(QPointF(card.center()), Qt.CopyAction | Qt.MoveAction, mime,
                           Qt.LeftButton, Qt.NoModifier)
        self.widget.dropEvent(event)
        self.assertTrue(event.isAccepted())
        self.assertEqual(event.dropAction(), Qt.CopyAction)
        self.shortcut.organizer.assign_paths.assert_called_once()
        supplied, category = self.shortcut.organizer.assign_paths.call_args.args
        self.assertEqual([normalize_path(item) for item in supplied], [path])
        self.assertEqual(category, 'category-0')


if __name__ == '__main__':
    unittest.main()
