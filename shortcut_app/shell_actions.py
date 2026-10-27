"""Windows Shell verbs and the native menu for original file/shortcut paths."""

import ctypes as C
from ctypes import wintypes as W
import os
from pathlib import Path
import sys

from PyQt5.QtCore import QPoint
from PyQt5.QtGui import QCursor
from PyQt5.QtWidgets import QApplication


class _ExecuteInfo(C.Structure):
    _fields_ = [('cbSize', W.DWORD), ('fMask', C.c_ulong), ('hwnd', W.HWND),
               ('lpVerb', W.LPCWSTR), ('lpFile', W.LPCWSTR), ('lpParameters', W.LPCWSTR),
               ('lpDirectory', W.LPCWSTR), ('nShow', C.c_int), ('hInstApp', W.HINSTANCE),
               ('lpIDList', C.c_void_p), ('lpClass', W.LPCWSTR), ('hkeyClass', W.HKEY),
               ('dwHotKey', W.DWORD), ('hIcon', W.HANDLE), ('hProcess', W.HANDLE)]


def native_menu_selection(paths):
    """Shell selections need a shared parent; never silently pick only one item."""
    return bool(paths) and len({os.path.normcase(os.path.dirname(os.path.abspath(path)))
                               for path in paths}) == 1


def native_point(point):
    screen = QApplication.screenAt(point) or QApplication.primaryScreen()
    if screen is None:
        return QPoint(point)
    origin, ratio = screen.geometry().topLeft(), screen.devicePixelRatio()
    return QPoint(round(origin.x() + (point.x() - origin.x()) * ratio),
                  round(origin.y() + (point.y() - origin.y()) * ratio))


class WindowsShell:
    def __init__(self, owner):
        self.owner = owner
        self._ole = self._shell = self._native = None
        app = QApplication.instance()
        if app:
            app.aboutToQuit.connect(self.close)

    def _initialize(self):
        if self._ole is not None:
            return
        ole = C.WinDLL('ole32')
        ole.CoInitializeEx.argtypes, ole.CoInitializeEx.restype = [C.c_void_p, W.DWORD], C.c_long
        ole.CoUninitialize.argtypes = []
        result = ole.CoInitializeEx(None, 2)
        if result < 0:
            raise OSError('无法初始化 Windows Shell (0x%08X)' % (result & 0xffffffff))
        # Keep the apartment alive for property pages and Shell extension windows.
        self._ole = ole

    def close(self):
        if self._ole is not None:
            self._ole.CoUninitialize()
            self._ole = None

    def invoke(self, path, verb):
        if verb not in ('open', 'runas', 'properties'):
            raise ValueError('Unsupported Shell verb')
        self._initialize()
        if self._shell is None:
            self._shell = C.WinDLL('shell32', use_last_error=True)
            self._shell.ShellExecuteExW.argtypes = [C.POINTER(_ExecuteInfo)]
            self._shell.ShellExecuteExW.restype = W.BOOL
        path = os.path.abspath(path)
        info = _ExecuteInfo()
        info.cbSize = C.sizeof(info)
        # INVOKEIDLIST supports properties/context verbs; NOASYNC completes binding
        # before return. FLAG_NO_UI lets the caller give one consistent error.
        info.fMask = 0x0000000c | 0x00000100 | 0x00000400
        info.hwnd = int(self.owner.winId())
        info.lpVerb, info.lpFile, info.nShow = verb, path, 1
        # Let a .lnk supply its saved arguments, working directory and flags.
        info.lpDirectory = None if path.lower().endswith('.lnk') or verb == 'properties' else os.path.dirname(path)
        if not self._shell.ShellExecuteExW(C.byref(info)):
            error = C.get_last_error()
            if error == 1223:  # User declined UAC: do not retry or launch normally.
                return False
            raise C.WinError(error)
        return True

    def reveal(self, path):
        self._initialize()
        shell = C.WinDLL('shell32', use_last_error=True)
        shell.SHParseDisplayName.argtypes = [W.LPCWSTR, C.c_void_p, C.POINTER(C.c_void_p), W.DWORD, C.c_void_p]
        shell.SHParseDisplayName.restype = C.c_long
        shell.SHOpenFolderAndSelectItems.argtypes = [C.c_void_p, W.UINT, C.c_void_p, W.DWORD]
        shell.SHOpenFolderAndSelectItems.restype = C.c_long
        self._ole.CoTaskMemFree.argtypes = [C.c_void_p]
        item = C.c_void_p()
        result = shell.SHParseDisplayName(os.path.abspath(path), None, C.byref(item), 0, None)
        if result < 0:
            raise OSError('无法定位原文件 (0x%08X)' % (result & 0xffffffff))
        try:
            result = shell.SHOpenFolderAndSelectItems(item, 0, None, 0)
            if result < 0:
                raise OSError('无法在资源管理器中定位文件 (0x%08X)' % (result & 0xffffffff))
        finally:
            self._ole.CoTaskMemFree(item)
        return True

    def context_menu(self, paths, point=None):
        if not native_menu_selection(paths):
            raise ValueError('Windows 原生菜单需要选择同一目录内的项目。')
        self._initialize()
        if self._native is None:
            root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
            library = root / 'native_desktop' / 'ShortcutShell.dll'
            if not library.is_file():
                raise OSError('缺少 Windows 右键菜单组件，请重新构建原生组件。')
            native = C.WinDLL(str(library))
            try:
                function = native.ShowShellContextMenu
            except AttributeError as error:
                raise OSError('右键菜单组件版本不匹配，请重新构建 ShortcutShell.dll。') from error
            function.argtypes = [W.HWND, C.c_void_p, W.UINT, C.c_int, C.c_int]
            function.restype = C.c_long
            self._native = native
        payload = ('\0'.join(os.path.abspath(path) for path in paths) + '\0\0').encode('utf-16-le')
        buffer = C.create_string_buffer(payload)
        position = native_point(point if point is not None else QCursor.pos())
        result = self._native.ShowShellContextMenu(int(self.owner.winId()), buffer,
                                                 len(payload) // 2, position.x(), position.y())
        if result < 0 and (result & 0xffffffff) != 0x800704c7:
            raise OSError('Windows 原生菜单操作失败 (0x%08X)' % (result & 0xffffffff))
        return result == 0
