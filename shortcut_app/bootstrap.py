"""在加载 Qt 前处理桌面恢复与看门狗命令。"""
import ctypes
import os
import sys
IS_FROZEN = bool(getattr(sys, 'frozen', False))
APP_TITLE = 'shortcut'
HIDDEN_MARKER_PATH = os.path.join(os.path.expanduser('~'), '.shortcut', 'desktop-hidden.json')

def _early_desktop_command():
    """在导入 PyQt 前处理守护进程和手动恢复，避免 GUI 崩溃后无法自救。"""
    if "--desktop-guardian" in sys.argv:
        from .desktop_guardian import run_guardian
        index = sys.argv.index("--desktop-guardian")
        values = sys.argv[index + 1:index + 6]
        try:
            owner_pid = int(values[0])
            marker_path = values[1]
            token = values[2]
        except (IndexError, ValueError):
            return 2
        stop_name = values[3] if len(values) > 3 else ""
        ready_name = values[4] if len(values) > 4 else ""
        return run_guardian(owner_pid, marker_path, token, stop_name, ready_name)

    if "--restore-desktop" in sys.argv:
        from .desktop_guardian import restore_desktop_now
        try:
            restored, detail = restore_desktop_now(HIDDEN_MARKER_PATH)
        except Exception as error:
            restored, detail = False, str(error)
        message = ("已恢复 Windows 桌面图标。" if restored
                   else "恢复 Windows 桌面图标失败：" + (detail or "未知错误"))
        if IS_FROZEN:
            ctypes.windll.user32.MessageBoxW(None, message, APP_TITLE,
                                             0x40 if restored else 0x10)
        else:
            print(message)
        return 0 if restored else 1
    return None


def run():
    result = _early_desktop_command()
    if result is not None:
        return result
    from .application import main
    return main()
