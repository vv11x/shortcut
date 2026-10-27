# -*- coding: utf-8 -*-
"""实时偏好设置；通过 Shortcut 接口保存设置，不再次导入程序入口。"""

import os
from .branding import application_icon
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider,
    QCheckBox, QRadioButton, QButtonGroup, QComboBox, QPushButton,
    QStackedWidget, QListWidget, QListWidgetItem, QFrame, QFileDialog,
    QScrollArea, QApplication, QSpinBox,
)


class PreferencesDialog(QDialog):
    def __init__(self, shortcut, parent=None):
        super().__init__(parent)
        self.shortcut = shortcut
        self.cfg = shortcut.cfg
        self.controls = {}
        self._slider_labels = {}
        self._mode_controls = []
        self._category_signature = None
        self.setWindowTitle("shortcut 偏好设置")
        self.setWindowIcon(application_icon())
        self.resize(820, 620)
        self.setMinimumSize(560, 360)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        screen = QApplication.screenAt(self.pos()) or QApplication.primaryScreen()
        if screen:
            area = screen.availableGeometry()
            self.resize(min(820, area.width() - 24), min(620, area.height() - 24))
        self._init_ui()
        self.refresh_theme()
        if self.shortcut.organizer:
            self.shortcut.organizer.changed.connect(self._refresh_categories)

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 10)
        row = QHBoxLayout()
        row.setSpacing(0)
        self.nav = QListWidget()
        self.nav.setFixedWidth(156)
        self.nav.setObjectName("nav_list")
        self.nav.setIconSize(QSize(20, 20))
        for title in ("外观与毛玻璃", "位置与尺寸", "动效与交互", "显示模式与桌面", "分类与图标", "系统与常规"):
            item = QListWidgetItem(title)
            item.setSizeHint(QSize(140, 42))
            self.nav.addItem(item)
        self.pages = QStackedWidget()
        self.pages.setObjectName("pages")
        for make_page in (self._page_appearance, self._page_position, self._page_animation,
                          self._page_desktop_folders, self._page_categories, self._page_system):
            self.pages.addWidget(self._scroll(make_page()))
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.setCurrentRow(0)
        row.addWidget(self.nav)
        row.addWidget(self.pages, 1)
        root.addLayout(row, 1)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setContentsMargins(16, 2, 16, 2)
        self.message.hide()
        root.addWidget(self.message)
        footer = QHBoxLayout()
        footer.setContentsMargins(16, 0, 16, 0)
        footer.addWidget(self._sub("偏好设置即时保存；分类管理中的编辑需单独保存。"), 1)
        close = QPushButton("关闭")
        close.setAutoDefault(False)
        close.clicked.connect(self.close)
        footer.addWidget(close)
        root.addLayout(footer)
        self._sync_applicability()

    def _apply_style(self):
        light = self.shortcut.is_light()
        bg, fg = ("#ffffff", "#222833") if light else ("#1e222b", "#f0f2f5")
        nav, border = ("#f5f6f9", "#e2e5eb") if light else ("#181a21", "#353d4d")
        field = "#eef2f7" if light else "#2c3240"
        self.setStyleSheet(f"""
            QDialog, #pages, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {bg}; color: {fg}; }}
            QWidget {{ color: {fg}; font-family: 'Microsoft YaHei UI', 'Segoe UI'; font-size: 13px; }}
            #nav_list {{ background: {nav}; border: none; border-right: 1px solid {border}; outline: none; padding-top: 10px; }}
            #nav_list::item {{ padding-left: 9px; border-radius: 6px; margin: 3px 6px; }}
            #nav_list::item:selected {{ background: #3b82f6; color: white; }}
            QLabel[header='true'] {{ font-size: 16px; font-weight: bold; }}
            QLabel[sub='true'] {{ color: {'#667387' if light else '#adb8ca'}; font-size: 12px; }}
            QCheckBox, QRadioButton {{ spacing: 7px; }}
            QWidget:disabled {{ color: {'#8893a3' if light else '#737e91'}; }}
            QPushButton, QComboBox, QSpinBox {{ background: {field}; border: 1px solid {border}; border-radius: 6px; padding: 6px; }}
            QPushButton:hover {{ border-color: #3b82f6; }}
            QSlider::groove:horizontal {{ height: 4px; background: {border}; border-radius: 2px; }}
            QSlider::sub-page:horizontal {{ background: #3b82f6; }}
            QSlider::handle:horizontal {{ background: white; border: 2px solid #3b82f6; width: 14px; margin: -5px 0; border-radius: 7px; }}
            QScrollArea {{ border: none; }}
        """)

    def refresh_theme(self):
        self._apply_style()
        self._sync_values()
        self._refresh_categories()

    def refresh_mode(self):
        """托盘或其他入口切换模式时同步当前设置窗口。"""
        self._sync_values()

    def showEvent(self, event):
        self.refresh_theme()
        super().showEvent(event)

    def _sync_values(self):
        """同步外部入口修改的值，不触发保存或系统操作。"""
        for key, control in self.controls.items():
            if key not in self.cfg:
                continue
            value = self.cfg[key]
            blocked = control.blockSignals(True)
            if isinstance(control, QCheckBox):
                control.setChecked(bool(value))
            elif isinstance(control, QComboBox):
                control.setCurrentIndex(control.findData(value))
            elif isinstance(control, (QSlider, QSpinBox)):
                control.setValue(int(value))
            control.blockSignals(blocked)
        screen = self.controls["screen"]
        name = self.cfg.get("screen_name", "")
        index = next((i for i in range(screen.count()) if screen.itemData(i)[1] == name), -1) if name else -1
        if index < 0:
            current = (self.cfg.get("screen_index", -1), name)
            index = next((i for i in range(screen.count()) if screen.itemData(i) == current), -1)
        blocked = screen.blockSignals(True)
        screen.setCurrentIndex(index)
        screen.blockSignals(blocked)
        for key, (label, title) in self._slider_labels.items():
            label.setText(f"{title}：{self.controls[key].value()}")
        self._sync_applicability()

    @staticmethod
    def _sub(text):
        label = QLabel(text)
        label.setTextFormat(Qt.PlainText)
        label.setWordWrap(True)
        label.setProperty("sub", True)
        return label

    def _page(self, title):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(13)
        header = QLabel(title)
        header.setWordWrap(True)
        header.setProperty("header", True)
        layout.addWidget(header)
        return widget, layout

    @staticmethod
    def _scroll(content):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(content)
        return scroll

    def _control(self, key, widget, mode=None):
        widget.setObjectName(key)
        self.controls[key] = widget
        if mode:
            self._mode_controls.append((widget, mode))
        return widget

    def _check(self, layout, key, text, callback, default=False, mode=None):
        box = self._control(key, QCheckBox(text), mode)
        box.setChecked(bool(self.cfg.get(key, default)))
        box.toggled.connect(lambda value: self._invoke(callback, value))
        layout.addWidget(box)
        return box

    def _choice(self, layout, key, title, choices, current, callback, mode=None):
        layout.addWidget(self._sub(title))
        combo = self._control(key, QComboBox(), mode)
        for text, value in choices:
            combo.addItem(text, value)
        index = next((i for i in range(combo.count()) if combo.itemData(i) == current), -1)
        combo.setCurrentIndex(max(0, index))
        combo.currentIndexChanged.connect(lambda index: self._invoke(callback, combo.itemData(index)))
        layout.addWidget(combo)
        return combo

    def _slider(self, layout, key, title, minimum, maximum, default, callback, mode=None):
        label = self._sub("")
        value = max(minimum, min(maximum, int(self.cfg.get(key, default))))
        slider = self._control(key, QSlider(Qt.Horizontal), mode)
        slider.setRange(minimum, maximum)
        slider.setValue(value)
        label.setText(f"{title}：{value}")
        self._slider_labels[key] = (label, title)
        slider.valueChanged.connect(lambda value: label.setText(f"{title}：{value}"))
        slider.valueChanged.connect(lambda value: self._invoke(callback, value))
        layout.addWidget(label)
        layout.addWidget(slider)
        return slider

    def _spin(self, layout, key, title, minimum, maximum, default):
        layout.addWidget(self._sub(title))
        spin = self._control(key, QSpinBox(), "shortcut")
        spin.setRange(minimum, maximum)
        spin.setValue(int(self.cfg.get(key, default)))
        spin.setSuffix(" px")
        spin.valueChanged.connect(lambda value: self._invoke(self._save_value, key, value, "refresh_geometry"))
        layout.addWidget(spin)
        return spin

    def _invoke(self, callback, *args):
        self.message.hide()
        try:
            return callback(*args)
        except Exception as error:
            self._show_message("设置未完成：" + str(error))
            raise

    def _show_message(self, text):
        self.message.setText(text)
        self.message.show()

    def _save_value(self, key, value, refresh=None):
        self.cfg[key] = value
        self.shortcut.save_preferences()
        if refresh:
            getattr(self.shortcut, refresh)()
        self._sync_applicability()

    def _flag(self, key, value, **kwargs):
        self.shortcut.tray.set_flag(key, value, **kwargs)
        self._sync_applicability()

    @staticmethod
    def _set_checked(control, checked):
        was_blocked = control.blockSignals(True)
        control.setChecked(checked)
        control.blockSignals(was_blocked)

    def _sync_applicability(self):
        folders = bool(self.cfg.get("desktop_folder_mode", False))
        for control, mode in self._mode_controls:
            enabled = folders if mode == "folders" else not folders
            control.setEnabled(enabled)
            control.setToolTip("仅在桌面文件夹模式下使用" if mode == "folders" else "仅在 Shortcut 侧栏模式下使用")
        for key in ("mode_shortcut", "mode_folders"):
            if key in self.controls:
                self._set_checked(self.controls[key], folders == (key == "mode_folders"))
        glass = bool(self.cfg.get("glass", True))
        for key, enabled, tip in (
            ("blur_px", glass, "启用毛玻璃后可调整模糊强度"),
            ("blur_mode", glass and not folders, "仅控制 Shortcut 的背景抓取；需启用毛玻璃"),
            ("bump_level", not folders and bool(self.cfg.get("magnify", True)), "仅在 Shortcut 模式且启用悬停放大时使用"),
            ("custom_bottom", not folders and self.cfg.get("position") == "custom", "选择自定义高度停靠时使用"),
            ("bottom_margin", not folders and self.cfg.get("position") != "custom", "四边停靠时与屏幕工作区边缘的间距"),
        ):
            if key in self.controls:
                self.controls[key].setEnabled(enabled)
                self.controls[key].setToolTip(tip)

    def _page_appearance(self):
        widget, layout = self._page("外观与毛玻璃")
        self._check(layout, "glass", "启用毛玻璃背景", lambda value: self._flag("glass", value, glass=True), True)
        self._slider(layout, "transparency", "玻璃通透度（%）", 0, 100, 40, self.shortcut.tray.set_transparency)
        layout.addWidget(self._sub("数值越大越通透；外观设置同时适用于当前显示模式及分类面板。"))
        self._slider(layout, "blur_px", "背景模糊强度", 2, 50, 6, self.shortcut.tray.set_blur)
        self._choice(layout, "theme", "颜色主题", [("跟随系统", "auto"), ("浅色玻璃", "light"),
                     ("深色夜间", "dark"), ("通透光感", "gloss")], self.cfg.get("theme", "auto"), self._set_theme)
        self._choice(layout, "blur_mode", "Shortcut 背景刷新频率（桌面文件夹按显示和变化刷新）", [
            ("智能省电", "smart"), ("每秒一次", "fast"), ("每 3 秒", "normal"),
            ("每 10 秒", "slow"), ("静态背景，仅显示时抓取", "off")],
            self.cfg.get("blur_mode", "smart"), lambda value: self._save_value("blur_mode", value, "start_backdrop"), "shortcut")
        self._check(layout, "sep_split", "在分隔符处切断 Shortcut 玻璃底板",
                    lambda value: self._flag("sep_split", value, geometry=True), mode="shortcut")
        layout.addWidget(self._sub("分隔符与背景刷新频率为 Shortcut 专用设置，桌面文件夹模式下不可调整。"))
        layout.addStretch()
        return widget

    def _set_theme(self, value):
        self.shortcut.tray.set_theme(value)
        self.refresh_theme()

    def _page_position(self):
        widget, layout = self._page("位置、尺寸与显示屏")
        layout.addWidget(self._sub("停靠、尺寸和层级仅用于 Shortcut；显示屏选择对两种模式均有效。桌面分类盒可独立拖动。"))
        self._choice(layout, "position", "停靠位置", [("屏幕底部", "bottom"), ("屏幕顶部", "top"),
                     ("屏幕左侧", "left"), ("屏幕右侧", "right"), ("自定义水平高度", "custom")],
                     self.cfg.get("position", "bottom"), self._set_position, "shortcut")
        self._spin(layout, "custom_bottom", "自定义模式：距工作区底部的高度", 0, 10000, 200)
        self._spin(layout, "bottom_margin", "四边停靠：距工作区边缘的间距", 0, 1000, 6)
        choices = [("跟随主显示屏", (-1, ""))]
        for index, screen in enumerate(QApplication.screens()):
            geometry = screen.geometry()
            choices.append((f"显示屏 {index + 1} · {screen.name()} ({geometry.width()}×{geometry.height()})", (index, screen.name())))
        current = (self.cfg.get("screen_index", -1), self.cfg.get("screen_name", ""))
        if current[1]:
            current = next((value for _, value in choices if value[1] == current[1]), current)
        self._choice(layout, "screen", "显示屏", choices, current, lambda value: self.shortcut.set_screen(*value))
        self._slider(layout, "icon_size", "Shortcut 图标大小（px）", 24, 256, 52, self.shortcut.tray.set_icon_size, "shortcut")
        self._check(layout, "fixed_shortcut_bar", "固定 Shortcut 玻璃底座长度", lambda value: self._flag("fixed_shortcut_bar", value, geometry=True), True, "shortcut")
        self._choice(layout, "layer", "窗口层级", [("置于普通窗口之下", "bottom"), ("始终置顶", "top")],
                     self.cfg.get("layer", "bottom"), self.shortcut.tray.set_layer, "shortcut")
        layout.addStretch()
        return widget

    def _set_position(self, value):
        self.shortcut.set_position(value)
        self._sync_applicability()

    def _page_animation(self):
        widget, layout = self._page("动效与交互")
        self._check(layout, "single_click_launch", "分类面板单击打开文件或应用", self._set_single_click, True)
        layout.addWidget(self._sub("关闭后双击打开；两种模式都可使用 Ctrl / Shift 多选、Enter 打开。"))
        layout.addWidget(self._sub("分类盒按下时轻缩，松开后展开分类；面板从点击位置滑入，点击外部或按 Esc 收回。"))
        self._check(layout, "launch_bounce", "点击 Shortcut 图标时播放跳动动画", lambda value: self._save_value("launch_bounce", value), True, "shortcut")
        self._check(layout, "magnify", "启用 Shortcut 鼠标悬停放大", lambda value: self._flag("magnify", value), True, "shortcut")
        self._choice(layout, "bump_level", "悬停放大程度", [("轻微", "low"), ("中等", "mid"), ("明显", "high")],
                     self.cfg.get("bump_level", "mid"), lambda value: self._save_value("bump_level", value, "refresh_geometry"), "shortcut")
        self._check(layout, "show_name", "悬停时显示 Shortcut 图标名称", lambda value: self._flag("show_name", value, geometry=True), True, "shortcut")
        self._check(layout, "running_dots", "显示固定应用的运行标记", lambda value: self._flag("running_dots", value, running=True), True, "shortcut")
        self._check(layout, "reorder", "允许拖动调整固定 Shortcut 图标的顺序", lambda value: self._flag("reorder", value), True, "shortcut")
        self._check(layout, "show_search", "显示 Shortcut 搜索按钮", self.shortcut.set_search_enabled, mode="shortcut")
        layout.addWidget(self._sub("悬停放大、名称、运行标记、跳动及搜索按钮仅用于 Shortcut。图标按压反馈由当前界面自动提供。"))
        layout.addStretch()
        return widget

    def _set_single_click(self, value):
        self._save_value("single_click_launch", bool(value))
        if self.shortcut.category_panel:
            self.shortcut.category_panel.set_single_click(value)

    def _page_desktop_folders(self):
        widget, layout = self._page("显示模式与桌面")
        layout.addWidget(self._sub("两种显示模式互斥，分类内容与原文件位置保持不变。"))
        layout.addWidget(self._sub("启用后按下方桌面图标设置收纳；隐藏界面或退出程序会恢复原生图标，重新显示后继续收纳。"))
        group = QButtonGroup(widget)
        folders = bool(self.cfg.get("desktop_folder_mode", False))
        for key, title, enabled in (("mode_shortcut", "Shortcut 侧栏", False), ("mode_folders", "桌面虚拟文件夹", True)):
            button = self._control(key, QRadioButton(title))
            group.addButton(button)
            button.setChecked(folders == enabled)
            button.toggled.connect(lambda checked, value=enabled: self._invoke(self._set_mode, value) if checked else None)
            layout.addWidget(button)
        layout.addWidget(self._sub("桌面模式为每个分类显示一个可拖动的大玻璃盒；点击盒子打开分类面板。"))
        self._choice(layout, "folder_grid_size", "桌面盒内缩略图排列", [("4×4（默认）", "4x4"), ("3×3", "3x3"), ("2×2", "2x2")],
                     self.cfg.get("folder_grid_size", "4x4"), self.shortcut.set_folder_grid_size, "folders")
        layout.addWidget(self._sub("缩略图排列仅适用于桌面文件夹模式。"))
        self._choice(layout, "desktop_display", "Windows 原生桌面图标", [("收纳当前界面中的项目", "managed"),
                     ("显示全部图标", "all"), ("隐藏全部图标", "hidden")], self.cfg.get("desktop_display", "managed"), self._set_desktop_display)
        layout.addWidget(self._sub("此选项控制 Windows 原生图标；已分类内容仍可从当前模式打开。"))
        layout.addWidget(self._sub("桌面盒会同时收纳未归类项目，保留原生回收站；从分类中移除的项目仍显示在原生桌面。"))
        layout.addStretch()
        return widget

    def _set_mode(self, folders):
        try:
            result = self.shortcut.set_desktop_folder_mode(folders)
        finally:
            self._sync_applicability()
        if result is False:
            self._show_message("显示模式切换未完成，已保留原设置。")

    def _set_desktop_display(self, mode):
        if self.shortcut.set_desktop_display(mode) is False:
            combo = self.controls["desktop_display"]
            old = combo.blockSignals(True)
            combo.setCurrentIndex(combo.findData(self.cfg.get("desktop_display", "managed")))
            combo.blockSignals(old)
            self._show_message("Windows 桌面显示设置未完成，已保留原设置。")

    def _page_categories(self):
        widget, layout = self._page("分类与自定义图标")
        layout.addWidget(self._sub("图标可使用图片或 ICO 文件；恢复默认后使用分类图标或桌面盒内的缩略图。"))
        organizer = self.shortcut.organizer
        manage = QPushButton("管理分类、规则与分隔符…")
        manage.setObjectName("manage_categories")
        manage.setAutoDefault(False)
        manage.setEnabled(organizer is not None)
        manage.clicked.connect(lambda: self._invoke(self._manage_categories))
        layout.addWidget(manage)
        scan = QPushButton("立即整理桌面")
        scan.setObjectName("scan_desktop")
        scan.setAutoDefault(False)
        scan.setEnabled(organizer is not None)
        scan.clicked.connect(lambda: self._invoke(organizer.request_scan))
        layout.addWidget(scan)
        if organizer:
            automatic = QCheckBox("自动整理桌面变化")
            automatic.setObjectName("automatic")
            automatic.setChecked(bool(organizer.state.get("automatic", True)))
            automatic.toggled.connect(lambda value: self._invoke(organizer.set_automatic, value))
            layout.addWidget(automatic)
        categories = organizer.state.get("categories", []) if organizer else []
        if not categories:
            layout.addWidget(self._sub("暂无分类。点击“管理分类、规则与分隔符”创建分类后，再设置图标。"))
        custom = self.cfg.get("category_custom_icons", {})
        for category in categories:
            cid, name = category["id"], category["name"]
            frame = QFrame()
            row = QHBoxLayout(frame)
            icon = QLabel()
            icon.setFixedSize(36, 36)
            artwork = self.shortcut._category_artwork(category)
            if artwork:
                dpr = self.devicePixelRatioF()
                preview = artwork.scaled(round(36 * dpr), round(36 * dpr), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                preview.setDevicePixelRatio(dpr)
                icon.setPixmap(preview)
            row.addWidget(icon)
            path = custom.get(cid)
            text = QLabel(name + ("\n已自定义：" + os.path.basename(path) if path else "\n默认图标"))
            text.setTextFormat(Qt.PlainText)
            text.setWordWrap(True)
            row.addWidget(text, 1)
            pick = QPushButton("更换图标…")
            pick.setAutoDefault(False)
            pick.setObjectName("pick_icon_" + cid)
            pick.clicked.connect(lambda checked=False, category_id=cid, category_name=name:
                                 self._invoke(self._pick_icon, category_id, category_name))
            row.addWidget(pick)
            if path:
                reset = QPushButton("恢复")
                reset.setAutoDefault(False)
                reset.setObjectName("reset_icon_" + cid)
                reset.clicked.connect(lambda checked=False, category_id=cid: self._invoke(self._set_icon, category_id, None))
                row.addWidget(reset)
            layout.addWidget(frame)
        layout.addStretch()
        return widget

    def _pick_icon(self, category_id, name):
        path, _ = QFileDialog.getOpenFileName(self, f"选择分类【{name}】的图标", "",
                                             "图片与图标 (*.png *.ico *.jpg *.jpeg *.svg);;所有文件 (*.*)")
        if path:
            self._set_icon(category_id, path)

    def _set_icon(self, category_id, path):
        if self.shortcut.set_category_custom_icon(category_id, path) is False:
            self._show_message("无法读取该图标，请选择有效的图片或 ICO 文件。")
            return
        self._refresh_categories()

    def _manage_categories(self):
        self.shortcut.manage_categories()
        self._refresh_categories()

    def _refresh_categories(self):
        organizer = self.shortcut.organizer
        categories = organizer.state.get("categories", []) if organizer else []
        custom = self.cfg.get("category_custom_icons", {})
        signature = (self.shortcut.is_light(), tuple((c["id"], c["name"], c.get("icon"), custom.get(c["id"])) for c in categories),
                     organizer.state.get("automatic", True) if organizer else None)
        if signature == self._category_signature:
            return
        self._category_signature = signature
        if not hasattr(self, "pages") or self.pages.count() < 5:
            return
        selected = self.pages.currentIndex()
        old = self.pages.widget(4)
        scroll_position = old.verticalScrollBar().value()
        self.pages.removeWidget(old)
        replacement = self._scroll(self._page_categories())
        self.pages.insertWidget(4, replacement)
        self.pages.setCurrentIndex(selected)
        replacement.widget().adjustSize()
        replacement.verticalScrollBar().setValue(scroll_position)
        old.deleteLater()

    def _page_system(self):
        widget, layout = self._page("系统与常规")
        self._check(layout, "autostart", "随 Windows 登录自动启动", self._set_autostart)
        self._choice(layout, "lang", "菜单语言 / Menu language", [("简体中文", "zh"), ("English", "en")],
                     self.cfg.get("lang", "zh"), self.shortcut.set_language)
        layout.addWidget(self._sub("语言选择应用于已提供翻译的菜单；部分设置与分类界面仍使用中文。"))
        trim = QPushButton("整理进程内存")
        trim.setAutoDefault(False)
        trim.setObjectName("trim_memory")
        trim.clicked.connect(lambda: self._invoke(self._trim_memory))
        layout.addWidget(trim)
        layout.addWidget(self._sub("请求回收闲置内存，实际占用由桌面规模、图标与系统状态决定。"))
        folder = QPushButton("打开用户配置目录…")
        folder.setAutoDefault(False)
        folder.setObjectName("open_config_directory")
        folder.clicked.connect(lambda: self._invoke(self.shortcut.open_config_directory))
        layout.addWidget(folder)
        layout.addStretch()
        return widget

    def _set_autostart(self, value):
        try:
            result = self.shortcut.set_autostart_enabled(value)
        except Exception as error:
            self._set_checked(self.controls["autostart"], bool(self.cfg.get("autostart", False)))
            self._show_message("自启动设置未完成：" + str(error))
            raise
        if result is False:
            self._set_checked(self.controls["autostart"], bool(self.cfg.get("autostart", False)))
            self._show_message("自启动设置未完成，请检查注册表访问权限后重试。")

    def _trim_memory(self):
        result = self.shortcut.trim_memory()
        self._show_message("已请求整理闲置内存。" if result is not False else "暂时无法整理内存，请稍后重试。")
