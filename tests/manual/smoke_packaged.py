import os
import json
import ctypes
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import tempfile
OUTPUT = Path(tempfile.gettempdir()) / 'shortcut-validation'
OUTPUT.mkdir(parents=True, exist_ok=True)
from shortcut_app.desktop_visibility import desktop_snapshot

root = Path(__file__).resolve().parents[2]
executable = Path(os.environ.get('SHORTCUT_EXE', str(root.parent / 'shortcut-output/dist/shortcut/shortcut.exe')))
profile = OUTPUT / 'packaged-profile'
profile.mkdir(exist_ok=True)
environment = dict(os.environ, USERPROFILE=str(profile), APPDATA=str(profile / 'AppData/Roaming'))
before = desktop_snapshot()
(OUTPUT / 'packaged-desktop-before.json').write_text(json.dumps(before), encoding='utf-8')
process = subprocess.Popen([str(executable)], env=environment)
log = profile / '.shortcut/shortcut.log'
try:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        assert process.poll() is None, 'packaged application exited unexpectedly'
        if log.exists() and '启动完成' in log.read_text(encoding='utf-8'):
            break
        time.sleep(.1)
    else:
        raise AssertionError('packaged application did not finish startup')
    time.sleep(2)
    contents = log.read_text(encoding='utf-8')
    assert 'Traceback' not in contents and '失败' not in contents, contents
    assert len(desktop_snapshot()['positions']) < len(before['positions']), 'native collection did not start'
    assert (executable.parent / '_internal/native_desktop/ShortcutDesktop.dll').exists()
    assert (executable.parent / '_internal/native_desktop/ShortcutShell.dll').exists()
    assert (executable.parent / '_internal/assets/branding/shortcut.ico').is_file()
    user = ctypes.WinDLL('user32', use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_ssize_t)
    user.GetPropW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    user.GetPropW.restype = ctypes.c_void_p
    user.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
    user.SendMessageW.restype = ctypes.c_ssize_t
    icons = []

    @callback_type
    def inspect_window(window, unused):
        if user.GetPropW(window, 'shortcut.MainWindow'):
            icons.append(user.SendMessageW(window, 0x7f, 1, 0))
        return 1

    user.EnumWindows.argtypes = [callback_type, ctypes.c_ssize_t]
    user.EnumWindows(inspect_window, 0)
    assert len(icons) == 1 and icons[0], 'packaged native window icon missing'
    print('PASS packaged icon asset and native window icon')
    print('PASS packaged startup and native desktop collection')
finally:
    subprocess.run([str(executable), '--stop'], env=environment, check=True, timeout=20)
    process.wait(timeout=20)
assert process.returncode == 0, process.returncode
# Shell Refresh 异步重建图标列表；进程退出后留出一次完整布局时间。
time.sleep(.5)
after = desktop_snapshot()
(OUTPUT / 'packaged-desktop-difference.json').write_text(json.dumps({
    'missing': sorted(set(before['positions']) - set(after['positions'])),
    'added': sorted(set(after['positions']) - set(before['positions'])),
    'moved': {p: [pos, after['positions'][p]] for p, pos in before['positions'].items()
              if p in after['positions'] and pos != after['positions'][p]},
}), encoding='utf-8')
assert after['positions'] == before['positions'], 'desktop item positions changed after packaged exit'
assert after['flags'] == before['flags'], 'desktop flags changed after packaged exit'
print('PASS packaged stop and full desktop restoration')
