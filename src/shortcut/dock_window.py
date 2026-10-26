from pathlib import Path

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QBoxLayout,
    QFileDialog,
    QLineEdit,
    QMenu,
    QPushButton,
    QToolButton,
    QWidget,
    QApplication,
)

from shortcut.catalog import DesktopCatalog
from shortcut.models import AppSettings, Category, path_key
from shortcut.panels import EntryPanel, SearchPopup
from shortcut.resources import category_icon, character_sheet, mascot_image
from shortcut.settings_dialog import SettingsDialog
from shortcut.shell import open_local_file, open_recycle_bin
from shortcut.storage import save_settings
from shortcut.windows_desktop import DesktopIconController, icons_visible


class CategoryButton(QToolButton):
    def __init__(self, category: Category, on_drop, parent: QWidget):
        super().__init__(parent)
        self.category = category
        self.on_drop = on_drop
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.setDropAction(Qt.CopyAction)
            event.accept()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.setDropAction(Qt.CopyAction)
            event.accept()

    def dropEvent(self, event) -> None:
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.on_drop(paths, self.category.id)
            event.setDropAction(Qt.CopyAction)
            event.accept()


class ShortcutDock(QWidget):
    def __init__(self, settings: AppSettings, catalog: DesktopCatalog, desktop_icons: DesktopIconController):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.settings = settings
        self.catalog = catalog
        self.desktop_icons = desktop_icons
        self.panels: dict[str, EntryPanel] = {}
        self.setObjectName("dock")
        self.setWindowTitle("shortcut")
        self.setWindowIcon(QIcon(str(mascot_image())))
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.layout_box = QBoxLayout(QBoxLayout.LeftToRight, self)
        self.layout_box.setContentsMargins(10, 8, 10, 8)
        self.layout_box.setSpacing(4)
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("搜索快捷方式")
        self.search_box.textChanged.connect(self.update_search)
        self.search_popup = SearchPopup()
        self.add_button = QPushButton("＋")
        self.add_button.setToolTip("添加固定入口")
        self.add_button.clicked.connect(self.add_entry_menu)
        self.recycle_button = QPushButton("回收站")
        self.recycle_button.setIcon(QIcon(str(category_icon("trash_empty"))))
        self.recycle_button.clicked.connect(open_recycle_bin)
        self.refresh_button = QPushButton("刷新")
        self.refresh_button.clicked.connect(self.refresh_catalog)
        self.settings_button = QPushButton("设置")
        self.settings_button.clicked.connect(self.open_settings)
        self.category_buttons: dict[str, CategoryButton] = {}
        self.layout_box.addWidget(self.search_box)
        self.layout_box.addWidget(self.add_button)
        self.layout_box.addWidget(self.recycle_button)
        self.layout_box.addWidget(self.refresh_button)
        self.layout_box.addWidget(self.settings_button)
        self.rebuild()
        self.position_on_screen()

    def apply_style(self) -> None:
        if self.settings.theme == "dark":
            background, foreground, field, hover = "rgba(28, 31, 39, 238)", "#f4f5fa", "#343946", "#42495b"
        elif self.settings.theme == "light":
            background, foreground, field, hover = "rgba(246, 247, 251, 246)", "#242936", "#e7eaf1", "#dce5f6"
        else:
            raise ValueError(f"Unsupported theme: {self.settings.theme}")
        self.setStyleSheet(
            f"QWidget#dock {{ background: {background}; color: {foreground}; border: 1px solid #505767; border-radius: 18px; }}"
            f"QToolButton, QPushButton {{ color: {foreground}; background: transparent; border: 0; border-radius: 12px; padding: 7px; min-width: 52px; }}"
            f"QToolButton:hover, QPushButton:hover {{ background: {hover}; }}"
            f"QLineEdit {{ color: {foreground}; background: {field}; border: 0; border-radius: 12px; padding: 9px 12px; min-width: 120px; }}"
        )
        self.search_popup.apply_theme(self.settings.theme)

    def rebuild(self) -> None:
        self.apply_style()
        for button in self.category_buttons.values():
            self.layout_box.removeWidget(button)
            button.deleteLater()
        self.category_buttons.clear()
        for index, category in enumerate(self.settings.categories):
            button = CategoryButton(category, self.assign_dropped_paths, self)
            button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            button.setIcon(QIcon(str(category_icon(category.icon))))
            button.setIconSize(QSize(34, 34))
            button.setText(f"{category.title}  {len(self.catalog.entries_for(category))}")
            button.clicked.connect(lambda checked=False, selected=category: self.open_category(selected))
            self.category_buttons[category.id] = button
            self.layout_box.insertWidget(index, button)
        direction = QBoxLayout.TopToBottom if self.settings.dock_edge in ("left", "right") else QBoxLayout.LeftToRight
        self.layout_box.setDirection(direction)
        self.adjustSize()
        self.position_on_screen()

    def position_on_screen(self) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        self.adjustSize()
        if self.settings.dock_edge == "top":
            self.move(screen.center().x() - self.width() // 2, screen.top() + 8)
        elif self.settings.dock_edge == "bottom":
            self.move(screen.center().x() - self.width() // 2, screen.bottom() - self.height() - 8)
        elif self.settings.dock_edge == "left":
            self.move(screen.left() + 8, screen.center().y() - self.height() // 2)
        elif self.settings.dock_edge == "right":
            self.move(screen.right() - self.width() - 8, screen.center().y() - self.height() // 2)
        else:
            raise ValueError(f"Unsupported dock edge: {self.settings.dock_edge}")

    def refresh_catalog(self) -> None:
        self.catalog.refresh()
        self.rebuild()
        for category_id, panel in self.panels.items():
            category = next(item for item in self.settings.categories if item.id == category_id)
            panel.set_entries(self.catalog.entries_for(category))

    def open_category(self, category: Category, desktop_box: bool = False) -> EntryPanel:
        panel = self.panels.get(category.id)
        if panel is None:
            panel = EntryPanel(
                category,
                self.catalog.entries_for(category),
                self.settings.categories,
                self.settings,
                self.assign_entry,
                self.assign_entries,
                self.fix_entry,
                self.dismiss_entry,
                self.save_entry_order,
                self.save_category_position,
                self.refresh_catalog,
                desktop_box=desktop_box,
            )
            self.panels[category.id] = panel
        else:
            panel.category = category
            panel.categories = self.settings.categories
            panel.settings = self.settings
            panel.setStyleSheet(panel.style_for(self.settings.theme))
            panel.set_view_mode(self.settings.view_mode)
            panel.set_entries(self.catalog.entries_for(category))
        panel.show()
        if not desktop_box:
            panel.raise_()
            panel.activateWindow()
        return panel

    def update_search(self, text: str) -> None:
        if not text.strip():
            self.search_popup.hide()
            return
        entries = self.catalog.search(text)
        self.search_popup.set_entries(entries)
        anchor = self.search_box.mapToGlobal(QPoint(0, self.search_box.height()))
        self.search_popup.move(anchor)
        self.search_popup.show()

    def add_entry_menu(self) -> None:
        menu = QMenu(self)
        files_action = menu.addAction("添加文件…")
        folder_action = menu.addAction("添加文件夹…")
        selected = menu.exec_(self.add_button.mapToGlobal(QPoint(0, self.add_button.height())))
        if selected == files_action:
            paths, _ = QFileDialog.getOpenFileNames(self, "添加文件入口")
        elif selected == folder_action:
            folder = QFileDialog.getExistingDirectory(self, "添加文件夹入口")
            paths = [folder] if folder else []
        else:
            return
        self.fix_entries([Path(value) for value in paths])

    def assign_dropped_paths(self, paths: list[Path], category_id: str) -> None:
        self.assign_entries(paths, category_id)

    def fix_entries(self, paths: list[Path]) -> None:
        known = {path_key(Path(value)) for value in self.settings.fixed_paths}
        for path in paths:
            if path_key(path) not in known:
                self.settings.fixed_paths.append(str(path.resolve()))
                known.add(path_key(path))
        save_settings(self.settings)
        self.refresh_catalog()

    def fix_entry(self, path: Path) -> None:
        self.fix_entries([path])

    def assign_entry(self, path: Path, category_id: str) -> None:
        self.assign_entries([path], category_id)

    def assign_entries(self, paths: list[Path], category_id: str) -> None:
        known = {path_key(Path(value)) for value in self.settings.fixed_paths}
        assigned = {path_key(path) for path in paths}
        if category_id not in {category.id for category in self.settings.categories}:
            raise KeyError(category_id)
        for path in paths:
            key = path_key(path)
            if key not in known:
                self.settings.fixed_paths.append(str(path.resolve()))
                known.add(key)
            self.settings.manual_assignments[key] = category_id
        self.settings.dismissed_paths = [value for value in self.settings.dismissed_paths if path_key(Path(value)) not in assigned]
        save_settings(self.settings)
        self.refresh_catalog()

    def dismiss_entry(self, path: Path, action: str) -> None:
        key = path_key(path)
        if action == "hide":
            if key not in {path_key(Path(value)) for value in self.settings.dismissed_paths}:
                self.settings.dismissed_paths.append(str(path.resolve()))
        elif action == "unfix":
            self.settings.fixed_paths = [value for value in self.settings.fixed_paths if path_key(Path(value)) != key]
        else:
            raise ValueError(f"Unsupported list action: {action}")
        save_settings(self.settings)
        self.refresh_catalog()

    def save_entry_order(self, category_id: str, paths: list[str]) -> None:
        self.settings.entry_orders[category_id] = paths
        save_settings(self.settings)

    def save_category_position(self, category_id: str, x: int, y: int) -> None:
        self.settings.category_positions[category_id] = [x, y]
        save_settings(self.settings)

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec_() == dialog.Accepted:
            self.settings = dialog.settings
            self.catalog.settings = self.settings
            save_settings(self.settings)
            self.catalog.refresh()
            for panel in self.panels.values():
                panel.close()
            self.panels.clear()
            self.rebuild()
            self.activate_display_mode()

    def activate_display_mode(self) -> None:
        if self.settings.display_mode == "dock":
            for panel in self.panels.values():
                if panel.desktop_box:
                    panel.close()
            self.panels = {key: panel for key, panel in self.panels.items() if not panel.desktop_box}
            self.show()
            self.position_on_screen()
        elif self.settings.display_mode == "desktop":
            self.hide()
            for panel in self.panels.values():
                panel.close()
            self.panels.clear()
            screen = QApplication.primaryScreen().availableGeometry()
            count = len(self.settings.categories)
            gap = 12
            columns = max(1, min(count, min(4, (screen.width() - 24 + gap) // (220 + gap))))
            rows = (count + columns - 1) // columns
            box_width = max(220, min(350, (screen.width() - 36 - (columns - 1) * gap) // columns))
            box_height = max(160, min(280, (screen.height() - 36 - (rows - 1) * gap) // rows))
            for index, category in enumerate(self.settings.categories):
                panel = self.open_category(category, desktop_box=True)
                panel.resize(box_width, box_height)
                position = self.settings.category_positions.get(category.id)
                if position:
                    panel.move(position[0], position[1])
                else:
                    panel.move(
                        screen.left() + 18 + (index % columns) * (box_width + gap),
                        screen.top() + 18 + (index // columns) * (box_height + gap),
                    )
        else:
            raise ValueError(f"Unsupported display mode: {self.settings.display_mode}")

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        dock_menu = menu.addMenu("停靠位置")
        for edge, label in (("top", "顶部"), ("bottom", "底部"), ("left", "左侧"), ("right", "右侧")):
            action = dock_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(self.settings.dock_edge == edge)
            action.triggered.connect(lambda checked=False, value=edge: self.set_edge(value))
        mode_menu = menu.addMenu("显示方式")
        for mode, label in (("dock", "Dock 侧栏"), ("desktop", "桌面分类盒")):
            action = mode_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(self.settings.display_mode == mode)
            action.triggered.connect(lambda checked=False, value=mode: self.set_display_mode(value))
        menu.addSeparator()
        hide_icons_action = menu.addAction("隐藏桌面图标")
        hide_icons_action.setCheckable(True)
        hide_icons_action.setChecked(self.desktop_icons.hidden or not icons_visible())
        hide_icons_action.toggled.connect(self.set_icons_hidden)
        menu.addSeparator()
        menu.addAction("设置", self.open_settings)
        menu.addAction("shortcut 角色设定图", lambda: open_local_file(character_sheet()))
        menu.addAction("退出", QApplication.quit)
        menu.exec_(event.globalPos())

    def set_edge(self, edge: str) -> None:
        self.settings.dock_edge = edge
        save_settings(self.settings)
        self.rebuild()

    def set_display_mode(self, mode: str) -> None:
        self.settings.display_mode = mode
        save_settings(self.settings)
        self.activate_display_mode()

    def set_icons_hidden(self, hidden: bool) -> None:
        if hidden:
            self.desktop_icons.hide()
        else:
            self.desktop_icons.show()
