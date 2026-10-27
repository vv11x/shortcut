"""IPC lifecycle regressions; no real desktop calls, sockets or child processes."""

import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import shortcut_app.desktop_manager as desktop_manager
class Signal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self, *args):
        for callback in list(self.callbacks):
            callback(*args)


class Timer:
    def __init__(self, parent=None):
        self.timeout = Signal()
        self.active = False
        self.interval = 0

    def setSingleShot(self, enabled):
        pass

    def setInterval(self, interval):
        self.interval = interval

    def start(self, interval=None):
        if interval is not None:
            self.interval = interval
        self.active = True

    def stop(self):
        self.active = False


class Process:
    NotRunning = 0
    Running = 2
    FailedToStart = 0

    def __init__(self, parent=None):
        self.finished = Signal()
        self.errorOccurred = Signal()
        self.current_state = self.NotRunning
        self.arguments = []
        self.waits = []
        self.on_start = None
        self.on_wait = None
        self.killed = False

    def state(self):
        return self.current_state

    def setProgram(self, program):
        self.program = program

    def setArguments(self, arguments):
        self.arguments = arguments

    def setWorkingDirectory(self, directory):
        self.directory = directory

    def start(self):
        self.current_state = self.Running
        if self.on_start:
            self.on_start()

    def waitForFinished(self, timeout):
        self.waits.append(timeout)
        if self.on_wait:
            return self.on_wait(timeout)
        self.current_state = self.NotRunning
        self.finished.emit(0, 0)
        return True

    def kill(self):
        self.killed = True

    def errorString(self):
        return "simulated startup failure"


class Server:
    def __init__(self, parent=None):
        self.newConnection = Signal()
        self.pending = []
        self.listening = False

    def listen(self, endpoint):
        self.listening = True
        self.endpoint = endpoint
        return True

    def nextPendingConnection(self):
        return self.pending.pop(0) if self.pending else None

    def close(self):
        self.listening = False


class Socket:
    def __init__(self, buffered=b""):
        self.readyRead = Signal()
        self.disconnected = Signal()
        self.buffered = buffered
        self.writes = []
        self.aborted = False
        self.deleted = False

    def readAll(self):
        data, self.buffered = self.buffered, b""
        return data

    def write(self, data):
        self.writes.append(data)
        return len(data)

    def flush(self):
        return True

    def abort(self):
        self.aborted = True
        self.disconnected.emit()

    def deleteLater(self):
        self.deleted = True


class FakeGuardian:
    instances = []

    def __init__(self, script_path, marker_path):
        self.script_path = script_path
        self.marker_path = marker_path
        self.token = "guardian-token"
        self.alive = True
        self.started = False
        self.hidden = False
        self.stopped = False
        self.aborted = False
        FakeGuardian.instances.append(self)

    def start(self):
        self.started = True
        return self

    def hide(self):
        self.hidden = True

    def stop(self):
        self.stopped = True
        self.alive = False

    def abort(self):
        self.aborted = True
        self.stop()


class DesktopManagerLifecycleTests(unittest.TestCase):
    def setUp(self):
        FakeGuardian.instances = []
        self.desktop = os.path.abspath("fake-desktop")
        self.visibility = Mock()
        self.restore = Mock()
        self.show_desktop = Mock(return_value=True)
        replacements = {
            "QProcess": Process, "QTimer": Timer, "QLocalServer": Server,
            "desktop_directories": lambda: [self.desktop],
            "set_icons_visible": self.visibility, "restore_stock_view": self.restore,
            "GuardianProcess": FakeGuardian, "show_desktop": self.show_desktop,
        }
        for name, value in replacements.items():
            replacement = patch.object(desktop_manager, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)
        self.marker = os.path.abspath("fake-desktop-hidden.json")
        self.manager = desktop_manager.DesktopManager(
            os.path.abspath("shortcut.py"), marker_path=self.marker)
        self.errors = []
        self.ready = []
        self.manager.error.connect(self.errors.append)
        self.manager.ready.connect(lambda: self.ready.append(True))

    def connect_socket(self, socket):
        self.manager.server.pending.append(socket)
        self.manager._connected()

    def test_startup_passes_main_pid_to_independent_native_watchdog(self):
        self.manager.set_mode("managed")
        self.assertEqual(self.manager.process.arguments[-1], str(os.getpid()))
        self.assertIn("--native-desktop", self.manager.process.arguments)
        self.assertTrue(self.manager._startup.active)

    def test_buffered_ready_is_drained_and_first_snapshot_is_sent(self):
        self.manager.set_mode("managed")
        path = os.path.join(self.desktop, "app.lnk")
        self.manager.update({"apps": [{"path": path}]}, [{"id": "apps"}])
        socket = Socket(b'{"ready":true}\n')
        self.connect_socket(socket)
        payload = json.loads(socket.writes[0])
        self.assertEqual(set(payload["paths"]), {path, desktop_manager.RECYCLE_KEY})
        self.assertEqual(self.ready, [True])
        self.assertFalse(self.manager._startup.active)

    def test_connection_before_index_still_receives_later_index_update(self):
        self.manager.set_mode("managed")
        socket = Socket()
        self.connect_socket(socket)
        self.assertEqual(json.loads(socket.writes[0])["paths"], [desktop_manager.RECYCLE_KEY])
        path = os.path.join(self.desktop, "app.lnk")
        self.manager.update({"apps": [{"path": path}]}, [{"id": "apps"}])
        self.assertIn(path, json.loads(socket.writes[-1])["paths"])

    def test_folder_mode_keeps_recycle_bin_and_collects_only_represented_desktop_files(self):
        self.manager.set_mode('managed')
        socket = Socket()
        self.connect_socket(socket)
        path = os.path.join(self.desktop, 'uncategorized.txt')
        other = os.path.abspath('other-folder/file.txt')
        self.manager.update({'__uncategorized__': [{'path': path}, {'path': other}]},
                            [{'id': '__uncategorized__'}], hide_recycle=False)
        self.assertEqual(json.loads(socket.writes[-1])['paths'], [path])
        self.manager.update({'__uncategorized__': [{'path': path}, {'path': other}]},
                            [{'id': '__uncategorized__'}], hide_recycle=True)
        self.assertIn(desktop_manager.RECYCLE_KEY, json.loads(socket.writes[-1])['paths'])

    def test_restore_error_is_not_silently_swallowed(self):
        self.manager.set_mode('managed')
        self.restore.side_effect = OSError('desktop restore failed')
        with self.assertRaisesRegex(OSError, 'desktop restore failed'):
            self.manager.stop()

    def test_stopping_rejects_late_connection_without_delivering_paths(self):
        self.manager.set_mode("managed")
        self.manager.stopping = True
        socket = Socket()
        self.connect_socket(socket)
        self.assertTrue(socket.aborted)
        self.assertTrue(socket.deleted)
        self.assertIsNone(self.manager.socket)
        self.assertEqual(socket.writes, [])

    def test_stop_closes_pipe_before_wait_and_recovers_once_after_finished(self):
        self.manager.set_mode("managed")
        socket = Socket()
        self.connect_socket(socket)

        def wait(timeout):
            self.assertTrue(socket.aborted)
            self.assertIsNone(self.manager.socket)
            self.assertEqual(timeout, 12000)
            self.manager.process.current_state = Process.NotRunning
            self.manager.process.finished.emit(0, 0)
            self.restore.assert_not_called()
            return True

        self.manager.process.on_wait = wait
        self.manager.stop()
        self.restore.assert_called_once_with()
        self.assertEqual(self.errors, [])
        self.assertFalse(self.manager._startup.active)

    def test_hung_helper_is_terminated_then_desktop_recovers_once(self):
        self.manager.set_mode("managed")
        self.manager.process.on_wait = lambda timeout: timeout == 1000
        self.manager.stop()
        self.assertEqual(self.manager.process.waits, [12000, 1000])
        self.assertTrue(self.manager.process.killed)
        self.restore.assert_called_once_with()

    def test_failed_start_cannot_rearm_startup_timeout(self):
        def fail():
            self.assertTrue(self.manager._startup.active)
            self.manager.process.current_state = Process.NotRunning
            self.manager.process.errorOccurred.emit(Process.FailedToStart)

        self.manager.process.on_start = fail
        self.manager.set_mode("managed")
        self.assertFalse(self.manager._startup.active)
        self.assertEqual(self.manager.mode, "all")
        self.assertEqual(len(self.errors), 1)
        self.restore.assert_called_once_with()

    def test_unexpected_helper_exit_restores_desktop_and_reports_error(self):
        self.manager.set_mode("managed")
        socket = Socket(b'{"error":"native failure"}\n')
        self.connect_socket(socket)
        self.manager.process.current_state = Process.NotRunning
        self.manager.process.finished.emit(1, 0)
        self.restore.assert_called_once_with()
        self.assertEqual(self.manager.mode, "all")
        self.assertIn("native failure", self.errors[0])
        self.assertTrue(socket.aborted)

    def test_disconnect_after_ready_bounds_helper_shutdown_and_resets_on_restart(self):
        self.manager.set_mode("managed")
        socket = Socket(b'{"ready":true}\n')
        self.connect_socket(socket)
        socket.disconnected.emit()
        self.assertTrue(self.manager._startup.active)
        self.assertEqual(self.manager._startup.interval, 12000)
        self.manager._startup_timeout()
        self.restore.assert_called_once_with()
        self.assertEqual(self.manager.mode, "all")
        self.manager.set_mode("managed")
        self.assertEqual(self.manager._startup.interval, 40000)

    def test_old_socket_disconnect_does_not_arm_new_connection_timeout(self):
        self.manager.set_mode("managed")
        old = Socket()
        self.connect_socket(old)
        self.manager.stop()
        self.manager.set_mode("managed")
        new = Socket(b'{"ready":true}\n')
        self.connect_socket(new)
        old.disconnected.emit()
        self.assertFalse(self.manager._startup.active)
        self.assertIs(self.manager.socket, new)


    def test_hidden_mode_starts_guardian_and_normal_stop_clears_marker(self):
        self.manager.set_mode("hidden")
        guardian = FakeGuardian.instances[-1]
        self.assertTrue(guardian.started)
        self.assertTrue(guardian.hidden)
        self.assertIs(self.manager.guardian, guardian)
        self.assertTrue(self.manager._guardian_check_timer.active)
        self.visibility.assert_not_called()

        self.manager.stop()
        self.show_desktop.assert_called_once_with(self.marker, "guardian-token")
        self.assertTrue(guardian.stopped)
        self.assertFalse(self.manager._guardian_check_timer.active)

    def test_leaving_hidden_restores_before_stopping_guardian(self):
        events = []
        self.manager.set_mode("hidden")
        guardian = FakeGuardian.instances[-1]
        guardian.stop = lambda: events.append("guardian_stop")
        self.show_desktop = Mock(side_effect=lambda path, token: events.append("show") or True)
        with patch.object(desktop_manager, "show_desktop", self.show_desktop):
            self.manager.set_mode("all")
        self.assertEqual(events, ["show", "guardian_stop"])
        self.assertEqual(self.manager.mode, "all")

    def test_guardian_death_restores_desktop_and_reports_error(self):
        self.manager.set_mode("hidden")
        guardian = FakeGuardian.instances[-1]
        guardian.alive = False
        self.manager._check_guardian()
        self.show_desktop.assert_called_once_with(self.marker, "guardian-token")
        self.assertTrue(guardian.stopped)
        self.assertEqual(self.manager.mode, "all")
        self.assertIn("已恢复", self.errors[0])

    def test_hidden_start_failure_aborts_guardian_and_keeps_desktop_visible(self):
        def fail(self):
            raise OSError("guard start failed")

        original_start = FakeGuardian.start
        FakeGuardian.start = fail
        self.addCleanup(setattr, FakeGuardian, "start", original_start)
        with self.assertRaises(OSError):
            self.manager.set_mode("hidden")
        guardian = FakeGuardian.instances[-1]
        self.assertTrue(guardian.aborted)
        self.assertEqual(self.manager.mode, "all")
        self.assertFalse(self.manager._guardian_check_timer.active)

    def test_hidden_mode_requires_a_recovery_marker(self):
        self.manager.marker_path = None
        with self.assertRaisesRegex(RuntimeError, "恢复标记路径"):
            self.manager.set_mode("hidden")
        self.visibility.assert_not_called()
        self.assertEqual(self.manager.mode, "all")

    def test_failed_restore_keeps_guardian_for_exit_recovery(self):
        self.manager.set_mode("hidden")
        guardian = FakeGuardian.instances[-1]
        self.show_desktop.return_value = False
        with self.assertRaises(OSError):
            self.manager.set_mode("all")
        self.assertIs(self.manager.guardian, guardian)
        self.assertTrue(self.manager._guardian_check_timer.active)
        self.assertEqual(self.manager.mode, "hidden")


if __name__ == "__main__":
    unittest.main()
