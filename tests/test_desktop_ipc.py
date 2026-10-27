"""Real Qt pipe/process timing with a fake native desktop in a test-only child."""

import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QProcess
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

import shortcut_app.desktop_manager as desktop_manager
from shortcut_app.organizer import normalize_path


ROOT = Path(__file__).resolve().parents[1]
CHILD = '''
import json, sys
sys.path.insert(0, ROOT_PATH)
from PyQt5.QtCore import QObject, pyqtSignal
import shortcut_app.native_desktop_host as host
class FakeNative(QObject):
    ready = pyqtSignal()
    error = pyqtSignal(str)
    explorer_exited = pyqtSignal()
    def __init__(self, owner_pid=0):
        super().__init__()
        self.bridge = None
    def connect_desktop(self):
        self.bridge = 1
        self.ready.emit()
    def set_paths(self, paths):
        print(json.dumps({"applied": paths}), flush=True)
    def stop(self):
        self.bridge = None
host.NativeDesktop = FakeNative
offset = sys.argv.index("--native-desktop")
sys.exit(host.run_native_desktop(sys.argv[offset + 1], int(sys.argv[offset + 2])))
'''


@unittest.skipUnless(os.name == "nt", "Windows desktop helper")
class DesktopIPCTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        script = Path(self.temp.name) / "fake_desktop_helper.py"
        script.write_text(CHILD.replace("ROOT_PATH", repr(str(ROOT))), encoding="utf-8")
        self.visibility = Mock()
        self.recovery = Mock()
        side_effects = patch.multiple(desktop_manager,
                                     set_icons_visible=self.visibility,
                                     restore_stock_view=self.recovery)
        side_effects.start()
        self.addCleanup(side_effects.stop)
        self.manager = desktop_manager.DesktopManager(str(script))
        self.addCleanup(self.dispose_manager)
        self.directory = normalize_path(Path(self.temp.name) / "desktop")
        self.manager.directories = frozenset({self.directory})
        self.path = normalize_path(Path(self.directory) / "app.lnk")
        self.ready_count = 0
        self.manager.ready.connect(self.ready)
        self.output = ""

    def ready(self):
        self.ready_count += 1

    def dispose_manager(self):
        self.manager.stop()
        self.manager.deleteLater()
        self.app.processEvents()

    def wait_until(self, predicate):
        deadline = time.monotonic() + 8
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertTrue(predicate(), self.manager.process.errorString())

    def applied(self, path):
        self.output += bytes(self.manager.process.readAllStandardOutput()).decode("utf-8")
        return any(path in json.loads(line).get("applied", [])
                   for line in self.output.split("\n")[:-1] if line)

    def update_index(self):
        self.manager.update({"apps": [{"path": self.path}]}, [{"id": "apps"}])

    def test_first_snapshot_and_later_index_update_reach_real_helper(self):
        self.manager.set_mode("managed")
        self.wait_until(lambda: self.ready_count == 1)
        self.wait_until(lambda: self.applied(desktop_manager.RECYCLE_KEY))
        self.update_index()
        self.wait_until(lambda: self.applied(self.path))
        self.manager.stop()
        self.assertEqual(self.manager.process.state(), QProcess.NotRunning)
        self.recovery.assert_called_once_with()

    def test_existing_index_is_applied_and_child_crash_recovers(self):
        self.update_index()
        self.manager.set_mode("managed")
        self.wait_until(lambda: self.ready_count == 1)
        self.wait_until(lambda: self.applied(self.path))
        # Terminate only the test child created above, whose native layer is fake.
        self.manager.process.kill()
        self.wait_until(lambda: self.manager.mode == "all")
        self.assertEqual(self.manager.process.state(), QProcess.NotRunning)
        self.recovery.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
