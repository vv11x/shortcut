import ctypes
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4
from ctypes import wintypes


SSF_HIDEICONS = 0x00004000
PROCESS_SYNCHRONIZE = 0x00100000
PROCESS_QUERY_LIMITED_INFORMATION = 0x00001000
WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102
WAIT_ABANDONED = 0x00000080
ERROR_INVALID_PARAMETER = 87
ERROR_ALREADY_EXISTS = 183
INFINITE = 0xFFFFFFFF
EVENT_MODIFY_STATE = 0x0002
GUARDIAN_MUTEX_NAME = r"Local\shortcut.DesktopVisibility.v1"
APP_MUTEX_NAME = r"Local\shortcut.SingleInstance.v1"
READY_EVENT_PREFIX = r"Local\shortcut.DesktopGuardianReady."


class ShellState(ctypes.Structure):
    _fields_ = [
        ("fShowAllObjects", wintypes.BOOL, 1),
        ("fShowExtensions", wintypes.BOOL, 1),
        ("fNoConfirmRecycle", wintypes.BOOL, 1),
        ("fShowSysFiles", wintypes.BOOL, 1),
        ("fShowCompColor", wintypes.BOOL, 1),
        ("fDoubleClickInWebView", wintypes.BOOL, 1),
        ("fDesktopHTML", wintypes.BOOL, 1),
        ("fWin95Classic", wintypes.BOOL, 1),
        ("fDontPrettyPath", wintypes.BOOL, 1),
        ("fShowAttribCol", wintypes.BOOL, 1),
        ("fMapNetDrvBtn", wintypes.BOOL, 1),
        ("fShowInfoTip", wintypes.BOOL, 1),
        ("fHideIcons", wintypes.BOOL, 1),
        ("fWebView", wintypes.BOOL, 1),
        ("fFilter", wintypes.BOOL, 1),
        ("fShowSuperHidden", wintypes.BOOL, 1),
        ("fNoNetCrawling", wintypes.BOOL, 1),
        ("dwWin95Unused", wintypes.DWORD),
        ("uWin95Unused", wintypes.UINT),
        ("lParamSort", wintypes.LONG),
        ("iSortDirection", ctypes.c_int),
        ("version", wintypes.UINT),
        ("uNotUsed", wintypes.UINT),
        ("fSepProcess", wintypes.BOOL, 1),
        ("fStartPanelOn", wintypes.BOOL, 1),
        ("fShowStartPage", wintypes.BOOL, 1),
        ("fAutoCheckSelect", wintypes.BOOL, 1),
        ("fIconsOnly", wintypes.BOOL, 1),
        ("fShowTypeOverlay", wintypes.BOOL, 1),
        ("fShowStatusBar", wintypes.BOOL, 1),
        ("fSpareFlags", wintypes.UINT, 9),
    ]


class FileTime(ctypes.Structure):
    _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]


def _kernel32():
    library = ctypes.WinDLL("kernel32", use_last_error=True)
    library.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    library.OpenProcess.restype = wintypes.HANDLE
    library.CloseHandle.argtypes = [wintypes.HANDLE]
    library.CloseHandle.restype = wintypes.BOOL
    library.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    library.WaitForSingleObject.restype = wintypes.DWORD
    library.GetProcessTimes.argtypes = [wintypes.HANDLE, ctypes.POINTER(FileTime), ctypes.POINTER(FileTime), ctypes.POINTER(FileTime), ctypes.POINTER(FileTime)]
    library.GetProcessTimes.restype = wintypes.BOOL
    library.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    library.CreateMutexW.restype = wintypes.HANDLE
    library.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    library.CreateEventW.restype = wintypes.HANDLE
    library.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    library.OpenEventW.restype = wintypes.HANDLE
    library.SetEvent.argtypes = [wintypes.HANDLE]
    library.SetEvent.restype = wintypes.BOOL
    library.ReleaseMutex.argtypes = [wintypes.HANDLE]
    library.ReleaseMutex.restype = wintypes.BOOL
    return library


def _shell32():
    library = ctypes.WinDLL("shell32", use_last_error=True)
    library.SHGetSetSettings.argtypes = [ctypes.POINTER(ShellState), wintypes.DWORD, wintypes.BOOL]
    library.SHGetSetSettings.restype = None
    return library


def icons_visible() -> bool:
    state = ShellState()
    _shell32().SHGetSetSettings(ctypes.byref(state), SSF_HIDEICONS, False)
    return not bool(state.fHideIcons)


def set_icons_visible(visible: bool) -> None:
    state = ShellState()
    state.fHideIcons = not visible
    _shell32().SHGetSetSettings(ctypes.byref(state), SSF_HIDEICONS, True)


def marker_path() -> Path:
    return Path(os.environ["LOCALAPPDATA"]) / "shortcut" / "desktop-hidden.json"


def _write_marker(marker: dict) -> None:
    path = marker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _read_marker() -> dict:
    return json.loads(marker_path().read_text(encoding="utf-8"))


def process_creation_time(pid: int) -> int | None:
    kernel32 = _kernel32()
    handle = kernel32.OpenProcess(PROCESS_SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error == ERROR_INVALID_PARAMETER:
            return None
        raise ctypes.WinError(error)
    try:
        created, exited, kernel_time, user_time = FileTime(), FileTime(), FileTime(), FileTime()
        if not kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel_time), ctypes.byref(user_time)):
            raise ctypes.WinError(ctypes.get_last_error())
        return (created.high << 32) | created.low
    finally:
        kernel32.CloseHandle(handle)


@contextmanager
def visibility_lock():
    kernel32 = _kernel32()
    handle = kernel32.CreateMutexW(None, False, GUARDIAN_MUTEX_NAME)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    result = kernel32.WaitForSingleObject(handle, INFINITE)
    if result not in (WAIT_OBJECT_0, WAIT_ABANDONED):
        kernel32.CloseHandle(handle)
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield
    finally:
        kernel32.ReleaseMutex(handle)
        kernel32.CloseHandle(handle)


class SingleInstance:
    def __init__(self):
        kernel32 = _kernel32()
        ctypes.set_last_error(0)
        self.handle = kernel32.CreateMutexW(None, True, APP_MUTEX_NAME)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(self.handle)
            self.handle = None

    @property
    def already_running(self) -> bool:
        return self.handle is None

    def close(self) -> None:
        if self.handle:
            kernel32 = _kernel32()
            kernel32.ReleaseMutex(self.handle)
            kernel32.CloseHandle(self.handle)
            self.handle = None


def begin_hidden_session(pid: int) -> dict:
    created = process_creation_time(pid)
    if created is None:
        raise ProcessLookupError(f"Process {pid} exited before desktop icon mode started")
    with visibility_lock():
        if marker_path().exists():
            raise RuntimeError(f"An unfinished desktop icon session already exists: {marker_path()}")
        marker = {
            "schema_version": 1,
            "token": uuid4().hex,
            "pid": pid,
            "process_created": created,
            "icons_were_visible": icons_visible(),
        }
        _write_marker(marker)
    return marker


def _restore_marker(token: str, show_icons: bool = False) -> bool:
    with visibility_lock():
        path = marker_path()
        if not path.exists():
            return False
        marker = _read_marker()
        if marker["token"] != token:
            return False
        set_icons_visible(True if show_icons else marker["icons_were_visible"])
        path.unlink()
        return True


def end_hidden_session(token: str) -> None:
    if not _restore_marker(token):
        raise RuntimeError(f"Desktop icon session marker is missing or owned by another session: {token}")


def recover_stale_session() -> bool:
    path = marker_path()
    if not path.exists():
        return False
    with visibility_lock():
        if not path.exists():
            return False
        marker = _read_marker()
        active_creation = process_creation_time(marker["pid"])
        if active_creation == marker["process_created"]:
            return False
        set_icons_visible(marker["icons_were_visible"])
        path.unlink()
        return True


def restore_desktop_now() -> None:
    path = marker_path()
    with visibility_lock():
        set_icons_visible(True)
        if path.exists():
            path.unlink()


class GuardianProcess:
    def __init__(self, process: subprocess.Popen):
        self.process = process

    @classmethod
    def start(cls, pid: int, token: str) -> "GuardianProcess":
        kernel32 = _kernel32()
        event_name = READY_EVENT_PREFIX + token
        ready_event = kernel32.CreateEventW(None, True, False, event_name)
        if not ready_event:
            raise ctypes.WinError(ctypes.get_last_error())
        if getattr(sys, "frozen", False):
            command = [sys.executable, "--desktop-guardian", str(pid), token]
        else:
            command = [sys.executable, "-m", "shortcut", "--desktop-guardian", str(pid), token]
        try:
            process = subprocess.Popen(command, creationflags=0x08000000)
        except Exception:
            kernel32.CloseHandle(ready_event)
            raise
        result = kernel32.WaitForSingleObject(ready_event, 10000)
        kernel32.CloseHandle(ready_event)
        if result == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
        if result != WAIT_OBJECT_0:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            raise RuntimeError(f"Desktop guardian failed to start; exit code: {process.poll()}")
        return cls(process)

    def wait(self) -> None:
        self.process.wait(timeout=5)


def run_guardian(pid: int, token: str) -> int:
    kernel32 = _kernel32()
    handle = kernel32.OpenProcess(PROCESS_SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error != ERROR_INVALID_PARAMETER:
            raise ctypes.WinError(error)
        _restore_marker(token)
        _signal_guardian_ready(token)
        return 0
    try:
        created, exited, kernel_time, user_time = FileTime(), FileTime(), FileTime(), FileTime()
        if not kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel_time), ctypes.byref(user_time)):
            raise ctypes.WinError(ctypes.get_last_error())
        owner_created = (created.high << 32) | created.low
        _signal_guardian_ready(token)
        while True:
            result = kernel32.WaitForSingleObject(handle, 2000)
            if result == WAIT_OBJECT_0:
                _restore_marker(token)
                return 0
            if result != WAIT_TIMEOUT:
                raise ctypes.WinError(ctypes.get_last_error())
            path = marker_path()
            if not path.exists():
                return 0
            with visibility_lock():
                marker = _read_marker()
                if marker["token"] != token or marker["process_created"] != owner_created:
                    return 0
    finally:
        kernel32.CloseHandle(handle)


def _signal_guardian_ready(token: str) -> None:
    kernel32 = _kernel32()
    handle = kernel32.OpenEventW(EVENT_MODIFY_STATE, False, READY_EVENT_PREFIX + token)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not kernel32.SetEvent(handle):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel32.CloseHandle(handle)


class DesktopIconController:
    def __init__(self):
        self.token: str | None = None
        self.guardian: GuardianProcess | None = None

    @property
    def hidden(self) -> bool:
        return self.token is not None

    def hide(self) -> None:
        marker = begin_hidden_session(os.getpid())
        try:
            guardian = GuardianProcess.start(os.getpid(), marker["token"])
        except Exception:
            _restore_marker(marker["token"])
            raise
        try:
            set_icons_visible(False)
        except Exception:
            end_hidden_session(marker["token"])
            guardian.wait()
            raise
        self.token = marker["token"]
        self.guardian = guardian

    def show(self) -> None:
        if self.token is None:
            set_icons_visible(True)
            return
        token = self.token
        end_hidden_session(token)
        self.token = None
        self.guardian.wait()
        self.guardian = None

    def stop(self) -> None:
        if self.hidden:
            self.show()


def main(arguments: list[str]) -> int:
    command = arguments[0]
    if command == "--restore-desktop":
        restore_desktop_now()
        return 0
    if command == "--desktop-guardian":
        return run_guardian(int(arguments[1]), arguments[2])
    raise ValueError(f"Unsupported shortcut command: {command}")
