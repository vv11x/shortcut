import sys
import logging

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from shortcut.catalog import DesktopCatalog
from shortcut.dock_window import ShortcutDock
from shortcut.resources import character_sheet, mascot_image
from shortcut.shell import open_local_file, open_recycle_bin
from shortcut.storage import load_settings
from shortcut.theme import get_menu_qss, get_tooltip_qss
from shortcut.windows_desktop import DesktopIconController, SingleInstance, icons_visible, marker_path, recover_stale_session


def run_gui() -> int:
    instance = SingleInstance()
    if instance.already_running:
        return 0
    logging.info("single-instance lock acquired")
    if marker_path().exists() and not recover_stale_session():
        raise RuntimeError("A desktop icon session belongs to a running shortcut process")

    QApplication.setApplicationName("shortcut")
    QApplication.setOrganizationName("vv11x")
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(QIcon(str(mascot_image())))

    settings = load_settings()
    app.setStyleSheet(get_tooltip_qss(settings.theme))
    catalog = DesktopCatalog(settings)
    catalog.refresh()
    logging.info("desktop catalog loaded: %d entries", len(catalog.entries))
    desktop_icons = DesktopIconController()
    dock = ShortcutDock(settings, catalog, desktop_icons)
    dock.activate_display_mode()
    logging.info("dock window shown")

    tray = QSystemTrayIcon(QIcon(str(mascot_image())), app)
    menu = QMenu()
    menu.setStyleSheet(get_menu_qss(settings.theme))
    show_action = QAction("显示 shortcut", menu)
    show_action.triggered.connect(lambda: dock.set_display_mode("dock"))
    refresh_action = QAction("刷新桌面项目", menu)
    refresh_action.triggered.connect(dock.refresh_catalog)
    settings_action = QAction("设置", menu)
    settings_action.triggered.connect(dock.open_settings)
    recycle_action = QAction("打开回收站", menu)
    recycle_action.triggered.connect(open_recycle_bin)
    character_action = QAction("角色设定图", menu)
    character_action.triggered.connect(lambda: open_local_file(character_sheet()))
    hide_icons_action = QAction("隐藏桌面图标", menu)
    hide_icons_action.setCheckable(True)
    hide_icons_action.setChecked(desktop_icons.hidden or not icons_visible())
    hide_icons_action.toggled.connect(dock.set_icons_hidden)
    quit_action = QAction("退出 shortcut", menu)
    quit_action.triggered.connect(app.quit)
    menu.addAction(show_action)
    menu.addAction(refresh_action)
    menu.addAction(settings_action)
    menu.addAction(character_action)
    menu.addAction(recycle_action)
    menu.addSeparator()
    menu.addAction(hide_icons_action)
    menu.addSeparator()
    menu.addAction(quit_action)
    tray.setContextMenu(menu)
    tray.show()
    logging.info("system tray icon shown")

    app.aboutToQuit.connect(desktop_icons.stop)
    app.aboutToQuit.connect(instance.close)
    logging.info("entering Qt event loop")
    return app.exec_()
