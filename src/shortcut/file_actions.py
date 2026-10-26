import ctypes
import subprocess
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication, QFileDialog, QWidget


class ShellFileOperation(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", wintypes.WORD),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", wintypes.LPVOID),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


def copy_paths(paths: list[Path], cut: bool) -> None:
    from PySide6.QtCore import QMimeData

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path.resolve())) for path in paths])
    effect = 2 if cut else 1
    mime.setData('application/x-qt-windows-mime;value="Preferred DropEffect"', effect.to_bytes(4, "little"))
    QApplication.clipboard().setMimeData(mime)


def delete_to_recycle_bin(paths: list[Path], parent: QWidget) -> None:
    source_buffer = ctypes.create_unicode_buffer("\0".join(str(path.resolve()) for path in paths) + "\0\0")
    operation = ShellFileOperation(
        hwnd=parent.winId(),
        wFunc=3,
        pFrom=ctypes.cast(source_buffer, wintypes.LPCWSTR),
        pTo=None,
        fFlags=0x0040,
        fAnyOperationsAborted=False,
        hNameMappings=None,
        lpszProgressTitle=None,
    )
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.SHFileOperationW.argtypes = [ctypes.POINTER(ShellFileOperation)]
    shell32.SHFileOperationW.restype = ctypes.c_int
    result = shell32.SHFileOperationW(ctypes.byref(operation))
    if result != 0:
        raise OSError(result, "Windows Shell could not move the selected item to the Recycle Bin")


def compress_paths(paths: list[Path], archiver_path: str, parent: QWidget) -> None:
    default_name = f"{paths[0].stem}.7z" if len(paths) == 1 else f"{paths[0].parent.name}.7z"
    output, _ = QFileDialog.getSaveFileName(parent, "创建压缩包", str(paths[0].parent / default_name), "7-Zip archive (*.7z)")
    if not output:
        return
    archive_path = Path(output)
    if archive_path.suffix.casefold() != ".7z":
        archive_path = archive_path.with_suffix(".7z")
    subprocess.Popen([archiver_path, "a", str(archive_path), *[str(path.resolve()) for path in paths]])


def extract_archive(path: Path, archiver_path: str, parent: QWidget) -> None:
    destination = QFileDialog.getExistingDirectory(parent, "选择解压位置", str(path.parent))
    if not destination:
        return
    subprocess.Popen([archiver_path, "x", str(path.resolve()), f"-o{destination}"])
