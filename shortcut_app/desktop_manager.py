"""向原生桌面连接进程传递分类结果；断开连接时恢复视图项目。"""

import json
import os
import sys
import uuid

from PyQt5.QtCore import QObject, QProcess, QTimer, pyqtSignal
from PyQt5.QtNetwork import QLocalServer

from .desktop_guardian import GuardianProcess, show_desktop
from .desktop_visibility import set_icons_visible, restore_stock_view
from .organizer import desktop_directories

RECYCLE_KEY = "::{645FF040-5081-101B-9F08-00AA002F954E}"


class DesktopManager(QObject):
    error = pyqtSignal(str)
    ready = pyqtSignal()

    def __init__(self, script_path, parent=None, marker_path=None):
        super().__init__(parent)
        self.script_path = script_path
        self.marker_path = marker_path
        self.paths = frozenset()
        self.hide_recycle = True
        self.directories = frozenset(desktop_directories())
        self.mode = "all"
        self.socket = None
        self.buffer = b""
        self.stopping = False
        self.guardian = None
        self._failure_message = ""
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._connected)
        self.process = QProcess(self)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._process_error)
        self._guardian_check_timer = QTimer(self)
        self._guardian_check_timer.setInterval(2000)
        self._guardian_check_timer.timeout.connect(self._check_guardian)
        self._startup = QTimer(self)
        self._startup.setSingleShot(True)
        # 容纳旧连接退出及有限超时重试；单次启动计时，不增加空闲检查。
        self._startup.setInterval(40000)
        self._startup.timeout.connect(self._startup_timeout)

    def update(self, groups, categories, hide_recycle=True):
        paths = frozenset(entry["path"] for category in categories
                          for entry in groups.get(category["id"], [])
                          if os.path.dirname(entry["path"]) in self.directories)
        if paths != self.paths or hide_recycle != self.hide_recycle:
            self.paths = paths
            self.hide_recycle = hide_recycle
            self._send_paths()

    def set_mode(self, mode):
        if self.mode == mode == "managed" and self.process.state() != QProcess.NotRunning:
            return
        if (self.mode == mode == "hidden" and self.guardian is not None
                and self.guardian.alive):
            return
        was_hidden = self.mode == "hidden"
        # 先停掉原生收纳服务；隐藏模式的清理由下面显式处理，失败时保留看门狗。
        self.stop(restore_hidden=False)
        if mode == "hidden":
            try:
                if was_hidden:
                    self._end_hidden()
                self._begin_hidden()
            except Exception:
                self.mode = "all"
                raise
        elif was_hidden:
            self._end_hidden()
        else:
            set_icons_visible(True)
        self.mode = mode
        if mode != "managed":
            return
        self.stopping = False
        self._failure_message = ""
        endpoint = "Shortcut.Desktop." + uuid.uuid4().hex
        if not self.server.listen(endpoint):
            raise OSError(self.server.errorString())
        program = sys.executable
        arguments = ["--native-desktop", endpoint, str(os.getpid())]
        if not getattr(sys, "frozen", False):
            arguments.insert(0, self.script_path)
        self.process.setProgram(program)
        self.process.setArguments(arguments)
        self.process.setWorkingDirectory(os.path.dirname(self.script_path))
        self._startup.start(40000)
        # FailedToStart can be delivered by start(); do not re-arm its timeout
        # after the failure callback has already stopped it.
        self.process.start()

    def _begin_hidden(self):
        if not self.marker_path:
            raise RuntimeError("隐藏桌面图标前必须配置恢复标记路径")
        if self.guardian is not None:
            self.guardian.stop()
            self.guardian = None
        guardian = GuardianProcess(self.script_path, self.marker_path)
        try:
            guardian.start()
            guardian.hide()
        except Exception:
            guardian.abort()
            raise
        self.guardian = guardian
        self._guardian_check_timer.start()

    def _end_hidden(self):
        if not self.marker_path:
            raise RuntimeError("恢复桌面图标时缺少恢复标记路径")
        guardian = self.guardian
        try:
            restored = show_desktop(self.marker_path, guardian.token if guardian else None)
        except Exception:
            if guardian is not None:
                self._guardian_check_timer.start()
            raise
        if not restored:
            raise OSError("未能恢复 Windows 桌面图标")
        if guardian is not None:
            guardian.stop()
        self.guardian = None
        self._guardian_check_timer.stop()

    def _check_guardian(self):
        if self.mode != "hidden" or self.guardian is None:
            self._guardian_check_timer.stop()
            return
        if self.guardian.alive:
            return
        guardian = self.guardian
        try:
            restored = show_desktop(self.marker_path, guardian.token if guardian else None)
        except Exception as error:
            self.error.emit("桌面图标守护进程已退出，恢复失败：%s" % error)
            self.guardian = None
            self._guardian_check_timer.stop()
            return
        self.guardian = None
        self._guardian_check_timer.stop()
        guardian.stop()
        self.mode = "all"
        if restored:
            self.error.emit("桌面图标守护进程已退出，已恢复 Windows 桌面图标。")
        else:
            self.error.emit("桌面图标守护进程已退出，恢复失败，将在下次启动时重试。")

    def _connected(self):
        incoming = self.server.nextPendingConnection()
        if incoming is None:
            return
        if self.stopping or self.mode != "managed" or self.socket is not None:
            incoming.abort()
            incoming.deleteLater()
            return
        self.socket = incoming
        self.buffer = b""
        incoming.readyRead.connect(self._read)
        incoming.disconnected.connect(lambda: self._disconnected(incoming))
        self._send_paths()
        # A fast helper may have sent ready/error before readyRead was connected.
        self._read()

    def _disconnected(self, incoming):
        if incoming is not self.socket or self.stopping or self.mode != "managed":
            return
        self._failure_message = self._failure_message or "桌面显示服务连接已中断"
        # The helper normally exits after restoring the view. Bound that wait
        # even if its native shutdown stalls after a previously successful start.
        self._startup.start(12000)

    def _send_paths(self):
        if self.socket:
            paths = self.paths | {RECYCLE_KEY} if self.hide_recycle else self.paths
            self.socket.write((json.dumps({"paths": sorted(paths)}, ensure_ascii=False)
                               + "\n").encode("utf-8"))
            self.socket.flush()

    def _read(self):
        if not self.socket or self.stopping or self.mode != "managed":
            return
        self.buffer += bytes(self.socket.readAll())
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            message = json.loads(line)
            if message.get("error"):
                self._failure_message = message["error"]
            if message.get("ready"):
                self._startup.stop()
                self.ready.emit()

    def _startup_timeout(self):
        detail = self._failure_message or "桌面显示服务未能及时启动"
        self.stop()
        self.mode = "all"
        self.error.emit(detail + "，已恢复 Windows 桌面图标。")

    def _finished(self, *args):
        self._startup.stop()
        self._close_pipe()
        # waitForFinished() can emit finished synchronously inside stop(). Let
        # stop restore once after the old helper has fully left its callbacks.
        if self.stopping:
            return
        if self.mode == "managed":
            self.mode = "all"
            self._restore_desktop()
            self.error.emit((self._failure_message + "\n" if self._failure_message else "")
                            + "桌面显示服务已退出，已恢复 Windows 桌面图标。")

    def _process_error(self, error):
        if error == QProcess.FailedToStart:
            self._startup.stop()
            self._close_pipe()
            was_managed = self.mode == "managed"
            self.mode = "all"
            if was_managed:
                self._restore_desktop()
            if not self.stopping:
                self.error.emit("桌面显示服务启动失败：" + self.process.errorString())

    def _restore_desktop(self):
        restore_stock_view()

    def _close_pipe(self):
        outgoing, self.socket = self.socket, None
        self.buffer = b""
        self.server.close()
        if outgoing is not None:
            # An asynchronous disconnect can otherwise wait for Qt socket events
            # while the GUI thread blocks in QProcess.waitForFinished(). Abort
            # the local pipe now so the helper can enter its normal shutdown.
            outgoing.abort()
            outgoing.deleteLater()

    def stop(self, restore_hidden=True):
        was_managed = self.mode == "managed"
        was_hidden = self.mode == "hidden"
        self.stopping = True
        self._startup.stop()
        self._close_pipe()
        if self.process.state() != QProcess.NotRunning:
            # 正常退出由管道断开触发；超时后关闭辅助进程并恢复原控件。
            # Native stop allows up to 5 s for REQUEST_STOP and 5.5 s for CLOSED.
            # Give that cleanup time before falling back to terminating helper.
            if not self.process.waitForFinished(12000):
                self.process.kill()
                self.process.waitForFinished(1000)
        if was_managed:
            self._restore_desktop()
        if was_hidden and restore_hidden:
            try:
                self._end_hidden()
            except OSError as error:
                self.error.emit("退出时恢复桌面图标失败，看门狗将在主程序退出后重试：%s" % error)
                raise
        if restore_hidden or not was_hidden:
            self.mode = "all"
