"""Exercise category activation through real Qt mouse and keyboard events."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QPoint, QPointF, Qt, QObject, pyqtSignal
from PyQt5.QtGui import QIcon, QMouseEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QProxyStyle, QStyle

from shortcut_app.organizer import default_state, normalize_path
from shortcut_app.organizer_ui import CategoryPanel


class _Service(QObject):
    changed = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.state = default_state()
        self.reorders = []
        self.items = [
            {"path": normalize_path("panel-test-%d.txt" % i),
             "name": "panel-test-%d.txt" % i, "kind": "documents"}
            for i in range(3)
        ]

    def groups(self):
        return {"documents": self.items}

    def reorder_paths(self, category_id, paths, before=None):
        self.reorders.append((category_id, paths, before))


class _SingleClickActivationStyle(QProxyStyle):
    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.SH_ItemView_ActivateItemOnSingleClick:
            return 1
        return super().styleHint(hint, option, widget, returnData)


class PanelInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.service = _Service()
        self.launches = []
        self.panel = CategoryPanel(
            self.service, self.launches.append, lambda path: None,
            cfg={"single_click_launch": True},
        )
        # Keep icon fetching out of the test; no real applications are queried.
        for item in self.service.items:
            self.panel.model.icons[item["path"]] = QIcon()
        self.panel.category_id = "documents"
        self.panel._refresh()
        self.panel.resize(500, 350)
        self.panel.show()
        self.app.processEvents()

    def tearDown(self):
        self.panel.hide()
        self.panel.model.shutdown()
        self.panel.deleteLater()
        self.app.processEvents()

    def click(self, row, modifiers=Qt.NoModifier):
        index = self.panel.model.index(row, 0)
        point = self.panel.view.visualRect(index).center()
        QTest.mouseClick(self.panel.view.viewport(), Qt.LeftButton, modifiers, point)

    def test_plain_single_click_opens_once(self):
        self.click(0)
        self.assertEqual(self.launches, [self.service.items[0]["path"]])
        self.assertFalse(self.panel.isVisible())

    def test_ctrl_click_preserves_multi_selection_without_opening(self):
        self.click(0, Qt.ControlModifier)
        self.click(1, Qt.ControlModifier)
        self.assertEqual(self.launches, [])
        self.assertTrue(self.panel.isVisible())
        self.assertEqual({index.row() for index in self.panel.view.selectedIndexes()}, {0, 1})

    def test_shift_click_selects_range_without_opening(self):
        self.click(0, Qt.ControlModifier)
        self.click(2, Qt.ShiftModifier)
        self.assertEqual(self.launches, [])
        self.assertTrue(self.panel.isVisible())
        self.assertEqual({index.row() for index in self.panel.view.selectedIndexes()}, {0, 1, 2})

    def test_double_click_mode_opens_once(self):
        self.panel.set_single_click(False)
        self.click(0)
        self.assertEqual(self.launches, [])
        index = self.panel.model.index(0, 0)
        point = self.panel.view.visualRect(index).center()
        QTest.mouseDClick(self.panel.view.viewport(), Qt.LeftButton, Qt.NoModifier, point)
        self.assertEqual(self.launches, [self.service.items[0]["path"]])

    def test_platform_single_click_activation_cannot_bypass_setting(self):
        self.panel.set_single_click(False)
        self.single_click_style = _SingleClickActivationStyle()
        self.panel.view.setStyle(self.single_click_style)
        native_activations = []
        self.panel.view.activated.connect(lambda index: native_activations.append(index.row()))
        self.click(0)
        self.assertEqual(native_activations, [0])
        self.assertEqual(self.launches, [])
        self.assertTrue(self.panel.isVisible())

    def test_drag_reorders_without_single_click_launch(self):
        viewport = self.panel.view.viewport()
        point = self.panel.view.visualRect(self.panel.model.index(0, 0)).center()
        QTest.mousePress(viewport, Qt.LeftButton, Qt.NoModifier, point)
        moved = point + QPoint(QApplication.startDragDistance() + 10, 0)
        event = QMouseEvent(
            QEvent.MouseMove, QPointF(moved), QPointF(viewport.mapToGlobal(moved)),
            Qt.NoButton, Qt.LeftButton, Qt.NoModifier,
        )
        QApplication.sendEvent(viewport, event)
        self.assertTrue(self.panel.drag_session.active)
        QTest.mouseRelease(viewport, Qt.LeftButton, Qt.NoModifier, moved)
        self.assertFalse(self.panel.drag_session.active)
        self.assertEqual(self.launches, [])
        self.assertTrue(self.panel.isVisible())
        self.assertEqual(self.service.reorders, [
            ("documents", [self.service.items[0]["path"]], self.service.items[1]["path"]),
        ])

    def test_enter_opens_once_in_both_modes(self):
        for single_click in (True, False):
            with self.subTest(single_click=single_click):
                self.panel.show()
                self.panel.set_single_click(single_click)
                self.panel.view.setCurrentIndex(self.panel.model.index(0, 0))
                self.launches.clear()
                QTest.keyClick(self.panel.view, Qt.Key_Return)
                self.assertEqual(self.launches, [self.service.items[0]["path"]])

    def test_reopening_during_dismissal_cancels_old_frame_and_reaches_anchor(self):
        from PyQt5.QtCore import QRect, QAbstractAnimation
        self.panel.open_category('documents', QRect(220, 420, 100, 100))
        self.panel._appear.setCurrentTime(80)
        self.panel.hide()
        self.assertTrue(self.panel._dismissal.isVisible())
        self.assertFalse(self.panel._dismissal.frame.isNull())
        self.panel.open_category('documents', QRect(500, 420, 100, 100))
        self.assertFalse(self.panel._dismissal.isVisible())
        self.assertEqual(self.panel._dismissal.animation.state(), QAbstractAnimation.Stopped)
        self.panel._appear.setCurrentTime(self.panel._appear.duration())
        self.assertEqual(self.panel.pos(), self.panel._target_pos)
        self.assertEqual(self.panel.windowOpacity(), 1.0)
        self.panel.hide_immediately()
        self.assertFalse(self.panel._dismissal.isVisible())


if __name__ == "__main__":
    unittest.main()
