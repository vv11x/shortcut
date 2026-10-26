from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices


def open_entry(path: Path) -> None:
    if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
        raise OSError(f"Windows Shell could not open: {path}")


def show_in_explorer(path: Path) -> None:
    import subprocess

    subprocess.Popen(["explorer.exe", f"/select,{path}"])


def open_recycle_bin() -> None:
    import subprocess

    subprocess.Popen(["explorer.exe", "shell:RecycleBinFolder"])


def open_local_file(path: Path) -> None:
    if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
        raise OSError(f"Windows Shell could not open: {path}")
