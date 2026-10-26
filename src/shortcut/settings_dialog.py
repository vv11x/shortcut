from copy import deepcopy

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from shortcut.models import AppSettings, Category, CategoryRule
from shortcut.resources import category_icon, category_icons


class SettingsDialog(QDialog):
    def __init__(self, settings: AppSettings, parent: QWidget | None = None):
        super().__init__(parent)
        self.settings = deepcopy(settings)
        self.setWindowTitle("shortcut 设置")
        self.setMinimumSize(720, 560)
        self.setStyleSheet(
            "QDialog { background: #20232b; color: #f4f5fa; }"
            "QLineEdit, QComboBox, QListWidget { color: #f4f5fa; background: #303541; border: 1px solid #4b5261; border-radius: 6px; padding: 6px; }"
            "QPushButton { color: #f4f5fa; background: #343946; border: 0; border-radius: 7px; padding: 7px 10px; }"
            "QPushButton:hover { background: #42495b; }"
        )

        root = QVBoxLayout(self)
        content = QHBoxLayout()
        root.addLayout(content, 1)

        left = QVBoxLayout()
        self.category_list = QListWidget()
        self.category_list.setDragDropMode(QListWidget.InternalMove)
        self.category_list.currentItemChanged.connect(self.switch_category)
        left.addWidget(self.category_list)
        category_buttons = QHBoxLayout()
        add_button = QPushButton("添加分类")
        remove_button = QPushButton("删除分类")
        add_button.clicked.connect(self.add_category)
        remove_button.clicked.connect(self.remove_category)
        category_buttons.addWidget(add_button)
        category_buttons.addWidget(remove_button)
        left.addLayout(category_buttons)
        content.addLayout(left, 1)

        form_widget = QWidget()
        form = QFormLayout(form_widget)
        self.name_edit = QLineEdit()
        self.icon_combo = QComboBox()
        for icon_name, title in category_icons():
            self.icon_combo.addItem(QIcon(str(category_icon(icon_name))), title, icon_name)
        self.extensions_edit = QLineEdit()
        self.terms_edit = QLineEdit()
        self.kind_list = QListWidget()
        self.kind_list.setMaximumHeight(92)
        for kind, label in (("application", "应用"), ("file", "文件"), ("folder", "文件夹")):
            item = QListWidgetItem(label, self.kind_list)
            item.setData(Qt.UserRole, kind)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
        self.rule_mode_combo = QComboBox()
        self.rule_mode_combo.addItem("满足任一条件", "any")
        self.rule_mode_combo.addItem("满足全部条件", "all")
        form.addRow("分类名称", self.name_edit)
        form.addRow("角色图标", self.icon_combo)
        form.addRow("扩展名（逗号分隔）", self.extensions_edit)
        form.addRow("名称包含（逗号分隔）", self.terms_edit)
        form.addRow("项目类型", self.kind_list)
        form.addRow("匹配方式", self.rule_mode_combo)
        form.addRow(QLabel("“其他”收纳未匹配规则的项目；其他空规则分类只接收手动归属。"))
        content.addWidget(form_widget, 2)

        global_form = QFormLayout()
        self.edge_combo = QComboBox()
        for edge, label in (("top", "顶部"), ("bottom", "底部"), ("left", "左侧"), ("right", "右侧")):
            self.edge_combo.addItem(label, edge)
        self.display_combo = QComboBox()
        self.display_combo.addItem("Dock 侧栏", "dock")
        self.display_combo.addItem("桌面分类盒", "desktop")
        self.view_combo = QComboBox()
        self.view_combo.addItem("图标", "icons")
        self.view_combo.addItem("列表", "list")
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("深色", "dark")
        self.theme_combo.addItem("浅色", "light")
        self.archiver_edit = QLineEdit(self.settings.archiver_path)
        archiver_row = QHBoxLayout()
        archiver_row.addWidget(self.archiver_edit)
        archiver_button = QPushButton("选择")
        archiver_button.clicked.connect(self.choose_archiver)
        archiver_row.addWidget(archiver_button)
        global_form.addRow("Dock 位置", self.edge_combo)
        global_form.addRow("显示方式", self.display_combo)
        global_form.addRow("项目视图", self.view_combo)
        global_form.addRow("外观", self.theme_combo)
        global_form.addRow("7-Zip 命令行工具", archiver_row)
        hidden_row = QHBoxLayout()
        hidden_button = QPushButton("管理已隐藏项目…")
        hidden_button.clicked.connect(self.manage_hidden_entries)
        hidden_row.addWidget(hidden_button)
        global_form.addRow("快捷方式列表", hidden_row)
        root.addLayout(global_form)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept_changes)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.populate_categories()
        self.edge_combo.setCurrentIndex(self.edge_combo.findData(self.settings.dock_edge))
        self.display_combo.setCurrentIndex(self.display_combo.findData(self.settings.display_mode))
        self.view_combo.setCurrentIndex(self.view_combo.findData(self.settings.view_mode))
        self.theme_combo.setCurrentIndex(self.theme_combo.findData(self.settings.theme))

    def populate_categories(self, selected_id: str | None = None) -> None:
        self.category_list.blockSignals(True)
        self.category_list.clear()
        for category in self.settings.categories:
            item = QListWidgetItem(category.title)
            item.setData(Qt.UserRole, category.id)
            self.category_list.addItem(item)
            if category.id == selected_id:
                self.category_list.setCurrentItem(item)
        if self.category_list.count() and self.category_list.currentRow() < 0:
            self.category_list.setCurrentRow(0)
        self.category_list.blockSignals(False)
        self.load_category(self.category_list.currentItem())

    def category_for_id(self, category_id: str) -> Category:
        return next(category for category in self.settings.categories if category.id == category_id)

    def switch_category(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        if previous is not None:
            self.save_category(previous.data(Qt.UserRole))
        self.load_category(current)

    def save_category(self, category_id: str) -> None:
        category = self.category_for_id(category_id)
        category.title = self.name_edit.text().strip()
        category.icon = self.icon_combo.currentData()
        category.rule = CategoryRule(
            extensions=[
                item.strip().casefold() if item.strip().startswith(".") else f".{item.strip().casefold()}"
                for item in self.extensions_edit.text().split(",")
                if item.strip()
            ],
            name_terms=[item.strip() for item in self.terms_edit.text().split(",") if item.strip()],
            item_kinds=[
                self.kind_list.item(index).data(Qt.UserRole)
                for index in range(self.kind_list.count())
                if self.kind_list.item(index).checkState() == Qt.Checked
            ],
            mode=self.rule_mode_combo.currentData(),
        )
        for row in range(self.category_list.count()):
            item = self.category_list.item(row)
            if item.data(Qt.UserRole) == category_id:
                item.setText(category.title)
                break

    def load_category(self, item: QListWidgetItem | None) -> None:
        if item is None:
            return
        category = self.category_for_id(item.data(Qt.UserRole))
        self.name_edit.setText(category.title)
        self.icon_combo.setCurrentIndex(self.icon_combo.findData(category.icon))
        self.extensions_edit.setText(", ".join(category.rule.extensions))
        self.terms_edit.setText(", ".join(category.rule.name_terms))
        for index in range(self.kind_list.count()):
            kind_item = self.kind_list.item(index)
            kind_item.setCheckState(Qt.Checked if kind_item.data(Qt.UserRole) in category.rule.item_kinds else Qt.Unchecked)
        self.rule_mode_combo.setCurrentIndex(self.rule_mode_combo.findData(category.rule.mode))

    def add_category(self) -> None:
        title, accepted = QInputDialog.getText(self, "添加分类", "分类名称")
        if accepted and title.strip():
            category = Category.create(title.strip())
            self.settings.categories.append(category)
            self.populate_categories(category.id)

    def remove_category(self) -> None:
        item = self.category_list.currentItem()
        if item is None:
            return
        category = self.category_for_id(item.data(Qt.UserRole))
        if category.id == "other":
            QMessageBox.information(self, "无法删除", "“其他”分类用于收纳未匹配规则的项目。")
            return
        if len(self.settings.categories) == 1:
            QMessageBox.information(self, "无法删除", "至少保留一个分类。")
            return
        row = self.category_list.currentRow()
        self.settings.categories.remove(category)
        self.settings.manual_assignments = {
            path: category_id
            for path, category_id in self.settings.manual_assignments.items()
            if category_id != category.id
        }
        self.settings.entry_orders.pop(category.id, None)
        self.settings.category_positions.pop(category.id, None)
        self.populate_categories()
        self.category_list.setCurrentRow(min(row, self.category_list.count() - 1))

    def choose_archiver(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 7-Zip 命令行程序", self.archiver_edit.text(), "7-Zip executable (7z.exe)")
        if path:
            self.archiver_edit.setText(path)

    def manage_hidden_entries(self) -> None:
        paths = self.settings.dismissed_paths
        if not paths:
            QMessageBox.information(self, "已隐藏项目", "当前没有已隐藏项目。")
            return
        selected, accepted = QInputDialog.getItem(self, "恢复项目", "选择要恢复到分类列表的项目", paths, 0, False)
        if accepted:
            paths.remove(selected)

    def accept_changes(self) -> None:
        item = self.category_list.currentItem()
        if item is not None:
            self.save_category(item.data(Qt.UserRole))
        if not self.settings.categories:
            raise ValueError("At least one category is required")
        if any(not category.title for category in self.settings.categories):
            raise ValueError("Category names cannot be empty")
        icon_names = {name for name, label in category_icons()}
        if any(category.icon not in icon_names for category in self.settings.categories):
            raise ValueError("A category refers to an unknown icon")
        order = [self.category_list.item(index).data(Qt.UserRole) for index in range(self.category_list.count())]
        categories_by_id = {category.id: category for category in self.settings.categories}
        self.settings.categories = [categories_by_id[category_id] for category_id in order]
        self.settings.dock_edge = self.edge_combo.currentData()
        self.settings.display_mode = self.display_combo.currentData()
        self.settings.view_mode = self.view_combo.currentData()
        self.settings.theme = self.theme_combo.currentData()
        self.settings.archiver_path = self.archiver_edit.text().strip()
        self.accept()
