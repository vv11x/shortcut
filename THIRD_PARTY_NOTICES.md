# Third-party notices

shortcut's Python source is distributed under the MIT License in `LICENSE`. The installer includes these third-party components under their own terms:

| Component | Version | License and source |
| --- | --- | --- |
| PySide6 and Shiboken6 | 6.11.1 | LGPLv3 option; `licenses/LGPL-3.0.txt`; [license terms](https://doc.qt.io/qtforpython-6.11/licenses.html); [corresponding source](https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.11.1-src/pyside-setup-everywhere-src-6.11.1.tar.xz) |
| Qt runtime modules | 6.11.1 | LGPLv3 option; `licenses/LGPL-3.0.txt`; [license terms](https://doc.qt.io/qt-6.11/licensing.html); [corresponding source](https://download.qt.io/official_releases/qt/6.11/6.11.1/single/qt-everywhere-src-6.11.1.tar.xz); [third-party attributions](https://doc.qt.io/qt-6.11/licenses-used-in-qt.html) |
| Python runtime | 3.13.9 | PSF License Version 2; full text in `licenses/Python-LICENSE.txt`; [source release](https://www.python.org/downloads/release/python-3139/) |
| PyInstaller bootloader | 6.21.0 | GPLv2 or later with a bootloader exception; full text in `licenses/PyInstaller-COPYING.txt` |
| Microsoft Visual C++ Runtime | 14.x | Redistributable runtime files; [Microsoft redistribution guidance](https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files) |
| Windows Shell APIs | Windows | Microsoft platform APIs; [Shell API documentation](https://learn.microsoft.com/windows/win32/shell/shell-entry) |

The Qt shared libraries remain separate files in the installed program directory so users can replace them. The installer contains only the Windows platform, Windows style, and ICO image plugins required by shortcut; the unused PDF image plugin and GPL-only Qt Virtual Keyboard plugin are excluded. The shortcut source is available in this repository.

7-Zip is not bundled. If selected by the user, it remains a separately installed application under its own license.
