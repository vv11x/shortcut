from pathlib import Path

from PySide6.QtCore import Qt, QPoint, QSize, QFileInfo, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFileIconProvider,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from shortcut.file_actions import compress_paths, copy_paths, delete_to_recycle_bin, extract_archive
from shortcut.models import AppSettings, Category, ShortcutEntry, path_key
from shortcut.resources import category_icon
from shortcut.shell import open_entry, show_in_explorer


class EntryListWidget(QListWidget):
    def __init__(self, on_drop_paths, parent: QWidget):
        super().__init__(parent)
        self.on_drop_paths = on_drop_paths
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.setDropAction(Qt.CopyAction)
            event.accept()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.setDropAction(Qt.CopyAction)
            event.accept()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
            self.on_drop_paths(paths)
            event.setDropAction(Qt.CopyAction)
            event.accept()
            return
        super().dropEvent(event)


class EntryPanel(QWidget):
    def __init__(
        self,
        category: Category,
        entries: list[ShortcutEntry],
        categories: list[Category],
        settings: AppSettings,
        on_assign,
        on_drop_paths,
        on_fix,
        on_dismiss,
        on_order_changed,
        on_position_changed,
        on_files_changed,
        desktop_box: bool = False,
        parent: QWidget | None = None,
    ):
        flags = Qt.Tool | Qt.WindowTitleHint if desktop_box else Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        super().__init__(parent, flags)
        self.category = category
        self.categories = categories
        self.settings = settings
        self.on_assign = on_assign
        self.on_drop_paths = on_drop_paths
        self.on_fix = on_fix
        self.on_dismiss = on_dismiss
        self.on_order_changed = on_order_changed
        self.on_position_changed = on_position_changed
        self.on_files_changed = on_files_changed
        self.desktop_box = desktop_box
        self.position_timer = QTimer(self)
        self.position_timer.setSingleShot(True)
        self.position_timer.timeout.connect(self.save_current_position)
        self.setWindowTitle(category.title)
        if desktop_box:
            self.setMinimumSize(220, 160)
        else:
            self.setMinimumSize(300, 240)
        self.setStyleSheet(self.style_for(settings.theme))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        header = QHBoxLayout()
        self.title_icon = QLabel()
        self.title_label = QLabel(category.title)
        self.title_icon.setPixmap(QIcon(str(category_icon(category.icon))).pixmap(24, 24))
        self.title_label.setStyleSheet("font-size: 16px; font-weight: 600;")
        header.addWidget(self.title_icon)
        header.addWidget(self.title_label)
        header.addStretch()
        self.count_label = QLabel(str(len(entries)))
        header.addWidget(self.count_label)
        close_button = QPushButton("×")
        close_button.setFixedSize(28, 28)
        close_button.setToolTip("关闭分类面板")
        close_button.clicked.connect(self.close)
        header.addWidget(close_button)
        layout.addLayout(header)

        self.items = EntryListWidget(self.drop_paths, self)
        self.items.setSelectionMode(QListWidget.ExtendedSelection)
        self.items.setDragEnabled(True)
        self.items.setDragDropMode(QListWidget.InternalMove)
        self.items.setDefaultDropAction(Qt.MoveAction)
        self.items.model().rowsMoved.connect(lambda *_: self.save_order())
        self.items.itemDoubleClicked.connect(self.open_item)
        self.items.setContextMenuPolicy(Qt.CustomContextMenu)
        self.items.customContextMenuRequested.connect(self.show_item_menu)
        layout.addWidget(self.items)
        self.set_view_mode(settings.view_mode)
        self.set_entries(entries)

    def drop_paths(self, paths: list[Path]) -> None:
        self.on_drop_paths(paths, self.category.id)

    @staticmethod
    def style_for(theme: str) -> str:
        if theme == "dark":
            background, foreground, selection = "#20232b", "#f4f5fa", "#42495b"
        elif theme == "light":
            background, foreground, selection = "#f6f7fb", "#242936", "#dce5f6"
        else:
            raise ValueError(f"Unsupported theme: {theme}")
        return (
            f"QWidget {{ color: {foreground}; background: {background}; }}"
            "QListWidget { border: 0; background: transparent; }"
            f"QPushButton {{ color: {foreground}; background: transparent; border: 0; border-radius: 6px; }}"
            f"QPushButton:hover {{ background: {selection}; }}"
            f"QListWidget::item {{ min-height: 38px; padding: 6px; border-radius: 8px; }}"
            f"QListWidget::item:selected {{ background: {selection}; }}"
        )

    def set_view_mode(self, mode: str) -> None:
        if mode == "icons":
            self.items.setViewMode(QListWidget.IconMode)
            self.items.setMovement(QListWidget.Free)
            self.items.setIconSize(QSize(64, 64))
            self.items.setGridSize(QSize(112, 104))
        elif mode == "list":
            self.items.setViewMode(QListWidget.ListMode)
            self.items.setMovement(QListWidget.Snap)
            self.items.setIconSize(QSize(24, 24))
        else:
            raise ValueError(f"Unsupported view mode: {mode}")

    def set_entries(self, entries: list[ShortcutEntry]) -> None:
        provider = QFileIconProvider()
        self.items.clear()
        self.title_label.setText(self.category.title)
        self.title_icon.setPixmap(QIcon(str(category_icon(self.category.icon))).pixmap(24, 24))
        self.count_label.setText(str(len(entries)))
        for entry in entries:
            item = QListWidgetItem(provider.icon(QFileInfo(str(entry.path))), entry.title)
            item.setData(Qt.UserRole, str(entry.path))
            item.setToolTip(str(entry.path))
            self.items.addItem(item)

    def selected_paths(self) -> list[Path]:
        selected = self.items.selectedItems()
        if not selected and self.items.currentItem():
            selected = [self.items.currentItem()]
        return [Path(item.data(Qt.UserRole)) for item in selected]

    def open_item(self, item: QListWidgetItem) -> None:
        open_entry(Path(item.data(Qt.UserRole)))

    def save_order(self) -> None:
        self.on_order_changed(
            self.category.id,
            [self.items.item(index).data(Qt.UserRole) for index in range(self.items.count())],
        )

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        if self.desktop_box:
            self.position_timer.start(250)

    def save_current_position(self) -> None:
        self.on_position_changed(self.category.id, self.pos().x(), self.pos().y())

    def closeEvent(self, event) -> None:
        self.position_timer.stop()
        if self.desktop_box:
            self.save_current_position()
        super().closeEvent(event)

    def show_item_menu(self, position: QPoint) -> None:
        item = self.items.itemAt(position)
        if item is not None and not item.isSelected():
            self.items.setCurrentItem(item)
        paths = self.selected_paths()
        if not paths:
            return

        menu = QMenu(self)
        open_action = menu.addAction("打开")
        reveal_action = menu.addAction("在资源管理器中显示")
        menu.addSeparator()
        category_menu = menu.addMenu("移动到分类")
        category_actions = {
            category_menu.addAction(category.title): category.id
            for category in self.categories
            if category.id != self.category.id
        }
        key_set = {path_key(path) for path in paths}
        fixed_set = {path_key(Path(value)) for value in self.settings.fixed_paths}
        fixed_action = menu.addAction("从固定入口移除" if key_set <= fixed_set else "添加到固定入口")
        dismiss_action = menu.addAction("从 shortcut 列表隐藏")
        menu.addSeparator()
        copy_action = menu.addAction("复制")
        cut_action = menu.addAction("剪切")
        archive_action = menu.addAction("压缩为 7z")
        archive_action.setEnabled(bool(self.settings.archiver_path))
        extract_action = menu.addAction("解压到…")
        extractable = len(paths) == 1 and paths[0].suffix.casefold() in {".7z", ".zip", ".rar", ".tar", ".gz"}
        extract_action.setEnabled(bool(self.settings.archiver_path) and extractable)
        menu.addSeparator()
        delete_action = menu.addAction("移到回收站")

        selected = menu.exec_(self.items.mapToGlobal(position))
        if selected == open_action:
            open_entry(paths[0])
        elif selected == reveal_action:
            show_in_explorer(paths[0])
        elif selected in category_actions:
            for path in paths:
                self.on_assign(path, category_actions[selected])
        elif selected == fixed_action:
            if key_set <= fixed_set:
                for path in paths:
                    self.on_dismiss(path, "unfix")
            else:
                for path in paths:
                    self.on_fix(path)
        elif selected == dismiss_action:
            for path in paths:
                self.on_dismiss(path, "hide")
        elif selected == copy_action:
            copy_paths(paths, cut=False)
        elif selected == cut_action:
            copy_paths(paths, cut=True)
        elif selected == archive_action:
            compress_paths(paths, self.settings.archiver_path, self)
        elif selected == extract_action:
            extract_archive(paths[0], self.settings.archiver_path, self)
        elif selected == delete_action:
            answer = QMessageBox.question(
                self,
                "移到回收站",
                f"将选中的 {len(paths)} 个项目移到 Windows 回收站？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer == QMessageBox.Yes:
                delete_to_recycle_bin(paths, self)
                self.on_files_changed()


class SearchPopup(QWidget):
    def __init__(self):
        super().__init__(None, Qt.Popup | Qt.FramelessWindowHint)
        self.setMinimumWidth(360)
        self.setMaximumHeight(360)
        self.apply_theme("dark")
        self.items = QListWidget(self)
        self.items.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.items.itemDoubleClicked.connect(self.open_item)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.items)

    def apply_theme(self, theme: str) -> None:
        if theme == "dark":
            background, foreground, selection = "#20232b", "#f4f5fa", "#42495b"
        elif theme == "light":
            background, foreground, selection = "#f6f7fb", "#242936", "#dce5f6"
        else:
            raise ValueError(f"Unsupported theme: {theme}")
        self.setStyleSheet(
            f"QWidget {{ background: {background}; color: {foreground}; border: 1px solid #42495b; border-radius: 10px; }}"
            "QListWidget { border: 0; background: transparent; }"
            "QListWidget::item { min-height: 36px; padding: 5px; }"
            f"QListWidget::item:selected {{ background: {selection}; }}"
        )

    def set_entries(self, entries: list[ShortcutEntry]) -> None:
        provider = QFileIconProvider()
        self.items.clear()
        for entry in entries:
            item = QListWidgetItem(provider.icon(QFileInfo(str(entry.path))), entry.title)
            item.setData(Qt.UserRole, str(entry.path))
            item.setToolTip(str(entry.path))
            self.items.addItem(item)
        self.resize(self.minimumWidth(), min(360, max(64, len(entries) * 48 + 16)))

    def open_item(self, item: QListWidgetItem) -> None:
        open_entry(Path(item.data(Qt.UserRole)))
        self.hide()
