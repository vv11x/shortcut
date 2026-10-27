# -*- coding: utf-8 -*-
"""隐藏桌面图标时的独立看门狗与异常退出恢复标记。

Windows 的“隐藏桌面图标”是 Explorer 的持久设置。主程序正常退出时会恢复它，
但崩溃、强制结束或断电不会执行清理。本模块在隐藏前写入带会话令牌的标记，
并启动一个独立进程等待主进程句柄；主进程消失后由守护进程恢复图标。
下次启动时如果发现遗留标记，也会先恢复，作为守护进程也未能运行时的兜底。
"""

import ctypes
from contextlib import contextmanager
import json
import os
import subprocess
import sys
import time
import traceback
import uuid
from ctypes import wintypes

from .desktop_visibility import icons_visible, restore_stock_view, set_icons_visible

SYNCHRONIZE = 0x00100000
EVENT_MODIFY_STATE = 0x0002
INFINITE = 0xFFFFFFFF
WAIT_OBJECT_0 = 0
WAIT_ABANDONED = 0x80
WAIT_FAILED = 0xFFFFFFFF
ERROR_INVALID_PARAMETER = 87
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200
_STATE_MUTEX = "Local\\Shortcut.DesktopVisibility.v1"

if os.name == "nt":
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _kernel32.WaitForSingleObject.restype = wintypes.DWORD
    _kernel32.WaitForMultipleObjects.argtypes = [wintypes.DWORD,
                                                 ctypes.POINTER(wintypes.HANDLE),
                                                 wintypes.BOOL, wintypes.DWORD]
    _kernel32.WaitForMultipleObjects.restype = wintypes.DWORD
    _kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL,
                                       wintypes.BOOL, wintypes.LPCWSTR]
    _kernel32.CreateEventW.restype = wintypes.HANDLE
    _kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL,
                                     wintypes.LPCWSTR]
    _kernel32.OpenEventW.restype = wintypes.HANDLE
    _kernel32.SetEvent.argtypes = [wintypes.HANDLE]
    _kernel32.SetEvent.restype = wintypes.BOOL
    _kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL,
                                       wintypes.LPCWSTR]
    _kernel32.CreateMutexW.restype = wintypes.HANDLE
    _kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
    _kernel32.ReleaseMutex.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
else:  # 仅便于非 Windows 环境导入测试，实际功能不可用。
    _kernel32 = None


def _check_windows():
    if _kernel32 is None:
        raise OSError("桌面图标守卫仅支持 Windows")


@contextmanager
def _state_lock(timeout=10000):
    """串行化“写入标记并隐藏”和“恢复并清理标记”这两个状态转换。"""
    _check_windows()
    handle = _kernel32.CreateMutexW(None, False, _STATE_MUTEX)
    if not handle:
        yield False
        return
    acquired = False
    try:
        result = _kernel32.WaitForSingleObject(handle, timeout)
        acquired = result in (WAIT_OBJECT_0, WAIT_ABANDONED)
        yield acquired
    finally:
        if acquired:
            _kernel32.ReleaseMutex(handle)
        _kernel32.CloseHandle(handle)


def read_marker(marker_path):
    try:
        with open(marker_path, "r", encoding="utf-8") as file:
            marker = json.load(file)
    except FileNotFoundError:
        return None
    if (isinstance(marker, dict) and isinstance(marker.get("token"), str)
            and isinstance(marker.get("pid"), int)):
        return marker
    raise ValueError("桌面图标恢复标记格式无效：%s" % marker_path)


def write_marker(marker_path, token, pid=None):
    directory = os.path.dirname(os.path.abspath(marker_path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    marker = {"version": 1, "token": token, "pid": int(pid or os.getpid()),
              "time": time.time()}
    temporary = marker_path + "." + token + ".tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as file:
            json.dump(marker, file, ensure_ascii=False)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, marker_path)
    finally:
        try:
            os.remove(temporary)
        except OSError:
            pass


def clear_marker(marker_path, token=None):
    """只删除属于指定会话的标记，避免旧看门狗清掉新会话的状态。"""
    marker = read_marker(marker_path)
    if marker is None:
        return True
    if token is not None and marker.get("token") != token:
        return False
    try:
        os.remove(marker_path)
        return True
    except FileNotFoundError:
        return True


def hide_desktop(marker_path, token):
    """先落盘标记，再关闭 Windows 桌面图标总开关。"""
    with _state_lock() as locked:
        if not locked:
            raise OSError("无法取得桌面图标状态锁")
        write_marker(marker_path, token)
        try:
            set_icons_visible(False)
        except Exception:
            # 仅在确认图标仍然可见时删除标记；状态不明时保留标记供恢复。
            try:
                if icons_visible():
                    clear_marker(marker_path, token)
            except Exception:
                pass
            raise


def show_desktop(marker_path, token=None):
    """恢复桌面图标并删除匹配的标记；令牌不匹配时不碰新会话。"""
    with _state_lock() as locked:
        if not locked:
            return False
        marker = read_marker(marker_path)
        if token is not None and marker is not None and marker.get("token") != token:
            return False
        set_icons_visible(True)
        if marker is not None:
            if not clear_marker(marker_path, marker.get("token")):
                raise OSError("桌面恢复标记已被其他会话修改")
        return True


def recover_stale_desktop(marker_path):
    """启动时恢复上一次异常退出遗留的隐藏状态。"""
    marker = read_marker(marker_path)
    if marker is None:
        return False, ""
    with _state_lock() as locked:
        marker = read_marker(marker_path)
        if marker is None:
            return False, ""
        if not locked:
            return False, "无法取得桌面图标状态锁"
        try:
            restore_stock_view()
        except Exception as error:
            return False, str(error)
        clear_marker(marker_path, marker.get("token"))
        return True, ""


def restore_desktop_now(marker_path):
    """手动修复命令使用：无条件恢复图标，并清理遗留标记。"""
    with _state_lock() as locked:
        if not locked:
            return False, "无法取得桌面图标状态锁"
        try:
            restore_stock_view()
        except Exception as error:
            return False, str(error)
        try:
            os.remove(marker_path)
        except FileNotFoundError:
            pass
        return True, ""


def guardian_arguments(script_path, owner_pid, marker_path, token,
                       stop_name, ready_name, executable=None, frozen=None):
    executable = executable or sys.executable
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    arguments = [executable]
    if not frozen:
        arguments.append(os.path.abspath(script_path))
    arguments.extend(["--desktop-guardian", str(int(owner_pid)), marker_path,
                      token, stop_name, ready_name])
    return arguments


def _guardian_log(marker_path, message):
    try:
        with open(marker_path + ".log", "a", encoding="utf-8",
                  errors="replace") as file:
            file.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), message))
    except Exception:
        pass


class GuardianProcess:
    """由主 Shortcut 启动的独立看门狗；主进程消失后它负责恢复桌面。"""

    def __init__(self, script_path, marker_path, owner_pid=None, ready_timeout=10.0):
        self.script_path = os.path.abspath(script_path)
        self.marker_path = marker_path
        self.owner_pid = int(owner_pid or os.getpid())
        self.token = uuid.uuid4().hex
        self.stop_event_name = "Local\\Shortcut.Guardian.Stop." + self.token
        self.ready_event_name = "Local\\Shortcut.Guardian.Ready." + self.token
        self.stop_event = None
        self.ready_event = None
        self.process = None
        self.ready_timeout = ready_timeout

    @property
    def alive(self):
        return self.process is not None and self.process.poll() is None

    def start(self):
        _check_windows()
        self.stop_event = _kernel32.CreateEventW(None, True, False,
                                                self.stop_event_name)
        self.ready_event = _kernel32.CreateEventW(None, True, False,
                                                 self.ready_event_name)
        if not self.stop_event or not self.ready_event:
            self.stop()
            raise OSError("无法创建桌面图标守护进程事件")
        arguments = guardian_arguments(
            self.script_path, self.owner_pid, self.marker_path, self.token,
            self.stop_event_name, self.ready_event_name)
        try:
            self.process = subprocess.Popen(
                arguments, cwd=os.path.dirname(self.script_path) or None,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, close_fds=True,
                creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP)
        except Exception:
            self.stop()
            raise
        if not self._wait_ready():
            self.stop()
            raise OSError("桌面图标守护进程未能及时启动")
        return self

    def _wait_ready(self):
        deadline = time.monotonic() + max(0.1, self.ready_timeout)
        while True:
            if self.process.poll() is not None:
                return False
            if _kernel32.WaitForSingleObject(self.ready_event, 50) in (
                    WAIT_OBJECT_0, WAIT_ABANDONED):
                return True
            if time.monotonic() >= deadline:
                return False

    def hide(self):
        hide_desktop(self.marker_path, self.token)

    def clear_marker(self):
        return clear_marker(self.marker_path, self.token)

    def abort(self):
        """隐藏失败时尽量恢复图标；状态不明时保留标记。"""
        restored = show_desktop(self.marker_path, self.token)
        self.stop()
        return restored

    def stop(self):
        process, self.process = self.process, None
        if self.stop_event:
            _kernel32.SetEvent(self.stop_event)
        if process is not None:
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    process.terminate()
                    process.wait(timeout=2)
                except Exception:
                    try:
                        process.kill()
                        process.wait(timeout=1)
                    except Exception:
                        pass
        if self.stop_event:
            _kernel32.CloseHandle(self.stop_event)
            self.stop_event = None
        if self.ready_event:
            _kernel32.CloseHandle(self.ready_event)
            self.ready_event = None


def _open_process(pid):
    handle = _kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
    if handle:
        return handle, None
    return None, ctypes.get_last_error()


def _open_event(name):
    return _kernel32.OpenEventW(EVENT_MODIFY_STATE | SYNCHRONIZE, False, name)


def _wait_handles(handles, timeout):
    array = (wintypes.HANDLE * len(handles))(*handles)
    return _kernel32.WaitForMultipleObjects(len(handles), array, False, timeout)


def _restore_after_death(marker_path, token, attempts=30, delay=1.0):
    total_attempts = max(1, attempts)
    for attempt in range(1, total_attempts + 1):
        marker = read_marker(marker_path)
        if marker is None or marker.get("token") != token:
            return False
        with _state_lock() as locked:
            marker = read_marker(marker_path)
            if marker is None or marker.get("token") != token:
                return False
            if not locked:
                failure = "无法取得桌面图标状态锁"
            else:
                try:
                    restore_stock_view()
                    if not clear_marker(marker_path, token):
                        raise OSError("桌面恢复标记已被其他会话修改")
                    return True
                except Exception as error:
                    failure = "%s\n%s" % (error, traceback.format_exc())
        _guardian_log(marker_path, "桌面图标恢复第 %d/%d 次失败：%s" %
                      (attempt, total_attempts, failure))
        if attempt < total_attempts:
            time.sleep(delay)
    _guardian_log(marker_path, "桌面图标恢复重试耗尽；标记保留供下次启动恢复")
    return False


def run_guardian(owner_pid, marker_path, token, stop_event_name="",
                 ready_event_name=""):
    """独立进程入口：等待主进程退出，然后恢复被隐藏的桌面图标。"""
    _check_windows()
    process, error = _open_process(owner_pid)
    if error is not None and error != ERROR_INVALID_PARAMETER:
        _guardian_log(marker_path, "OpenProcess failed: %s" % error)
        return 1
    stop_event = _open_event(stop_event_name) if stop_event_name else None
    ready_event = _open_event(ready_event_name) if ready_event_name else None
    try:
        # 打开进程句柄成功后再报告就绪，主进程收到就绪才真正隐藏图标。
        if ready_event:
            _kernel32.SetEvent(ready_event)
        if process is None:
            return 0 if _restore_after_death(marker_path, token) else 1
        handles = [process]
        if stop_event:
            handles.append(stop_event)
        result = _wait_handles(handles, INFINITE)
        if stop_event and result == WAIT_OBJECT_0 + 1:
            return 0
        if result in (WAIT_OBJECT_0, WAIT_FAILED):
            return 0 if _restore_after_death(marker_path, token) else 1
        _guardian_log(marker_path, "等待主程序句柄时收到意外结果：%s" % result)
        return 1
    except Exception:
        _guardian_log(marker_path, traceback.format_exc())
        return 1
    finally:
        for handle in (process, stop_event, ready_event):
            if handle:
                _kernel32.CloseHandle(handle)
