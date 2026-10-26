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

# The GUI uses PNG artwork and the standard Windows platform plugin. Keep the
# Qt runtime to the plugins it needs; in particular, do not ship the optional
# GPL-only Virtual Keyboard plugin or PDF/image-format plugins this app never
# loads.
qt_plugins = {
    "pyside6/plugins/platforms/qwindows.dll",
    "pyside6/plugins/styles/qmodernwindowsstyle.dll",
    "pyside6/plugins/imageformats/qico.dll",
}
unused_qt_binaries = {
    "pyside6/qt6pdf.dll",
    "pyside6/qt6svg.dll",
    "pyside6/qt6virtualkeyboard.dll",
    "pyside6/qt6qml.dll",
    "pyside6/qt6qmlmeta.dll",
    "pyside6/qt6qmlmodels.dll",
    "pyside6/qt6qmlworkerscript.dll",
    "pyside6/qt6quick.dll",
    "libssl-3-x64.dll",
    "libcrypto-3-x64.dll",
}
analysis.binaries = [
    item
    for item in analysis.binaries
    if (
        not item[0].replace("\\", "/").casefold().startswith("pyside6/plugins/")
        or item[0].replace("\\", "/").casefold() in qt_plugins
    )
    and item[0].replace("\\", "/").casefold() not in unused_qt_binaries
]

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
