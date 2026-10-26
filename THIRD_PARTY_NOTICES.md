# Third-party notices

shortcut's Python source is distributed under the MIT License in `LICENSE`. The installer also includes these third-party components under their own terms:

| Component | Version | License and source |
| --- | --- | --- |
| PySide6 | 6.11.1 | LGPLv3 option; [Qt for Python licensing](https://doc.qt.io/qtforpython-6/licenses.html) |
| Shiboken6 | 6.11.1 | LGPLv3 option; [Qt for Python licensing](https://doc.qt.io/qtforpython-6/licenses.html) |
| Qt | 6.11.1 | LGPLv3 option for the included modules; [Qt licensing](https://doc.qt.io/qt-6/licensing.html) |
| Python | 3.13 | [Python License](https://docs.python.org/3/license.html) |
| PyInstaller bootloader | 6.21.0 | GPLv2 or later with a bootloader exception; see `licenses/PyInstaller-COPYING.txt` |
| Windows Shell APIs | Windows | Microsoft platform APIs; [Shell API documentation](https://learn.microsoft.com/windows/win32/shell/shell-entry) |

The PySide6 and Qt shared libraries remain separate files in the installed program directory so users can replace them. LGPLv3 and PyInstaller license texts are included in `licenses/`. The source for shortcut is available in this repository.

7-Zip is not bundled. If selected by the user, it remains a separately installed application under its own license.
