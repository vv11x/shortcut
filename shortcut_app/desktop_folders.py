# -*- coding: utf-8 -*-
"""Desktop category boxes using the organizer's paths and asynchronous icon cache."""

import ctypes
from ctypes import wintypes
import math

from PyQt5.QtCore import Qt, QPoint, QRect, QRectF, QSize, QTimer, QVariantAnimation, QEasingCurve, pyqtSignal
from PyQt5.QtGui import (QColor, QFont, QFontMetrics, QPainter, QPainterPath,
                         QPen, QPixmap, QLinearGradient, QRegion)
from PyQt5.QtWidgets import QApplication, QWidget, QMenu

from .organizer import normalize_path, UNCATEGORIZED


class _DesktopEvents(QWidget):
    """A separate top-level receiver survives Explorer and receives broadcasts."""
    changed = pyqtSignal()

    def __init__(self, user):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint)
        self.message = user.RegisterWindowMessageW('TaskbarCreated')
        self.winId()

    def nativeEvent(self, event_type, message):
        if event_type in (b'windows_generic_MSG', b'windows_dispatcher_MSG'):
            if wintypes.MSG.from_address(int(message)).message == self.message:
                self.changed.emit()
        return super().nativeEvent(event_type, message)


class _DesktopHost:
    """Place the native child above Explorer's list, never behind its opaque window."""
    def __init__(self, changed):
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        pointer = ctypes.c_void_p
        signatures = {
            'FindWindowExW': ([pointer, pointer, ctypes.c_wchar_p, ctypes.c_wchar_p], pointer),
            'GetParent': ([pointer], pointer), 'IsWindow': ([pointer], wintypes.BOOL),
            'SetParent': ([pointer, pointer], pointer),
            'GetWindowLongPtrW': ([pointer, ctypes.c_int], ctypes.c_ssize_t),
            'SetWindowLongPtrW': ([pointer, ctypes.c_int, ctypes.c_ssize_t], ctypes.c_ssize_t),
            'SetWindowPos': ([pointer, pointer, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, ctypes.c_uint], wintypes.BOOL),
            'ScreenToClient': ([pointer, ctypes.POINTER(wintypes.POINT)], wintypes.BOOL),
            'GetWindowThreadProcessId': ([pointer, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
            'RegisterWindowMessageW': ([ctypes.c_wchar_p], ctypes.c_uint),
            'UnhookWinEvent': ([pointer], wintypes.BOOL),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.user, name)
            function.argtypes, function.restype = arguments, result
        self._enumerator = ctypes.WINFUNCTYPE(wintypes.BOOL, pointer, wintypes.LPARAM)
        self.user.EnumWindows.argtypes = [self._enumerator, wintypes.LPARAM]
        self.user.EnumWindows.restype = wintypes.BOOL
        self._event_type = ctypes.WINFUNCTYPE(None, pointer, wintypes.DWORD, pointer,
                                             ctypes.c_long, ctypes.c_long, wintypes.DWORD, wintypes.DWORD)
        self.user.SetWinEventHook.argtypes = [wintypes.DWORD, wintypes.DWORD, pointer,
                                            self._event_type, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD]
        self.user.SetWinEventHook.restype = pointer
        self.host = self.window = self.hook = 0
        self.style = None
        self.events = _DesktopEvents(self.user)
        self.events.changed.connect(changed)

        def destroyed(hook, event, hwnd, object_id, child_id, thread, timestamp):
            if hwnd == self.host and object_id == 0 and child_id == 0:
                self.events.changed.emit()
        self._destroyed = self._event_type(destroyed)

    def _find_host(self):
        found = []

        def visit(hwnd, unused):
            view = self.user.FindWindowExW(hwnd, None, 'SHELLDLL_DefView', None)
            if view:
                found.append(view)
                return False
            return True
        self.user.EnumWindows(self._enumerator(visit), 0)
        if not found:
            raise OSError('Windows 桌面尚未就绪')
        return found[0]

    def alive(self):
        return bool(self.host and self.window and self.user.IsWindow(self.host)
                    and self.user.IsWindow(self.window)
                    and self.user.GetParent(self.window) == self.host)

    def native_window(self, widget):
        """Create only this child under Explorer's DPI context, preserving the app's context."""
        user, host = self.user, self._find_host()
        get_context = getattr(user, 'GetWindowDpiAwarenessContext', None)
        set_context = getattr(user, 'SetThreadDpiAwarenessContext', None)
        equal = getattr(user, 'AreDpiAwarenessContextsEqual', None)
        if not (get_context and set_context and equal):
            return int(widget.winId())
        get_context.argtypes, get_context.restype = [ctypes.c_void_p], ctypes.c_void_p
        set_context.argtypes, set_context.restype = [ctypes.c_void_p], ctypes.c_void_p
        equal.argtypes, equal.restype = [ctypes.c_void_p, ctypes.c_void_p], wintypes.BOOL
        target = get_context(host)
        previous = set_context(target)
        if not previous:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            window = int(widget.winId())
            if not user.IsWindow(window) or not equal(get_context(window), target):
                widget.destroy(True, True)
                widget.create()
                window = int(widget.winId())
            return window
        finally:
            set_context(previous)

    def attach(self, window, screen, rectangle):
        self.detach()
        user, host = self.user, self._find_host()
        # Cross-process SetParent with mismatched DPI can reset process awareness.
        # Refuse it instead of changing scaling for the rest of the application.
        context = getattr(user, 'GetWindowDpiAwarenessContext', None)
        equal = getattr(user, 'AreDpiAwarenessContextsEqual', None)
        if context and equal:
            context.argtypes, context.restype = [ctypes.c_void_p], ctypes.c_void_p
            equal.argtypes, equal.restype = [ctypes.c_void_p, ctypes.c_void_p], wintypes.BOOL
            if not equal(context(window), context(host)):
                raise OSError('桌面与 Shortcut 的显示缩放模式不兼容')
        style = user.GetWindowLongPtrW(window, -16)
        user.SetWindowLongPtrW(window, -16, (style & ~0x80000000) | 0x40000000 | 0x04000000)
        ctypes.set_last_error(0)
        previous = user.SetParent(window, host)
        error = ctypes.get_last_error()
        if not previous and error:
            user.SetWindowLongPtrW(window, -16, style)
            raise ctypes.WinError(error)
        self.host, self.window, self.style = host, window, style
        try:
            self.position(screen, rectangle)
            owner = wintypes.DWORD()
            user.GetWindowThreadProcessId(host, ctypes.byref(owner))
            self.hook = user.SetWinEventHook(0x8001, 0x8001, None, self._destroyed, owner.value, 0, 0)
            if not self.hook:
                raise OSError('无法监听 Windows 桌面重建事件')
        except Exception:
            self.detach()
            raise

    @staticmethod
    def native_rectangle(screen, rectangle):
        # On Windows, Qt screen origins keep native virtual-desktop positions;
        # offsets and dimensions within a screen are device-independent.
        origin, ratio = screen.geometry().topLeft(), screen.devicePixelRatio()
        return QRect(round(origin.x() + (rectangle.x() - origin.x()) * ratio),
                     round(origin.y() + (rectangle.y() - origin.y()) * ratio),
                     round(rectangle.width() * ratio), round(rectangle.height() * ratio))

    def position(self, screen, rectangle):
        native = self.native_rectangle(screen, rectangle)
        point = wintypes.POINT(native.x(), native.y())
        if not self.user.ScreenToClient(self.host, ctypes.byref(point)):
            raise ctypes.WinError(ctypes.get_last_error())
        # HWND_TOP only among the desktop's children, never above applications.
        if not self.user.SetWindowPos(self.window, None, point.x, point.y,
                                      native.width(), native.height(), 0x10 | 0x20):
            raise ctypes.WinError(ctypes.get_last_error())

    def detach(self):
        if self.hook:
            self.user.UnhookWinEvent(self.hook)
            self.hook = 0
        if (self.window and self.user.IsWindow(self.window)
                and self.user.GetParent(self.window) == self.host):
            self.user.SetParent(self.window, None)
            if self.style is not None:
                self.user.SetWindowLongPtrW(self.window, -16, self.style)
        self.host = self.window = 0
        self.style = None

    def close(self):
        self.detach()
        self.events.close()
        self.events.deleteLater()


class DesktopFoldersWidget(QWidget):
    positionChanged = pyqtSignal()
    hostError = pyqtSignal(str)
    hostReady = pyqtSignal()

    def __init__(self, shortcut, cfg):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus)
        self.shortcut, self.cfg = shortcut, cfg
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self._hover_idx = self._pressed_idx = -1
        self._feedback_levels = {}
        self._feedback_from, self._feedback_to = {}, {}
        self._feedback = QVariantAnimation(self)
        self._feedback.setDuration(130)
        self._feedback.setStartValue(0.0)
        self._feedback.setEndValue(1.0)
        self._feedback.setEasingCurve(QEasingCurve.OutCubic)
        self._feedback.valueChanged.connect(self._feedback_step)
        self._reveal_level = 1.0
        self._reveal = QVariantAnimation(self)
        self._reveal.setDuration(260)
        self._reveal.setStartValue(0.0)
        self._reveal.setEndValue(1.0)
        self._reveal.setEasingCurve(QEasingCurve.OutCubic)
        self._reveal.valueChanged.connect(self._reveal_step)
        self._drag_start = self._drag_origin = None
        self._moving_window = False
        self._page = 0
        self._cards, self._grids, self._entries, self._custom = [], {}, {}, {}
        self._screen, self._area = None, QRect()
        self._backdrop = QPixmap()
        self._backdrop_source = QPixmap()
        self._host_backend = None
        self._host_error = ''
        self._closed = self._host_waiting = False
        self._reconnect_attempts = 0
        self._reconnect = QTimer(self)
        self._reconnect.setSingleShot(True)
        self._reconnect.setInterval(500)
        self._reconnect.timeout.connect(self._retry_host)
        self._capture_timer = QTimer(self)
        self._capture_timer.setSingleShot(True)
        self._capture_timer.setInterval(80)
        self._capture_timer.timeout.connect(self._capture_and_show)
        self.font = QFont('Microsoft YaHei UI', 10)
        self.font_metrics = QFontMetrics(self.font)
        self.tile_size, self.label_h, self.padding = 210, 38, 24
        self.gap_x = self.gap_y = 22
        self._model = getattr(getattr(shortcut, 'category_panel', None), 'model', None)
        if self._model is not None:
            self._model.iconReady.connect(self._icon_ready)
        self.refresh()

    def categories_data(self):
        organizer = getattr(self.shortcut, 'organizer', None)
        if organizer is None:
            return []
        categories = list(organizer.state.get('categories', []))
        if self.cfg.get('desktop_display', 'managed') == 'managed':
            categories.append({'id': UNCATEGORIZED, 'name': '未归类', 'icon': 'other'})
        return categories

    def _grid_side(self):
        return {'2x2': 2, '3x3': 3, '4x4': 4}.get(str(self.cfg.get('folder_grid_size', '4x4')), 4)

    def refresh(self):
        if self._closed:
            return
        self._screen = getattr(self.shortcut, 'target_screen', lambda: None)() or QApplication.primaryScreen()
        area = QRect(self._screen.availableGeometry())
        if area != self._area:
            self._backdrop = QPixmap()
            self._backdrop_source = QPixmap()
        self._area = area
        self.setGeometry(area)
        margin = min(self.padding, max(4, area.width() // 20))
        self.tile_size = max(80, min(210, area.width() - margin * 2, area.height() - margin * 2 - 48))
        capacity_x = max(1, (area.width() - margin * 2 + self.gap_x) // (self.tile_size + self.gap_x))
        capacity_y = max(1, (area.height() - margin * 2 - 30 + self.gap_y) // (self.tile_size + self.label_h + self.gap_y))
        try:
            columns = max(1, min(8, int(self.cfg.get('desktop_folder_cols', 4))))
        except (TypeError, ValueError):
            columns = 4
        self._columns = min(columns, capacity_x)
        self._capacity = max(1, self._columns * capacity_y)
        self._categories = self.categories_data()
        self._pages = max(1, math.ceil(len(self._categories) / self._capacity))
        self._page = min(self._page, self._pages - 1)
        organizer = getattr(self.shortcut, 'organizer', None)
        groups = organizer.groups() if organizer is not None else {}
        self._entries = {category['id']: list(groups.get(category['id'], [])) for category in self._categories}
        self._custom.clear()
        for category in self._categories:
            path = self.cfg.get('category_custom_icons', {}).get(category['id'])
            if path:
                pixmap = QPixmap(path)
                if not pixmap.isNull():
                    self._custom[category['id']] = pixmap
        self._layout_cards()
        self._rebuild_grids()
        self._reblur_backdrop()
        if self._host_backend and self._host_backend.alive():
            self._host_backend.position(self._screen, self._area)
        self.update()

    def _layout_cards(self):
        self._cards = []
        visible = self._categories[self._page * self._capacity:(self._page + 1) * self._capacity]
        positions = self.cfg.get('desktop_folder_positions', {})
        start = self.cfg.get('desktop_folders_pos', [self._area.x() + self.padding, self._area.y() + self.padding])
        try:
            origin = QPoint(int(start[0]), int(start[1]))
            start = origin - self._area.topLeft() if self._area.contains(origin) else QPoint(self.padding, self.padding)
        except (TypeError, ValueError, IndexError):
            start = QPoint(self.padding, self.padding)
        width = min(len(visible), self._columns) * (self.tile_size + self.gap_x) - self.gap_x
        rows = math.ceil(len(visible) / self._columns)
        height = rows * (self.tile_size + self.label_h + self.gap_y) - self.gap_y
        start.setX(max(0, min(start.x(), self.width() - width)))
        start.setY(max(0, min(start.y(), self.height() - height - (30 if self._pages > 1 else 0))))
        for index, category in enumerate(visible):
            position = QPoint(start.x() + (index % self._columns) * (self.tile_size + self.gap_x),
                              start.y() + (index // self._columns) * (self.tile_size + self.label_h + self.gap_y))
            saved = positions.get(category['id'])
            if isinstance(saved, (list, tuple)) and len(saved) == 2:
                try:
                    saved_point = QPoint(int(saved[0]), int(saved[1]))
                    if self._area.contains(saved_point):
                        position = saved_point - self._area.topLeft()
                except (TypeError, ValueError):
                    pass
            card = self._clamp_card(QRect(position, QSize(self.tile_size, self.tile_size + self.label_h)))
            tile = QRectF(card.x(), card.y() + self.label_h, card.width(), self.tile_size)
            label = QRectF(card.x() + 16, card.y() + 4, card.width() - 32, self.label_h - 4)
            self._cards.append((QRectF(card), tile, label, category))
        self._set_card_mask()

    def _clamp_card(self, card):
        card.moveLeft(max(0, min(card.x(), self.width() - card.width())))
        card.moveTop(max(0, min(card.y(), self.height() - card.height() - (30 if self._pages > 1 else 0))))
        return card

    def _footer(self):
        return QRect(max(0, self.width() // 2 - 135), max(0, self.height() - 30), 270, 28)

    def _set_card_mask(self):
        region = QRegion()
        for card, tile, label, category in self._cards:
            path = QPainterPath()
            path.addRoundedRect(card, 24, 24)
            region |= QRegion(path.toFillPolygon().toPolygon())
        if self._pages > 1:
            region |= QRegion(self._footer())
        self.setMask(region)

    def folder_rects(self):
        return list(self._cards)

    def _rebuild_grids(self):
        self._grids.clear()
        for card, tile, label, category in self._cards:
            cid = category['id']
            if self._model is not None and cid not in self._custom:
                for item in self._entries.get(cid, [])[:self._grid_side() ** 2]:
                    self._model.request_icon(item['path'])
            self._grids[cid] = self._render_mini_grid(cid, self.tile_size)

    def _render_mini_grid(self, cid, tile_size):
        """Only cached QIcons: no disk reads, Shell calls or icon requests."""
        ratio = self._screen.devicePixelRatio()
        pixels = math.ceil(tile_size * ratio)
        image = QPixmap(pixels, pixels)
        image.setDevicePixelRatio(ratio)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        custom = self._custom.get(cid)
        if custom is not None:
            size = int(tile_size * .70)
            painter.drawPixmap(QRectF((tile_size - size) / 2, (tile_size - size) / 2, size, size), custom, QRectF(custom.rect()))
        else:
            side = self._grid_side()
            margin, gap = max(12, int(tile_size * .08)), max(6, int(tile_size * .05))
            cell = max(10, (tile_size - margin * 2 - gap * (side - 1)) // side)
            entries = self._entries.get(cid, [])[:side * side]
            for index, item in enumerate(entries):
                rect = QRect(margin + (index % side) * (cell + gap), margin + (index // side) * (cell + gap), cell, cell)
                icon = self._model.icons.get(normalize_path(item['path'])) if self._model is not None else None
                if icon is None and self._model is not None:
                    icon = self._model.fallback
                if icon is not None:
                    icon.paint(painter, rect)
                else:
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(QColor(125, 160, 218, 90))
                    painter.drawRoundedRect(QRectF(rect), 7, 7)
            if not entries:
                painter.setPen(QColor('#60738e' if self.shortcut.is_light() else '#c5d3e8'))
                painter.setFont(QFont('Microsoft YaHei UI', 10))
                painter.drawText(QRect(0, 0, tile_size, tile_size), Qt.AlignCenter, '拖入应用或文件\n添加到此分类')
        painter.end()
        return image

    def _icon_ready(self, path):
        if self._closed:
            return
        normalized = normalize_path(path)
        for card, tile, label, category in self._cards:
            cid = category['id']
            if any(normalize_path(item['path']) == normalized for item in self._entries.get(cid, [])[:self._grid_side() ** 2]):
                self._grids[cid] = self._render_mini_grid(cid, self.tile_size)
                self.update(card.toAlignedRect())

    def _capture_backdrop(self):
        if not self.cfg.get('glass', True) or not self._backdrop_source.isNull():
            return
        # One snapshot before showing. refresh() never grabs the visible boxes.
        image = self._screen.grabWindow(0, self._area.x(), self._area.y(), self._area.width(), self._area.height())
        if not image.isNull():
            self._backdrop_source = image.scaled(max(1, self.width() // 2), max(1, self.height() // 2),
                                                 Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            self._backdrop_source.setDevicePixelRatio(1)
            self._reblur_backdrop()

    def _reblur_backdrop(self):
        if not self._backdrop_source.isNull():
            divisor = max(2, min(50, int(self.cfg.get('blur_px', 6))))
            self._backdrop = self._backdrop_source.scaled(max(1, self.width() // divisor),
                                                        max(1, self.height() // divisor),
                                                        Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        elif self.isVisible() and self.cfg.get('glass', True) and not self._capture_timer.isActive():
            self.hide()
            self._capture_timer.start()

    def _capture_and_show(self):
        if (not self._closed and not self._host_waiting and self.cfg.get('desktop_folder_mode', False)
                and getattr(self.shortcut, '_presentation_visible', True)):
            self._capture_backdrop()
            self.show()
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        light = self.shortcut.is_light()
        transparency = max(0, min(100, int(self.cfg.get('transparency', 40)))) / 100
        for index, (card, tile, label, category) in enumerate(self._cards):
            painter.save()
            hover, press = self._feedback_levels.get(category['id'], (0.0, 0.0))
            reveal = max(0.0, min(1.0, (self._reveal_level - min(index, 6) * .035) / .79))
            painter.setOpacity(reveal)
            scale = 1 - .035 * press - .045 * (1 - reveal)
            painter.translate(card.center())
            painter.scale(scale, scale)
            painter.translate(-card.center())
            path = QPainterPath()
            path.addRoundedRect(card, 24, 24)
            painter.setClipPath(path)
            if self.cfg.get('glass', True) and not self._backdrop.isNull():
                source = QRectF(card.x() * self._backdrop.width() / max(1, self.width()),
                                card.y() * self._backdrop.height() / max(1, self.height()),
                                card.width() * self._backdrop.width() / max(1, self.width()),
                                card.height() * self._backdrop.height() / max(1, self.height()))
                painter.drawPixmap(card, self._backdrop, source)
            alpha = round(246 - transparency * 102) if light else round(242 - transparency * 95)
            painter.fillPath(path, QColor(246, 249, 255, alpha) if light else QColor(24, 31, 45, alpha))
            shine = QLinearGradient(card.topLeft(), card.bottomRight())
            shine.setColorAt(0, QColor(255, 255, 255, 65 if light else 30))
            shine.setColorAt(1, QColor(255, 255, 255, 0))
            painter.fillPath(path, shine)
            painter.setClipping(False)
            active = getattr(self.shortcut, '_active_category_id', None) == category['id']
            emphasis = max(hover, press, 1.0 if active else 0.0)
            if emphasis:
                painter.fillPath(path, QColor(86, 153, 252, round(22 * emphasis)))
            edge = QColor(round(255 - 169 * emphasis), round(255 - 102 * emphasis),
                          round(255 - 3 * emphasis), round((170 if light else 65) + 50 * emphasis))
            painter.setPen(QPen(edge, 1 + .5 * emphasis))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(card.adjusted(.8, .8, -.8, -.8), 24, 24)
            grid = self._grids.get(category['id'])
            if grid is not None:
                painter.drawPixmap(tile.topLeft(), grid)
            painter.setFont(self.font)
            painter.setPen(QColor('#223149' if light else '#f0f5ff'))
            count = len(self._entries.get(category['id'], []))
            title = self.font_metrics.elidedText(category['name'], Qt.ElideRight, max(1, int(label.width()) - 40))
            painter.drawText(label, Qt.AlignLeft | Qt.AlignVCenter, title)
            painter.setPen(QColor('#6d7b8e' if light else '#a4b3ca'))
            painter.drawText(label, Qt.AlignRight | Qt.AlignVCenter, str(count))
            painter.restore()
        if self._pages > 1:
            footer = self._footer()
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(28, 36, 50, 220))
            painter.drawRoundedRect(QRectF(footer), 12, 12)
            painter.setPen(QColor('#edf3ff'))
            painter.drawText(footer, Qt.AlignCenter, '‹ 上一页    %d / %d    下一页 ›' % (self._page + 1, self._pages))

    def category_at(self, global_point):
        if not self.isVisible():
            return None
        local = QPoint(global_point) - self._area.topLeft()
        for card, tile, label, category in self._cards:
            if card.contains(local) and category['id'] != UNCATEGORIZED:
                return category['id']
        return None

    def contains_global(self, global_point):
        return self.isVisible() and self.mask().contains(QPoint(global_point) - self._area.topLeft())

    def set_drop_category(self, category_id):
        self._hover_idx = next((index for index, item in enumerate(self._cards)
                                if item[3]['id'] == category_id), -1)
        self._animate_feedback()

    def _animate_feedback(self):
        self._feedback.stop()
        self._feedback_from = dict(self._feedback_levels)
        self._feedback_to = {category['id']: (float(index == self._hover_idx),
                                            float(index == self._pressed_idx and not self._moving_window))
                             for index, (_, _, _, category) in enumerate(self._cards)}
        self._feedback.start()

    def _feedback_step(self, progress):
        self._feedback_levels = {
            cid: tuple(start + (end - start) * progress for start, end in
                       zip(self._feedback_from.get(cid, (0.0, 0.0)), target))
            for cid, target in self._feedback_to.items()}
        self.update()

    def _reveal_step(self, progress):
        self._reveal_level = progress
        self.update()

    def _hit(self, position):
        return next((index for index, item in enumerate(self._cards) if item[0].contains(position)), -1)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._pressed_idx = self._hit(event.pos())
            self._drag_start = QPoint(event.globalPos())
            self._moving_window = False
            if self._pressed_idx >= 0:
                self._drag_origin = self._cards[self._pressed_idx][0].toRect().topLeft()
            self._animate_feedback()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pressed_idx >= 0 and self._drag_start is not None and event.buttons() & Qt.LeftButton:
            delta = event.globalPos() - self._drag_start
            if self._moving_window or delta.manhattanLength() >= QApplication.startDragDistance():
                starting_move = not self._moving_window
                self._moving_window = True
                if starting_move:
                    self._animate_feedback()
                card, tile, label, category = self._cards[self._pressed_idx]
                moved = self._clamp_card(QRect(self._drag_origin + delta, QSize(self.tile_size, self.tile_size + self.label_h)))
                shift = moved.topLeft() - card.toRect().topLeft()
                self._cards[self._pressed_idx] = (QRectF(moved), tile.translated(shift), label.translated(shift), category)
                self._set_card_mask()
                self.update()
                event.accept()
                return
        hit = self._hit(event.pos())
        if hit != self._hover_idx:
            self._hover_idx = hit
            self.setCursor(Qt.PointingHandCursor if hit >= 0 else Qt.ArrowCursor)
            self._animate_feedback()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        index = self._pressed_idx
        self._pressed_idx = -1
        if event.button() == Qt.LeftButton and index >= 0:
            card, tile, label, category = self._cards[index]
            if self._moving_window:
                point = card.toRect().topLeft() + self._area.topLeft()
                self.cfg.setdefault('desktop_folder_positions', {})[category['id']] = [point.x(), point.y()]
                self.positionChanged.emit()
            elif card.contains(event.pos()):
                self.shortcut.open_category(category['id'], anchor=card.toAlignedRect().translated(self._area.topLeft()), shortcut_edge=None)
            self._moving_window = False
            self._drag_start = self._drag_origin = None
            self._animate_feedback()
            event.accept()
            return
        if event.button() == Qt.LeftButton and self._pages > 1 and self._footer().contains(event.pos()):
            self._change_page(-1 if event.pos().x() < self._footer().center().x() else 1)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        self._hover_idx = -1
        self._animate_feedback()
        super().leaveEvent(event)

    def _change_page(self, delta):
        page = max(0, min(self._page + delta, self._pages - 1))
        if page != self._page:
            self._page = page
            self._pressed_idx = self._hover_idx = -1
            self._layout_cards()
            self._rebuild_grids()
            self._feedback_levels.clear()
            self._reveal.start()
            self.update()

    def wheelEvent(self, event):
        if self._pages > 1 and event.angleDelta().y():
            self._change_page(-1 if event.angleDelta().y() > 0 else 1)
            event.accept()
        else:
            event.ignore()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction('偏好设置…').triggered.connect(self.shortcut.open_preferences_dialog)
        menu.addAction('切回 Shortcut 栏').triggered.connect(lambda: self.shortcut.set_desktop_folder_mode(False))
        menu.exec_(event.globalPos())
        menu.deleteLater()

    @staticmethod
    def _local_paths(event):
        return [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]

    def dragEnterEvent(self, event):
        if self._local_paths(event):
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        category = self.category_at(self._area.topLeft() + event.pos())
        self.set_drop_category(category)
        if category and self._local_paths(event):
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.set_drop_category(None)
        event.accept()

    def dropEvent(self, event):
        category, paths = self.category_at(self._area.topLeft() + event.pos()), self._local_paths(event)
        self.set_drop_category(None)
        if category and paths:
            self.shortcut.organizer.assign_paths(paths, category)
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            event.ignore()

    def ensure_desktop_host(self):
        if self._closed:
            return False
        if QApplication.platformName() != 'windows':
            return True  # Offscreen previews and tests never access Win32.
        try:
            if self._host_backend is None:
                self._host_backend = _DesktopHost(self._desktop_changed)
            if not self._host_backend.alive():
                hwnd = self._host_backend.native_window(self)
                self._host_backend.attach(hwnd, self._screen, self._area)
                self._host_waiting = False
                self.hostReady.emit()
            else:
                self._host_backend.position(self._screen, self._area)
            return True
        except OSError as error:
            self._host_error = str(error)
            return False

    def _desktop_changed(self):
        if self._closed or not self.cfg.get('desktop_folder_mode', False):
            return
        self._host_waiting = True
        self._reconnect_attempts = 0
        self._capture_timer.stop()
        self.hide()
        self._reconnect.start()

    def begin_host_recovery(self):
        if not self._host_waiting:
            self._desktop_changed()

    def _retry_host(self):
        if self._closed or not self.cfg.get('desktop_folder_mode', False):
            return
        self._reconnect_attempts += 1
        if self.ensure_desktop_host():
            self._host_waiting = False
            if getattr(self.shortcut, '_presentation_visible', True):
                self.show()
        elif self._reconnect_attempts < 12:
            self._reconnect.start()
        else:
            self._host_waiting = False
            self.hide()
            self.hostError.emit('桌面文件夹无法连接 Windows 桌面：' + self._host_error)

    def _ensure_bottom(self):
        return self.ensure_desktop_host()  # Compatibility; no HWND_BOTTOM calls.

    def showEvent(self, event):
        if not self._closed:
            self._reveal.start()
            self._capture_backdrop()
            if not self.ensure_desktop_host():
                QTimer.singleShot(0, self._desktop_changed)
        super().showEvent(event)

    def hideEvent(self, event):
        self._feedback.stop()
        self._reveal.stop()
        self._feedback_levels.clear()
        self._hover_idx = self._pressed_idx = -1
        self._drag_start = self._drag_origin = None
        self._moving_window = False
        self._backdrop = QPixmap()
        self._backdrop_source = QPixmap()
        if not self._host_waiting:
            self._reconnect.stop()
        super().hideEvent(event)

    def shutdown(self):
        if self._closed:
            return
        self._closed = True
        self._reconnect.stop()
        self._capture_timer.stop()
        self.hide()
        if self._host_backend:
            self._host_backend.close()
            self._host_backend = None
        if self._model is not None:
            try:
                self._model.iconReady.disconnect(self._icon_ready)
            except (TypeError, RuntimeError):
                pass
