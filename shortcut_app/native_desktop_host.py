"""连接 Explorer 自己的桌面视图；仅在连接或文件事件时工作。"""

import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import sys
import threading

from PyQt5.QtCore import QTimer, QEventLoop, pyqtSignal
from PyQt5.QtNetwork import QLocalSocket
from PyQt5.QtWidgets import QApplication, QWidget

from .desktop_visibility import _desktop_view, shell_interface, _method, _check

P = C.c_void_p
READY, CLOSED = 0x8351, 0x8352
user = C.WinDLL('user32', use_last_error=True)
kernel = C.WinDLL('kernel32', use_last_error=True)
user.SetWindowsHookExW.argtypes = [C.c_int, P, P, C.c_uint]
user.SetWindowsHookExW.restype = P
user.UnhookWindowsHookEx.argtypes = [P]
user.UnhookWindowsHookEx.restype = C.c_int
user.RegisterWindowMessageW.argtypes = [C.c_wchar_p]
user.RegisterWindowMessageW.restype = C.c_uint
user.GetWindowThreadProcessId.argtypes = [P, C.POINTER(C.c_uint)]
user.GetWindowThreadProcessId.restype = C.c_uint
user.PostThreadMessageW.argtypes = [C.c_uint, C.c_uint, C.c_size_t, C.c_ssize_t]
user.PostThreadMessageW.restype = C.c_int
user.SendMessageTimeoutW.argtypes = [P, C.c_uint, C.c_size_t, C.c_ssize_t,
                                    C.c_uint, C.c_uint, C.POINTER(C.c_size_t)]
user.SendMessageTimeoutW.restype = C.c_ssize_t
user.FindWindowW.argtypes = [C.c_wchar_p, C.c_wchar_p]
user.FindWindowW.restype = P
user.FindWindowExW.argtypes = [P, P, C.c_wchar_p, C.c_wchar_p]
user.FindWindowExW.restype = P
user.GetClassNameW.argtypes = [P, C.c_wchar_p, C.c_int]
user.GetClassNameW.restype = C.c_int
user.IsWindow.argtypes = [P]
user.IsWindow.restype = C.c_int
user.PostMessageW.argtypes = [P, C.c_uint, C.c_size_t, C.c_ssize_t]
user.PostMessageW.restype = C.c_int
kernel.OpenProcess.argtypes = [C.c_uint, C.c_int, C.c_uint]
kernel.OpenProcess.restype = P
kernel.CreateEventW.argtypes = [P, C.c_int, C.c_int, C.c_wchar_p]
kernel.CreateEventW.restype = P
kernel.SetEvent.argtypes = [P]
kernel.WaitForMultipleObjects.argtypes = [C.c_uint, C.POINTER(P), C.c_int, C.c_uint]
kernel.CloseHandle.argtypes = [P]


class CopyData(C.Structure):
    _fields_ = [('tag', C.c_size_t), ('length', C.c_uint), ('data', P)]


class NativeDesktop(QWidget):
    ready = pyqtSignal()
    error = pyqtSignal(str)
    explorer_exited = pyqtSignal()
    stats_received = pyqtSignal(object)
    closed = pyqtSignal()

    def __init__(self, parent=None, owner_pid=0):
        super().__init__(parent)
        self.owner_pid = int(owner_pid)
        root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
        self.library = C.WinDLL(str(root / 'native_desktop' / 'ShortcutDesktop.dll'))
        self.hook = None
        self.bridge = None
        self.cancel = None
        self.watcher = None
        self.stopping = False
        self.connect_message = user.RegisterWindowMessageW('Shortcut.NativeDesktop.Connect.v1')
        self.winId()  # 仅作 IPC 接收端；从不显示窗口，不占用桌面层级。
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.setInterval(8000)
        self.timeout.timeout.connect(self._timeout)

    def connect_desktop(self):
        self.stopping = False
        hwnd = P()
        try:
            with _desktop_view() as view:
                with shell_interface(view, '000214E3-0000-0000-C000-000000000046') as shell_view:
                    _check(_method(shell_view, 3, C.POINTER(P))(shell_view, C.byref(hwnd)), '读取原生桌面窗口')
        except Exception:
            hwnd = P(0)
        if not hwnd or not user.IsWindow(hwnd):
            progman = user.FindWindowW('Progman', 'Program Manager')
            defview = user.FindWindowExW(progman, None, 'SHELLDLL_DefView', None)
            if not defview:
                w = None
                while True:
                    w = user.FindWindowExW(None, w, 'WorkerW', None)
                    if not w:
                        break
                    dv = user.FindWindowExW(w, None, 'SHELLDLL_DefView', None)
                    if dv:
                        defview = dv
                        break
            hwnd = P(defview) if defview else hwnd
        pid = C.c_uint()
        thread = user.GetWindowThreadProcessId(hwnd, C.byref(pid))
        if not thread:
            raise OSError('未能获取桌面线程 (HWND: %s)' % hwnd)
        self._wait_for_previous_connection(pid.value)
        self.hook = user.SetWindowsHookExW(3, C.cast(self.library.DesktopConnect, P),
                                          self.library._handle, thread)
        if not self.hook:
            raise C.WinError(C.get_last_error())
        if not user.PostThreadMessageW(thread, self.connect_message, int(self.winId()), self.owner_pid):
            self._unhook()
            raise C.WinError(C.get_last_error())
        process = kernel.OpenProcess(0x100000, False, pid.value)
        cancel = kernel.CreateEventW(None, True, False, None)
        if not process or not cancel:
            if process:
                kernel.CloseHandle(process)
            if cancel:
                kernel.CloseHandle(cancel)
            self._unhook()
            raise OSError('无法监测 Explorer 生命周期')
        self.cancel = cancel
        # 等待内核对象，不占用 Qt 线程，也没有每秒检查进程的循环。
        def watch():
            result = kernel.WaitForMultipleObjects(2, (P * 2)(cancel, process), False, 0xffffffff)
            if result == 1:
                self.explorer_exited.emit()
            kernel.CloseHandle(process)
            # cancel 由 stop() 在线程离开等待后关闭。
        self.watcher = threading.Thread(target=watch, name='Explorer lifetime', daemon=True)
        self.watcher.start()
        self.timeout.start()

    def _wait_for_previous_connection(self, explorer_pid):
        # 超时退出可能留下仍在恢复项目的连接；等它退出，不能叠加 Shell 回调。
        window = None
        pending = False
        while True:
            window = user.FindWindowExW(P(-3), window, None, None)
            if not window:
                break
            name = C.create_unicode_buffer(256)
            user.GetClassNameW(window, name, len(name))
            prefix = 'Shortcut.NativeDesktop.'
            if not name.value.startswith(prefix):
                continue
            owner = C.c_uint()
            user.GetWindowThreadProcessId(window, C.byref(owner))
            controller = name.value[len(prefix):]
            if owner.value != explorer_pid or not controller.isdecimal():
                continue
            if not user.IsWindow(int(controller)):
                user.PostMessageW(window, 0x10, 0, 0)  # 异步请求原组件恢复，不阻塞辅助进程。
            pending = True
        if pending:
            raise OSError('等待上一次原生桌面连接退出')

    def _unhook(self):
        if self.hook:
            user.UnhookWindowsHookEx(self.hook)
            self.hook = None

    def _timeout(self):
        self._unhook()
        self.error.emit('原生桌面组件连接超时')

    def nativeEvent(self, event_type, message):
        msg = W.MSG.from_address(int(message))
        if msg.message == READY:
            self.timeout.stop()
            self._unhook()
            hr = C.c_long(msg.lParam).value
            if hr < 0 or not msg.wParam:
                self.error.emit('当前 Windows 原生桌面不支持收纳 (0x%08X)' % (hr & 0xffffffff))
            else:
                self.bridge = int(msg.wParam)
                self.ready.emit()
            return True, 0
        if msg.message == CLOSED:
            self.bridge = None
            self.closed.emit()
            if not self.stopping:
                hr = C.c_long(msg.lParam).value
                self.error.emit('原生桌面收纳已停止 (0x%08X)' % (hr & 0xffffffff))
            return True, 0
        if msg.message == 0x4a:
            data = C.cast(msg.lParam, C.POINTER(CopyData)).contents
            if data.tag == 2 and data.length == 48:
                self.stats_received.emit(list(C.cast(data.data, C.POINTER(C.c_uint64 * 6)).contents))
            return True, 1
        return super().nativeEvent(event_type, message)

    def send(self, tag, payload=b'\0\0'):
        if not self.bridge:
            return
        buffer = C.create_string_buffer(payload)
        data = CopyData(tag, len(payload), C.cast(buffer, P))
        result = C.c_size_t()
        if not user.SendMessageTimeoutW(self.bridge, 0x4a, int(self.winId()), C.addressof(data),
                                       2, 5000, C.byref(result)):
            raise C.WinError(C.get_last_error())
        _check(C.c_long(result.value).value, '应用原生桌面收纳')

    def set_paths(self, paths):
        self.send(1, ('\0'.join(paths) + '\0\0').encode('utf-16-le'))

    def stop(self):
        if self.stopping:
            return
        self.stopping = True
        self.timeout.stop()
        self._unhook()
        if self.cancel:
            kernel.SetEvent(self.cancel)
            self.watcher.join(1)
            if not self.watcher.is_alive():
                kernel.CloseHandle(self.cancel)
            self.cancel = None
        if self.bridge:
            result = C.c_size_t()
            loop = QEventLoop()
            expiry = QTimer()
            expiry.setSingleShot(True)
            expiry.timeout.connect(loop.quit)
            self.closed.connect(loop.quit)
            user.SendMessageTimeoutW(self.bridge, 0x8354, 0, 0, 2, 5000, C.byref(result))
            if self.bridge:
                expiry.start(5500)
                loop.exec_()
            self.closed.disconnect(loop.quit)
            self.bridge = None


def run_native_desktop(endpoint, owner_pid=0):
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    socket = QLocalSocket()
    paths = []
    paths_received = False
    buffer = bytearray()
    attempts = 0
    finished = False
    native = None
    apply_failures = 0
    awaiting_ready = False
    retry_apply = QTimer()
    retry_apply.setSingleShot(True)
    retry_apply.setInterval(500)
    reconnect = QTimer()
    reconnect.setSingleShot(True)
    reconnect.setInterval(500)

    def report(message):
        socket.write((json.dumps(message, ensure_ascii=False) + '\n').encode('utf-8'))
        socket.flush()

    def stop():
        nonlocal finished
        if finished:
            return
        finished = True
        try:
            reconnect.stop()
        except Exception:
            pass
        try:
            retry_apply.stop()
        except Exception:
            pass
        if native:
            try:
                native.stop()
            except Exception:
                pass
        app.quit()

    def fail(message):
        if not finished:
            try:
                report({'error': message})
            finally:
                stop()

    def apply():
        nonlocal apply_failures, awaiting_ready
        if finished or not paths_received or not native or not native.bridge:
            return
        try:
            native.set_paths(paths)
        except Exception as error:
            # Explorer 短暂忙碌时仅重试两次；等待期间的分类变化合并为最新路径。
            if getattr(error, 'winerror', None) == 1460 and apply_failures < 2:
                apply_failures += 1
                retry_apply.start()
                return
            fail(str(error))
            return
        apply_failures = 0
        retry_apply.stop()
        if awaiting_ready and not finished:
            awaiting_ready = False
            report({'ready': True})

    def ready():
        nonlocal attempts, awaiting_ready
        attempts = 0
        awaiting_ready = True
        # 避开 Windows 回调重入；完成分类投递后再通知主 Shortcut。
        QTimer.singleShot(0, apply)

    def start():
        nonlocal attempts
        if finished:
            return
        attempts += 1
        try:
            native.connect_desktop()
        except OSError as error:
            if attempts < 20:
                reconnect.start()
            else:
                fail(str(error))
        except Exception as error:
            fail(str(error))

    def explorer_exited():
        nonlocal apply_failures, attempts, awaiting_ready
        if finished:
            return
        retry_apply.stop()
        apply_failures = 0
        attempts = 0
        awaiting_ready = False
        native.bridge = None
        native.stop()
        if not finished:
            reconnect.start()

    def read():
        nonlocal paths, paths_received
        if finished:
            return
        buffer.extend(bytes(socket.readAll()))
        updated = False
        try:
            while b'\n' in buffer:
                line, _, rest = buffer.partition(b'\n')
                buffer[:] = rest
                message = json.loads(line)
                if (not isinstance(message, dict) or not isinstance(message.get('paths'), list)
                        or any(not isinstance(path, str) or '\0' in path for path in message['paths'])):
                    raise ValueError('无效的桌面收纳路径消息')
                paths = message['paths']
                paths_received = updated = True
        except (ValueError, UnicodeError) as error:
            fail('桌面收纳通信失败：' + str(error))
            return
        if updated and native and native.bridge and not retry_apply.isActive():
            apply()

    socket.readyRead.connect(read)
    socket.disconnected.connect(stop)
    socket.errorOccurred.connect(lambda _: stop())
    try:
        socket.connectToServer(endpoint)
        if not socket.waitForConnected(3000) or finished:
            return 1
        # waitForConnected 期间可能已收到初始消息；即使不再触发 readyRead 也不能漏掉。
        read()
        if finished:
            return 1
        native = NativeDesktop(owner_pid=owner_pid)
        native.ready.connect(ready)
        native.error.connect(fail)
        native.explorer_exited.connect(explorer_exited)
        reconnect.timeout.connect(start)
        retry_apply.timeout.connect(apply)
        QTimer.singleShot(0, start)
        app.aboutToQuit.connect(stop)
        return app.exec_()
    except Exception as error:
        fail(str(error))
        return 1
    finally:
        stop()
