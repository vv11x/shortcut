import argparse
import ctypes
import subprocess
import time
from ctypes import wintypes
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXECUTABLE = PROJECT_ROOT / "dist" / "shortcut" / "shortcut.exe"
WINDOW_TITLE = "shortcut"


def visible_window_processes(title: str) -> set[int]:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [enum_proc, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL

    process_ids: set[int] = set()

    def visit(window, parameter):
        if not user32.IsWindowVisible(window):
            return True
        length = user32.GetWindowTextLengthW(window)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(window, buffer, length + 1)
        if buffer.value == title:
            process_id = wintypes.DWORD()
            user32.GetWindowThreadProcessId(window, ctypes.byref(process_id))
            process_ids.add(process_id.value)
        return True

    callback = enum_proc(visit)
    user32.EnumWindows(callback, 0)
    return process_ids


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", nargs="?", type=Path, default=DEFAULT_EXECUTABLE)
    executable = parser.parse_args().executable.resolve()

    internal_directory = executable.parent / "_internal"
    bundled_icu = [internal_directory / name for name in ("icuuc.dll", "icudt78.dll")]
    present_icu = [path.name for path in bundled_icu if path.exists()]
    if present_icu:
        raise RuntimeError(f"The package contains incompatible host ICU DLLs: {present_icu}")

    process = subprocess.Popen([str(executable)], cwd=executable.parent)
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"shortcut.exe exited during startup with code {process.returncode}")
            if process.pid in visible_window_processes(WINDOW_TITLE):
                print("PASS: shortcut.exe stayed running and showed its dock window")
                return
            time.sleep(0.1)
        raise RuntimeError("shortcut.exe remained running but did not show its dock window")
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


if __name__ == "__main__":
    main()
