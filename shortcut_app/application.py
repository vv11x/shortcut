# -*- coding: utf-8 -*-
"""
shortcut —— Windows 玻璃 Shortcut 与桌面虚拟分类
================================================================
运行环境：Windows + Python + PyQt5；当前验证环境为 Windows 11 x64、Python 3.14
特点：
  * 屏幕四边停靠，真毛玻璃（自己抓屏模糊）+ 液态玻璃高光
  * macOS 风格鼠标放大（鱼眼）效果，点击有回弹动画
  * 托盘与右键菜单管理，支持固定入口、分类规则和手动拖入
  * 一键设置开机自启动（写入注册表 HKCU Run）
  * 配置文件：%USERPROFILE%\\.shortcut\\config.json
  * 日志文件：%USERPROFILE%\\.shortcut\\shortcut.log

调试：命令行运行  python shortcut.py --preview 预览.png  可以导出一张预览图
     命令行运行  python shortcut.py --reset          清空所有已固定的图标
"""

import ctypes
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
import traceback
import copy
from ctypes import wintypes

# ----------------------------------------------------------------------------
# 基本常量
# ----------------------------------------------------------------------------
APP_NAME = "shortcut"            # 配置目录名 + 注册表自启动项名
APP_TITLE = "shortcut"               # 显示给用户看的名字
MAIN_WINDOW_MARKER = "shortcut.MainWindow"
VERSION = "1.1.41"

# 打包成 exe 之后（PyInstaller），__file__ 指向临时解包目录，不能用；
# 这时程序目录就是 exe 自己所在的目录。
IS_FROZEN = bool(getattr(sys, "frozen", False))
if IS_FROZEN:
    SCRIPT_PATH = os.path.abspath(sys.executable)
else:
    SCRIPT_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "shortcut.py"))
# MSIX 宿主启动的子进程可能重定向 AppData，导致手动启动与登录启动各用一份配置。
# 用户主目录下的独立目录不参与 AppData 重定向，也不会随程序更新被替换。
CONFIG_DIR = os.path.join(os.path.expanduser("~"), "." + APP_NAME)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
LOG_PATH = os.path.join(CONFIG_DIR, "shortcut.log")
HIDDEN_MARKER_PATH = os.path.join(CONFIG_DIR, "desktop-hidden.json")





from .organizer import (default_state, fix_user_path, normalize_path,
                       resolve_shortcut_info, separator_positions, shortcut_target)
from .desktop_visibility import set_icons_visible

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

DEFAULT_CONFIG = {
    "organizer": default_state(),  # 虚拟分类配置，不改变桌面文件的位置
    "show_desktop_icons": True,  # 保留旧配置键；桌面显示方式由 desktop_display 管理。
    "desktop_display": "managed",
    "items": [],          # [{"path": "...", "name": "..."}]
    "icon_size": 52,      # 沿用上游的图标基准尺寸（像素）
    "magnify": True,      # 鼠标放大效果
    "glass": True,        # 毛玻璃（背景模糊）效果
    "running_dots": True, # 运行中的程序显示小圆点
    "show_name": True,    # 鼠标悬停时在图标上方显示程序名称
    "transparency": 40,   # 玻璃通透度 0~100（越大越透）
    "theme": "auto",      # 沿用上游默认外观，已有配置保持原样
    "layer": "bottom",    # 窗口层级：bottom=置底（不挡窗口）/ top=置顶
    "blur_mode": "smart", # 背景抓取频率：smart/fast/normal/slow/off
    "blur_px": 6,         # 毛玻璃模糊程度（缩小的倍数，越大越糊）
    "bump_level": "mid",  # 悬停放大程度：low/mid/high，沿用旧配置键
    "lang": "zh",         # 界面语言：zh=中文 / en=English
    "reorder": True,      # 默认允许拖动排序；超过系统拖动阈值后才进入拖动
    "sep_split": False,   # 连成一体模式：默认不切断玻璃背景
    "screen_index": -1,   # 屏幕序号（-1为主屏）
    "screen_name": "",    # 屏幕设备标识
    "position": "bottom", # 位置：bottom/top/left/right，custom 保留旧水平自定义高度
    "custom_bottom": 200, # 自定义位置时，距屏幕底部多少像素
    "autostart": False,   # 开机自启动
    "bottom_margin": 6,   # 距离任务栏上方的高度
    "fixed_shortcut_bar": True, # 固定玻璃条长度，悬停时不发生拉伸伸缩
    "desktop_folder_mode": False, # 桌面文件夹模式：在桌面上整齐陈列手机式半透明文件夹盒子
    "folder_grid_size": "4x4", # 每个桌面分类盒内的缩略图网格
    "single_click_launch": True, # 手机式弹窗单击即开
    "launch_bounce": True, # macOS 风格启动轻快跳动
    "category_custom_icons": {}, # 自定义分类图标映射 {cid: path}
    "desktop_folders_pos": [80, 80], # 桌面文件夹在桌面的坐标
    "desktop_folder_positions": {}, # 按分类保存各盒子的桌面位置
    "desktop_folder_cols": 4,
    "show_search": False, # 是否显示独立的悬浮搜索气泡（默认关闭防遮挡）
}

# 窗口位置
POSITIONS = [("屏幕底部（默认）", "bottom"), ("屏幕顶部", "top"),
             ("屏幕左侧", "left"), ("屏幕右侧", "right"), ("自定义…", "custom")]

# 背景抓取频率（毫秒）
BLUR_INTERVAL = {"smart": 8000, "fast": 1000, "normal": 3000, "slow": 10000, "off": 0}

# 沿用旧档位配置；现在控制局部放大
BUMP_LEVELS = [("low", "低（轻微）", 1.32),
               ("mid", "中（默认）", 1.42),
               ("high", "高（明显）", 1.52)]

# ----------------------------------------------------------------------------
# 语言：托盘里可以中英切换。英文直接查表，查不到就原样返回中文。
# ----------------------------------------------------------------------------
LANG = {"cur": "zh"}

EN = {
    # 主菜单
    "显示 / 隐藏 Shortcut": "Show / Hide Shortcut",
    "显示桌面图标": "Show desktop icons",
    "添加图标…": "Add Icon…",
    "添加分隔符": "Add Separator",
    "分隔符隔断背景": "Split Background at Separators",
    "图标顺序可拖动": "Draggable Icon Order",
    "移除图标": "Remove Icon",
    "—— 分隔符 ——": "—— Separator ——",
    "（还没有固定任何图标）": "(nothing pinned yet)",
    # 图标大小
    "图标大小": "Icon Size",
    "小": "Small",
    "中": "Medium",
    "大": "Large",
    "特大": "Extra Large",
    "%s（%d 像素）": "%s (%d px)",
    "自定义…（当前 %d 像素）": "Custom… (%d px now)",
    # 颜色模式
    "颜色模式": "Color Mode",
    "跟随系统": "Follow System",
    "浅色": "Light",
    "深色": "Dark",
    "光感": "Glossy",
    # 层级
    "窗口层级": "Window Layer",
    "置底（不挡任何窗口，推荐）": "Bottom (recommended)",
    "置顶（始终看得见）": "Top (always visible)",
    # 位置
    "窗口位置": "Window Position",
    "屏幕底部（默认）": "Screen Bottom (default)",
    "屏幕顶部": "Screen Top",
    "屏幕左侧": "Screen Left",
    "屏幕右侧": "Screen Right",
    "自定义…": "Custom…",
    "调整自定义高度…（当前距底部 %d 像素）": "Custom Height… (%d px from bottom)",
    # 背景抓取
    "背景抓取频率": "Background Capture",
    "智能（省电，推荐）": "Smart (power saving)",
    "实时（每秒一次）": "Realtime (every second)",
    "普通（每 3 秒）": "Normal (every 3 s)",
    "省电（每 10 秒）": "Low power (every 10 s)",
    "停止抓取（静态壁纸，只抓一次）": "Never (static wallpaper)",
    "立即刷新一次背景": "Refresh Background Now",
    # 悬停动画
    "悬停动画": "Hover Animation",
    "启用悬停放大": "Enable Hover Magnification",
    "放大程度：%s": "Magnification: %s",
    "低（轻微）": "Low (subtle)",
    "中（默认）": "Medium (default)",
    "高（明显）": "High (obvious)",
    # 毛玻璃
    "毛玻璃（背景模糊）": "Frosted Glass",
    "启用毛玻璃效果": "Enable Frosted Glass",
    "模糊程度：%s": "Blur: %s",
    "低（更清晰）": "Low (clearer)",
    "高（更朦胧）": "High (hazier)",
    "模糊程度：自定义…（当前 %d）": "Blur: Custom… (%d now)",
    # 其它开关
    "运行中的程序显示小圆点": "Show Running Dots",
    "悬停时显示程序名称": "Show App Name on Hover",
    "玻璃通透度": "Glass Transparency",
    "默认": "Default",
    "通透": "Clear",
    "很通透": "Very Clear",
    "自定义…": "Custom…",
    "自定义…（%d%%）": "Custom… (%d%%)",
    "自定义玻璃通透度：\n（0% ~ 100%，数字越大越通透纯净）": "Custom glass transparency:\n(0% ~ 100%, higher is clearer)",
    "%s（%d%%）": "%s (%d%%)",
    "开机自动启动": "Start with Windows",
    # 语言本身
    "语言 / Language": "语言 / Language",
    "简体中文": "简体中文",
    "English": "English",
    # 底部
    "使用说明": "User Guide",
    "打开配置文件夹": "Open Config Folder",
    "退出": "Quit",
    # 对话框与提示
    "选择要固定到 Shortcut 的程序（可多选）": "Choose programs to pin (multi-select)",
    "程序与快捷方式 (*.exe *.lnk *.bat *.cmd *.url *.msc *.ps1);;所有文件 (*.*)":
        "Programs & shortcuts (*.exe *.lnk *.bat *.cmd *.url *.msc *.ps1);;All files (*.*)",
    "已添加 %d 个图标到 Shortcut": "Added %d icon(s) to the shortcut",
    "毛玻璃模糊强度：\n（3 ~ 30，数字越大越模糊、越朦胧）":
        "Blur strength:\n(3 ~ 30, bigger = hazier)",
    "玻璃条距离屏幕底部多少像素？\n（Shortcut 始终水平居中，数字越大越往上）":
        "How many pixels from the bottom of the screen?\n(the shortcut stays horizontally centered)",
    "请输入图标像素大小：\n（建议 32 ~ 160，数字越大图标越大）":
        "Icon size in pixels:\n(32 ~ 160 recommended)",
    "已开启开机自启动": "Autostart enabled",
    "已取消开机自启动": "Autostart disabled",
    "设置失败，请查看日志：\n": "Failed, please check the log:\n",
    "请在托盘菜单里操作：添加图标 / 移除图标。": "Use the tray menu: Add Icon / Remove Icon.",
    "请在右下角托盘图标上右键 → 添加图标": "Right-click the tray icon → Add Icon",
    "Shortcut 已经在运行了（请看右下角托盘）。": "The shortcut is already running (see the tray).",
}


def T(s):
    """把界面文字翻成当前语言。"""
    if LANG["cur"] == "en":
        return EN.get(s, s)
    return s


def set_lang(v):
    LANG["cur"] = "en" if str(v) == "en" else "zh"

# SetWindowPos 用的常量
HWND_TOPMOST = -1
HWND_BOTTOM = 1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010


# ----------------------------------------------------------------------------
# 日志
# ----------------------------------------------------------------------------
def log(msg):
    try:
        if not os.path.isdir(CONFIG_DIR):
            os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8", errors="replace") as f:
            f.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), str(msg)))
    except Exception:
        pass


def _restore_desktop_icons_safe():
    try:
        from .desktop_guardian import show_desktop
        if not show_desktop(HIDDEN_MARKER_PATH):
            raise OSError("桌面图标恢复标记属于其他会话")
    except Exception:
        log("恢复桌面图标失败：\n" + traceback.format_exc())


import atexit
atexit.register(_restore_desktop_icons_safe)


def _excepthook(etype, value, tb):
    log("未捕获异常:\n" + "".join(traceback.format_exception(etype, value, tb)))
    _restore_desktop_icons_safe()


sys.excepthook = _excepthook


# ----------------------------------------------------------------------------
# 配置读写
# ----------------------------------------------------------------------------
def load_config():
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if os.path.isfile(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise TypeError("配置文件必须包含 JSON 对象")
        for k in DEFAULT_CONFIG:
            if k in data:
                cfg[k] = data[k]
    if not isinstance(cfg.get("items"), list):
        cfg["items"] = []
    if str(cfg.get("theme")) == "fog":
        cfg["theme"] = "gloss"        # 旧的"雾透模式"改名成"光感"
    clean = []
    for it in cfg["items"]:
        if not isinstance(it, dict):
            continue
        if it.get("sep"):
            clean.append({"sep": True})
        elif it.get("path"):
            clean.append({"path": it["path"],
                          "name": it.get("name") or os.path.splitext(os.path.basename(it["path"]))[0]})
    cfg["items"] = clean

    # 强类型安全清洗与异常 Fallback
    try:
        cfg["icon_size"] = max(24, min(256, int(cfg.get("icon_size") or 52)))
    except Exception:
        cfg["icon_size"] = 52
    try:
        cfg["transparency"] = max(0, min(100, int(cfg.get("transparency", 40))))
    except Exception:
        cfg["transparency"] = 40
    try:
        cfg["blur_px"] = max(2, min(50, int(cfg.get("blur_px") or 6)))
    except Exception:
        cfg["blur_px"] = 6
    if not isinstance(cfg.get("organizer"), dict):
        cfg["organizer"] = default_state()
    pos = cfg.get("desktop_folders_pos")
    if not isinstance(pos, (list, tuple)) or len(pos) < 2 or not all(isinstance(x, (int, float)) for x in pos[:2]):
        cfg["desktop_folders_pos"] = [80, 80]
    if cfg.get("folder_grid_size") not in ("2x2", "3x3", "4x4"):
        cfg["folder_grid_size"] = "4x4"
    positions = cfg.get("desktop_folder_positions", {})
    cfg["desktop_folder_positions"] = {
        key: list(value[:2]) for key, value in positions.items()
        if isinstance(key, str) and isinstance(value, (list, tuple)) and len(value) >= 2
        and all(isinstance(number, (int, float)) and math.isfinite(number) for number in value[:2])
    } if isinstance(positions, dict) else {}
    try:
        cfg["desktop_folder_cols"] = max(1, min(8, int(cfg.get("desktop_folder_cols", 4))))
    except (TypeError, ValueError):
        cfg["desktop_folder_cols"] = 4

    return cfg


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)
    return True


# ----------------------------------------------------------------------------
# Windows 系统相关的小工具（全部用 ctypes，不需要额外库）
# ----------------------------------------------------------------------------
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32
shell32 = ctypes.windll.shell32
comctl32 = ctypes.windll.comctl32

def trim_process_memory():
    """在后台静默空闲时裁剪进程工作集，释放物理内存并归还给操作系统。"""
    try:
        import gc
        gc.collect()
        h_proc = kernel32.GetCurrentProcess()
        kernel32.SetProcessWorkingSetSize(h_proc, ctypes.c_size_t(-1), ctypes.c_size_t(-1))
    except Exception:
        pass

# --- 屏幕捕获排除（抓背景时把自己藏起来） --------------------------------
WDA_NONE = 0x0
WDA_EXCLUDEFROMCAPTURE = 0x11


# --- 图标提取（尽量拿高分辨率图标） --------------------------------------
class BITMAP(ctypes.Structure):
    _fields_ = [
        ("bmType", wintypes.LONG),
        ("bmWidth", wintypes.LONG),
        ("bmHeight", wintypes.LONG),
        ("bmWidthBytes", wintypes.LONG),
        ("bmPlanes", wintypes.WORD),
        ("bmBitsPixel", wintypes.WORD),
        ("bmBits", ctypes.c_void_p),
    ]


class ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", wintypes.BOOL),
        ("xHotspot", wintypes.DWORD),
        ("yHotspot", wintypes.DWORD),
        ("hbmMask", wintypes.HBITMAP),
        ("hbmColor", wintypes.HBITMAP),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]


# IID_IImageList
_IID_IIMAGELIST = _GUID(0x46EB5926, 0x582E, 0x4017,
                        (ctypes.c_ubyte * 8)(0x9F, 0xDF, 0xE8, 0x99, 0x8D, 0xAA, 0x09, 0x50))

try:
    # SHGetImageList 在 shell32 里只有序号 727，没有名字导出，只能按序号取：
    # 注意写法是 (序号, 库)，不是把序号当第二个参数传
    _SHGetImageList = ctypes.WINFUNCTYPE(
        ctypes.c_long, ctypes.c_int, ctypes.POINTER(_GUID),
        ctypes.POINTER(ctypes.c_void_p))((727, shell32))
    _SHGetImageList.restype = ctypes.c_long
    _SHGetImageList.argtypes = [ctypes.c_int, ctypes.POINTER(_GUID),
                                ctypes.POINTER(ctypes.c_void_p)]
except Exception:
    _SHGetImageList = None
    log("SHGetImageList 绑定失败: " + traceback.format_exc())


class SHFILEINFOW(ctypes.Structure):
    _fields_ = [("hIcon", wintypes.HICON),
                ("iIcon", ctypes.c_int),
                ("dwAttributes", wintypes.DWORD),
                ("szDisplayName", wintypes.WCHAR * 260),
                ("szTypeName", wintypes.WCHAR * 80)]


def extract_shell_hicon(path, size=256):
    """用 Windows 外壳的"超大图标"列表取图标。

    文件夹、URL 快捷方式、商店应用这些没法用 PrivateExtractIconsW 抠图标，
    只能问外壳要。QFileIconProvider 只给 32/40 像素，放大会糊，
    这里直接取 256 像素那一档（取不到再退 48 / 32）。
    """
    if _SHGetImageList is None:
        return None
    try:
        SHGFI_SYSICONINDEX = 0x000004000
        info = SHFILEINFOW()
        r = shell32.SHGetFileInfoW(ctypes.c_wchar_p(path), 0, ctypes.byref(info),
                                   ctypes.sizeof(info), SHGFI_SYSICONINDEX)
        if not r:
            return None
        comctl32.ImageList_GetIcon.restype = wintypes.HICON
        comctl32.ImageList_GetIcon.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.UINT]
        # SHIL_JUMBO=4(256px) → SHIL_EXTRALARGE=2(48px) → SHIL_LARGE=0(32px)
        for shil in (4, 2, 0):
            himl = ctypes.c_void_p()
            if _SHGetImageList(shil, ctypes.byref(_IID_IIMAGELIST), ctypes.byref(himl)) != 0:
                continue
            if not himl:
                continue
            try:
                hicon = comctl32.ImageList_GetIcon(himl, int(info.iIcon), 0x1)
                if hicon:
                    return int(hicon)
            finally:
                table = ctypes.cast(himl, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
                release = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)(table[2])
                release(himl)
    except Exception:
        log("extract_shell_hicon 失败 %s: %s" % (path, traceback.format_exc()))
    return None


def extract_hicon(path, size=256):
    """用 PrivateExtractIconsW 从 exe/dll/ico 里取出指定尺寸的 HICON。"""
    try:
        fn = user32.PrivateExtractIconsW
    except AttributeError:
        return None
    try:
        fn.restype = wintypes.UINT
        fn.argtypes = [wintypes.LPCWSTR, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                       ctypes.POINTER(wintypes.HICON), ctypes.POINTER(wintypes.UINT),
                       wintypes.UINT, wintypes.UINT]
        hicon = wintypes.HICON(0)
        n = fn(path, 0, size, size, ctypes.byref(hicon), None, 1, 0)
        if n and hicon.value:
            return hicon.value
    except Exception:
        log("extract_hicon 失败 %s: %s" % (path, traceback.format_exc()))
    return None


def hicon_to_qimage(hicon):
    """HICON -> QImage（带透明通道）。"""
    from PyQt5.QtGui import QImage
    from PyQt5.QtCore import Qt
    info = ICONINFO()
    if not user32.GetIconInfo(wintypes.HICON(int(hicon)), ctypes.byref(info)):
        user32.DestroyIcon(wintypes.HICON(int(hicon)))
        return None
    hdc = None
    memdc = None
    hdib = None
    old = None
    try:
        if not info.hbmColor:
            return None
        bm = BITMAP()
        if not gdi32.GetObjectW(wintypes.HGDIOBJ(int(info.hbmColor)), ctypes.sizeof(BITMAP), ctypes.byref(bm)):
            return None
        w, h = int(bm.bmWidth), int(bm.bmHeight)
        if w <= 0 or h <= 0:
            return None
        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = w
        bmi.biHeight = -h          # 负数 = 从上到下的行序
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0      # BI_RGB
        hdc = user32.GetDC(None)
        bits = ctypes.c_void_p()
        hdib = gdi32.CreateDIBSection(wintypes.HDC(hdc), ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        if not hdib:
            return None
        memdc = gdi32.CreateCompatibleDC(wintypes.HDC(hdc))
        if not memdc:
            return None
        old = gdi32.SelectObject(wintypes.HDC(memdc), wintypes.HGDIOBJ(hdib))
        user32.DrawIconEx(wintypes.HDC(memdc), 0, 0, wintypes.HICON(int(hicon)), w, h, 0, None, 3)  # DI_NORMAL
        buf = ctypes.string_at(bits, w * h * 4)
        img = QImage(buf, w, h, w * 4, QImage.Format_ARGB32_Premultiplied).copy()
        if old:
            gdi32.SelectObject(wintypes.HDC(memdc), old)
            old = None
        return img.convertToFormat(QImage.Format_ARGB32)
    except Exception:
        log("hicon_to_qimage 失败: " + traceback.format_exc())
        return None
    finally:
        try:
            if memdc and old:
                gdi32.SelectObject(wintypes.HDC(memdc), old)
            if hdib:
                gdi32.DeleteObject(wintypes.HGDIOBJ(hdib))
            if memdc:
                gdi32.DeleteDC(wintypes.HDC(memdc))
            if hdc:
                user32.ReleaseDC(None, wintypes.HDC(hdc))
            if info.hbmColor:
                gdi32.DeleteObject(wintypes.HGDIOBJ(info.hbmColor))
            if info.hbmMask:
                gdi32.DeleteObject(wintypes.HGDIOBJ(info.hbmMask))
            user32.DestroyIcon(wintypes.HICON(int(hicon)))
        except Exception:
            pass


def resolve_lnk_target(path):
    """从 .lnk 快捷方式中解析出真实目标路径。"""
    return shortcut_target(path) or None


# --- 正在运行的进程 ------------------------------------------------------
class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260)]


def get_running_exe_names():
    """返回当前正在运行的进程的可执行文件名集合（小写）。

    用 CreateToolhelp32Snapshot 一次拿全，比逐个 OpenProcess 快十倍以上
    （后者要 6ms 左右，每几秒跑一次会造成动画微卡顿）。
    """
    names = set()
    try:
        TH32CS_SNAPPROCESS = 0x00000002
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if not snap or int(snap) == -1:
            return names
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            ok = kernel32.Process32FirstW(wintypes.HANDLE(snap), ctypes.byref(entry))
            while ok:
                name = entry.szExeFile
                if name:
                    names.add(name.lower())
                ok = kernel32.Process32NextW(wintypes.HANDLE(snap), ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(wintypes.HANDLE(snap))
    except Exception:
        log("get_running_exe_names 失败: " + traceback.format_exc())
    return names


# --- 开机自启动 ----------------------------------------------------------
def pythonw_path():
    """返回 pythonw.exe 的绝对路径（用它启动才不会弹出黑色控制台窗口）。"""
    exe = sys.executable or ""
    d = os.path.dirname(exe)
    cand = os.path.join(d, "pythonw.exe")
    if os.path.exists(cand):
        return cand
    return exe


def wait_for_previous_process(pid, timeout_ms=20000):
    """重启子进程先等待旧实例释放共享内存与原生桌面连接。"""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x100000, False, int(pid))
    if not handle:
        return ctypes.get_last_error() == 87  # 进程已经退出。
    try:
        return kernel.WaitForSingleObject(handle, timeout_ms) == 0
    finally:
        kernel.CloseHandle(handle)


def autostart_command():
    """开机自启动要执行的命令行。打包成 exe 后直接就是 exe 自己。"""
    if IS_FROZEN:
        return '"%s"' % SCRIPT_PATH
    return '"%s" "%s"' % (pythonw_path(), SCRIPT_PATH)


def set_autostart(enable):
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE)
    except Exception:
        return False
    try:
        if enable:
            cmd = autostart_command()
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
            log("已设置开机自启动: " + cmd)
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
                log("已取消开机自启动")
            except FileNotFoundError:
                pass
        return True
    except Exception:
        log("设置开机自启动失败: " + traceback.format_exc())
        return False
    finally:
        winreg.CloseKey(key)


def system_is_light():
    """读注册表判断 Windows 当前是不是浅色模式（读不到就当作深色）。"""
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
                             0, winreg.KEY_QUERY_VALUE)
    except Exception:
        return False
    try:
        for name in ("SystemUsesLightTheme", "AppsUseLightTheme"):
            try:
                v, _ = winreg.QueryValueEx(key, name)
                return bool(int(v))
            except FileNotFoundError:
                continue
        return False
    except Exception:
        return False
    finally:
        winreg.CloseKey(key)


def start_menu_dirs():
    out = []
    for p in (os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs"),
              os.path.join(os.environ.get("ProgramData", ""), r"Microsoft\Windows\Start Menu\Programs")):
        if p and os.path.isdir(p):
            out.append(p)
    return out


# ----------------------------------------------------------------------------
# PyQt5 部分
# ----------------------------------------------------------------------------
import PyQt5
from PyQt5.QtCore import (Qt, QTimer, QPoint, QPointF, QRectF, QSize, QFileInfo,
                          QSharedMemory, QEvent, pyqtSignal, QRect)
from PyQt5.QtGui import (QColor, QImage, QImageReader, QPainter, QPainterPath, QPixmap,
                         QLinearGradient, QRadialGradient, QPen, QBrush, QFont,
                         QFontMetrics, QGuiApplication, QCursor, QTransform)
from PyQt5.QtWidgets import (QApplication, QWidget, QSystemTrayIcon,
                             QAction, QActionGroup, QFileDialog, QMessageBox,
                             QFileIconProvider, QToolTip, QInputDialog)
from .organizer_service import OrganizerService
from .organizer_ui import CategoryPanel, set_entry_image_loader, _entry_menu_position
from .category_manager import CategoryManager
from .organizer_artwork import category_pixmap
from .menu_ui import ThemedMenu
from .branding import application_icon, configure_application
from .icon_theme import themed_icon_source
from .shortcut_search import ShortcutSearch
from .file_actions import FileActions
from .entry_drag import EntryDrag

# Qt 5 的安装路径探测在中文虚拟环境中可能损坏，显式保留 Unicode 插件路径。
_qt_platforms = os.path.join(os.path.dirname(PyQt5.__file__), "Qt5", "plugins", "platforms")
if os.path.isdir(_qt_platforms):
    os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH", _qt_platforms)

_DEFAULT_SHORTCUT_EDGE = object()


def configure_display_scaling():
    """保留 Windows 的 125%／150% 等实际缩放，避免先取整再补偿。"""
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)


def entry_hicon(path, px):
    """快捷方式先取 Shell 的显示图标，保留自定义资源与图标索引。"""
    is_link = path.lower().endswith(".lnk")
    if is_link:
        handle = extract_shell_hicon(path, 256)
        if handle:
            return handle
    real = (resolve_lnk_target(path) or path) if is_link else path
    if real.lower().endswith((".exe", ".dll", ".ico")) and os.path.exists(real):
        handle = extract_hicon(real, max(64, int(px)))
        if handle:
            return handle
    return None if is_link else extract_shell_hicon(path, 256)


class IconProvider(object):
    """负责把文件路径变成好看的图标（会缓存）。"""

    def __init__(self):
        self.provider = QFileIconProvider()
        self.cache = {}

    def get(self, path, px):
        key = (path.lower(), int(px))
        if key in self.cache:
            return self.cache[key]
        pm = None
        # 共用面板的提取顺序，避免固定入口和分类内图标不一致。
        hicon = entry_hicon(path, px)
        if hicon:
            img = hicon_to_qimage(hicon)
            if img is not None and not img.isNull():
                if img.format() != QImage.Format_ARGB32_Premultiplied:
                    img = img.convertToFormat(QImage.Format_ARGB32_Premultiplied)
                pm = QPixmap.fromImage(img)
        # 系统大图标不可用时，交给 Qt 自带的方式。
        if pm is None or pm.isNull():
            try:
                ic = self.provider.icon(QFileInfo(path))
                if not ic.isNull():
                    pm = ic.pixmap(QSize(int(px), int(px)))
            except Exception:
                pm = None
        if pm is None or pm.isNull():
            pm = QPixmap(int(px), int(px))
            pm.fill(Qt.transparent)
        else:
            img = pm.toImage()
            if img.format() != QImage.Format_ARGB32_Premultiplied:
                img = img.convertToFormat(QImage.Format_ARGB32_Premultiplied)
            # 提取缓存保留源像素，最终尺寸缓存负责一次缩放。
            pm = QPixmap.fromImage(img)
        self.cache[key] = pm
        return pm

    def clear(self):
        self.cache.clear()












def normalize_entry_image(image):
    """部分网页图标在 256px 画布中只有十几像素，先去掉异常留白再居中缩放。"""
    image = image.convertToFormat(QImage.Format_ARGB32)
    width, height = image.width(), image.height()
    alpha = image.constBits().asstring(image.byteCount())[3::4]
    occupied = [(y, alpha[y * width:(y + 1) * width]) for y in range(height)
                if any(alpha[y * width:(y + 1) * width])]
    if occupied:
        left = min(next(x for x, value in enumerate(row) if value) for _, row in occupied)
        right = max(width - 1 - next(x for x, value in enumerate(reversed(row)) if value) for _, row in occupied)
        top, bottom = occupied[0][0], occupied[-1][0]
        if right - left + 1 < width * .5 and bottom - top + 1 < height * .5:
            crop = QRect(left, top, right - left + 1, bottom - top + 1).adjusted(-2, -2, 2, 2)
            image = image.copy(crop.intersected(image.rect()))
            image = image.scaled(112, 112, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    if image.width() > 256 or image.height() > 256:
        image = image.scaled(256, 256, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return image


def entry_image(path):
    """供后台面板图标任务使用，上游的大图标提取返回 QImage 后再交给界面。"""
    ole = ctypes.windll.ole32
    initialized = ole.CoInitialize(None) >= 0
    try:
        handle = entry_hicon(path, 256)
        image = hicon_to_qimage(handle) if handle else None
        return normalize_entry_image(image) if image is not None else None
    finally:
        if initialized:
            ole.CoUninitialize()


class Shortcut(QWidget):
    """悬浮在桌面底部的 Shortcut 图标栏。"""

    running_ready = pyqtSignal(object)     # 后台线程扫描完进程后回传结果

    def __init__(self, cfg, tray=None, preview=False):
        super(Shortcut, self).__init__(None)
        self.cfg = cfg
        self.tray = tray
        self.preview = preview
        self.icons = IconProvider()
        self._exe_cache = {}
        self._category_signature = None
        self.organizer = None
        self.desktop_manager = None
        self.recycle_bin = None
        self.file_actions = FileActions(self)
        self.entry_drag = EntryDrag(self)
        self.category_panel = None
        self.category_manager = None
        self.search_bar = None
        self._drop_index = -1
        self.setAcceptDrops(True)

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool
                            | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)
        self.setWindowTitle(APP_TITLE)
        self.setWindowIcon(application_icon())
        self._register_main_window()

        self.base_icon = int(cfg["icon_size"])
        self.ui_mult = self._ui_mult()
        self.icon_size = self._scaled(self.base_icon)
        self.font_pt = max(8, int(round(9 * self.ui_mult)))
        self.prepare_label_font()
        self.pad_x = int(self.icon_size * 0.36)
        self.pad_y = int(self.icon_size * 0.34)
        self.gap_ratio = 0.26
        self.max_scale = 1.42
        self.corner_n = 4.0            # 超椭圆圆角指数（越大越"方"，2=正圆）
        self.mouse_x = -99999.0
        self.mouse_smooth = -99999.0   # 保留预览入口的鼠标状态
        self.stretch = 0.0             # 当前局部放大进度，不再驱动玻璃鼓包
        self.stretch_target = 0.0
        self.label_alpha = 0.0         # 名称气泡的淡入淡出
        self.spec_x = -99999.0
        self.spec_alpha = 0.0
        self.spec_target = 0.0
        self.hover_index = -1
        self.pressed = -1
        self.drag_idx = -1
        self.drag_moved = False
        self.drag_from_x = 0.0
        self.drag_start_pos = QPoint()
        self._drag_snapshot = None
        self.items = []
        self.cur = []
        self.tgt = []
        self.pops = []
        self.press_scale = []
        self.ripples = []
        self.bounces = []
        self._active_category_id = None
        self.desktop_folders = None
        self._pref_dialog = None
        self._presentation_visible = True
        self._shutting_down = False
        self.rects = []
        self.running = set()
        self.backdrop = None          # 模糊后的背景画面
        self.backdrop_ok = None       # 是否支持屏幕捕获排除
        self._hover_backdrop_pending = False
        self._sys_light = system_is_light()   # 缓存的系统深浅色状态
        self.label_below = False      # 名称是否画在玻璃条下方（贴屏幕顶部时为 True）
        self._last_move_calc = 0.0    # 上次重算目标尺寸的时间（鼠标事件节流用）
        self._frame_time = None      # 动画按实际经过时间插值，掉帧不改变速度
        self._split_flags = []
        self._logged_once = False

        self.timer = QTimer(self)
        self.timer.setInterval(16)     # ~60fps
        self.timer.timeout.connect(self._tick)

        self.proc_timer = QTimer(self)
        self.proc_timer.setInterval(8000)
        self.proc_timer.timeout.connect(self.refresh_running)
        self.running_ready.connect(self._apply_running)
        self._proc_busy = False

        self.geo_timer = QTimer(self)
        self.geo_timer.setInterval(2500)
        self.geo_timer.timeout.connect(self.check_position)

        # 定期重新抓一次背后的画面，让毛玻璃里的内容保持新鲜。
        # 具体间隔由"背景抓取频率"设置决定，智能模式下平时几乎不抓，
        # 只在显示、鼠标靠近、改设置时抓一次。
        self.blur_timer = QTimer(self)
        self.blur_timer.setInterval(BLUR_INTERVAL["smart"])
        self.blur_timer.timeout.connect(self.refresh_backdrop)

        # Shortcut 隐藏后仍让桌面盒子的自动主题响应系统变化。
        self.presentation_timer = QTimer(self)
        self.presentation_timer.setInterval(2500)
        self.presentation_timer.timeout.connect(self.apply_theme_follow)

        self._build_items()
        self.reposition()

    def is_light(self):
        """当前是不是浅色系（文字/小圆点用深色）。光感模式也算浅色系。"""
        t = str(self.cfg.get("theme", "auto"))
        if t in ("light", "gloss", "fog"):
            return True
        if t == "dark":
            return False
        return bool(self._sys_light)

    def theme_colors(self):
        """按当前模式返回整套配色与外观参数。

        公共字段：
          tint / tint_scale / tint_floor  玻璃底色和它的浓度曲线
          grad / hl                       竖向渐变与顶部高光（会被合成为一条）
          border / border_w               描边颜色与粗细
          corner                          圆角半径占条高的比例
          tile / tile_*                   图标是否带圆角底板（iOS 那种）
        """
        t = str(self.cfg.get("theme", "auto"))
        if t in ("gloss", "fog"):
            # ── 光感模式：玻璃上有一道明显的光照（上方光源 + 顶边亮线 + 斜向光斑） ──
            #     不做白色图标底板，图标保持原样，整体是"湿润的玻璃"质感
            return dict(
                light=True,
                gloss=True,
                tint=QColor(245, 248, 255),
                tint_scale=0.55,          # 比浅色模式透一点，光才透得出来
                tint_floor=20,
                fg=QColor(36, 42, 56),
                grad=[(0.00, 130), (0.18, 80), (0.52, 28), (0.80, 18), (1.00, 45)],
                hl=[(0.00, 100), (0.42, 28), (1.00, 0)],
                border=QColor(255, 255, 255, 160),
                border_w=1.0,
                corner=0.44,
                spec=140,                          # 跟随鼠标的高光更强（就是"光照"）
                spec_wide=1.9,                     # 光斑更宽更柔
                shadow=QColor(255, 255, 255, 180),
                label_bg=QColor(252, 253, 255, 240),
                label_border=QColor(255, 255, 255, 160),
                label_fg=QColor(30, 36, 50, 246),
                tile=False,
            )
        if self.is_light():
            return dict(
                light=True,
                tint=QColor(255, 255, 255),        # 纯白玻璃底色，避免发灰发脏
                tint_scale=0.65,
                tint_floor=28,
                fg=QColor(34, 34, 44),             # 小圆点/提示文字
                grad=[(0.00, 75), (0.30, 38), (0.72, 18), (1.00, 45)],
                hl=[(0.00, 120), (0.55, 36), (1.00, 0)],
                border=QColor(255, 255, 255, 135),  # 纯白高光微边，去掉深灰发脏边框
                border_w=1.0,
                corner=0.40,
                spec=80,
                shadow=QColor(255, 255, 255, 150),
                label_bg=QColor(255, 255, 255, 240),
                label_border=QColor(255, 255, 255, 140),
                label_fg=QColor(25, 25, 35, 246),
                tile=False,
            )
        return dict(
            light=False,
            tint=QColor(14, 15, 20),
            tint_scale=0.95,
            tint_floor=0,
            fg=QColor(255, 255, 255),
            grad=[(0.00, 24), (0.28, 10), (0.70, 4), (1.00, 14)],
            hl=[(0.00, 65), (0.55, 16), (1.00, 0)],
            border=QColor(255, 255, 255, 52),
            border_w=1.0,
            corner=0.40,
            spec=65,
            shadow=QColor(0, 0, 0, 130),
            label_bg=QColor(16, 17, 22, 235),
            label_border=QColor(255, 255, 255, 45),
            label_fg=QColor(255, 255, 255, 245),
            tile=False,
        )

    def apply_theme_follow(self):
        """跟随系统模式下，定期检查系统有没有切换深浅色。"""
        if str(self.cfg.get("theme", "auto")) != "auto":
            return
        cur = system_is_light()
        if cur != self._sys_light:
            self._sys_light = cur
            self.apply_presentation_theme()

    # ---------------- 屏幕与显示 ----------------
    def target_screen(self):
        screens = QGuiApplication.screens()
        name = self.cfg.get("screen_name")
        if name:
            for s in screens:
                if s.name() == name:
                    return s
        idx = self.cfg.get("screen_index", -1)
        if 0 <= idx < len(screens):
            return screens[idx]
        return QGuiApplication.primaryScreen()

    def set_screen(self, idx, name):
        self.cfg["screen_index"] = idx
        self.cfg["screen_name"] = name
        self.save_preferences()
        self.reload()
        if self.desktop_folders:
            self.desktop_folders.refresh()

    # ---------------- 尺寸与布局 ----------------
    def _ui_mult(self):
        """Windows 缩放适配。

        Qt 在某些机器上不会自动启用高 DPI 缩放，这时窗口坐标就等于物理像素，
        图标会显得偏小。这里用 Windows 自己的缩放比例补一次：
            目标物理尺寸 = 配置值 × Windows缩放
        如果 Qt 已经缩放过了（devicePixelRatio>1），就不再重复放大。
        """
        try:
            qt = float(self.target_screen().devicePixelRatio())
        except Exception:
            qt = 1.0
        if qt <= 0.01:
            qt = 1.0
        try:
            dpi = float(user32.GetDpiForSystem())
        except Exception:
            dpi = 96.0
        win = max(1.0, dpi / 96.0)
        m = win / qt
        return m if 0.1 < m < 4.0 else 1.0

    def _scaled(self, v):
        return max(20, int(round(v * self.ui_mult)))

    def bar_h(self):
        return self.icon_size + self.pad_y * 2

    def sep_width(self):
        """分隔符竖条本身的宽度（很窄）。"""
        return max(7.0, self.icon_size * 0.17)

    def sep_gap_width(self):
        """隔断模式下，被切开的玻璃条之间留出的空隙宽度。"""
        return max(14.0, self.icon_size * 0.42)

    def is_split_sep(self, i):
        """第 i 项是不是"隔断分隔符"：本身是分隔符，且左右两边都还有图标。

        结果在 _compute_split_flags() 里一次算好，避免每次查询都切片扫描列表
        （鼠标事件里会频繁调用，性能关键）。
        """
        flags = getattr(self, "_split_flags", None)
        if not flags or not (0 <= i < len(flags)):
            return False
        return flags[i]

    def _compute_split_flags(self):
        n = len(self.items)
        first_icon = -1
        last_icon = -1
        for i, it in enumerate(self.items):
            if not it.get("sep"):
                if first_icon < 0:
                    first_icon = i
                last_icon = i
        on = bool(self.cfg.get("sep_split", False))
        self._split_flags = [
            bool(on and self.items[i].get("sep")
                 and first_icon >= 0 and first_icon < i < last_icon)
            for i in range(n)
        ]

    def item_slot_width(self, i):
        """第 i 项在排版里占的宽度。"""
        if not (0 <= i < len(self.items)):
            return float(self.icon_size)
        if not self.items[i].get("sep"):
            return float(self.icon_size)
        if self.is_split_sep(i):
            return self.sep_gap_width()
        return self.sep_width()

    def is_vertical(self):
        return self.cfg.get("position", "bottom") in ("left", "right")

    def axis_length(self):
        """排布和动画沿主轴计算；竖排复用原横排的鱼眼插值。"""
        return self.height() if self.is_vertical() else self.width()

    def axis_transform(self):
        # 主轴 x 映射到屏幕 y，侧向 y 映射到屏幕 x；只转换几何，不旋转图标。
        return QTransform(0, 1, 1, 0, 0, 0) if self.is_vertical() else QTransform()

    def window_to_axis(self, point):
        return QPointF(point.y(), point.x()) if self.is_vertical() else QPointF(point)

    def window_rect(self, rect):
        return self.axis_transform().mapRect(rect)

    def side_label_width(self):
        return int(220 * self.ui_mult)

    def head_room(self):
        # 为朝屏幕内部放大的图标和名称预留透明区域；顶部/左侧镜像到下方。
        if self.bump_down():
            return 0
        room = int(max(self.icon_size * 0.55, self.bump_max())) + 8
        if self.cfg.get("show_name", True) and not self.label_below:
            room += (self.side_label_width() if self.is_vertical() else self.label_height()) + 8
        return room

    def bump_down(self):
        """顶部/左侧向正侧向放大，底部/右侧向负侧向放大。"""
        return bool(self.label_below)

    def bump_max(self):
        return self.icon_size * (self.hover_scale() - 1.0)

    def hover_scale(self):
        """旧低/中/高设置改为局部放大强度，默认峰值 1.42 倍。"""
        level = str(self.cfg.get("bump_level", "mid"))
        return next((scale for key, _, scale in BUMP_LEVELS if key == level), self.max_scale)

    def foot_room(self):
        """玻璃条【下方】留出的透明空间。

        顶部/左侧图标向正侧向放大，名称也在同侧，
        所以下方要一次留够；否则会被窗口边缘切掉。
        """
        if not self.bump_down():
            return 0
        grow = int(max(self.icon_size * 0.62, self.bump_max())) + 8   # 包含点击回弹的空间
        room = grow
        if self.cfg.get("show_name", True):
            label_room = self.side_label_width() if self.is_vertical() else self.label_height()
            room = max(room, int(label_room + grow + 6))
        return room

    def label_top_y(self, bar):
        """名称放在放大区之外，避免图标经过时推着气泡上下移动。"""
        if self.label_below:
            return bar.bottom() + self.icon_size * 0.32 + 8.0
        return 2.0

    def prepare_label_font(self):
        """窗口出现前完成中文文字引擎的首次绘制，避免第一次悬停时阻塞动画。"""
        self._label_font = QFont("Microsoft YaHei UI", self.font_pt)
        self._label_metrics = QFontMetrics(self._label_font)
        sample = QImage(240, 48, QImage.Format_ARGB32_Premultiplied)
        sample.fill(Qt.transparent)
        painter = QPainter(sample)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.setFont(self._label_font)
        painter.drawText(sample.rect(), Qt.AlignCenter, "应用 文档 · 0123 Aa")
        painter.end()

    def label_height(self):
        fm = self._label_metrics
        return float(fm.height() + 10)

    def side_room(self):
        """为局部鱼眼增加的总宽度预留主轴两端空间，不在动画中改变窗口尺寸。"""
        return int(self.icon_size * 0.55) + 4

    def side_expand(self):
        # 固定底座模式：悬停时不伸缩拉长玻璃条
        if self.cfg.get("fixed_shortcut_bar", True):
            return 0.0
        return sum(max(0.0, width - self.icon_size)
                   for item, width in zip(self.items, self.cur)
                   if not item.get("sep")) / 2.0

    def bar_rect_f(self):
        """底座保持固定长度与高度，悬停时不发生伸缩变形。"""
        e = self.side_expand()
        left = self.side_room() - e
        return QRectF(left, float(self.head_room()),
                      float(self.axis_length()) - 2.0 * left, float(self.bar_h()))

    def total_size(self):
        n = len(self.items)
        if n == 0:
            w = max(330, int(self.icon_size * 5.1))
        else:
            gap = self.icon_size * self.gap_ratio
            body = sum(self.item_slot_width(i) for i in range(n))
            w = int(self.pad_x * 2 + body + (n - 1) * gap)
        # 左右各留一条透明带，给"外扩"用
        h = int(self.bar_h() + self.head_room() + self.foot_room())
        length = w + self.side_room() * 2
        return QSize(h, length) if self.is_vertical() else QSize(length, h)

    def _build_items(self):
        self.layout_position()
        self.items = []
        self.pressed = self.drag_idx = -1
        for config_index, it in enumerate(self.cfg["items"]):
            if it.get("sep"):
                self.items.append({"sep": True, "path": "", "name": "",
                                   "pixmap": None, "exe": "", "config_index": config_index})
                continue
            path = it["path"]
            if path not in self._exe_cache:
                self._exe_cache[path] = self._exe_name(path)
            self.items.append({
                "path": path,
                "name": it.get("name") or os.path.splitext(os.path.basename(path))[0],
                "pixmap": self.icons.get(path, self.source_icon_size()),
                "exe": self._exe_cache[path],
                "config_index": config_index,
            })
        if self.organizer is not None:
            groups = self.organizer.groups()
            self._category_signature = self._organizer_signature(groups)
            categories = list(self.organizer.state["categories"])
            categories.append({"id": "__uncategorized__", "name": "未分类", "icon": "other"})
            separators = separator_positions(self.organizer.state)
            screen = self.target_screen()
            available = ((screen.availableGeometry().height() if self.is_vertical()
                          else screen.availableGeometry().width()) if screen else 1920) - self.search_extent(expanded=True)
            separator_width = self.sep_gap_width() if self.cfg.get("sep_split", False) else self.sep_width()
            system_room = self.icon_size * 3.8 + self.sep_width() + self.icon_size * self.gap_ratio
            slots = max(2, int((available - 100 - system_room) / (self.icon_size * 1.35)) - len(self.items))
            while True:
                shown = list(categories) if len(categories) <= slots else categories[:slots - 1]
                if len(shown) < len(categories):
                    shown.append({"id": "__more__", "name": "更多分类", "icon": "other"})
                lines = sum(category["id"] in separators for category in shown[:-1])
                lines += bool(self.items and "__before_categories__" in separators)
                needed = (100 + system_room + (len(self.items) + len(shown)) * self.icon_size * 1.35
                          + lines * (separator_width + self.icon_size * self.gap_ratio))
                if needed <= available or slots <= 2:
                    break
                slots -= 1
            if ("__before_categories__" in separators and self.items
                    and not self.items[-1].get("sep")):
                self.items.append({"sep": True, "path": "", "name": "", "pixmap": None,
                                   "exe": "", "config_index": None, "category_separator": True,
                                   "separator_after": "__before_categories__"})
            for position, category in enumerate(shown):
                cid = category["id"]
                count = len(groups.get(cid, []))
                self.items.append({"path": "", "name": category["name"] + (" · %d" % count if cid != "__more__" else ""),
                                   "pixmap": self._category_artwork(category),
                                   "exe": "", "category": cid, "config_index": None})
                if cid in separators and position < len(shown) - 1:
                    # 只在配置的位置划区，继续沿用原有分隔符绘制与动画。
                    self.items.append({"sep": True, "path": "", "name": "", "pixmap": None,
                                       "exe": "", "config_index": None, "category_separator": True,
                                       "separator_after": cid})
        if self.items:
            self.items.append({"sep": True, "system_separator": True, "path": "", "name": "",
                               "pixmap": None, "exe": "", "config_index": None})
        self.items.append({"computer": True, "path": "", "name": "此电脑", "exe": "",
                           "pixmap": themed_icon_source("computer"),
                           "config_index": None})
        self.items.append({"trash": True, "path": "", "name": "回收站", "exe": "",
                           "pixmap": None, "config_index": None})
        self.items.append({"settings": True, "path": "", "name": "偏好设置", "exe": "",
                           "pixmap": self._settings_artwork(),
                           "config_index": None})
        self._trash_changed(repaint=False)
        n = len(self.items)
        self.cur = []
        self.tgt = []
        self.pops = [0.0] * n
        self.press_scale = [1.0] * n
        self.ripples = [0.0] * n
        self.bounces = [0.0] * n
        self._compute_split_flags()
        if n == 0:
            self.stretch_target = 0.0
            self.stretch = 0.0
        self.resize(self.total_size())
        self._recalc(uniform=True)
        self.refresh_running()

    @staticmethod
    def _exe_name(path):
        real = path
        if path.lower().endswith(".lnk"):
            real = resolve_lnk_target(path) or path
        base = os.path.basename(real)
        return base.lower()

    def setup_recycle_bin(self):
        from .recycle_bin import RecycleBin
        self.recycle_bin = RecycleBin(self)
        self.recycle_bin.changed.connect(self._trash_changed)
        self.recycle_bin.error.connect(lambda message: self.organizer_message("回收站", message))
        QApplication.instance().aboutToQuit.connect(self.recycle_bin.stop)
        self._trash_changed()

    def _trash_changed(self, repaint=True):
        service = self.recycle_bin
        count = service.count if service else None
        for item in self.items:
            if not item.get("trash"):
                continue
            item["name"] = ("正在处理…" if service and service.busy else
                            "回收站" if count is None else "回收站 · 空" if count == 0 else
                            "回收站 · %d 项" % count)
            pixmap = themed_icon_source("trash_full" if count else "trash_empty")
            if item["pixmap"] is None or item["pixmap"].cacheKey() != pixmap.cacheKey():
                item["pixmap"] = pixmap
                item.pop("_scaled", None)
        if repaint:
            self.update(self.repaint_rect())

    def _recalc(self, uniform=False, light=False):
        n = len(self.items)
        if not n:
            self.tgt, self.cur, self.rects = [], [], []
            return
        S = float(self.icon_size)
        gap = S * self.gap_ratio
        rest = []
        x = self.side_room() + float(self.pad_x)
        for i in range(n):
            width = self.item_slot_width(i)
            rest.append(x + width / 2.0)
            x += width + gap
        pointer = self.mouse_x
        # 将当前排布上的鼠标映射回静态排布。图标让位后仍指向原目标，
        # 不拿不断移动的中心反复求解，避免停住鼠标后尺寸来回振荡。
        if not uniform and len(self.rects) == n and pointer > -9000:
            centers = [rect[0] for rect in self.rects]
            if pointer <= centers[0]:
                pointer = rest[0] + pointer - centers[0]
            elif pointer >= centers[-1]:
                pointer = rest[-1] + pointer - centers[-1]
            else:
                for i in range(1, n):
                    if pointer <= centers[i]:
                        fraction = (pointer - centers[i-1]) / (centers[i] - centers[i-1])
                        pointer = rest[i-1] + fraction * (rest[i] - rest[i-1])
                        break
        radius = S * 2.1
        active = not uniform and self.cfg['magnify'] and pointer > -9000
        amplitude = self.hover_scale() - 1.0
        self.tgt = []
        for i, item in enumerate(self.items):
            width = self.item_slot_width(i)
            if active and not item.get('sep'):
                distance = abs(pointer - rest[i])
                if distance < radius:
                    width = S * (1.0 + amplitude * .5 * (1.0 + math.cos(math.pi * distance / radius)))
            self.tgt.append(width)
        # 不再按总宽度归一化，远处图标始终保持原尺寸。
        if uniform or len(self.cur) != n:
            self.cur = list(self.tgt)
        if not light:
            self._layout()
            self.update(self.repaint_rect())

    def repaint_rect(self):
        """需要重绘的区域。比整个窗口小一圈，能明显省下绘制开销。

        注意：只要开着名称显示，就必须**无条件**把名称那一条也圈进来。
        名称画在玻璃条外面的透明区，如果只在"名称正在显示"时才重绘那一块，
        淡出的最后一帧就不会被擦掉，屏幕上的旧名称会一直残留。
        """
        if self.is_vertical():
            # 包含水平名称气泡与侧向放大区，淡出最后一帧也必须擦除。
            return self.rect()
        bar = self.bar_rect_f()
        grow = self.icon_size * 0.85 + 8
        r = QRectF(bar).adjusted(-self.side_room() - 4,
                               -grow if not self.bump_down() else -4,
                               self.side_room() + 4,
                               grow if self.bump_down() else 6)
        if self.cfg.get("show_name", True):
            th = self.label_height()
            ly = self.label_top_y(bar)
            r = r.united(QRectF(0.0, ly, float(self.width()), th))
        return r.toAlignedRect()

    # ---------------- 外形 ----------------
    def _corner_sets_for(self, r):
        """缓存的超椭圆（苹果式连续曲率）圆角采样点。

        普通圆角用的是正圆，圆弧和直边的接缝处曲率会突变，看着有一点"折"；
        超椭圆的曲率在接缝处正好为 0，所以过渡是连续的 —— 这就是苹果圆角更顺滑的原因。
        每段的圆角完全一样，所以只算一次缓存起来（性能关键）。
        """
        key = (round(r, 2), round(self.corner_n, 2))
        if getattr(self, "_corn_key", None) != key:
            e = 2.0 / max(2.01, self.corner_n)
            sets = {}
            for name, t0, t1 in (("tr", -math.pi / 2.0, 0.0), ("br", 0.0, math.pi / 2.0),
                                 ("bl", math.pi / 2.0, math.pi), ("tl", math.pi, math.pi * 1.5)):
                lst = []
                for i in range(1, 17):
                    t = t0 + (t1 - t0) * (i / 16.0)
                    cc, ss = math.cos(t), math.sin(t)
                    lst.append((math.copysign(abs(cc) ** e, cc),
                                math.copysign(abs(ss) ** e, ss)))
                sets[name] = lst
            self._corn_key = key
            self._corn_sets = sets
        return self._corn_sets

    def _add_corner_cached(self, path, cx, cy, r, name):
        for dx, dy in self._corn_sets[name]:
            path.lineTo(cx + dx * r, cy + dy * r)

    def corner_ratio(self):
        """圆角半径占条高的比例。光感模式更圆一些。"""
        t = str(self.cfg.get("theme", "auto"))
        return 0.44 if t in ("gloss", "fog") else 0.40

    def corner_radius(self):
        return max(8.0, min(self.bar_h() * self.corner_ratio(), self.bar_h() / 2.0))

    def shape_segments(self):
        """把玻璃背景按"隔断分隔符"切成若干段，返回 [(x_left, x_right), ...]。

        只有夹在两个图标中间的分隔符才会隔断；放在最左/最右的不生效。
        """
        bar = self.bar_rect_f()
        n = len(self.items)
        if n == 0 or not self.rects:
            return [(bar.left(), bar.right())]
        segs = []
        start = bar.left()
        gap_w = self.sep_gap_width()
        for i in range(n):
            if not self.is_split_sep(i):
                continue
            if i >= len(self.rects):
                continue
            c = self.rects[i][0]
            segs.append((start, c - gap_w / 2.0))
            start = c + gap_w / 2.0
        segs.append((start, bar.right()))
        # 太窄的段直接丢掉，避免画出怪东西
        return [(a, b) for (a, b) in segs if b - a > 12.0]

    def _one_shape(self, x_l, x_r, top0, bot):
        """保留原连续圆角和玻璃材质，悬停不再把边缘顶出鼓包。"""
        width = x_r - x_l
        if width <= 2.0:
            return None
        r = min(self.corner_radius(), width / 2.0 - .5, (bot - top0) / 2.0)
        self._corner_sets_for(r)
        path = QPainterPath()
        path.moveTo(x_l + r, top0)
        path.lineTo(x_r - r, top0)
        self._add_corner_cached(path, x_r - r, top0 + r, r, 'tr')
        path.lineTo(x_r, bot - r)
        self._add_corner_cached(path, x_r - r, bot - r, r, 'br')
        path.lineTo(x_l + r, bot)
        self._add_corner_cached(path, x_l + r, bot - r, r, 'bl')
        path.lineTo(x_l, top0 + r)
        self._add_corner_cached(path, x_l + r, top0 + r, r, 'tl')
        path.closeSubpath()
        return path

    def shape_paths(self):
        """整条玻璃的全部形状（隔断模式下会是好几段）。"""
        bar = self.bar_rect_f()
        top0 = bar.top()
        bot = bar.bottom()
        out = []
        for (a, b) in self.shape_segments():
            pa = self._one_shape(a, b, top0, bot)
            if pa is not None:
                out.append(pa)
        return out

    def shape_path(self):
        """兼容用：返回第一段形状（没有隔断时就等于整条）。"""
        ps = self.shape_paths()
        return ps[0] if ps else QPainterPath()

    def _layout(self):
        if not self.items:
            self.rects = []
            return
        bar = self.bar_rect_f()
        base_y = bar.top() + self.pad_y if self.bump_down() else bar.bottom() - self.pad_y
        gap = float(self.icon_size) * self.gap_ratio
        widths = [self.cur[i] if i < len(self.cur) else self.item_slot_width(i)
                  for i in range(len(self.items))]
        # 固定底座模式：各图标中心锚定在静止槽位，悬停放大不改变整条长度或推挤基准
        if self.cfg.get("fixed_shortcut_bar", True):
            n = len(self.items)
            slot_widths = [self.item_slot_width(i) for i in range(n)]
            static_len = sum(slot_widths) + gap * (n - 1)
            start_x = (self.axis_length() - static_len) / 2.0
            self.rects = []
            cur_x = start_x
            for i, (item, width) in enumerate(zip(self.items, widths)):
                sw = slot_widths[i]
                cx = cur_x + sw / 2.0
                self.rects.append((cx, width, width, base_y, bool(item.get('sep'))))
                cur_x += sw + gap
        else:
            # 固定间距、整排居中，放大的尺寸自然推开相邻图标与分隔符。
            length = sum(widths) + gap * (len(widths) - 1)
            x = (self.axis_length() - length) / 2.0
            self.rects = []
            for item, width in zip(self.items, widths):
                self.rects.append((x + width / 2.0, width, width, base_y, bool(item.get('sep'))))
                x += width + gap

    # ---------------- 位置 ----------------
    def search_extent(self, expanded=False):
        if (self.organizer is None or not self.cfg.get("show_search", False)
                or self.cfg.get("desktop_folder_mode", False)):
            return 0
        return int(round((220 if expanded and not self.is_vertical() else 40) * self.ui_mult)) + int(round(8 * self.ui_mult))

    def sync_search_geometry(self):
        if self.search_bar is None:
            return
        if (not self.cfg.get("show_search", False) or not self.isVisible()
                or self.cfg.get("desktop_folder_mode", False)):
            self.search_bar.hide()
            return
        width = int(round(40 * self.ui_mult))
        height = int(round(40 * self.ui_mult))
        gap = int(round(8 * self.ui_mult))
        bar = self.window_rect(QRectF(self.side_room(), self.head_room(),
                                     self.axis_length() - 2 * self.side_room(), self.bar_h())).toAlignedRect()
        area = self.target_screen().availableGeometry()
        if self.is_vertical():
            # 竖排窗口为名称气泡预留了很宽的透明区域，不能用窗口外沿定位。
            x = self.x() + bar.center().x() - width // 2
            y = self.y() + bar.top() - height - gap
        else:
            x = self.x() + bar.right() + 1 + gap
            if x + width > area.right() - 6:
                x = self.x() + bar.left() - width - gap
            y = self.y() + bar.center().y() - height // 2
        x = max(area.left() + 6, min(x, area.right() + 1 - width - 6))
        y = max(area.top() + 6, min(y, area.bottom() + 1 - height - 6))
        self.search_bar.set_anchor(QRect(x, y, width, height))
        self.search_bar.show()

    def layout_position(self):
        """返回玻璃靠屏幕边的侧向位置，并决定放大朝哪一侧。"""
        scr = self.target_screen()
        geo = scr.availableGeometry() if scr else None
        if geo is None:
            return 100, QRectF(0, 0, 1920, 1080)
        mode = str(self.cfg.get("position", "bottom"))
        margin = int(self.cfg.get("bottom_margin", 6))
        if mode in ("left", "right"):
            self.label_below = mode == "left"
            bar_side = geo.left() + margin if mode == "left" else geo.right() + 1 - margin - self.bar_h()
            return bar_side, geo
        if mode == "top":
            bar_top = geo.top() + margin
        elif mode == "custom":
            off = int(self.cfg.get("custom_bottom", 200))
            bar_top = geo.bottom() + 1 - off - self.bar_h()
        else:
            bar_top = geo.bottom() + 1 - margin - self.bar_h()
        # 上方空间不够放名称时，把名称改放到玻璃条下面
        need_above = int(self.icon_size * 0.55) + 8
        if self.cfg.get("show_name", True):
            need_above += int(self.label_height() + 8)
        self.label_below = bool(bar_top - geo.top() < need_above)
        return bar_top, geo

    def target_pos(self):
        bar_top, geo = self.layout_position()
        if self.is_vertical():
            x = bar_top - self.head_room()
            y = geo.top() + (geo.height() - self.height() + self.search_extent()) // 2
            return QPoint(int(x), int(y))
        x = geo.left() + (geo.width() - self.width() - self.search_extent()) // 2
        # 提前留出搜索展开的空间，点击时主 Shortcut 不移动，也不重算鱼眼布局。
        x = min(x, geo.right() + 1 - self.width() - self.search_extent(expanded=True) - 8)
        y = bar_top - self.head_room()
        return QPoint(int(x), int(y))

    def reposition(self):
        # 必须先算位置（这一步会决定名称放上面还是下面），
        # 再按算好的结果调整窗口大小，最后才移动。
        # 顺序反了的话，换位置的第一次会用到旧的名称方向，位置就会错一格。
        self.layout_position()
        want = self.total_size()
        if want != self.size():
            self.resize(want)
        self.move(self.target_pos())
        # 窗口尺寸 / 名称方向可能变了，图标坐标必须跟着重算，
        # 否则会出现"玻璃条位置对了、图标还停在旧位置"的现象
        self.cur = []
        self.tgt = []
        self._recalc(uniform=True)

        self.sync_search_geometry()

    def set_position(self, mode):
        if self.search_bar:
            self.search_bar.collapse(animate=False)
        if self.category_panel:
            self.category_panel.hide()
        self.cfg["position"] = mode
        self.save_preferences()
        # 换轴时清除旧鼠标坐标与拖动状态，避免第一次悬停沿旧方向放大。
        self.timer.stop()
        self.mouse_x = self.mouse_smooth = self.spec_x = -99999.0
        self.stretch = self.stretch_target = self.spec_alpha = self.spec_target = self.label_alpha = 0.0
        self.hover_index = self.pressed = self.drag_idx = self._drop_index = -1
        self.setCursor(Qt.ArrowCursor)
        self.backdrop = None
        self._build_items()
        self.reposition()
        self.refresh_backdrop()
        self.update()

    def add_screen_menu(self, menu):
        screen_menu = menu.addMenu(T("选择显示屏"))
        if isinstance(menu, ThemedMenu):
            screen_menu.menuAction().setIcon(menu.glyph("display"))
        sg = QActionGroup(screen_menu)
        sg.setExclusive(True)
        screens = QGuiApplication.screens()
        current_scr = self.target_screen()
        for i, s in enumerate(screens):
            is_prim = (s == QGuiApplication.primaryScreen())
            label = f"屏幕 {i+1} ({s.geometry().width()}x{s.geometry().height()})" + (" [主屏]" if is_prim else "")
            act = screen_menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(s == current_scr)
            sg.addAction(act)
            act.triggered.connect(lambda _=False, idx=i, sname=s.name(): self.set_screen(idx, sname))

    def open_settings_menu(self, idx=None):
        self.open_preferences_dialog()

    def add_position_menu(self, menu):
        positions = menu.addMenu(T("窗口位置"))
        if isinstance(menu, ThemedMenu):
            positions.menuAction().setIcon(menu.glyph("location"))
        group = QActionGroup(positions)
        group.setExclusive(True)
        for label, mode in POSITIONS:
            if mode == "custom":
                continue
            action = positions.addAction(T(label))
            action.setCheckable(True)
            action.setChecked(self.cfg.get("position", "bottom") == mode)
            group.addAction(action)
            action.triggered.connect(lambda _=False, value=mode: self.set_position(value))

    def apply_layer(self):
        """把窗口放到指定层级。

        置底用 HWND_BOTTOM：Shortcut 会退到所有普通窗口的下面（和桌面同级），
        这样最大化窗口、全屏应用都不会被它挡住；因为有定时重设，
        其它窗口激活改变 z 序后它会自动再沉下去。
        """
        if self.preview or not self.isVisible():
            return
        if self.search_bar and (self.search_bar.expanded or self.search_bar._reveal > 0):
            # 输入期间保持搜索窗口的焦点和层级，收起后再恢复置底策略。
            return
        try:
            user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND,
                                            ctypes.c_int, ctypes.c_int,
                                            ctypes.c_int, ctypes.c_int, ctypes.c_uint]
            user32.SetWindowPos.restype = wintypes.BOOL
            hwnd = wintypes.HWND(int(self.winId()))
            layer = str(self.cfg.get("layer", "bottom"))
            target = HWND_TOPMOST if layer == "top" else HWND_BOTTOM
            user32.SetWindowPos(hwnd, wintypes.HWND(target), 0, 0, 0, 0,
                                SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
            if self.search_bar and self.search_bar.isVisible() and not self.search_bar.expanded:
                user32.SetWindowPos(wintypes.HWND(int(self.search_bar.winId())), wintypes.HWND(target),
                                    0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
        except Exception:
            log("apply_layer 失败: " + traceback.format_exc())

    def check_position(self):
        if not self.isVisible():
            return
        was_below = self.label_below
        self.layout_position()          # 顺带更新 label_below
        size = self.total_size()
        changed = size != self.size()
        if changed:
            self.resize(size)
        want = self.target_pos()
        moved = want != self.pos()
        if moved:
            self.move(want)
        # 尺寸或名称方向变了，图标坐标要重算（否则图标会停在旧位置）
        if changed or self.label_below != was_below:
            self.cur = []
            self.tgt = []
            self._recalc(uniform=True)
        self.apply_theme_follow()
        self.apply_layer()
        if changed or moved or self.label_below != was_below:
            self.sync_search_geometry()
            self.refresh_backdrop()

        # 后台静默空闲时自动压缩物理内存工作集
        if (self.hover_index < 0 and self.pressed < 0
                and (not self.category_panel or not self.category_panel.isVisible())
                and (not self.search_bar or not self.search_bar.expanded)):
            self._idle_ticks = getattr(self, "_idle_ticks", 0) + 1
            if self._idle_ticks == 4:  # 空闲满 10 秒后触发一次内存极限瘦身
                trim_process_memory()
        else:
            self._idle_ticks = 0

    # ---------------- 运行状态 ----------------
    def _tracked_executables(self):
        return {item["exe"] for item in self.items
                if item.get("exe", "").endswith((".exe", ".com", ".scr"))}

    def refresh_running(self):
        """扫描"哪些程序正在运行"。

        枚举系统进程放在后台线程，避免与界面动画争用主线程；
        扫完用信号把结果传回来，只更新相关应用的标记。
        """
        needed = (not self.preview and self.isVisible()
                  and self.cfg["running_dots"] and bool(self._tracked_executables()))
        if not needed:
            self.proc_timer.stop()
            if self.running:
                self.running = set()
                if self.isVisible():
                    self.update(self.repaint_rect())
            return
        if not self.proc_timer.isActive():
            self.proc_timer.start()
        if getattr(self, "_proc_busy", False):
            return
        self._proc_busy = True
        threading.Thread(target=self._scan_procs, daemon=True).start()

    def _scan_procs(self):
        try:
            names = get_running_exe_names()
        except Exception:
            names = set()
        try:
            self.running_ready.emit(names)
        except Exception:
            pass

    def _apply_running(self, names):
        self._proc_busy = False
        # 其他应用的进程变化不影响 Shortcut，不因此唤醒绘制。
        names = (set(names) & self._tracked_executables()
                 if self.cfg["running_dots"] and self.isVisible() else set())
        if names != self.running:
            self.running = names
            if self.isVisible():
                self.update(self.repaint_rect())

    # ---------------- 动画 ----------------
    def _tick(self):
        now = time.perf_counter()
        dt = now - self._frame_time if self._frame_time is not None else .016
        self._frame_time = now
        moving = False
        # 无超调的时间插值：入场稍快、离开稍柔和；鼠标中途改向直接接续当前状态。
        n_items = len(self.items)
        if len(self.cur) != n_items:
            self.cur = list(self.tgt)
        if len(self.pops) != n_items:
            self.pops = [0.0] * n_items
        if len(self.press_scale) != n_items:
            self.press_scale = [1.0] * n_items
        if len(self.ripples) != n_items:
            self.ripples = [0.0] * n_items
        if len(self.bounces) != n_items:
            self.bounces = [0.0] * n_items

        for i in range(len(self.cur)):
            delta = self.tgt[i] - self.cur[i]
            if abs(delta) > .06:
                tau = .060 if delta > 0 else .085
                self.cur[i] += delta * (1.0 - math.exp(-dt / tau))
                moving = True
            elif delta:
                self.cur[i] = self.tgt[i]
                moving = True

        # 按下态平滑下沉与微压插值 (MouseDown Compression)
        for i in range(n_items):
            tgt_press = 0.91 if i == self.pressed else 1.0
            delta_p = tgt_press - self.press_scale[i]
            if abs(delta_p) > 0.003:
                tau_p = 0.035 if delta_p < 0 else 0.055
                self.press_scale[i] += delta_p * (1.0 - math.exp(-dt / tau_p))
                moving = True
            elif delta_p:
                self.press_scale[i] = tgt_press
                moving = True

        # 释放后的弹性阻尼弹跳 (Spring Rebound, ~320ms)
        for i in range(len(self.pops)):
            if self.pops[i] > 0:
                self.pops[i] = max(0.0, self.pops[i] - dt / 0.32)
                moving = True

        # 点击光波涟漪淡出 (Ripple Pulse, ~380ms)
        for i in range(len(self.ripples)):
            if self.ripples[i] > 0:
                self.ripples[i] = max(0.0, self.ripples[i] - dt / 0.38)
                moving = True

        # macOS 风格启动轻快跳动 (Launch Bounce, ~360ms * 3次)
        for i in range(len(self.bounces)):
            if self.bounces[i] > 0:
                self.bounces[i] = max(0.0, self.bounces[i] - dt / 0.36)
                moving = True
        for current, target, tau, epsilon in (
                ('spec_alpha', self.spec_target, .080, .008),
                ('label_alpha', 1.0 if 0 <= self.hover_index < len(self.items) else 0.0, .060, .008)):
            value = getattr(self, current)
            delta = target - value
            if abs(delta) > epsilon:
                setattr(self, current, value + delta * (1.0 - math.exp(-dt / tau)))
                moving = True
            elif delta:
                setattr(self, current, target)
                moving = True
        self.stretch = max((max(0.0, width / self.icon_size - 1.0)
                            for item, width in zip(self.items, self.cur) if not item.get('sep')), default=0.0) / (self.hover_scale() - 1.0)
        if moving:
            self._layout()
        else:
            self.timer.stop()
            self._frame_time = None
            if self._hover_backdrop_pending:
                self._hover_backdrop_pending = False
                if str(self.cfg.get("blur_mode", "smart")) != "off":
                    self.refresh_backdrop()
        # 无放大时鼠标仍可移动柔光；最后一帧也负责擦除已淡出的内容。
        self.update(self.repaint_rect())

    def _kick(self):
        if not self.preview and not self.isVisible():
            return
        if not self.timer.isActive():
            self._frame_time = time.perf_counter()
            self.timer.start()

    # ---------------- 鼠标 ----------------
    def enterEvent(self, e):
        if QApplication.activePopupWidget() is not None:
            return
        # 弹窗关闭可能只有 Enter 而没有 MouseMove，必须更新坐标，不能重新点亮旧位置。
        local = self.mapFromGlobal(e.globalPos() if hasattr(e, "globalPos") else QCursor.pos())
        pos = self.window_to_axis(local)
        bar = self.bar_rect_f()
        idx = self._hit(local)
        near = self.rect().contains(local) and ((bar.top() - 12 <= pos.y() <= bar.bottom() + 12) or idx >= 0)
        self.hover_index = idx if near else -1
        self.mouse_x = self.mouse_smooth = self.spec_x = float(pos.x()) if near else -99999.0
        self.spec_target = self.stretch_target = 1.0 if near else 0.0
        self.setCursor(Qt.PointingHandCursor if self.hover_index >= 0 else Qt.ArrowCursor)
        self._recalc(light=True)
        if self.cfg["glass"] and str(self.cfg.get("blur_mode", "smart")) != "off":
            # 动画先使用已有底图，停稳后合并补抓一次，不占用移入事件和首帧。
            self._hover_backdrop_pending = True
        self._kick()
        super(Shortcut, self).enterEvent(e)

    def _clear_hover(self):
        """弹窗接管鼠标时也收回旧高亮，不能只等待系统发送 Leave。"""
        self.mouse_x = -99999.0
        self.spec_target = 0.0
        self.stretch_target = 0.0
        self.hover_index = -1
        self.pressed = -1
        self.setCursor(Qt.ArrowCursor)
        QToolTip.hideText()
        self._recalc()
        self._kick()

    def leaveEvent(self, e):
        self._clear_hover()
        super(Shortcut, self).leaveEvent(e)

    def mouseMoveEvent(self, e):
        self._idle_ticks = 0
        if QApplication.activePopupWidget() is not None:
            return
        pos = self.window_to_axis(e.pos())
        self.mouse_x = float(pos.x())
        self.spec_x = float(pos.x())
        # 沿 Shortcut 拖动排序，拖离玻璃条或按 Shift 时进入虚拟入口拖动。
        if self.pressed >= 0 and e.buttons() & Qt.LeftButton:
            it = self.items[self.pressed]
            if (it.get("path") and not it.get("sep")
                    and (not self.cfg.get("reorder", True) or e.modifiers() & Qt.ShiftModifier
                         or not self.bar_rect_f().adjusted(-16, -30, 16, 30).contains(pos))
                    and (e.pos() - self.drag_start_pos).manhattanLength() > QApplication.startDragDistance()):
                paths = [it["path"]]
                icon = it.get("pixmap") or QPixmap()
                self.pressed = self.drag_idx = -1
                def cancel():
                    self._entry_drag_target(paths, QPoint(), "clear", "pinned")
                    self._restore_drag_order()
                    self._clear_hover()
                def drop(point):
                    if self._entry_drag_target(paths, point, "drop", "pinned"):
                        self._drag_snapshot = None
                        self._clear_hover()
                    else:
                        cancel()
                self.entry_drag.begin(self, paths, icon, e.globalPos(),
                                      lambda point: self._entry_drag_target(paths, point, "hover", "pinned"), drop, cancel)
                return
        # 拖动排序模式：按住左键移动 = 排序
        if self.drag_idx >= 0 and (e.buttons() & Qt.LeftButton):
            if (e.pos() - self.drag_start_pos).manhattanLength() >= QApplication.startDragDistance():
                self.drag_moved = True
            if self.drag_moved:
                if (self.items[self.drag_idx].get("category")
                        and not self.bar_rect_f().adjusted(-16, -30, 16, 30).contains(pos)):
                    return
                if QWidget.keyboardGrabber() is not self:
                    self.grabKeyboard()
                now = time.perf_counter()
                if now - self._last_move_calc < .008:
                    return
                self._last_move_calc = now
                self._drag_reorder(float(pos.x()))
                self.hover_index = self.drag_idx      # 名称气泡跟着被拖的图标
                self._recalc(light=True)
                self._kick()
                super(Shortcut, self).mouseMoveEvent(e)
                return
        # 只有鼠标进到玻璃条或放大图标附近才触发；名称留白不触发，
        # 免得鼠标从上面路过时整条乱动。
        bar = self.bar_rect_f()
        idx = self._hit(e.pos())
        near = (bar.top() - 12 <= pos.y() <= bar.bottom() + 12) or idx >= 0
        self.stretch_target = 1.0 if (self.items and near) else 0.0
        self.spec_target = 1.0 if near else 0.0
        if not near:
            # 侧边名称预留区较宽，鼠标经过透明留白时不驱动鱼眼或柔光。
            self.mouse_x = self.spec_x = -99999.0
        if idx != self.hover_index:
            self.hover_index = idx
            QToolTip.hideText()
            # 只有悬停目标变了才设置鼠标形状（SetCursor 是系统调用，别每次都调）
            self.setCursor(Qt.PointingHandCursor if idx >= 0 else Qt.ArrowCursor)
            self._recalc(light=True)
        else:
            # 高刷新率鼠标每秒能上报上千次移动，没必要每次运动都全量重算；
            # 限制到约 120Hz，剩下的交给 60fps 的动画帧去插值，肉眼看不出差别。
            now = time.perf_counter()
            if now - self._last_move_calc >= 0.008:
                self._last_move_calc = now
                self._recalc(light=True)
        self._kick()
        super(Shortcut, self).mouseMoveEvent(e)

    def _hit(self, pos):
        if not self.rects:
            return -1
        pos = self.window_to_axis(pos)
        y = float(pos.y())
        x = float(pos.x())
        gap = float(self.icon_size) * self.gap_ratio
        for i, r in enumerate(self.rects):
            if r[4]:            # 分隔符不响应鼠标
                continue
            cx, w, h, by = r[0], r[1], r[2], r[3]
            # 允许覆盖图标间隙的一半，消除相邻图标之间 17px 的不可点击死区
            if abs(x - cx) > (w + gap) / 2.0:
                continue
            if self.bump_down():
                # by 是图标顶边
                if (by - 10) <= y <= (by + h + 16):
                    return i
            else:
                # by 是图标底边
                if (by - h - 10) <= y <= (by + 16):
                    return i
        return -1

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.drag_start_pos = QPoint(e.pos())
            self._drag_snapshot = {"items": [dict(item) for item in self.cfg["items"]],
                                   "categories": list(self.organizer.state["categories"]) if self.organizer else [],
                                   "separators": separator_positions(self.organizer.state) if self.organizer else []}
            self.pressed = self._hit(e.pos())
            # 弹窗关闭后的点击不一定先经过 MouseMove，点击反馈直接绑定此次命中的入口。
            self.hover_index = self.pressed
            self.mouse_x = self.spec_x = float(self.window_to_axis(e.pos()).x()) if self.pressed >= 0 else -99999.0
            self.spec_target = self.stretch_target = 1.0 if self.pressed >= 0 else 0.0
            self._recalc(light=True)
            self._kick()
            self.drag_idx = -1
            self.drag_moved = False
            self.drag_from_x = float(self.window_to_axis(e.pos()).x())
            if ((self.cfg.get("reorder", True) or (self.pressed >= 0 and self.items[self.pressed].get("category"))) and self.pressed >= 0
                    and not self.items[self.pressed].get("sep")
                    and not self.items[self.pressed].get("trash")
                    and not self.items[self.pressed].get("computer")):
                if self.items[self.pressed].get("category") in ("__uncategorized__", "__more__"):
                    return
                self.drag_idx = self.pressed
                self.drag_from_x = float(self.window_to_axis(e.pos()).x())
        super(Shortcut, self).mousePressEvent(e)

    def _restore_drag_order(self):
        snapshot, self._drag_snapshot = self._drag_snapshot, None
        self.pressed = self.drag_idx = -1
        self.drag_moved = False
        if QWidget.keyboardGrabber() is self:
            self.releaseKeyboard()
        if not snapshot:
            return
        changed = self.cfg["items"] != snapshot["items"]
        self.cfg["items"] = snapshot["items"]
        if self.organizer and (self.organizer.state["categories"] != snapshot["categories"]
                               or separator_positions(self.organizer.state) != snapshot["separators"]):
            self.organizer.update_categories(snapshot["categories"], snapshot["separators"])
        if changed:
            save_config(self.cfg)
        self._build_items()
        self.reposition()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self.drag_idx >= 0:
            self._restore_drag_order()
            self._clear_hover()
            event.accept()
            return
        super().keyPressEvent(event)

    def _drag_reorder(self, x):
        # 快速跨过多项时直接追到当前指针所在位置，不要求每个邻居收到一次鼠标事件。
        for _ in range(len(self.items)):
            previous = self.drag_idx
            self._drag_reorder_step(x)
            if self.drag_idx == previous:
                break

    def _drag_reorder_step(self, x):
        """拖动排序：跟紧邻的图标/分隔符「一步一步」交换位置。

        带迟滞（要多越过邻居中心 30% 图标宽度才换），所以不会在临界点反复横跳；
        换位后也不重置图标尺寸，避免忽大忽小的闪烁。
        """
        category_drag = self.items[self.drag_idx].get("category") if self.drag_idx >= 0 else None
        n = len(self.items) if category_drag else len(self.cfg["items"])
        if self.drag_idx < 0 or n < 2:
            return
        margin = self.icon_size * 0.30
        # 找左右两边最近的"非自己"条目（分隔符也参与，这样才能被拖到分隔符后面）
        left = None
        for i in range(self.drag_idx - 1, -1, -1):
            if category_drag and self.items[i].get("sep"):
                continue
            if i != self.drag_idx:
                left = i
                break
        right = None
        for i in range(self.drag_idx + 1, n):
            if category_drag and self.items[i].get("sep"):
                continue
            right = i
            break
        target = -1
        if left is not None and x < self.rects[left][0] - margin:
            target = left
        elif right is not None and x > self.rects[right][0] + margin:
            target = right
        if target < 0 or target == self.drag_idx:
            return
        if category_drag and self.items[target].get("category") in (None, "__uncategorized__", "__more__"):
            return
        if category_drag:
            # 分类跨越分隔符时交换图标位置，保留划区，避免出现连续竖线。
            self.items[self.drag_idx], self.items[target] = self.items[target], self.items[self.drag_idx]
        else:
            it = self.items.pop(self.drag_idx)
            self.items.insert(target, it)
        if category_drag:
            visible = {entry["separator_after"] for entry in self.items if entry.get("category_separator")}
            separators = [key for key in separator_positions(self.organizer.state)
                          if key not in visible]
            anchor = "__before_categories__"
            for entry in self.items:
                if entry.get("category"):
                    anchor = entry["category"]
                elif entry.get("category_separator"):
                    separators.append(anchor)
                    entry["separator_after"] = anchor
            self.organizer.state["shortcut_separators"] = separators
            order = [entry["category"] for entry in self.items if entry.get("category") not in (None, "__uncategorized__", "__more__")]
            categories = self.organizer.state["categories"]
            by_id = {c["id"]: c for c in categories}
            self.organizer.state["categories"] = [by_id[cid] for cid in order] + [c for c in categories if c["id"] not in order]
        else:
            ci = self.cfg["items"].pop(self.drag_idx)
            self.cfg["items"].insert(target, ci)
            for i, entry in enumerate(self.items[:n]):
                entry["config_index"] = i
        self.drag_idx = target
        self.pressed = target
        # 顺序变了，"哪些分隔符要隔断背景"必须跟着重算，
        # 否则把图标拖到分隔符两边时不会出现隔断效果
        self._compute_split_flags()
        self._recalc()          # 不重置尺寸，保持放大状态，避免闪烁
        self._kick()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            if QWidget.keyboardGrabber() is self:
                self.releaseKeyboard()
            if self.drag_idx >= 0:
                if self.drag_moved:
                    position = self.window_to_axis(e.pos())
                    if not self.bar_rect_f().adjusted(-16, -30, 16, 30).contains(position):
                        entry = self.items[self.drag_idx]
                        if entry.get("path") and self._entry_drag_target([entry["path"]], e.globalPos(), "drop", "pinned"):
                            self.drag_idx = self.pressed = -1
                            self._drag_snapshot = None
                            self._clear_hover()
                        else:
                            self._restore_drag_order()
                            self._clear_hover()
                        e.accept()
                        return
                    self._drag_reorder(float(self.window_to_axis(e.pos()).x()))
                    category_drag = self.items[self.drag_idx].get("category")
                    self.drag_idx = -1
                    self.pressed = -1
                    self._drag_snapshot = None
                    if category_drag:
                        self.organizer.update_categories(self.organizer.state["categories"])
                    else:
                        save_config(self.cfg)      # 拖完把新顺序存下来
                    self._kick()
                    super(Shortcut, self).mouseReleaseEvent(e)
                    return
                self.drag_idx = -1
            idx = self._hit(e.pos())
            if idx >= 0 and idx == self.pressed:
                self.pops[idx] = 1.0
                if idx < len(self.ripples):
                    self.ripples[idx] = 1.0
                self.start_launch_bounce(idx)
                self._kick()
                if self.items[idx].get("trash"):
                    if self.recycle_bin:
                        self.recycle_bin.open()
                elif self.items[idx].get("computer"):
                    self.launch("shell:MyComputerFolder")
                elif self.items[idx].get("settings"):
                    self.open_settings_menu(idx)
                elif self.items[idx].get("category"):
                    self.open_category(self.items[idx]["category"])
                else:
                    self.launch(self.items[idx]["path"])
            self.pressed = -1
            self._drag_snapshot = None
        super(Shortcut, self).mouseReleaseEvent(e)

    def launch(self, path):
        if not path:
            return
        path = str(path).strip('\"\'')
        # 全局路径与旧用户名纠偏
        path = fix_user_path(path)
        log("启动: " + path)

        # 1. 协议、特殊外壳路径（包括 "此电脑"、CLSID、shell 协议、本地文件夹）
        base_name = os.path.basename(path).lower()
        if (path.startswith("shell:")
                or path.startswith("::{")
                or "此电脑" in base_name
                or "this pc" in base_name
                or "computer" == base_name
                or os.path.isdir(path)):
            try:
                target = path if (path.startswith("shell:") or os.path.isdir(path)) else "shell:MyComputerFolder"
                subprocess.Popen(["explorer.exe", target], close_fds=True)
                log("成功通过 explorer 打开系统外壳: " + target)
                return
            except Exception as e:
                log("explorer 打开失败: " + str(e))

        # 2. 网页与游戏 URL 快捷方式（.url 文件）
        if path.lower().endswith(".url") and os.path.exists(path):
            try:
                import configparser
                cp = configparser.ConfigParser()
                cp.read(path, encoding="utf-8", errors="ignore")
                url = cp.get("InternetShortcut", "URL", fallback=None)
                if url:
                    os.startfile(url)
                    log("成功启动 URL 协议: " + url)
                    return
            except Exception:
                pass

        # 3. 快捷方式 (.lnk) 智能解析与外壳拉起
        target_path = path
        if path.lower().endswith(".lnk"):
            # 先让 Windows 执行原快捷方式，保留其“管理员运行”、显示方式等属性。
            try:
                if self.file_actions.shell.invoke(path, "open"):
                    log("通过原快捷方式启动: " + path)
                return  # 取消 UAC 时也不能降级为普通启动或再次提示。
            except OSError as error:
                log("原快捷方式启动失败，尝试恢复目标路径: " + str(error))
            # 只解析所选入口；其他目录的同名链接可能有不同目标或启动参数。
            # 尝试通过 IShellLinkW 解析出快捷方式的真实目标、启动参数和工作目录
            info = resolve_shortcut_info(target_path)
            if info:
                real_target, args, work_dir = info
                if real_target and os.path.exists(real_target):
                    cwd = work_dir if (work_dir and os.path.exists(work_dir)) else os.path.dirname(real_target)
                    # 优先使用 Windows 原生 ShellExecuteW 启动（保留参数如 PWA app-id、桌面图标参数、工作目录）
                    ret = ctypes.windll.shell32.ShellExecuteW(None, "open", real_target, args if args else None, cwd, 1)
                    if ret > 32:
                        log("通过 ShellExecuteW 成功运行目标: " + real_target + (" " + args if args else ""))
                        return
                    elif ret in (5, 740):
                        # 权限受限，自动触发 UAC 提权提示
                        ret_runas = ctypes.windll.shell32.ShellExecuteW(None, "runas", real_target, args if args else None, cwd, 1)
                        if ret_runas > 32:
                            log("以管理员权限启动目标程序: " + real_target)
                            return
                        elif ret_runas == 1223:
                            log("用户取消了 UAC 提权: " + real_target)
                            return
                    elif ret == 1223:
                        log("用户取消了启动: " + real_target)
                        return

        # 4. 常规外壳启动与 UAC 提权（适用于直接指向的 exe、文档、以及 UWP 商店应用如 Twinkle Tray）
        try:
            cwd = os.path.dirname(target_path) if os.path.isdir(os.path.dirname(target_path)) else None
            ret = ctypes.windll.shell32.ShellExecuteW(None, "open", target_path, None, cwd, 1)
            if ret > 32:
                log("通过系统外壳关联成功拉起: " + target_path)
                return
            elif ret in (5, 740):
                ret_runas = ctypes.windll.shell32.ShellExecuteW(None, "runas", target_path, None, cwd, 1)
                if ret_runas > 32:
                    log("以管理员权限拉起: " + target_path)
                    return
                elif ret_runas == 1223:
                    log("用户取消了 UAC 提权: " + target_path)
                    return
            elif ret == 1223:
                log("用户取消了操作: " + target_path)
                return

            # 回退机制：os.startfile
            os.startfile(target_path)
            log("通过 os.startfile 成功拉起: " + target_path)
        except OSError as exc:
            win_err = getattr(exc, "winerror", None)
            if win_err == 740:
                ret_runas = ctypes.windll.shell32.ShellExecuteW(None, "runas", target_path, None, None, 1)
                if ret_runas > 32:
                    log("以管理员权限拉起: " + target_path)
                elif ret_runas == 1223:
                    log("用户取消了 UAC 提权: " + target_path)
            elif win_err == 1223:
                log("用户取消了操作: " + target_path)
            else:
                log("启动异常: " + traceback.format_exc())

    def contextMenuEvent(self, e):
        idx = self._hit(e.pos())
        if idx >= 0 and self.items[idx].get("settings"):
            self.open_settings_menu(idx)
            return
        m = ThemedMenu(self, light=self.is_light(), colors=self.theme_colors())
        file_commands, file_paths = {}, []

        # 偏好设置总设置项快捷入口
        pref_act = m.addAction(m.glyph("settings"), "偏好设置 (总设置)…")
        pref_act.triggered.connect(self.open_preferences_dialog)
        m.addSeparator()

        if idx >= 0 and self.items[idx].get("trash") and self.recycle_bin:
            m.addAction(m.glyph("open"), "打开回收站").triggered.connect(self.recycle_bin.open)
            empty = m.addAction(m.glyph("remove"), "清空回收站…")
            empty.setEnabled(self.recycle_bin.count != 0 and not self.recycle_bin.busy)
            empty.triggered.connect(self.recycle_bin.empty)
            m.addSeparator()
        elif idx >= 0 and self.items[idx].get("computer"):
            m.addAction(m.glyph("open"), "打开此电脑").triggered.connect(
                lambda: self.launch("shell:MyComputerFolder"))
            m.addSeparator()
        elif idx >= 0 and self.items[idx].get("category"):
            cid = self.items[idx]["category"]
            m.addAction(m.glyph("open"), "打开分类").triggered.connect(lambda: self.open_category(cid))
            act_change_icon = m.addAction(m.glyph("settings"), "更换分类图标…")
            act_change_icon.triggered.connect(lambda _=False, c=cid: self._ask_change_category_icon(c))
            custom_map = self.cfg.get("category_custom_icons", {})
            if custom_map.get(cid):
                act_reset_icon = m.addAction("恢复默认分类图标")
                act_reset_icon.triggered.connect(lambda _=False, c=cid: self.set_category_custom_icon(c, None))
            m.addSeparator()
            self.add_organizer_actions(m)
            m.addSeparator()
        elif idx >= 0 and not self.items[idx].get("sep"):
            it = self.items[idx]
            a = QAction("打开 " + it["name"], m)
            a.setIcon(m.glyph("open"))
            a.triggered.connect(lambda _=False, p=it["path"]: self.launch(p))
            m.addAction(a)
            m.addSeparator()
            file_paths = [it["path"]]
            file_commands = self.file_actions.add_menu(m, file_paths)
            m.addSeparator()
            if self.organizer is not None:
                sub = m.addMenu("放入分类")
                for c in self.organizer.state["categories"]:
                    sub.addAction(c["name"]).triggered.connect(lambda _=False, cid=c["id"], path=it["path"]: self.organizer.assign_paths([path], cid))
        elif self.organizer is not None:
            self.add_organizer_actions(m)
        self.add_screen_menu(m)
        self.add_desktop_icons_action(m)
        self.add_position_menu(m)
        m.addSeparator()
        hide_action = m.addAction(m.glyph("show"), "隐藏 Shortcut")
        hide_action.setToolTip("可从托盘菜单重新显示")
        hide_action.triggered.connect(lambda: self.set_presentation_visible(False))
        m.addAction(m.glyph("exit"), "退出").triggered.connect(QApplication.instance().quit)
        m.setToolTipsVisible(True)
        anchor = self.menu_anchor(idx)
        screen = QApplication.screenAt(anchor.center()) or self.target_screen()
        preferred = {"bottom": "above", "top": "below", "left": "right", "right": "left"}.get(
            self.cfg.get("position", "bottom"), "below" if self.bump_down() else "above")
        m.ensurePolished()
        self._clear_hover()
        chosen = m.exec_(_entry_menu_position(anchor, m.sizeHint(), screen.availableGeometry(), preferred))
        m.deleteLater()
        if chosen in file_commands:
            self.file_actions.perform(file_commands[chosen], file_paths)

    def menu_anchor(self, index):
        """Shortcut 菜单按可见图标展开，透明动画区不参与定位。"""
        if 0 <= index < len(self.rects):
            cx, width, height, base, _ = self.rects[index]
            local = self.window_rect(QRectF(cx - width / 2, base if self.bump_down() else base - height,
                                            width, height)).adjusted(-6, -6, 6, 6)
        else:
            local = self.window_rect(self.bar_rect_f())
        rect = local.toAlignedRect().intersected(self.rect())
        return QRect(self.mapToGlobal(rect.topLeft()), rect.size())

    def setup_organizer(self, directories=None):
        set_entry_image_loader(entry_image)
        self.organizer = OrganizerService(self.cfg["organizer"], self.save_preferences, self, directories)
        self.category_panel = CategoryPanel(self.organizer, self.launch, self.pin_path, self.is_light(),
                                            menu_theme=self.theme_colors, file_actions=self.file_actions,
                                            drag_session=self.entry_drag, drag_target=self._entry_drag_target,
                                            cfg=self.cfg)
        self.category_panel.on_hide_callback = self._on_panel_closed
        self.search_bar = ShortcutSearch(self)
        self.organizer.changed.connect(self._organizer_changed)
        self.organizer.error.connect(lambda message: self.organizer_message("整理提示", message))
        self.organizer.completed.connect(lambda count: self.organizer_message("整理完成", "已分类 %d 个项目，原文件位置保持不变。" % count))
        QApplication.instance().aboutToQuit.connect(self.organizer.stop)

        # 桌面文件夹模式组件
        from .desktop_folders import DesktopFoldersWidget
        self.desktop_folders = DesktopFoldersWidget(self, self.cfg)
        self.desktop_folders.positionChanged.connect(self.save_preferences)
        self.desktop_folders.hostError.connect(self._folder_host_error)
        self.desktop_folders.hostReady.connect(self._folder_host_ready)
        self.desktop_folders.hide()

        self._build_items()
        self.reposition()
        self.organizer.start()
        QApplication.instance().aboutToQuit.connect(self.shutdown_presentation)
        if self.isVisible():
            self.sync_presentation()

    def _organizer_changed(self):
        # 只更新分类入口，避免文件变化时重取独立应用图标。
        groups = self.organizer.groups()
        self._update_desktop_paths(groups)
        if self.desktop_folders and self.desktop_folders.isVisible():
            self.desktop_folders.refresh()
        signature = self._organizer_signature(groups)
        if signature == self._category_signature:
            return
        old = self._category_signature
        if (old and signature[0] == old[0]
                and tuple(c[:3] for c in signature[1]) == tuple(c[:3] for c in old[1])
                and signature[3:] == old[3:]):
            # 数量变化只更新名称，不重建图标或排布，避免打断鼠标动画。
            categories = {c["id"]: c for c in self.organizer.state["categories"]}
            categories["__uncategorized__"] = {"id": "__uncategorized__", "name": "未分类", "icon": "other"}
            for item in self.items:
                cid = item.get("category")
                if cid in categories:
                    category = categories[cid]
                    item["name"] = category["name"] + " · %d" % len(groups.get(cid, []))
            self._category_signature = signature
            self.update(self.repaint_rect())
            return
        self._build_items()
        self.reposition()
        # 智能模式没有周期抓屏，分类增删改变窗口范围后立即更新底图。
        self.refresh_backdrop()
        self._kick()

    def _category_artwork(self, category):
        cid = category.get("id")
        custom_icons = self.cfg.get("category_custom_icons", {})
        custom_path = custom_icons.get(cid)
        size = self.source_icon_size()
        if custom_path and os.path.exists(custom_path):
            pm = QPixmap(custom_path)
            if not pm.isNull():
                return pm
        key = category.get("icon", "other")
        themed = themed_icon_source(key)
        return themed if themed is not None else category_pixmap(key, size, self.is_light())

    def _ask_change_category_icon(self, cid):
        from PyQt5.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择分类图标文件", "",
            "图片与图标 (*.png *.ico *.jpg *.jpeg *.svg *.webp);;所有文件 (*.*)"
        )
        if file_path:
            self.set_category_custom_icon(cid, file_path)

    def set_category_custom_icon(self, cid, file_path):
        if file_path and not QImageReader(file_path).canRead():
            self.organizer_message("分类图标", "无法读取所选图像，请选择有效的图片或图标文件。")
            return False
        if "category_custom_icons" not in self.cfg:
            self.cfg["category_custom_icons"] = {}
        if file_path:
            self.cfg["category_custom_icons"][cid] = file_path
        else:
            self.cfg["category_custom_icons"].pop(cid, None)
        self.save_preferences()
        self._build_items()
        self.update(self.repaint_rect())
        if self.desktop_folders:
            self.desktop_folders.refresh()
        if self.category_panel and self.category_panel.isVisible():
            self.category_panel._refresh()
        return True

    def set_desktop_folder_mode(self, enable):
        enable = bool(enable)
        if enable and self.desktop_folders is None:
            self.organizer_message("桌面文件夹", "桌面组件尚未准备好，请稍后重试。")
            return False
        if self.entry_drag.active:
            self.entry_drag.cancel()
        if self.category_panel:
            self.category_panel.hide_immediately()
        if self.search_bar:
            self.search_bar.collapse(animate=False)
        self.cfg["desktop_folder_mode"] = enable
        self._presentation_visible = True
        self._build_items()
        self.reposition()
        result = self.sync_presentation()
        self.save_preferences()
        if self._pref_dialog:
            self._pref_dialog.refresh_mode()
        return result

    def presentation_visible(self):
        if self.cfg.get("desktop_folder_mode", False):
            return bool(self.desktop_folders and self.desktop_folders.isVisible())
        return self.isVisible()

    def set_presentation_visible(self, visible):
        self._presentation_visible = bool(visible)
        return self.sync_presentation()

    def _update_desktop_paths(self, groups=None):
        if self.desktop_manager is None:
            return
        categories = list(self.organizer.state["categories"])
        if self.cfg.get("desktop_folder_mode", False):
            # 未归类也有桌面盒入口，不能再重复留在原生桌面上。
            categories.append({"id": "__uncategorized__"})
        self.desktop_manager.update(self.organizer.groups() if groups is None else groups, categories,
                                    hide_recycle=not self.cfg.get("desktop_folder_mode", False))

    def _sync_desktop_collection(self, visible, mode=None):
        if self.desktop_manager is None:
            return  # 源码预览不操作真实桌面。
        self._update_desktop_paths()
        self.desktop_manager.set_mode((mode or self.cfg.get("desktop_display", "managed"))
                                      if visible else "all")

    def sync_presentation(self):
        if self._shutting_down:
            return False
        if not self._presentation_visible:
            self.hide()
            if self.desktop_folders:
                self.desktop_folders.hide()
            if self.category_panel:
                self.category_panel.hide_immediately()
            self.presentation_timer.stop()
            self._sync_desktop_collection(False)
            return True
        if self.cfg.get("desktop_folder_mode", False) and self.desktop_folders:
            self.hide()
            self.desktop_folders.refresh()
            if not self.desktop_folders.ensure_desktop_host():
                # 等待桌面宿主连接期间，不收纳原生图标。
                self.desktop_folders.begin_host_recovery()
                self._sync_desktop_collection(False)
                return True
            self._sync_desktop_collection(True)
            self.desktop_folders.show()
            self.presentation_timer.start()
            return True
        if self.desktop_folders:
            self.desktop_folders.hide()
        self.presentation_timer.stop()
        self.reposition()
        self._sync_desktop_collection(True)
        self.show()
        self.start_backdrop()
        return True

    def _folder_host_ready(self):
        if (not self._shutting_down and self._presentation_visible
                and self.cfg.get("desktop_folder_mode", False) and self.desktop_folders):
            self._sync_desktop_collection(True)
            self.desktop_folders.show()
            self.presentation_timer.start()

    def _folder_host_error(self, message):
        if self._shutting_down or not self.cfg.get("desktop_folder_mode", False):
            return
        if self.desktop_folders:
            self.desktop_folders.hide()
        self.presentation_timer.stop()
        self._sync_desktop_collection(False)
        self.organizer_message("桌面文件夹", message)

    def shutdown_presentation(self):
        if self._shutting_down:
            return
        self._shutting_down = True
        self.presentation_timer.stop()
        self.entry_drag.cancel()
        if self.desktop_manager:
            self.desktop_manager.stop()
        if self.desktop_folders:
            self.desktop_folders.shutdown()
        if self.category_panel:
            self.category_panel.hide_immediately()
        if self.search_bar:
            self.search_bar.hide()
        if self._pref_dialog:
            self._pref_dialog.close()
        self.hide()

    def save_preferences(self):
        if save_config(self.cfg) is False:
            raise OSError("无法保存设置，请检查配置目录权限或磁盘空间。")
        if self._pref_dialog is not None:
            self._pref_dialog.refresh_mode()

    def set_autostart_enabled(self, enabled):
        if not set_autostart(bool(enabled)):
            return False
        self.cfg["autostart"] = bool(enabled)
        self.save_preferences()
        return True

    def open_config_directory(self):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        os.startfile(CONFIG_DIR)

    def trim_memory(self):
        return trim_process_memory()

    def set_language(self, language):
        set_lang(language)
        self.cfg["lang"] = LANG["cur"]
        self.save_preferences()
        if self.tray:
            self.tray.rebuild()

    def set_search_enabled(self, enabled):
        self.cfg["show_search"] = bool(enabled)
        self.save_preferences()
        self.reload()

    def apply_presentation_theme(self):
        self._build_items()
        self.reposition()
        if self.category_panel:
            self.category_panel.apply_appearance(self.is_light())
        if self.search_bar:
            self.search_bar.update_theme()
            self.search_bar._capture_background()
        if self.desktop_folders:
            self.desktop_folders.refresh()
        if self._pref_dialog:
            self._pref_dialog.refresh_theme()
        self.refresh_backdrop()
        self.update()

    def set_folder_grid_size(self, grid_size):
        if grid_size not in ("2x2", "3x3", "4x4"):
            raise ValueError("无效的文件夹缩略图网格")
        self.cfg["folder_grid_size"] = grid_size
        self.save_preferences()
        if self.desktop_folders:
            self.desktop_folders.refresh()
        self._build_items()
        self.update(self.repaint_rect())

    def open_preferences_dialog(self):
        from .preferences_dialog import PreferencesDialog
        if self.category_manager is not None:
            self.category_manager.raise_()
            self.category_manager.activateWindow()
            return
        if self._pref_dialog is None:
            self._pref_dialog = PreferencesDialog(self)
        self._pref_dialog.refresh_theme()
        self._pref_dialog.show()
        self._pref_dialog.raise_()
        self._pref_dialog.activateWindow()

    def restart_shortcut(self):
        arguments = [SCRIPT_PATH] if IS_FROZEN else [pythonw_path(), SCRIPT_PATH]
        arguments.extend(["--wait-for-exit", str(os.getpid())])
        try:
            subprocess.Popen(arguments, close_fds=True)
        except OSError as error:
            self.organizer_message("重启失败", str(error))
            return False
        QApplication.instance().quit()
        return True

    def start_launch_bounce(self, idx):
        if not bool(self.cfg.get("launch_bounce", True)):
            return
        if 0 <= idx < len(self.bounces):
            self.bounces[idx] = 3.0
            self._kick()

    def _on_panel_closed(self):
        self._active_category_id = None
        if self.desktop_folders:
            self.desktop_folders.update()
        self.update(self.repaint_rect())

    def _settings_artwork(self):
        size = self.source_icon_size()
        themed = themed_icon_source("utilities")
        if themed is not None:
            return themed
        image = QPixmap(size, size)
        image.fill(Qt.transparent)
        p = QPainter(image)
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(size / 64.0, size / 64.0)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#7895b0"))
        p.drawRoundedRect(QRectF(10, 10, 44, 44), 10, 10)
        p.end()
        return image

    def _organizer_signature(self, groups):
        return (self.is_light(), tuple((c["id"], c["name"], c.get("icon"), len(groups.get(c["id"], [])))
                                     for c in self.organizer.state["categories"]), len(groups.get("__uncategorized__", [])),
                tuple(separator_positions(self.organizer.state)), bool(self.cfg.get("sep_split", False)),
                tuple(sorted(self.cfg.get("category_custom_icons", {}).items())))

    def organizer_message(self, title, message):
        log(title + ": " + message)
        if self.tray is not None:
            self.tray.showMessage(title, message, QSystemTrayIcon.Information, 2500)

    def _entry_drag_target(self, paths, point, stage, kind="category"):
        index = self._hit(self.mapFromGlobal(point)) if stage != "clear" and self.isVisible() else -1
        entry = self.items[index] if index >= 0 else {}
        category = entry.get("category")
        valid_category = category and category not in ("__uncategorized__", "__more__")
        highlight = index if valid_category or entry.get("trash") else -1
        if highlight != self._drop_index:
            self._drop_index = highlight
            self.update()
        if stage == "clear":
            if self.desktop_folders and hasattr(self.desktop_folders, "set_drop_category"):
                self.desktop_folders.set_drop_category(None)
            return
        folders = self.desktop_folders
        folder_category = folders.category_at(point) if folders and folders.isVisible() else None
        on_folders = bool(folders and folders.contains_global(point))
        if folders and hasattr(folders, "set_drop_category"):
            folders.set_drop_category(folder_category if stage == "hover" else None)
        local = self.window_to_axis(self.mapFromGlobal(point))
        on_shortcut = self.isVisible() and (index >= 0 or self.bar_rect_f().contains(local))
        panel = self.category_panel
        on_panel = panel and panel.isVisible() and panel.rect().contains(panel.mapFromGlobal(point))
        panel_content = on_panel and panel.view.viewport().rect().contains(panel.view.viewport().mapFromGlobal(point))
        panel_category = panel.category_id if panel_content else None
        if panel_category in ("__uncategorized__", "__more__"):
            panel_category = None
        if stage == "hover":
            if valid_category:
                return "归入 %s" % entry["name"].split(" · ")[0]
            if panel_category:
                return "归入当前分类"
            if folder_category:
                return "归入桌面分类盒子"
            if entry.get("trash"):
                return "放开后确认移入回收站"
            if on_shortcut and index < 0:
                return "固定至 Shortcut"
            if on_shortcut or on_panel or on_folders:
                return "此处不能放置 · Esc 取消"
            return "移除固定入口 · 原文件保留" if kind == "pinned" else "移除分类入口 · 原文件保留"
        self._drop_index = -1
        self.update()
        if valid_category or panel_category or folder_category:
            self.organizer.assign_paths(paths, category if valid_category else panel_category or folder_category)
        elif entry.get("trash"):
            if panel:
                panel.hide()
            return self.file_actions.perform("delete", paths)
        elif on_shortcut and index < 0:
            for path in paths:
                self.pin_path(path)
        elif on_shortcut or on_panel or on_folders:
            return False
        elif kind == "pinned":
            selected = {normalize_path(path) for path in paths}
            self.cfg["items"] = [item for item in self.cfg["items"]
                                 if not item.get("path") or normalize_path(item["path"]) not in selected]
            save_config(self.cfg)
            self._build_items()
            self.reposition()
        else:
            self.organizer.exclude_paths(paths)
        return True

    def pin_path(self, path):
        if not any(normalize_path(it.get("path", "")) == normalize_path(path) for it in self.cfg["items"] if it.get("path")):
            self.cfg["items"].append({"path": path, "name": os.path.splitext(os.path.basename(path))[0]})
            save_config(self.cfg)
            self.reload()

    def open_category(self, cid, anchor=None, shortcut_edge=_DEFAULT_SHORTCUT_EDGE):
        if self.search_bar:
            self.search_bar.collapse()
        if self.organizer is None:
            return
        self._active_category_id = cid
        if self.desktop_folders:
            self.desktop_folders.update()
        self.update(self.repaint_rect())
        if cid == "__more__":
            menu = ThemedMenu(self, light=self.is_light(), colors=self.theme_colors())
            groups = self.organizer.groups()
            for c in self.organizer.state["categories"] + [{"id": "__uncategorized__", "name": "未分类"}]:
                menu.addAction(c["name"] + " · %d" % len(groups.get(c["id"], []))).triggered.connect(lambda _=False, key=c["id"]: self.open_category(key))
            menu.addSeparator()
            menu.addAction("管理分类与分隔符…").triggered.connect(self.manage_categories)
            if anchor is None:
                bar = self.bar_rect_f()
                point = self.axis_transform().map(QPointF(bar.center().x(), bar.bottom() if self.bump_down() else bar.top()))
                anchor_pt = self.mapToGlobal(point.toPoint())
                anchor_rect = QRect(anchor_pt.x() - 10, anchor_pt.y() - 10, 20, 20)
            else:
                anchor_rect = anchor
            screen = QApplication.screenAt(anchor_rect.center()) or self.target_screen()
            preferred = {"bottom": "above", "top": "below", "left": "right", "right": "left"}.get(
                self.cfg.get("position", "bottom"), "below" if self.bump_down() else "above")
            menu.ensurePolished()
            self._clear_hover()
            menu.exec_(_entry_menu_position(anchor_rect, menu.sizeHint(), screen.availableGeometry(), preferred))
            menu.deleteLater()
            self._active_category_id = None
            self.update(self.repaint_rect())
            return
        # 锚点使用所点分类和可见玻璃边缘，透明的动画预留区不能拉开面板间距。
        if anchor is None:
            bar = self.bar_rect_f()
            index = next((i for i, item in enumerate(self.items) if item.get("category") == cid), None)
            center = self.rects[index][0] if index is not None else bar.center().x()
            bounds = next((path.boundingRect() for segment, path in zip(self.shape_segments(), self.shape_paths())
                           if segment[0] <= center <= segment[1]), bar)
            top, bottom = bounds.top(), bounds.bottom()
            local = self.window_rect(QRectF(center - self.icon_size / 2, top,
                                           self.icon_size, bottom - top)).toAlignedRect()
            anchor = QRect(self.mapToGlobal(local.topLeft()), local.size())
        self._clear_hover()
        effective_edge = self.cfg.get("position", "bottom") if shortcut_edge is _DEFAULT_SHORTCUT_EDGE else shortcut_edge
        self.category_panel.open_category(cid, anchor, not self.bump_down(), self.is_light(),
                                          shortcut_edge=effective_edge)

    def manage_categories(self):
        if self.category_manager is not None:
            self.category_manager.raise_()
            self.category_manager.activateWindow()
            return
        if self.search_bar:
            self.search_bar.collapse()
        if self.category_panel:
            self.category_panel.hide_immediately()
        parent = self._pref_dialog if self._pref_dialog is not None and self._pref_dialog.isVisible() else self
        manager = CategoryManager(self.organizer, self.is_light(), parent, shortcut_config=self.cfg)
        manager.setWindowModality(Qt.WindowModal)
        self.category_manager = manager
        try:
            manager.exec_()
        finally:
            self.category_manager = None
            manager.deleteLater()

    def add_organizer_actions(self, menu):
        scan = menu.addAction("一键整理桌面")
        scan.triggered.connect(self.organizer.request_scan)
        manage = menu.addAction("管理分类与分隔符…")
        manage.triggered.connect(self.manage_categories)
        action = menu.addAction("自动整理桌面变化")
        if isinstance(menu, ThemedMenu):
            scan.setIcon(menu.glyph("automatic"))
            manage.setIcon(menu.glyph("settings"))
        action.setCheckable(True)
        action.setChecked(self.organizer.state.get("automatic", True))
        action.triggered.connect(self.organizer.set_automatic)

    def add_desktop_icons_action(self, menu):
        sub = menu.addMenu("桌面图标")
        group = QActionGroup(sub)
        for mode, label in (("managed", "收纳当前界面中的项目"),
                            ("all", "显示全部图标"), ("hidden", "隐藏全部图标")):
            action = sub.addAction(label)
            action.setCheckable(True)
            action.setChecked(self.cfg.get("desktop_display", "managed") == mode)
            group.addAction(action)
            action.triggered.connect(lambda _=False, value=mode: self.set_desktop_display(value))
        sub.setToolTipsVisible(True)
        sub.actions()[0].setToolTip("Shortcut 收纳已分类项目；桌面盒同时收纳未归类项目并保留原生回收站。隐藏界面或退出后恢复完整桌面，原文件不移动。")

    def set_desktop_display(self, mode):
        try:
            if self.desktop_manager:
                # 模式切换统一管理原生连接；初次索引为空时也要启动托管，
                # 后续文件事件才能只收起已分类项目，保留未分类及已移除入口。
                self._sync_desktop_collection(self._presentation_visible, mode)
            else:
                if mode == "hidden":
                    raise OSError("隐藏桌面图标前，桌面守护服务尚未初始化")
                # 原生服务尚未创建时，managed 保留完整桌面。
                set_icons_visible(mode != "hidden")
        except OSError as error:
            self.desktop_display_error(str(error))
            return False
        self.cfg["desktop_display"] = mode
        self.cfg["show_desktop_icons"] = mode != "hidden"
        if save_config(self.cfg) is False:
            self.desktop_display_error("桌面显示方式已更改，但无法保存设置。")
            return False
        if self.desktop_folders:
            self.desktop_folders.refresh()
        return True

    def desktop_display_error(self, message):
        log("桌面显示提示：" + message)
        self.organizer_message("桌面显示提示", message)

    def dragEnterEvent(self, event):
        if (self.organizer or self.recycle_bin) and any(u.isLocalFile() for u in event.mimeData().urls()):
            event.setDropAction(Qt.CopyAction)
            event.accept()

    def dragMoveEvent(self, event):
        idx = self._hit(event.pos())
        cid = self.items[idx].get("category") if idx >= 0 else None
        trash = idx >= 0 and self.items[idx].get("trash") and self.recycle_bin and not self.recycle_bin.busy
        self._drop_index = idx if cid or trash else -1
        self.update()
        if cid in ("__uncategorized__", "__more__"):
            event.ignore()
        elif cid or idx < 0 or trash:
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._drop_index = -1
        self.update()

    def dropEvent(self, event):
        idx = self._hit(event.pos())
        cid = self.items[idx].get("category") if idx >= 0 else None
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if idx >= 0 and self.items[idx].get("trash") and self.recycle_bin:
            if not self.recycle_bin.recycle(paths):
                event.ignore()
                return
        elif cid and cid not in ("__uncategorized__", "__more__"):
            self.organizer.assign_paths(paths, cid)
        elif idx < 0:
            for path in paths:
                self.pin_path(path)
        else:
            event.ignore()
            return
        self._drop_index = -1
        event.setDropAction(Qt.CopyAction)
        # 文件操作由回收服务负责；不能让拖出端再次执行 MoveAction 删除原文件。
        event.accept()
        self.update()

    # ---------------- 绘制 ----------------
    @staticmethod
    def _stop_alpha(stops, t):
        """在一条渐变的色标里插值取值。"""
        if t <= stops[0][0]:
            return float(stops[0][1])
        for i in range(1, len(stops)):
            p0, a0 = stops[i - 1]
            p1, a1 = stops[i]
            if t <= p1:
                if p1 <= p0:
                    return float(a1)
                return a0 + (a1 - a0) * (t - p0) / (p1 - p0)
        return float(stops[-1][1])

    def merged_grad_stops(self, c):
        """把"竖向渐变"和"顶部高光"合并成一条渐变。

        两者都是白色的竖向渐变，合成一条之后每段只要裁切一次、填充一次，
        能省掉一次昂贵的路径裁切光栅化（性能关键）。
        """
        hl_span = 0.42
        out = []
        for f in (0.0, 0.10, 0.20, 0.28, 0.42, 0.70, 1.0):
            a1 = self._stop_alpha(c["grad"], f)
            a2 = self._stop_alpha(c["hl"], f / hl_span) if f <= hl_span else 0.0
            m = 1.0 - (1.0 - a1 / 255.0) * (1.0 - a2 / 255.0)
            out.append((f, int(round(m * 255))))
        return out

    def source_icon_size(self):
        """外壳图标按悬停和回弹的物理尺寸提取，不用逻辑像素截断源图。"""
        return max(96, math.ceil(self.icon_size * self.hover_scale() * 1.16
                                 * self.target_screen().devicePixelRatio()))

    def icon_scaled(self, it, size):
        """从原图一次缩放到实际屏幕像素，按分辨率及源图分别缓存。"""
        dpr = self.devicePixelRatioF()
        q = max(1, round(size * dpr))
        src = it.get("pixmap")
        if src is None or src.isNull():
            return None
        key = (q, dpr, src.cacheKey())
        cache = it.get("_scaled")
        if cache is None:
            cache = {}
            it["_scaled"] = cache
        pm = cache.get(key)
        if pm is not None:
            return pm
        if q == src.width() and q == src.height():
            pm = QPixmap(src)
        else:
            pm = src.scaled(q, q, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        pm.setDevicePixelRatio(dpr)
        # 缓存满了就淘汰最旧的一个，不要整体清空 ——
        # 整体清空会让那一帧所有图标都重新缩放，滑动时每隔十几帧卡一下（抽搐感来源之一）
        if len(cache) >= 6:
            cache.pop(next(iter(cache)), None)
        cache[key] = pm
        return pm

    def pixel_aligned_rect(self, rect):
        dpr = self.devicePixelRatioF()
        return QRectF(round(rect.x() * dpr) / dpr, round(rect.y() * dpr) / dpr,
                      round(rect.width() * dpr) / dpr, round(rect.height() * dpr) / dpr)

    def _paint_glass_piece(self, p, path, path_rect, bar, c, tint_a, stops):
        """画一段玻璃（隔断模式下会有好几段，每段都有自己的圆角）。

        整段只做一次 setClipPath —— 复杂路径的裁切光栅化是这里最贵的操作，
        之前每层各裁一次，一帧要裁好几遍，这就是鼠标滑动时占用偏高的主因。
        """
        p.save()
        p.setClipPath(path)
        if self.cfg["glass"] and self.backdrop is not None:
            # 只画这一段所在的那块区域，避免整窗重绘浪费性能
            p.drawPixmap(path_rect, self.backdrop, path_rect)
            if tint_a > 0:
                col = QColor(c["tint"])
                col.setAlpha(tint_a)
                p.fillRect(path_rect, col)
        else:
            col = QColor(c["tint"])
            col.setAlpha(min(255, tint_a + 20))
            p.fillRect(path_rect, col)

        # 竖向渐变 + 顶部高光（已经合并成一条渐变，省一次裁切+填充）
        # 注：实测这里用 QLinearGradient 直接填充比"缓存贴图再拉伸"更快，
        # 因为 Qt 的线性渐变填充走的是优化过的快路径。
        g = QLinearGradient(QPointF(0, path_rect.top()), QPointF(0, path_rect.bottom()))
        for pos, a in stops:
            g.setColorAt(pos, QColor(255, 255, 255, a))
        p.fillRect(path_rect, QBrush(g))

        # 跟着鼠标走的柔光（液态感的关键）
        # 只填"柔光实际照到的那一块"：半径外的颜色本来就是全透明，
        # 限制填充范围不改变画面，但能省掉几倍的像素量。
        if self.spec_alpha > 0.01:
            wide = float(c.get("spec_wide", 1.2))
            radius = bar.height() * wide
            if path_rect.left() - radius <= self.spec_x <= path_rect.right() + radius:
                rad = QRadialGradient(QPointF(self.spec_x, bar.center().y()), radius)
                a = int(c["spec"] * self.spec_alpha)
                rad.setColorAt(0.0, QColor(255, 255, 255, a))
                rad.setColorAt(0.55, QColor(255, 255, 255, int(a * 0.35)))
                rad.setColorAt(1.0, QColor(255, 255, 255, 0))
                box = QRectF(self.spec_x - radius, path_rect.top(),
                             radius * 2.0, path_rect.height()).intersected(path_rect)
                if not box.isEmpty():
                    p.fillRect(box, QBrush(rad))

        # 光感模式：再补一道斜向的"光扫过玻璃"的光带，就是那种带光照的观感
        # （同样只填光带实际覆盖的那一段，右边全透明的地方不浪费像素）
        if c.get("gloss"):
            gx0 = path_rect.left()
            gy0 = path_rect.top()
            sweep_w = path_rect.height() * 1.5
            sweep = QLinearGradient(QPointF(gx0, gy0),
                                    QPointF(gx0 + sweep_w, path_rect.bottom()))
            sweep.setColorAt(0.00, QColor(255, 255, 255, 0))
            sweep.setColorAt(0.13, QColor(255, 255, 255, 132))
            sweep.setColorAt(0.30, QColor(255, 255, 255, 28))
            sweep.setColorAt(0.52, QColor(255, 255, 255, 0))
            sbox = QRectF(gx0, path_rect.top(), sweep_w,
                          path_rect.height()).intersected(path_rect)
            if not sbox.isEmpty():
                p.fillRect(sbox, QBrush(sweep))
        p.restore()

        # 描边（不需要裁切）
        pen = QPen(c["border"])
        pen.setWidthF(float(c.get("border_w", 1.0)))
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)

        bar = self.bar_rect_f()
        paths = self.shape_paths()
        prects = [pa.boundingRect() for pa in paths]
        path = paths[0] if paths else QPainterPath()
        path_rect = prects[0] if prects else bar

        # 玻璃整体：自己抓屏 + 自己模糊，模糊区域完全跟随玻璃形状，
        # 四个角天生透明，不会有方形轮廓。
        #
        # 通透度作用于【整块玻璃】：
        #   tp<=40 时整块玻璃保持不透明，只是压在背景上的深色变淡（偏实 → 默认）
        #   tp>40  时整块玻璃（模糊画面 + 深色 + 高光 + 描边）一起变淡，
        #           于是无论背后是亮壁纸还是深色窗口，都能明显看出"更通透"了
        tp = max(0, min(100, int(self.cfg.get("transparency", 40))))
        c = self.theme_colors()
        ratio = (100.0 - tp) / 100.0
        base_a = 235.0 * ratio
        # 底色浓度与预留底色随通透度动态缩放，通透度越高底色越纯净无杂色
        tint_floor = c["tint_floor"] * ratio
        tint_a = int(round(min(255.0, base_a * c["tint_scale"] + tint_floor)))
        glass_a = 1.0 - max(0.0, tp - 35.0) / 65.0 * 0.65
        glass_a = max(0.18, min(1.0, glass_a))

        p.save()
        p.setTransform(self.axis_transform())
        p.setOpacity(glass_a)

        stops = self.merged_grad_stops(c)
        for pa, pr in zip(paths, prects):
            self._paint_glass_piece(p, pa, pr, bar, c, tint_a, stops)

        p.restore()      # 玻璃画完，透明度恢复，下面的名称和图标始终是全不透明的

        # 悬停时的程序名称：放在图标放大区之外，不挡任何东西；
        # 如果 Shortcut 贴着屏幕顶部，就改画在玻璃条下面，保证看得清。
        if (self.cfg.get("show_name", True) and self.label_alpha > 0.02
                and 0 <= self.hover_index < len(self.items)):
            name = self.items[self.hover_index]["name"]
            f = self._label_font
            fm = self._label_metrics
            if self.is_vertical():
                name = fm.elidedText(name, Qt.ElideRight, self.side_label_width() - 24)
            tw = float(fm.width(name) + 24)
            th = self.label_height()
            cx = self.rects[self.hover_index][0]
            if self.is_vertical():
                visible_bar = self.window_rect(bar)
                gap = self.icon_size * .32 + 8.0
                lx = visible_bar.right() + gap if self.bump_down() else visible_bar.left() - gap - tw
                ly = min(max(cx - th / 2.0, 4.0), self.height() - th - 4.0)
            else:
                lx = min(max(cx - tw / 2.0, 4.0), max(4.0, self.width() - tw - 4.0))
                ly = self.label_top_y(bar)
            lab = QRectF(lx, ly, tw, th)
            lp = QPainterPath()
            rad = min(th / 2.0, 9.0 * self.ui_mult)
            lp.addRoundedRect(lab, rad, rad)
            p.save()
            p.setOpacity(self.label_alpha)
            p.fillPath(lp, c["label_bg"])
            lg = QLinearGradient(lab.topLeft(), lab.bottomLeft())
            lg.setColorAt(0.0, QColor(255, 255, 255, 44 if not c["light"] else 120))
            lg.setColorAt(1.0, QColor(255, 255, 255, 8 if not c["light"] else 30))
            p.fillPath(lp, QBrush(lg))
            p.setPen(QPen(c["label_border"], 1.0))
            p.setBrush(Qt.NoBrush)
            p.drawPath(lp)
            p.setFont(f)
            p.setPen(c["label_fg"])
            p.drawText(lab, Qt.AlignCenter, name)
            p.restore()

        if not self.items:
            hint = T("请在右下角托盘图标上右键 → 添加图标")
            f = self._label_font
            p.setFont(f)
            p.setPen(c["shadow"])
            actual_bar = self.window_rect(bar)
            if self.is_vertical():
                hint = T("添加图标…")
            p.drawText(actual_bar.adjusted(0, 1, 0, 1), Qt.AlignCenter, hint)
            p.setPen(c["fg"])
            p.drawText(actual_bar, Qt.AlignCenter, hint)
            return

        # 图标 / 分隔符（点击时弹一下：平时以底边为支点往上弹，贴屏幕顶部时反过来）
        down = self.bump_down()
        for i, it in enumerate(self.items):
            cx, w, h, by = self.rects[i][0], self.rects[i][1], self.rects[i][2], self.rects[i][3]
            if self.rects[i][4] or it.get("sep"):
                if it.get("system_separator"):
                    continue
                # 分隔符：一根居中的圆头细竖条，长度约为图标区的 44%
                sh = max(9.0, self.icon_size * 0.44)
                swid = max(1.6, self.icon_size * 0.055)
                dc = QColor(c["fg"])
                dc.setAlpha(96 if c["light"] else 120)
                p.setPen(Qt.NoPen)
                p.setBrush(dc)
                cy = (by + self.icon_size / 2.0) if down else (by - self.icon_size / 2.0)
                p.drawRoundedRect(self.window_rect(QRectF(cx - swid / 2.0, cy - sh / 2.0, swid, sh)),
                                  swid / 2.0, swid / 2.0)
                continue
            pop = self.pops[i] if i < len(self.pops) else 0.0
            if pop > 0.0:
                t = 1.0 - pop
                # 经典阻尼弹簧振荡: 峰值约 +0.085 物理过冲，微幅反向收敛到 1.0 (约 320ms)
                spring = math.sin(t * math.pi * 2.5) * math.exp(-3.5 * t)
                pop_extra = 1.0 + 0.16 * spring
            else:
                pop_extra = 1.0

            press = self.press_scale[i] if i < len(self.press_scale) else 1.0
            is_active_cat = (it.get("category") and it.get("category") == self._active_category_id)
            if is_active_cat:
                pop_extra = max(pop_extra, 1.10)
            effective_scale = press * pop_extra
            dw = w * effective_scale
            dh = h * effective_scale
            # 物理按压下沉量：按下时向基准线微压 1.8px
            press_cushion = (1.0 - press) * (self.icon_size * 0.16)
            top_y = (by - dh + press_cushion) if not down else (by - press_cushion)

            # macOS 风格启动轻快跳动 (Launch Bounce)
            b_val = self.bounces[i] if i < len(self.bounces) else 0.0
            if b_val > 0.0:
                phase = 3.0 - b_val
                decay = max(0.0, 1.0 - phase / 3.0)
                jump_y = abs(math.sin(phase * math.pi)) * (self.icon_size * 0.44) * decay
                top_y = (top_y - jump_y) if not down else (top_y + jump_y)

            rect = self.pixel_aligned_rect(self.window_rect(QRectF(cx - dw / 2.0, top_y, dw, dh)))
            center_pt = rect.center()

            # 1. 悬浮、激活与按压环境柔光背晕 (Ambient Halo Glow: 随放大与按压联动)
            hover_ratio = max(0.0, (w / self.icon_size - 1.0) / max(0.01, self.hover_scale() - 1.0))
            if i == self.hover_index or is_active_cat:
                hover_ratio = max(hover_ratio, self.label_alpha, 0.7 if is_active_cat else 0.0)
            glow_intensity = max(hover_ratio, (1.0 - press) * 1.5, pop * 0.75)
            if glow_intensity > 0.02 and not it.get("sep"):
                glow_r = dw * 0.60
                glow_a = int((40 if c["light"] else 52) * glow_intensity)
                if press < 0.98:
                    glow_a = min(255, int(glow_a * 1.35))
                rad_glow = QRadialGradient(center_pt, glow_r)
                rad_glow.setColorAt(0.0, QColor(255, 255, 255, glow_a))
                rad_glow.setColorAt(0.55, QColor(255, 255, 255, int(glow_a * 0.38)))
                rad_glow.setColorAt(1.0, QColor(255, 255, 255, 0))
                p.save()
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(rad_glow))
                p.drawEllipse(center_pt, glow_r, glow_r)
                p.restore()

            # 2. 点击释放光波涟漪环 (Click Ripple Pulse: 自中心向外扩散淡出)
            rip = self.ripples[i] if i < len(self.ripples) else 0.0
            if rip > 0.01:
                rt = 1.0 - rip
                r_rip = dw * (0.36 + 0.44 * rt)
                rip_a = int(140 * (1.0 - rt) * (1.0 - rt))
                if rip_a > 2:
                    p.save()
                    p.setPen(QPen(QColor(255, 255, 255, rip_a), 1.5))
                    p.setBrush(QColor(255, 255, 255, int(rip_a * 0.22)))
                    p.drawEllipse(center_pt, r_rip, r_rip)
                    p.restore()

            if i == self._drop_index:
                p.setPen(QPen(QColor(80, 160, 255, 230), 2))
                p.setBrush(QColor(80, 160, 255, 40))
                p.drawRoundedRect(rect.adjusted(-5, -5, 5, 5), 14, 14)
            # 运行中的小圆点：始终在图标【下方】，而且是先画它、再画图标，
            # 所以它的层级低于图标 —— 图标放大盖过来时会挡住圆点，而不是压在图标上面。
            if self.cfg["running_dots"] and it["exe"] and it["exe"] in self.running:
                dot = max(3.0, self.icon_size * 0.075)
                dc = QColor(c["fg"])
                dc.setAlpha(210)
                p.setPen(Qt.NoPen)
                p.setBrush(dc)
                if down:
                    # 贴屏幕顶部时图标是从上边缘向下长的，点放在"静止时图标的下边"
                    dy = by + self.icon_size + dot * 1.4
                else:
                    dy = by + dot * 1.6
                p.drawEllipse(self.axis_transform().map(QPointF(cx, dy)), dot, dot)
            pm = self.icon_scaled(it, dw)
            if pm is None:
                pass
            elif c.get("tile"):
                # 雾透模式：图标坐在一块白色圆角底板上（iOS 那种观感）
                tile_r = dw * float(c.get("tile_radius", 0.30))
                tile = QRectF(rect)
                # 柔和投影：按下时阴影微收拢，增强真实按压纵深感
                p.setPen(Qt.NoPen)
                p.setBrush(c["tile_shadow"])
                shadow_offset_y = dh * (0.045 if press >= 0.98 else 0.02)
                p.drawRoundedRect(tile.adjusted(dw * 0.02, shadow_offset_y,
                                                -dw * 0.02, shadow_offset_y),
                                  tile_r, tile_r)
                p.setBrush(c["tile_color"])
                p.drawRoundedRect(tile, tile_r, tile_r)
                # 原图标按比例缩小画在底板正中
                k = float(c.get("tile_icon", 0.60))
                iw = dw * k
                ih = dh * k
                p.drawPixmap(QRectF(tile.center().x() - iw / 2.0,
                                    tile.center().y() - ih / 2.0, iw, ih),
                             pm, QRectF(pm.rect()))
            else:
                p.drawPixmap(rect, pm, QRectF(pm.rect()))

    # ---------------- 背景模糊（自己实现的真毛玻璃） ----------------
    def _capture_behind(self):
        """抓取 Shortcut 背后真实的桌面画面。

        关键一步：抓图之前先把本窗口标记成"不参与屏幕捕获"
        (WDA_EXCLUDEFROMCAPTURE)，否则会把 Shortcut 自己拍进去，形成无限套娃。
        抓完立刻恢复原状，所以你自己截图时 Shortcut 依然会正常出现。
        返回 (截图, 是否成功)。
        """
        hwnd = wintypes.HWND(int(self.winId()))
        ok = False
        try:
            user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
            user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
            ok = bool(user32.SetWindowDisplayAffinity(hwnd, 0x11))
            if not ok:
                return None, False
            scr = self.target_screen()
            g = self.frameGeometry()
            return scr.grabWindow(0, g.x(), g.y(), max(1, g.width()), max(1, g.height())), True
        except Exception:
            log("抓取背景失败: " + traceback.format_exc())
            return None, ok
        finally:
            if ok:
                try:
                    user32.SetWindowDisplayAffinity(hwnd, 0)
                except Exception:
                    pass

    def blur_divisor(self):
        """毛玻璃模糊程度：把背景缩小到 1/div 再放大回来，div 越大越糊。"""
        try:
            return max(2, min(50, int(self.cfg.get("blur_px", 6))))
        except Exception:
            return 6

    def refresh_backdrop(self):
        """抓背景 → 缩小再放大（等于一次大半径模糊）→ 作为玻璃后面的画面。"""
        if self.preview or not self.isVisible():
            return
        if not self.cfg["glass"]:
            # 关掉毛玻璃：完全不抓屏，直接用半透明底色
            self.blur_timer.stop()
            if self.backdrop is not None:
                self.backdrop = None
                self.update()
            return
        pm, ok = self._capture_behind()
        if not ok:
            if self.backdrop_ok is not False:
                self.backdrop_ok = False
                log("本机不支持屏幕捕获排除，毛玻璃降级为普通半透明（不影响使用）")
            self.blur_timer.stop()
            self.update()
            return
        if pm is None or pm.isNull():
            return
        self.backdrop_ok = True
        try:
            scr = self.target_screen()
            dpr = float(scr.devicePixelRatio()) or 1.0
            div = self.blur_divisor()
            w, h = max(2, pm.width() // div), max(2, pm.height() // div)
            small = pm.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            small = small.scaled(max(1, w // 2), max(1, h // 2),
                                 Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            # 注意：要还原成"设备像素"尺寸并标好缩放比，
            # 否则在 125%/150%/200% 缩放的屏幕上玻璃里的画面会被拉糊。
            out = small.scaled(max(1, int(round(self.width() * dpr))),
                               max(1, int(round(self.height() * dpr))),
                               Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            out.setDevicePixelRatio(dpr)
            # 背景按实际屏幕抓取，换轴一次后与逻辑玻璃坐标一致；不在动画帧重复转换。
            self.backdrop = out.transformed(self.axis_transform()) if self.is_vertical() else out
        except Exception:
            log("模糊处理失败: " + traceback.format_exc())
            return
        self.update()

    def start_backdrop(self):
        if self.preview or not self.isVisible():
            return
        mode = str(self.cfg.get("blur_mode", "smart"))
        self.blur_timer.setInterval(BLUR_INTERVAL.get(mode, BLUR_INTERVAL["smart"]))
        if not self._logged_once:
            self._logged_once = True
            try:
                scr = self.target_screen()
                try:
                    dpi_sys = int(user32.GetDpiForSystem())
                except Exception:
                    dpi_sys = -1
                try:
                    dpi_win = int(user32.GetDpiForWindow(wintypes.HWND(int(self.winId()))))
                except Exception:
                    dpi_win = -1
                log("屏幕=%dx%d 可用=%dx%d 缩放=%s 系统DPI=%d 窗口DPI=%d 倍率=%.2f 图标=%d 窗口=%dx%d 位置=(%d,%d) 毛玻璃=%s 层级=%s 抓取=%s"
                    % (scr.geometry().width(), scr.geometry().height(),
                       scr.availableGeometry().width(), scr.availableGeometry().height(),
                       scr.devicePixelRatio(), dpi_sys, dpi_win, self.ui_mult, self.icon_size,
                       self.width(), self.height(), self.x(), self.y(), self.cfg["glass"],
                       self.cfg.get("layer", "bottom"), mode))
            except Exception:
                pass
        if not self.cfg["glass"]:
            self.backdrop = None
            self.blur_timer.stop()
            self.update()
            return
        self.refresh_backdrop()
        if mode in ("off", "smart"):
            # 智能模式由显示、鼠标进入和布局变化刷新，不做空闲抓屏。
            self.blur_timer.stop()
        elif self.backdrop_ok and not self.blur_timer.isActive():
            self.blur_timer.start()

    def _register_main_window(self):
        # 文件夹模式可能从未显示 Shortcut；隐藏主窗口也须供 --stop 准确定位。
        user32.SetPropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.HANDLE]
        user32.SetPropW.restype = wintypes.BOOL
        user32.SetPropW(int(self.winId()), MAIN_WINDOW_MARKER, 1)

    def moveEvent(self, event):
        super(Shortcut, self).moveEvent(event)
        if self.search_bar is not None:
            self.sync_search_geometry()

    def resizeEvent(self, event):
        super(Shortcut, self).resizeEvent(event)
        if self.search_bar is not None:
            self.sync_search_geometry()

    def showEvent(self, e):
        self._register_main_window()
        super(Shortcut, self).showEvent(e)
        if self.search_bar:
            self.sync_search_geometry()
        if not self.preview:
            self.geo_timer.start()
            self.refresh_running()
        QTimer.singleShot(50, self.start_backdrop)
        QTimer.singleShot(60, self.apply_layer)
        QTimer.singleShot(1500, trim_process_memory)

    def hideEvent(self, e):
        if self.search_bar:
            self.search_bar.hide()
        if self.category_panel:
            self.category_panel.hide()
        self.blur_timer.stop()
        self.proc_timer.stop()
        self.geo_timer.stop()
        self.timer.stop()
        self._hover_backdrop_pending = False
        self._frame_time = None
        self.mouse_x = self.mouse_smooth = self.spec_x = -99999.0
        self.hover_index = self.pressed = self.drag_idx = self._drop_index = -1
        self.spec_alpha = self.spec_target = self.label_alpha = self.stretch = self.stretch_target = 0.0
        self.pops = [0.0] * len(self.items)
        self.press_scale = [1.0] * len(self.items)
        self.ripples = [0.0] * len(self.items)
        self._recalc(uniform=True)
        super(Shortcut, self).hideEvent(e)

    def closeEvent(self, e):
        # 关闭 Shortcut 窗口 = 退出整个程序
        try:
            QApplication.instance().quit()
        except Exception:
            pass
        super(Shortcut, self).closeEvent(e)

    def reload(self):
        if self.search_bar:
            self.search_bar.collapse(animate=False)
            self.search_bar.invalidate()
        self.base_icon = int(self.cfg["icon_size"])
        self.ui_mult = self._ui_mult()
        self.icon_size = self._scaled(self.base_icon)
        self.font_pt = max(8, int(round(9 * self.ui_mult)))
        self.prepare_label_font()
        self.pad_x = int(self.icon_size * 0.36)
        self.pad_y = int(self.icon_size * 0.34)
        self.icons.clear()
        self._exe_cache.clear()
        self._build_items()
        self.reposition()
        if self.search_bar:
            self.search_bar.update_theme()
        self.start_backdrop()
        self._kick()

    def refresh_geometry(self):
        """只重新算尺寸和位置（比如开关名称显示、开关隔断时布局变了）。

        reposition() 内部已经会算好位置、调整窗口大小并重算图标坐标，
        这里不用再重复一遍。
        """
        self.reposition()
        self.start_backdrop()
        self._kick()


# ----------------------------------------------------------------------------
# 托盘图标
# ----------------------------------------------------------------------------




class ShortcutTray(QSystemTrayIcon):
    def __init__(self, shortcut):
        super(ShortcutTray, self).__init__(application_icon())
        self.shortcut = shortcut
        self.cfg = shortcut.cfg
        set_lang(self.cfg.get("lang", "zh"))     # 按配置设好界面语言
        self.menu = ThemedMenu(light=shortcut.is_light(), colors=shortcut.theme_colors())
        self.setContextMenu(self.menu)
        self.menu.aboutToShow.connect(self.rebuild)
        self.activated.connect(self._activated)
        self.rebuild()
        self.setToolTip(APP_TITLE + " —— 右键管理图标")

    def _activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.menu.popup(QCursor.pos())

    # ---------- 菜单 ----------
    def rebuild(self):
        m = self.menu
        m.clear()
        d = self.shortcut
        m.set_theme(d.is_light(), d.theme_colors())

        # 1. 偏好设置总设置弹窗（首位放置，点击弹出完整控制中心）
        act_pref = QAction(T("偏好设置 (总设置)…"), m)
        act_pref.triggered.connect(d.open_preferences_dialog)
        m.addAction(act_pref)
        m.addSeparator()

        # 2. 桌面文件夹模式快捷开关
        act_df = QAction(T("桌面文件夹模式"), m)
        act_df.setCheckable(True)
        act_df.setChecked(bool(self.cfg.get("desktop_folder_mode", False)))
        act_df.triggered.connect(lambda v: d.set_desktop_folder_mode(v))
        m.addAction(act_df)

        # 3. 桌面图标模式
        d.add_desktop_icons_action(m)

        # 4. 一键整理
        if d.organizer is not None:
            d.add_organizer_actions(m)

        # 5. 添加应用图标
        a = QAction(T("添加到分类…" if self.cfg.get("desktop_folder_mode", False) else "添加应用图标…"), m)
        a.triggered.connect(self.add_icons)
        m.addAction(a)

        m.addSeparator()

        # 6. 显示 / 隐藏 Shortcut
        a = QAction(T("显示 / 隐藏桌面文件夹" if self.cfg.get("desktop_folder_mode", False) else "显示 / 隐藏 Shortcut"), m)
        a.setCheckable(True)
        a.setChecked(d.presentation_visible())
        a.triggered.connect(lambda: d.set_presentation_visible(not d.presentation_visible()))
        m.addAction(a)

        # 7. 重启与退出
        act_restart = QAction(T("重启 Shortcut"), m)
        act_restart.triggered.connect(d.restart_shortcut)
        m.addAction(act_restart)

        act_quit = QAction(T("退出"), m)
        act_quit.triggered.connect(QApplication.instance().quit)
        m.addAction(act_quit)

    def _show_shortcut(self):
        self.shortcut.set_presentation_visible(True)

    def add_icons(self):
        start = ""
        dirs = start_menu_dirs()
        if dirs:
            start = dirs[0]
        files, _ = QFileDialog.getOpenFileNames(
            None,
            T("选择要固定到 Shortcut 的程序（可多选）"),
            start,
            T("程序与快捷方式 (*.exe *.lnk *.bat *.cmd *.url *.msc *.ps1);;所有文件 (*.*)"))
        if not files:
            return
        if self.cfg.get("desktop_folder_mode", False) and self.shortcut.organizer:
            categories = self.shortcut.organizer.state["categories"]
            if not categories:
                self.shortcut.manage_categories()
                categories = self.shortcut.organizer.state["categories"]
                if not categories:
                    return
            labels = [f"{index + 1} · {category['name']}" for index, category in enumerate(categories)]
            label, accepted = QInputDialog.getItem(None, "添加到分类", "选择桌面文件夹：", labels, 0, False)
            if accepted:
                self.shortcut.organizer.assign_paths(files, categories[labels.index(label)]["id"])
                self._show_shortcut()
            return
        added = 0
        for f in files:
            f = os.path.abspath(f)
            if any((not it.get("sep")) and str(it.get("path", "")).lower() == f.lower()
                   for it in self.cfg["items"]):
                continue
            name = os.path.splitext(os.path.basename(f))[0]
            self.cfg["items"].append({"path": f, "name": name})
            added += 1
        save_config(self.cfg)
        self.shortcut.reload()
        self._show_shortcut()
        if added:
            self.showMessage(APP_TITLE, T("已添加 %d 个图标到 Shortcut") % added, application_icon(), 2000)

    def set_icon_size(self, px):
        self.cfg["icon_size"] = int(px)
        self.shortcut.save_preferences()
        self.shortcut.reload()

    def set_blur(self, val):
        self.cfg["blur_px"] = int(val)
        self.shortcut.save_preferences()
        self.shortcut.refresh_backdrop()      # 立刻按新的模糊程度重抓一次
        if self.shortcut.desktop_folders:
            self.shortcut.desktop_folders.refresh()
        if self.shortcut.search_bar:
            self.shortcut.search_bar._capture_background()

    def set_transparency(self, val):
        self.cfg["transparency"] = int(val)
        self.shortcut.save_preferences()
        self.shortcut.update()
        if self.shortcut.category_panel:
            self.shortcut.category_panel.surface.update()
        if self.shortcut.search_bar:
            self.shortcut.search_bar.surface.update()
            self.shortcut.search_bar.update()
        if self.shortcut.desktop_folders:
            self.shortcut.desktop_folders.refresh()

    def set_theme(self, val):
        self.cfg["theme"] = val
        self.shortcut.save_preferences()
        if val == "auto":
            self.shortcut._sys_light = system_is_light()
        self.shortcut.apply_presentation_theme()

    def set_layer(self, val):
        self.cfg["layer"] = val
        self.shortcut.save_preferences()
        self.shortcut.apply_layer()

    def set_flag(self, key, value, glass=False, running=False, geometry=False):
        self.cfg[key] = bool(value)
        self.shortcut.save_preferences()
        if key == "magnify":
            self.shortcut._recalc(light=True)
            self.shortcut._kick()
        if glass or key == "glass":
            self.shortcut.start_backdrop()
        if running:
            self.shortcut.refresh_running()
        if geometry or key in ("show_name", "fixed_shortcut_bar", "sep_split"):
            self.shortcut.refresh_geometry()
        if key == "glass":
            if self.shortcut.desktop_folders:
                self.shortcut.desktop_folders.refresh()
            if self.shortcut.category_panel:
                self.shortcut.category_panel.surface.update()
            if self.shortcut.search_bar:
                self.shortcut.search_bar._capture_background()
                self.shortcut.search_bar.surface.update()
        self.shortcut.update()


# ----------------------------------------------------------------------------
# 预览模式（用于截图检查外观，不影响正常使用）
# ----------------------------------------------------------------------------
def run_preview(out_path, hover_index=None, size_px=None):
    configure_display_scaling()
    app = QApplication(sys.argv)
    configure_application(app)
    cfg = load_config()
    if not cfg["items"]:
        demo = []
        for p in (r"C:\Windows\explorer.exe", r"C:\Windows\system32\notepad.exe",
                  r"C:\Windows\system32\mspaint.exe", r"C:\Windows\system32\calc.exe",
                  r"C:\Windows\system32\cmd.exe", r"C:\Windows\system32\mstsc.exe",
                  r"C:\Windows\system32\control.exe"):
            if os.path.exists(p):
                demo.append({"path": p, "name": os.path.splitext(os.path.basename(p))[0]})
        cfg["items"] = demo
    if size_px:
        cfg["icon_size"] = int(size_px)
    shortcut = Shortcut(cfg, None, preview=True)
    shortcut.show()
    app.processEvents()
    if hover_index is not None and 0 <= hover_index < len(shortcut.items):
        cx = shortcut.rects[hover_index][0]
        shortcut.mouse_x = cx
        shortcut.mouse_smooth = cx
        shortcut.stretch = 1.0
        shortcut.stretch_target = 1.0
        shortcut.spec_x = cx
        shortcut.spec_alpha = 1.0
        shortcut.spec_target = 1.0
        shortcut.hover_index = hover_index
        shortcut._recalc()
        shortcut.cur = list(shortcut.tgt)
        shortcut._layout()
    app.processEvents()

    # 造一个假的桌面背景，方便看毛玻璃质感
    W, H = 1400, 460
    bg = QImage(W, H, QImage.Format_ARGB32)
    bp = QPainter(bg)
    bp.setRenderHint(QPainter.Antialiasing, True)
    g = QLinearGradient(0, 0, W, H)
    g.setColorAt(0.0, QColor(28, 42, 92))
    g.setColorAt(0.45, QColor(96, 74, 150))
    g.setColorAt(0.75, QColor(196, 108, 140))
    g.setColorAt(1.0, QColor(240, 176, 120))
    bp.fillRect(0, 0, W, H, QBrush(g))
    bp.setBrush(QColor(255, 255, 255, 26))
    bp.setPen(Qt.NoPen)
    for i in range(9):
        bp.drawEllipse(QPointF(W * (0.08 + i * 0.11), H * (0.25 + 0.4 * math.sin(i))), 90, 90)
    bp.end()

    pm = QPixmap(shortcut.size())
    pm.fill(Qt.transparent)
    shortcut.render(pm)
    out = QImage(W, H, QImage.Format_ARGB32)
    out.fill(Qt.transparent)
    op = QPainter(out)
    op.drawImage(0, 0, bg)
    x = (W - pm.width()) // 2
    y = H - 46 - pm.height()
    op.drawPixmap(x, y, pm)
    op.end()
    out.save(out_path)
    print("预览已保存:", out_path, "尺寸:", pm.width(), "x", pm.height())
    return 0


# ----------------------------------------------------------------------------
# 主程序
# ----------------------------------------------------------------------------
def main():
    args = sys.argv[1:]
    if "--wait-for-exit" in args:
        index = args.index("--wait-for-exit")
        if not wait_for_previous_process(int(args[index + 1])):
            log("重启失败：上一个 Shortcut 实例尚未退出。")
            return 1
    if "--native-desktop" in args:
        from .native_desktop_host import run_native_desktop
        index = args.index("--native-desktop")
        owner_pid = int(args[index + 2]) if len(args) > index + 2 else 0
        return run_native_desktop(args[index + 1], owner_pid)

    if "--stop" in args:
        try:
            user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user32.GetPropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
            user32.GetPropW.restype = wintypes.HANDLE
            marked = []
            callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            def find_main(candidate, _):
                if user32.GetPropW(candidate, MAIN_WINDOW_MARKER):
                    marked.append(candidate)
                return True
            callback = callback_type(find_main)
            user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
            user32.EnumWindows(callback, 0)
            if marked:
                for hwnd in marked:
                    user32.PostMessageW(hwnd, 0x0010, 0, 0)   # WM_CLOSE
                print("已通知 Shortcut 退出。")
            else:
                print("没有找到正在运行的 Shortcut。")
        except Exception:
            print("退出失败：" + traceback.format_exc())
        return 0

    if "--reset" in args:
        cfg = load_config()
        cfg["items"] = []
        save_config(cfg)
        print("已清空 Shortcut 上固定的图标。")
        return 0

    if "--preview" in args:
        i = args.index("--preview")
        out = args[i + 1] if len(args) > i + 1 else "preview.png"
        hover = None
        if "--hover" in args:
            try:
                hover = int(args[args.index("--hover") + 1])
            except Exception:
                hover = None
        size_px = None
        if "--size" in args:
            try:
                size_px = int(args[args.index("--size") + 1])
            except Exception:
                size_px = None
        return run_preview(out, hover, size_px)

    configure_display_scaling()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)   # 关掉窗口不退出，常驻托盘
    configure_application(app)

    # 只允许运行一个实例
    shm = QSharedMemory(APP_NAME + "_single_instance")
    if not shm.create(1):
        cfg0 = load_config()
        set_lang(cfg0.get("lang", "zh"))
        QMessageBox.information(None, APP_TITLE, T("Shortcut 已经在运行了（请看右下角托盘）。"))
        return 0

    # 取得单实例锁后，遗留标记才确定属于已经退出的上一实例。
    from .desktop_guardian import recover_stale_desktop
    recovered, recovery_detail = recover_stale_desktop(HIDDEN_MARKER_PATH)
    if recovered:
        log("检测到上次异常退出，已恢复 Windows 桌面图标。")
    elif recovery_detail:
        log("恢复上次桌面图标失败：" + recovery_detail)

    cfg = load_config()
    log("配置文件: " + CONFIG_PATH)
    set_lang(cfg.get("lang", "zh"))

    shortcut = Shortcut(cfg)
    tray = ShortcutTray(shortcut)
    shortcut.tray = tray
    tray.show()
    if recovery_detail:
        tray.showMessage(APP_TITLE, "上次异常退出后未能恢复桌面图标：" + recovery_detail,
                         application_icon(), 5000)
    shortcut.setup_organizer()
    shortcut.setup_recycle_bin()

    # 如果配置里开着自启动，就顺手把注册表补/修正一遍（防止你挪动过文件夹）
    if cfg.get("autostart"):
        set_autostart(True)

    if not cfg["items"]:
        tray.showMessage(APP_TITLE,
                         "桌面已启用虚拟分类。点击分类查看内容；右键可一键整理、管理规则。原文件位置保持不变。",
                         application_icon(), 5000)

    from .desktop_manager import DesktopManager
    shortcut.desktop_manager = DesktopManager(SCRIPT_PATH, shortcut,
                                          marker_path=HIDDEN_MARKER_PATH)
    shortcut.desktop_manager.error.connect(shortcut.desktop_display_error)
    shortcut.desktop_manager.ready.connect(lambda: QTimer.singleShot(120, shortcut.refresh_backdrop)
                                       if shortcut.isVisible() else None)
    def _restore_desktop_on_exit():
        _restore_desktop_icons_safe()
    app.aboutToQuit.connect(_restore_desktop_on_exit)
    shortcut.sync_presentation()
    log("启动完成，共 %d 个图标" % len(shortcut.items))
    return app.exec_()


