from pathlib import Path


project_root = Path(SPECPATH)
data_files = [
    (str(project_root / "assets"), "assets"),
]

analysis = Analysis(
    [str(project_root / "src" / "shortcut" / "entry.py")],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=data_files,
    hiddenimports=[
        "shortcut.app",
        "shortcut.catalog",
        "shortcut.dock_window",
        "shortcut.entry",
        "shortcut.file_actions",
        "shortcut.models",
        "shortcut.panels",
        "shortcut.resources",
        "shortcut.settings_dialog",
        "shortcut.shell",
        "shortcut.storage",
        "shortcut.windows_desktop",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    noarchive=False,
    optimize=0,
)

archive = PYZ(analysis.pure)
executable = EXE(
    archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="shortcut",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(project_root / "assets" / "branding" / "shortcut.ico"),
)
collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="shortcut",
)
