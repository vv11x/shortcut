# -*- coding: utf-8 -*-
"""Shortcut 分类面板与文件操作入口；拖放归类不改变原文件。"""

import os
import math
from collections import OrderedDict

from PyQt5.QtCore import (QAbstractListModel, QEasingCurve, QEvent, QFileInfo, QItemSelectionModel, QModelIndex, QObject,
                          QPoint, QParallelAnimationGroup, QPropertyAnimation, QRect, QRectF, QSize, Qt, QThread,
                          QTimer, QVariantAnimation, pyqtSignal, pyqtSlot)
from PyQt5.QtGui import (QColor, QContextMenuEvent, QIcon, QImage, QKeySequence, QLinearGradient,
                         QPainter, QPainterPath, QPen, QPixmap)
from PyQt5.QtWidgets import (QAbstractItemView, QActionGroup, QApplication,
                             QFileIconProvider, QFrame, QHBoxLayout, QLabel,
                             QListView, QShortcut, QSizePolicy, QStyle, QStyledItemDelegate,
                             QVBoxLayout, QWidget)

from .organizer import normalize_path


from .entry_drag import EntryDrag


UNCATEGORIZED = "__uncategorized__"
_ENTRY_IMAGE_LOADER = None


def set_entry_image_loader(loader):
    """启动时接入高分辨率系统图标读取器；后台回调只返回 QImage。"""
    global _ENTRY_IMAGE_LOADER
    _ENTRY_IMAGE_LOADER = loader


def _entry_label(item):
    """应用和快捷方式隐藏后缀，普通文件及文件夹保留完整名称。"""
    name = item.get("name") or os.path.basename(item["path"])
    if item.get("kind") == "folders" and not item.get("target"):
        return name
    stem, extension = os.path.splitext(name)
    if extension.casefold() in {".lnk", ".url"} or item.get("kind") == "apps":
        return stem or name
    return name


def _entry_menu_position(anchor, menu_size, available, preferred="right"):
    """以图标的可见轮廓为锚点，点击名称或图标时位置一致；使用逻辑像素。"""
    area = available.adjusted(8, 8, -8, -8)
    width, height = menu_size.width(), menu_size.height()
    right, left = anchor.right() + 8, anchor.left() - width - 8
    above, below = anchor.top() - height - 8, anchor.bottom() + 8
    if preferred in ("above", "below"):
        x = anchor.center().x() - width // 2
        y = above if preferred == "above" else below
        if y < area.top():
            y = below
        if y + height - 1 > area.bottom():
            y = above
    else:
        x = left if preferred == "left" else right
        y = anchor.top() - 8
        if x < area.left():
            x = right
        if x + width - 1 > area.right():
            x = left
    x = max(area.left(), min(x, area.right() - menu_size.width() + 1))
    y = max(area.top(), min(y, area.bottom() - menu_size.height() + 1))
    return QPoint(x, y)


from .organizer_artwork import category_pixmap
from .menu_ui import ThemedMenu


def _stylesheet(light):
    fg, muted = ("#202632", "#6b778c") if light else ("#f2f4f8", "#a6b0c2")
    surface = "rgba(255,255,255,248)" if light else "rgba(30,34,44,248)"
    field = "rgba(255,255,255,160)" if light else "rgba(255,255,255,18)"
    border = "rgba(0,0,0,14)" if light else "rgba(255,255,255,24)"
    return """
        QWidget { color: %s; font-family: 'Microsoft YaHei UI', 'Segoe UI'; font-size: 13px; }
        QDialog#categoryManager { background: %s; border: 1px solid %s; border-radius: 16px; }
        QFrame#glassSurface { background: transparent; border: none; }
        QLabel { background: transparent; }
        QLabel[muted='true'] { color: %s; }
        QPushButton { background: %s; border: 1px solid %s; border-radius: 8px; padding: 7px 14px; font-weight: 500; }
        QPushButton:hover { background: rgba(120,140,170,30); border-color: rgba(120,140,170,60); }
        QPushButton:pressed { background: rgba(120,140,170,50); }
        QPushButton:disabled { color: %s; }
        QPushButton[primary='true'] { background: #3b82f6; color: white; border: 1px solid #3b82f6; }
        QPushButton[primary='true']:hover { background: #2563eb; }
        QListView, QListWidget { background: transparent; border: none; outline: none; }
        QListWidget::item { padding: 9px 12px; border-radius: 8px; }
        QListWidget::item:selected { background: rgba(59,130,246,32); color: %s; }
        QLineEdit, QComboBox { background: %s; border: 1px solid %s; border-radius: 7px; padding: 6px 8px; min-height: 20px; }
        QComboBox QAbstractItemView { background: %s; selection-background-color: #3b82f6; }
        QScrollArea { border: none; background: transparent; }
        QScrollBar:vertical { background: transparent; width: 6px; margin: 2px; }
        QScrollBar::handle:vertical { background: rgba(140,155,175,90); border-radius: 3px; min-height: 30px; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
    """ % (fg, surface, border, muted, field, border, muted, fg, field, border,
           surface)


class _IconWorker(QObject):
    ready = pyqtSignal(str, QIcon)
    imageReady = pyqtSignal(str, QImage)

    def __init__(self):
        super().__init__()
        self.provider = None

    @pyqtSlot(str)
    def fetch(self, path):
        if QThread.currentThread().isInterruptionRequested():
            return
        loader = _ENTRY_IMAGE_LOADER
        if loader is not None:
            try:
                image = loader(path)
                if isinstance(image, QImage) and not image.isNull():
                    self.imageReady.emit(path, image)
                    return
            except Exception:
                # 高分辨率提取失败时仍保留系统图标入口。
                pass
        if self.provider is None:
            self.provider = QFileIconProvider()
        self.ready.emit(path, self.provider.icon(QFileInfo(path)))


class _EntryModel(QAbstractListModel):
    iconRequested = pyqtSignal(str)
    iconReady = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = []
        self.row_by_path = {}
        self.manual = set()
        self.icons = OrderedDict()
        self.pending = set()
        self.thread = QThread(self)
        self.worker = _IconWorker()
        self.worker.moveToThread(self.thread)
        self.thread.finished.connect(self.worker.deleteLater)
        self.iconRequested.connect(self.worker.fetch)
        self.worker.ready.connect(self._icon_ready)
        self.worker.imageReady.connect(self._image_ready)
        self.thread.start()
        QApplication.instance().aboutToQuit.connect(self.shutdown)
        self.fallback = QApplication.style().standardIcon(QStyle.SP_FileIcon)

    def shutdown(self):
        if self.thread.isRunning():
            self.thread.requestInterruption()
            self.thread.quit()
            self.thread.wait()

    def replace(self, entries, manual):
        entries, manual = list(entries), set(manual)
        if self.items == entries and self.manual == manual:
            return
        self.beginResetModel()
        self.items = entries
        self.row_by_path = {normalize_path(entry["path"]): row for row, entry in enumerate(self.items)}
        self.manual = manual
        self.endResetModel()

    def request_icon(self, path):
        """面板和 Shortcut 预览共享队列，返回 None 表示后台仍在获取。"""
        path = normalize_path(path)
        if path in self.icons:
            self.icons.move_to_end(path)
            return self.icons[path]
        if path not in self.pending:
            self.pending.add(path)
            self.iconRequested.emit(path)
        return None

    def rowCount(self, parent=None):
        return len(self.items) if parent is None or not parent.isValid() else 0

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self.items):
            return None
        item = self.items[index.row()]
        path = item["path"]
        if role == Qt.DisplayRole:
            return _entry_label(item)
        if role == Qt.ToolTipRole:
            marker = "手动指定分类\n" if normalize_path(path) in self.manual else ""
            return marker + item.get("name", os.path.basename(path)) + "\n" + path
        if role == Qt.UserRole:
            return item
        if role == Qt.UserRole + 1:
            return normalize_path(path) in self.manual
        if role == Qt.DecorationRole:
            return self.request_icon(path) or self.fallback
        return None

    @pyqtSlot(str, QIcon)
    def _icon_ready(self, path, icon):
        self.pending.discard(path)
        self.icons[path] = icon
        while len(self.icons) > 160:
            self.icons.popitem(last=False)
        row = self.row_by_path.get(path)
        if row is not None:
            ix = self.index(row, 0)
            self.dataChanged.emit(ix, ix, [Qt.DecorationRole])
        self.iconReady.emit(path)

    @pyqtSlot(str, QImage)
    def _image_ready(self, path, image):
        self._icon_ready(path, QIcon(QPixmap.fromImage(image)))

    def flags(self, index):
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled


class _EntryDelegate(QStyledItemDelegate):
    def __init__(self, light=True, parent=None):
        super().__init__(parent)
        self.light = light
        self.list_mode = False
        self.menu_active = False

    def sizeHint(self, option, index):
        if self.list_mode:
            return QSize(120, 36)
        return QSize(116, 126)

    def icon_rect(self, cell):
        if self.list_mode:
            return QRect(cell.left() + 12, cell.center().y() - 11, 22, 22)
        box = cell.adjusted(4, 3, -4, -3)
        return QRect(box.center().x() - 28, box.top() + 6, 56, 56)

    def paint(self, painter, option, index):
        if self.list_mode:
            self._paint_list(painter, option, index)
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        box = option.rect.adjusted(4, 3, -4, -3)
        icon_rect = self.icon_rect(option.rect)

        view = self.parent()
        pressed_row = getattr(view, '_pressed_row', -1) if view else -1
        is_pressed = (index.row() == pressed_row)
        selected = bool(option.state & QStyle.State_Selected)
        is_hovered = (not self.menu_active and bool(option.state & QStyle.State_MouseOver))

        card_rect = QRectF(icon_rect).adjusted(-7, -6, 7, 6)
        transformed = False
        if is_pressed or selected or is_hovered:
            painter.save()
            transformed = True
            if is_pressed:
                # 按下态：物理下沉微缩 (scale ~0.93)
                center = card_rect.center()
                painter.translate(center)
                painter.scale(0.93, 0.93)
                painter.translate(-center)

                # 按压态毛玻璃底板与微光边框
                press_bg = QColor(255, 255, 255, 75 if self.light else 45)
                press_border = QColor(100, 150, 245, 170 if self.light else 190)
                painter.setPen(QPen(press_border, 1.2))
                painter.setBrush(press_bg)
                painter.drawRoundedRect(card_rect, 13, 13)
            elif selected:
                # 选中态：明确的 3D 悬浮状态（向上浮起 3px + 悬浮立体阴影 + 荧光边框）
                painter.translate(0, -3.0)
                # 悬浮立体柔和阴影
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(0, 0, 0, 48 if self.light else 80))
                painter.drawRoundedRect(card_rect.adjusted(0, 5, 0, 5), 14, 14)
                # 高亮悬浮底板
                sel_bg = QColor(100, 160, 255, 65 if self.light else 85)
                sel_border = QColor(100, 170, 255, 220 if self.light else 240)
                painter.setPen(QPen(sel_border, 1.5))
                painter.setBrush(sel_bg)
                painter.drawRoundedRect(card_rect, 13, 13)
            elif is_hovered:
                # 悬停态：微浮起 2px + 纯净通透毛玻璃卡片（立体微投影）
                painter.translate(0, -2.0)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(0, 0, 0, 32 if self.light else 60))
                painter.drawRoundedRect(card_rect.adjusted(0, 3.5, 0, 3.5), 14, 14)
                hov_bg = QColor(255, 255, 255, 75 if self.light else 35)
                hov_border = QColor(255, 255, 255, 160 if self.light else 85)
                painter.setPen(QPen(hov_border, 1.0))
                painter.setBrush(hov_bg)
                painter.drawRoundedRect(card_rect, 13, 13)

        icon = index.data(Qt.DecorationRole)
        if icon:
            icon.paint(painter, icon_rect)
        if transformed:
            painter.restore()

        painter.setPen(QColor("#253041" if self.light else "#f2f4f9"))
        name = str(index.data(Qt.DisplayRole))
        metrics = painter.fontMetrics()
        width = box.width() - 10
        # 最多两行，完整名称和路径留在悬停提示中。
        split = 0
        for i in range(1, len(name) + 1):
            if metrics.horizontalAdvance(name[:i]) > width:
                break
            split = i
        if split == len(name):
            lines = [name]
        else:
            # 括号和空格优先作为换行边界，避免把英文别名拆成零碎尾巴。
            boundary = next((i for i in range(split, 0, -1)
                             if name[i].isspace() or name[i] in "(（[【"), split)
            if boundary >= max(1, split // 2) and metrics.horizontalAdvance(name[boundary:].lstrip()) <= width:
                split = boundary
            lines = [name[:max(split, 1)].rstrip(),
                     metrics.elidedText(name[max(split, 1):].lstrip(), Qt.ElideMiddle, width)]
        for offset, line in enumerate(lines):
            painter.drawText(QRect(box.left() + 5, box.top() + 69 + offset * 17,
                                   width, 18), Qt.AlignHCenter | Qt.AlignTop, line)
        painter.restore()

    def _paint_list(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        box = option.rect.adjusted(2, 2, -2, -2)

        view = self.parent()
        pressed_row = getattr(view, '_pressed_row', -1) if view else -1
        is_pressed = (index.row() == pressed_row)
        selected = bool(option.state & QStyle.State_Selected)
        is_hovered = (not self.menu_active and bool(option.state & QStyle.State_MouseOver))

        card_rect = QRectF(box)
        transformed = False
        if is_pressed or selected or is_hovered:
            painter.save()
            transformed = True
            if is_pressed:
                center = card_rect.center()
                painter.translate(center)
                painter.scale(0.97, 0.95)
                painter.translate(-center)
                painter.setPen(QPen(QColor(100, 150, 245, 170 if self.light else 190), 1.2))
                painter.setBrush(QColor(255, 255, 255, 75 if self.light else 45))
                painter.drawRoundedRect(card_rect, 8, 8)
            elif selected:
                painter.translate(0, -1.5)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(0, 0, 0, 40 if self.light else 65))
                painter.drawRoundedRect(card_rect.adjusted(0, 2.5, 0, 2.5), 8, 8)
                painter.setPen(QPen(QColor(100, 160, 255, 210 if self.light else 230), 1.2))
                painter.setBrush(QColor(100, 150, 245, 60 if self.light else 80))
                painter.drawRoundedRect(card_rect, 8, 8)
            elif is_hovered:
                painter.translate(0, -1.0)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(0, 0, 0, 24 if self.light else 45))
                painter.drawRoundedRect(card_rect.adjusted(0, 2, 0, 2), 8, 8)
                painter.setPen(QPen(QColor(255, 255, 255, 150 if self.light else 80), 1.0))
                painter.setBrush(QColor(255, 255, 255, 75 if self.light else 35))
                painter.drawRoundedRect(card_rect, 8, 8)

        icon = index.data(Qt.DecorationRole)
        if icon:
            icon.paint(painter, self.icon_rect(option.rect))
        if transformed:
            painter.restore()

        painter.setPen(QColor("#253041" if self.light else "#f2f4f9"))
        text_box = option.rect.adjusted(44, 0, -12, 0)
        name = painter.fontMetrics().elidedText(str(index.data(Qt.DisplayRole)), Qt.ElideMiddle, text_box.width())
        painter.drawText(text_box, Qt.AlignLeft | Qt.AlignVCenter, name)
        painter.restore()


class _EntryView(QListView):
    pathsDropped = pyqtSignal(list)
    dragRequested = pyqtSignal(list, QPixmap, QPoint)
    itemContextMenuRequested = pyqtSignal(QPoint)
    openRequested = pyqtSignal(QModelIndex)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.can_drop = True
        self._pressed_row = -1
        self._press_position = None
        self._insert_row = None
        self._drag_position = QPoint()
        self._scroll_step = 0
        self._scroll_drag_timer = QTimer(self)
        self._scroll_drag_timer.setInterval(60)
        self._scroll_drag_timer.timeout.connect(self._scroll_drag)
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setGridSize(QSize(116, 126))
        self.setUniformItemSizes(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        # Qt 自带拖动会向桌面复制文件；内部虚拟拖动由鼠标释放位置提交。
        self.setDragEnabled(False)
        self.setDefaultDropAction(Qt.CopyAction)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)

    def set_display_mode(self, list_mode):
        self.setViewMode(QListView.ListMode if list_mode else QListView.IconMode)
        self.setFlow(QListView.TopToBottom if list_mode else QListView.LeftToRight)
        self.setWrapping(not list_mode)
        self.setMovement(QListView.Static)
        self.setGridSize(QSize() if list_mode else QSize(116, 126))

    def contextMenuEvent(self, event):
        if event.reason() == QContextMenuEvent.Keyboard:
            index = self.currentIndex()
            if index.isValid():
                self.scrollTo(index)
                pos = self.visualRect(index).intersected(self.viewport().rect()).center()
            else:
                pos = QPoint(-1, -1)
        else:
            # Windows 弹出窗口的菜单事件可能带着顶层面板坐标；始终从屏幕坐标换算到内容区。
            pos = self.viewport().mapFromGlobal(event.globalPos())
        self.itemContextMenuRequested.emit(pos)
        event.accept()

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        index = self.indexAt(self.viewport().mapFromGlobal(event.globalPos()))
        if event.button() == Qt.LeftButton and index.isValid():
            self._pressed_row = index.row()
            self._press_position = QPoint(event.globalPos())
            self.viewport().update()
        else:
            self._pressed_row = -1
            self._press_position = None

    def mouseMoveEvent(self, event):
        if (self._press_position is not None and event.buttons() & Qt.LeftButton
                and (event.globalPos() - self._press_position).manhattanLength() >= QApplication.startDragDistance()):
            self._press_position = None
            if self._pressed_row >= 0:
                self._pressed_row = -1
                self.viewport().update()
            self._drag_position = QPoint(event.globalPos())
            self.startDrag(Qt.CopyAction)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._press_position = None
        pressed_row = getattr(self, '_pressed_row', -1)
        if pressed_row >= 0:
            self._pressed_row = -1
            self.viewport().update()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            index = self.currentIndex()
            if index.isValid():
                self.openRequested.emit(index)
                event.accept()
                return
        super().keyPressEvent(event)

    def leaveEvent(self, event):
        if getattr(self, '_pressed_row', -1) >= 0:
            self._pressed_row = -1
            self.viewport().update()
        super().leaveEvent(event)

    def insertion_row(self, position):
        count = self.model().rowCount()
        if not count:
            return 0
        index = self.indexAt(position)
        if not index.isValid():
            first = self.visualRect(self.model().index(0, 0))
            if position.y() < first.top():
                return 0
            last = self.visualRect(self.model().index(count - 1, 0))
            if position.y() > last.bottom():
                return count
            # 在行内微小间隙查找最近的项目，防止突跳末尾
            closest_row = 0
            min_dist = float("inf")
            for r in range(count):
                rect = self.visualRect(self.model().index(r, 0))
                dist = (rect.center() - position).manhattanLength()
                if dist < min_dist:
                    min_dist = dist
                    closest_row = r
            cell = self.visualRect(self.model().index(closest_row, 0))
            after = position.y() > cell.center().y() if self.viewMode() == QListView.ListMode else position.x() > cell.center().x()
            return closest_row + int(after)
        cell = self.visualRect(index)
        after = position.y() > cell.center().y() if self.viewMode() == QListView.ListMode else position.x() > cell.center().x()
        return index.row() + int(after)

    def set_insertion(self, row):
        if row is None:
            self._scroll_drag_timer.stop()
            self._scroll_step = 0
        if row != self._insert_row:
            self._insert_row = row
            self.viewport().update()

    def update_drag_position(self, position):
        self._drag_position = QPoint(position)
        self.set_insertion(self.insertion_row(position))
        bar = self.verticalScrollBar()
        self._scroll_step = -1 if position.y() < 26 else 1 if position.y() > self.viewport().height() - 26 else 0
        if (self._scroll_step < 0 and bar.value() > bar.minimum()
                or self._scroll_step > 0 and bar.value() < bar.maximum()):
            if not self._scroll_drag_timer.isActive():
                self._scroll_drag_timer.start()
        else:
            self._scroll_drag_timer.stop()

    def _scroll_drag(self):
        bar = self.verticalScrollBar()
        old = bar.value()
        bar.setValue(old + self._scroll_step * 30)
        self.set_insertion(self.insertion_row(self._drag_position))
        if bar.value() == old:
            self._scroll_drag_timer.stop()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._insert_row is None or not self.model().rowCount():
            return
        count = self.model().rowCount()
        cell = self.visualRect(self.model().index(min(self._insert_row, count - 1), 0))
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#87adf2"), 2.5, Qt.SolidLine, Qt.RoundCap))
        if self.viewMode() == QListView.ListMode:
            y = cell.bottom() if self._insert_row == count else cell.top()
            painter.drawLine(8, y, self.viewport().width() - 8, y)
        else:
            x = cell.right() if self._insert_row == count else cell.left()
            painter.drawLine(x, cell.top() + 13, x, cell.bottom() - 13)

    def dragEnterEvent(self, event):
        if self.can_drop and event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        if self.can_drop and event.mimeData().hasUrls():
            paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
            if paths:
                self.pathsDropped.emit(paths)
                event.setDropAction(Qt.CopyAction)
                event.accept()
                return
        event.ignore()

    def startDrag(self, actions):
        indexes = sorted(self.selectedIndexes(), key=lambda index: index.row())
        if not indexes:
            return
        icon = indexes[0].data(Qt.DecorationRole)
        self.dragRequested.emit([ix.data(Qt.UserRole)["path"] for ix in indexes],
                                icon.pixmap(40, 40) if icon else QPixmap(), self._drag_position)


class _ElidedLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.full_text = ""
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def setText(self, text):
        self.full_text = str(text)
        self.setToolTip(self.full_text)
        self._elide()

    def _elide(self):
        QLabel.setText(self, self.fontMetrics().elidedText(self.full_text, Qt.ElideMiddle, self.width()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()


class _GlassSurface(QFrame):
    """打开前捕获一次背景，绘制只取缓存，不在空闲时抓屏。"""
    def __init__(self, light=True, parent=None, cfg=None):
        super().__init__(parent)
        self.light = light
        self.cfg = cfg if cfg is not None else {}
        self.snapshot = QPixmap()
        self.screen_geometry = QRect()
        self.capture_count = 0

    def capture(self, screen):
        if not self.cfg.get("glass", True):
            self.snapshot = QPixmap()
            self.update()
            return
        captured = screen.grabWindow(0)
        self.screen_geometry = screen.geometry()
        if not captured.isNull():
            divisor = max(2, min(50, int(self.cfg.get("blur_px", 6))))
            self.snapshot = captured.scaled(max(1, self.screen_geometry.width() // divisor),
                                            max(1, self.screen_geometry.height() // divisor),
                                            Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            self.snapshot.setDevicePixelRatio(1)
            self.capture_count += 1
        else:
            self.snapshot = QPixmap()
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        transparency = max(0, min(100, int(self.cfg.get("transparency", 40))))
        p.setOpacity(1.0 - .65 * transparency / 100.0)
        rect = QRectF(self.rect()).adjusted(.6, .6, -.6, -.6)
        path = QPainterPath()
        path.addRoundedRect(rect, 22, 22)
        p.setClipPath(path)
        if self.cfg.get("glass", True) and not self.snapshot.isNull():
            origin = self.mapToGlobal(QPoint(0, 0))
            sx = self.snapshot.width() / self.screen_geometry.width()
            sy = self.snapshot.height() / self.screen_geometry.height()
            source = QRectF((origin.x() - self.screen_geometry.x()) * sx,
                            (origin.y() - self.screen_geometry.y()) * sy,
                            self.width() * sx, self.height() * sy)
            p.drawPixmap(QRectF(self.rect()), self.snapshot, source)
            tint = QColor(255, 255, 255, 130) if self.light else QColor(16, 18, 24, 150)
        else:
            tint = QColor(250, 252, 255, 225) if self.light else QColor(24, 26, 34, 230)
        p.fillPath(path, tint)
        shine = QLinearGradient(0, 0, 0, self.height())
        shine.setColorAt(0, QColor(255, 255, 255, 26 if self.light else 14))
        shine.setColorAt(.35, QColor(255, 255, 255, 0))
        shine.setColorAt(1, QColor(255, 255, 255, 8 if self.light else 4))
        p.fillPath(path, shine)
        p.setClipping(False)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 135 if self.light else 42), 1))
        p.drawRoundedRect(rect, 22, 22)


class _PanelDismissal(QWidget):
    """Popup 被 Qt 收起后，用不接收输入的快照完成返回动画。"""
    def __init__(self, owner):
        super().__init__(owner, Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint
                         | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.frame = QPixmap()
        self.progress = 0.0
        self.opacity = 1.0
        self.offset = QPoint()
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(150)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.setEasingCurve(QEasingCurve.InCubic)
        self.animation.valueChanged.connect(self._step)
        self.animation.finished.connect(self.stop)

    def play(self, frame, geometry, offset, opacity):
        self.stop()
        self.frame, self.offset = frame, offset
        self.opacity = opacity
        self.progress = 0.0
        self.setGeometry(geometry)
        self.show()
        self.animation.start()

    def _step(self, progress):
        self.progress = progress
        self.update()

    def stop(self):
        self.animation.stop()
        self.hide()
        self.frame = QPixmap()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setOpacity(self.opacity * (1 - self.progress))
        inset = self.progress * .025
        rect = QRectF(self.rect()).adjusted(self.width() * inset, self.height() * inset,
                                           -self.width() * inset, -self.height() * inset)
        rect.translate(self.offset.x() * self.progress, self.offset.y() * self.progress)
        painter.drawPixmap(rect, self.frame, QRectF(self.frame.rect()))


class CategoryPanel(QWidget):
    def __init__(self, service, launch_callback, pin_callback, light=True, parent=None, menu_theme=None, file_actions=None,
                 drag_session=None, drag_target=None, cfg=None):
        # Windows 的原生弹窗阴影按矩形窗口绘制，会露在透明圆角外侧。
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setWindowTitle("shortcut 分类面板")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.service = service
        self.launch_callback = launch_callback
        self.pin_callback = pin_callback
        self.file_actions = file_actions
        self.drag_session = drag_session or EntryDrag(self)
        self.drag_target = drag_target
        self.light = light
        self.menu_theme = menu_theme
        self.cfg = cfg
        self.category_id = None
        self._anchor = QRect()
        self._prefer_above = True
        self._shortcut_edge = None
        self._appear = QParallelAnimationGroup(self)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._slide = QPropertyAnimation(self, b"pos", self)
        for animation in (self._fade, self._slide):
            animation.setDuration(220)
            animation.setEasingCurve(QEasingCurve.OutCubic)
            self._appear.addAnimation(animation)
        self._dismissal = _PanelDismissal(self)
        self._animate_hide = True
        self._target_pos = QPoint()
        self.on_hide_callback = None
        self.setAcceptDrops(True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.surface = _GlassSurface(light, cfg=cfg)
        self.surface.setObjectName("glassSurface")
        outer.addWidget(self.surface)
        layout = QVBoxLayout(self.surface)
        layout.setContentsMargins(19, 15, 19, 13)
        layout.setSpacing(9)
        top = QHBoxLayout()
        self.badge = QLabel()
        self.badge.setFixedSize(32, 32)
        top.addWidget(self.badge)
        self.title = _ElidedLabel()
        self.title.setStyleSheet("font-size: 16px; font-weight: 600;")
        top.addWidget(self.title, 1)
        self.count = QLabel()
        self.count.setProperty("muted", True)
        top.addWidget(self.count)
        layout.addLayout(top)
        self.hint = QLabel("拖入应用或文件，手动归类 · 原文件位置不变")
        self.hint.setProperty("muted", True)
        self.hint.setWordWrap(True)
        self.hint.hide()
        self.model = _EntryModel(self)
        self.view = _EntryView()
        self.delegate = _EntryDelegate(light, self.view)
        self.view.setItemDelegate(self.delegate)
        self.view.setModel(self.model)
        self.view.itemContextMenuRequested.connect(self._context_menu)
        self.view.doubleClicked.connect(self._on_item_double_clicked)
        self.view.clicked.connect(self._on_item_clicked)
        # activated 的鼠标触发方式取决于系统样式；键盘打开使用独立信号，避免双击启动两次。
        self.view.openRequested.connect(self._launch_index)
        self.view.pathsDropped.connect(self._assign)
        self.view.dragRequested.connect(self._start_entry_drag)
        self._file_shortcuts = []
        if self.file_actions:
            for key, command in ((QKeySequence.Copy, "copy"), (QKeySequence.Cut, "cut"), (QKeySequence.Delete, "delete")):
                shortcut = QShortcut(QKeySequence(key), self.view)
                shortcut.setContext(Qt.WidgetWithChildrenShortcut)
                shortcut.setAutoRepeat(False)
                shortcut.activated.connect(lambda value=command: self._file_command(value))
                self._file_shortcuts.append(shortcut)
        layout.addWidget(self.view, 1)
        self.empty = QLabel("拖入应用或文件，创建你的分类\n也可以在管理分类中添加筛选规则\n原文件位置保持不变")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setProperty("muted", True)
        self.empty.setMinimumHeight(92)
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty)
        self.status = QLabel()
        self.status.setProperty("muted", True)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.status.hide()
        self.view.setToolTip("双击打开；拖动调整顺序，拖出移除分类入口；原文件位置不变，Esc 取消拖动")
        self.setStyleSheet(_stylesheet(light))
        service.changed.connect(self._changed)
        service.error.connect(self._error)

    def open_category(self, category_id, anchor_rect, prefer_above=True, light=None, shortcut_edge=None):
        was_visible = self.isVisible()
        previous_pos, previous_opacity = self.pos(), self.windowOpacity()
        self._dismissal.stop()
        self._appear.stop()
        self.category_id = category_id
        self._anchor = QRect(anchor_rect)
        self._prefer_above = prefer_above
        self._shortcut_edge = shortcut_edge
        if light is not None and light != self.light:
            self.light = light
            self.delegate.light = light
            self.surface.light = light
            self.surface.update()
            self.setStyleSheet(_stylesheet(light))
        self.status.hide()
        if not self._refresh():
            return
        self._place()
        self._target_pos = self.pos()
        self._slide.setStartValue(previous_pos if was_visible else self._target_pos + self._anchor_offset())
        self._slide.setEndValue(self._target_pos)
        self._fade.setStartValue(previous_opacity if was_visible else 0.0)
        self._fade.setEndValue(1.0)
        if not was_visible:
            screen = QApplication.screenAt(self._anchor.center()) or QApplication.primaryScreen()
            self.surface.capture(screen)
            self.setWindowOpacity(0)
        self.move(self._slide.startValue())
        self.show()
        self.raise_()
        self.view.setFocus()
        self._appear.start()

    def _anchor_offset(self):
        delta = self._anchor.center() - QRect(self._target_pos, self.size()).center()
        length = max(1, abs(delta.x()), abs(delta.y()))
        return QPoint(round(delta.x() * 14 / length), round(delta.y() * 14 / length))

    def hide_immediately(self):
        self._dismissal.stop()
        self._animate_hide = False
        try:
            self.hide()
        finally:
            self._animate_hide = True

    def apply_appearance(self, light):
        self.light = bool(light)
        self.delegate.light = self.light
        self.surface.light = self.light
        self.setStyleSheet(_stylesheet(self.light))
        self.surface.update()
        self.view.viewport().update()
        if self.isVisible():
            self._refresh()

    def hideEvent(self, event):
        if self.drag_session.active and self.drag_session.source is self.view.viewport():
            self.drag_session.cancel()
        if self._animate_hide:
            self._dismissal.play(self.grab(), self.geometry(), self._anchor_offset(), self.windowOpacity())
        self._appear.stop()
        self.setWindowOpacity(1)
        if self.on_hide_callback:
            self.on_hide_callback()
        super().hideEvent(event)

    def wheelEvent(self, event):
        if hasattr(self, "view") and self.view and self.view.isVisible():
            QApplication.sendEvent(self.view.viewport(), event)
            event.accept()
        else:
            super().wheelEvent(event)

    def _start_entry_drag(self, paths, icon, position):
        category_id = self.category_id

        def move(point):
            local = self.view.viewport().mapFromGlobal(point)
            if self.view.viewport().rect().contains(local):
                self.view.update_drag_position(local)
                if self.drag_target:
                    self.drag_target(paths, point, "clear")
                return "放开调整顺序 · Esc 取消"
            self.view.set_insertion(None)
            if self.rect().contains(self.mapFromGlobal(point)):
                return "拖到项目之间调整顺序"
            return self.drag_target(paths, point, "hover") if self.drag_target else "放开移除分类入口 · 原文件保留"

        def cancel():
            self.view.set_insertion(None)
            if self.drag_target:
                self.drag_target(paths, QPoint(), "clear")

        def drop(point):
            local = self.view.viewport().mapFromGlobal(point)
            row = self.view.insertion_row(local)
            cancel()
            if self.view.viewport().rect().contains(local):
                selected = {normalize_path(path) for path in paths}
                before = next((entry["path"] for entry in self.model.items[row:]
                               if normalize_path(entry["path"]) not in selected), None)
                self.service.reorder_paths(category_id, paths, before)
                selection = self.view.selectionModel()
                selection.clearSelection()
                for path in paths:
                    row = self.model.row_by_path.get(normalize_path(path))
                    if row is not None:
                        selection.select(self.model.index(row, 0), QItemSelectionModel.Select)
                return
            if self.rect().contains(self.mapFromGlobal(point)):
                return
            if self.drag_target:
                self.drag_target(paths, point, "drop")
            else:
                self.service.exclude_paths(paths)
            self.hide()

        self.drag_session.begin(self.view.viewport(), paths, icon, position, move, drop, cancel)

    def _changed(self):
        if self.isVisible():
            if self._refresh():
                self._place()

    def _refresh(self):
        category = next((c for c in self.service.state.get("categories", [])
                         if c["id"] == self.category_id), None)
        if self.category_id == UNCATEGORIZED:
            category = {"id": UNCATEGORIZED, "name": "未分类", "icon": "other"}
        if category is None:
            self.hide()
            return False
        mode_changed = self._apply_view_mode()
        self.title.setText(category["name"])
        custom_path = (self.cfg or {}).get("category_custom_icons", {}).get(self.category_id)
        custom = QPixmap(custom_path) if custom_path else QPixmap()
        ratio = self.devicePixelRatioF()
        pixels = math.ceil(32 * ratio)
        badge = (custom.scaled(pixels, pixels, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                 if not custom.isNull() else
                 category_pixmap(category.get("icon", "folders"), pixels, self.light))
        badge.setDevicePixelRatio(ratio)
        self.badge.setPixmap(badge)
        entries = self.service.groups().get(self.category_id, [])
        manual = {path for path, cid in self.service.state.get("manual", {}).items()
                  if cid == self.category_id}
        scroll_position = 0 if mode_changed else self.view.verticalScrollBar().value()
        self.model.replace(entries, manual)
        self.view.verticalScrollBar().setValue(scroll_position)
        self.count.setText("%d 项" % len(entries))
        self.view.setVisible(bool(entries))
        self.empty.setVisible(not entries)
        self.view.can_drop = self.category_id != UNCATEGORIZED
        self.hint.setText("这些项目尚未匹配分类，可修改规则或恢复自动分类"
                          if self.category_id == UNCATEGORIZED else
                          "拖入应用或文件，手动归类 · 原文件位置不变")
        self.surface.setToolTip(self.hint.text())
        return True

    def _apply_view_mode(self):
        list_mode = self.service.state.get("view_modes", {}).get(self.category_id, "icons") == "list"
        if self.delegate.list_mode == list_mode:
            return False
        self.delegate.list_mode = list_mode
        self.view.set_display_mode(list_mode)
        return True

    def _set_view_mode(self, mode):
        current = self.view.currentIndex()
        self.service.set_view_mode(self.category_id, mode)
        self._apply_view_mode()
        self._place()
        self.view.doItemsLayout()
        if current.isValid():
            self.view.scrollTo(current, QAbstractItemView.PositionAtCenter)
        self.view.viewport().update()

    def _view_actions(self, menu):
        submenu = menu.addMenu("查看")
        submenu.menuAction().setIcon(menu.glyph("list" if self.delegate.list_mode else "grid"))
        group = QActionGroup(submenu)
        group.setExclusive(True)
        actions = {}
        for name, mode in (("大图标", "icons"), ("列表", "list")):
            action = submenu.addAction(name)
            action.setCheckable(True)
            action.setChecked(self.delegate.list_mode == (mode == "list"))
            group.addAction(action)
            actions[action] = mode
        return actions

    def _new_menu(self):
        colors = self.menu_theme() if self.menu_theme else None
        return ThemedMenu(self, light=colors.get("light", self.light) if colors else self.light, colors=colors)

    def _exec_menu(self, menu, position):
        # 菜单接管鼠标后只保留选中高亮，避免另一项残留的悬停看起来像错选。
        self.delegate.menu_active = True
        QApplication.sendEvent(self.view.viewport(), QEvent(QEvent.Leave))
        self.view.viewport().update()
        try:
            return menu.exec_(position)
        finally:
            self.delegate.menu_active = False
            self.view.viewport().update()

    def _display_menu(self, global_pos):
        menu = self._new_menu()
        actions = self._view_actions(menu)
        screen = QApplication.screenAt(global_pos) or QApplication.primaryScreen()
        menu.ensurePolished()
        chosen = self._exec_menu(menu, _entry_menu_position(QRect(global_pos, QSize(1, 1)), menu.sizeHint(), screen.availableGeometry()))
        menu.deleteLater()
        if chosen in actions:
            self._set_view_mode(actions[chosen])

    def contextMenuEvent(self, event):
        self._display_menu(event.globalPos())

    def _place(self):
        screen = QApplication.screenAt(self._anchor.center()) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        count = len(self.model.items)
        status_height = 35 if not self.status.isHidden() else 0
        if self.delegate.list_mode:
            columns, row_height, base_height = 1, 36, 69
            width = min(480, area.width() - 24)
            capacity = max(1, min(14, (area.height() - 24 - base_height - status_height) // row_height))
        else:
            columns, row_height, base_height = max(1, min(5, count)), 126, 78
            width = min(max(316, 116 * columns + 50) if count else 360, area.width() - 24)
            columns = max(1, min(columns, (width - 38) // 116))
            capacity = max(1, min(4, (area.height() - 24 - base_height - status_height) // row_height))
        # 仅预留标题、边距和列表间隔，不保留工具栏空位。
        rows = max(1, min(capacity, (count + columns - 1) // columns))
        height = base_height + rows * row_height if count else 178
        height += status_height
        height = min(height, area.height() - 24)
        if self._shortcut_edge in ("left", "right"):
            # 侧边 Shortcut 向屏幕内部展开；空间不足时换侧，仍以当前屏幕为边界。
            left, right = self._anchor.left() - width - 12, self._anchor.right() + 12
            x = right if self._shortcut_edge == "left" else left
            if x < area.left() + 8:
                x = right
            if x + width > area.right() - 8:
                x = left
            y = self._anchor.center().y() - height // 2
        else:
            x = self._anchor.center().x() - width // 2
            above, below = self._anchor.top() - height - 12, self._anchor.bottom() + 12
            y = above if self._prefer_above else below
            if y < area.top() + 8:
                y = below
            if y + height > area.bottom() - 8:
                y = above
        x = max(area.left() + 8, min(x, area.right() - width - 8))
        y = max(area.top() + 8, min(y, area.bottom() - height - 8))
        self.setGeometry(x, y, width, height)
        scrollbar = 8 if count > rows * columns else 0
        # 明确预留滚动条，避免滚动条出现后挤掉一列并反复改变布局。
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn if scrollbar else Qt.ScrollBarAlwaysOff)
        padding = (max(0, (width - 38 - scrollbar - min(count, columns) * 116 - 4) // 2)
                   if count and not self.delegate.list_mode else 0)
        self.view.setViewportMargins(padding, 0, padding, 0)

    def _assign(self, paths):
        if self.category_id != UNCATEGORIZED:
            self.service.assign_paths(paths, self.category_id)
            self._set_status("已手动归类，自动整理将保留这个归属")

    def dragEnterEvent(self, event):
        if self.category_id != UNCATEGORIZED and event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        if self.category_id != UNCATEGORIZED and event.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
            if paths:
                self._assign(paths)
                event.setDropAction(Qt.CopyAction)
                event.accept()
                return
        event.ignore()

    def set_single_click(self, enabled):
        if self.cfg is not None:
            self.cfg["single_click_launch"] = bool(enabled)

    def _on_item_clicked(self, index):
        if self.cfg and not self.cfg.get("single_click_launch", True):
            return
        if QApplication.keyboardModifiers() & (Qt.ControlModifier | Qt.ShiftModifier):
            return
        self._launch_index(index)

    def _on_item_double_clicked(self, index):
        if self.cfg is None or self.cfg.get("single_click_launch", True):
            return
        if QApplication.keyboardModifiers() & (Qt.ControlModifier | Qt.ShiftModifier):
            return
        self._launch_index(index)

    def _launch_index(self, index):
        if not index.isValid():
            return
        entry = index.data(Qt.UserRole)
        if entry and entry.get("path"):
            self.hide()
            self.launch_callback(entry["path"])

    def _context_menu(self, pos):
        index = self.view.indexAt(pos) if self.view.viewport().rect().contains(pos) else self.model.index(-1, 0)
        if not index.isValid():
            self._display_menu(self.view.viewport().mapToGlobal(pos))
            return
        selection = self.view.selectionModel()
        # 已选中的多项继续批量操作；点到新项目时明确切换，菜单不沿用旧的当前项。
        command = QItemSelectionModel.NoUpdate if selection.isSelected(index) else QItemSelectionModel.ClearAndSelect
        selection.setCurrentIndex(index, command)
        selected = self.view.selectedIndexes()
        paths = [ix.data(Qt.UserRole)["path"] for ix in selected]
        menu = self._new_menu()
        open_action = menu.addAction(menu.glyph("open"), "打开")
        pin_action = menu.addAction(menu.glyph("pin"), "固定至 Shortcut")
        menu.addSeparator()
        file_commands = self.file_actions.add_menu(menu, paths) if self.file_actions else {}
        if file_commands:
            menu.addSeparator()
        move_menu = menu.addMenu("手动归入分类")
        move_menu.menuAction().setIcon(menu.glyph("categories"))
        actions = {}
        for category in self.service.state.get("categories", []):
            action = move_menu.addAction(QIcon(category_pixmap(category.get("icon", "folders"), 22)), category["name"])
            action.setEnabled(category["id"] != self.category_id)
            actions[action] = category["id"]
        auto_action = menu.addAction(menu.glyph("automatic"), "恢复自动分类")
        auto_action.setEnabled(any(normalize_path(path) in self.service.state.get("manual", {}) for path in paths))
        exclude_action = menu.addAction(menu.glyph("remove"), "从分类中移除")
        exclude_action.setToolTip("仅移除分类入口，保留原文件和位置")
        menu.setToolTipsVisible(True)
        menu.addSeparator()
        view_actions = self._view_actions(menu)
        cell = self.view.visualRect(index)
        local = cell if self.delegate.list_mode else self.delegate.icon_rect(cell).adjusted(-6, -6, 6, 6)
        local = local.intersected(self.view.viewport().rect())
        if local.isEmpty():
            local = self.view.visualRect(index).intersected(self.view.viewport().rect())
        anchor = QRect(self.view.viewport().mapToGlobal(local.topLeft()), local.size())
        screen = QApplication.screenAt(anchor.center()) or QApplication.primaryScreen()
        menu.ensurePolished()
        action = self._exec_menu(menu, _entry_menu_position(anchor, menu.sizeHint(), screen.availableGeometry()))
        menu.deleteLater()
        if action == open_action:
            self.hide()
            for path in paths:
                self.launch_callback(path)
        elif action == pin_action:
            for path in paths:
                self.pin_callback(path)
        elif action in file_commands:
            self._file_command(file_commands[action], paths)
        elif action == auto_action:
            self.service.restore_auto(paths)
        elif action == exclude_action:
            self.service.exclude_paths(paths)
        elif action in actions:
            self.service.assign_paths(paths, actions[action])
        elif action in view_actions:
            self._set_view_mode(view_actions[action])

    def _file_command(self, command, paths=None):
        if self.file_actions is None:
            return
        if paths is None:
            paths = [ix.data(Qt.UserRole)["path"] for ix in self.view.selectedIndexes()]
        if not paths:
            return
        if command == "delete" or command.startswith(("compress:", "extract:")):
            self.hide()
        self.file_actions.perform(command, paths)

    def _error(self, message):
        self._set_status(message)

    def _set_status(self, message):
        self.status.setText(message)
        self.status.setVisible(bool(message))
        if self.isVisible():
            self._place()
