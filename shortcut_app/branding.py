"""应用、窗口及托盘共用同一份图标和 Windows 应用标识。"""

import ctypes
from functools import lru_cache
from pathlib import Path
import sys

from PyQt5.QtGui import QIcon


APPLICATION_ID = 'vv11x.shortcut'


@lru_cache(maxsize=1)
def application_icon():
    root = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]
    path = root / 'assets/branding/shortcut.ico'
    if not path.is_file():
        raise FileNotFoundError(path)
    icon = QIcon(str(path))
    if icon.isNull():
        raise RuntimeError('无法读取 shortcut 应用图标：' + str(path))
    return icon


def configure_application(application):
    set_identity = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
    set_identity.argtypes = [ctypes.c_wchar_p]
    set_identity.restype = ctypes.c_long
    result = set_identity(APPLICATION_ID)
    if result < 0:
        raise OSError('设置 shortcut Windows 应用标识失败：0x%08X' % (result & 0xffffffff))
    application.setApplicationName('shortcut')
    application.setApplicationDisplayName('shortcut')
    application.setWindowIcon(application_icon())
