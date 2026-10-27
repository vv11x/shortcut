# -*- mode: python ; coding: utf-8 -*-


from pathlib import Path
project_root = Path(SPECPATH).parent

a = Analysis(
    [str(project_root / 'shortcut.py')],
    pathex=[str(project_root)],
    binaries=[(str(project_root / 'native_desktop/ShortcutDesktop.dll'), 'native_desktop'),
              (str(project_root / 'native_desktop/ShortcutShell.dll'), 'native_desktop')],
    datas=[
        (str(project_root / 'assets/icons/shortcut-moe-v1'), 'assets/icons/shortcut-moe-v1'),
        (str(project_root / 'assets/branding/shortcut.ico'), 'assets/branding'),
        (str(project_root / 'LICENSE'), '.'),
        (str(project_root / 'THIRD_PARTY_NOTICES.md'), '.'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='shortcut',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=str(project_root / 'packaging/version_info.txt'),
    icon=[str(project_root / 'assets/branding/shortcut.ico')],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='shortcut',
)
