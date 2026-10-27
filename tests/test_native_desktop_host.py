"""Helper lifecycle tests using fake Qt; no Explorer or native library access."""

import ast
import json
from pathlib import Path
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]


class Signal:
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)

    def emit(self, *args):
        for slot in list(self.slots):
            slot(*args)


class HelperHarness:
    def __init__(self, initial=None):
        harness = self
        self.queue = []
        self.timers = []
        self.natives = []
        self.scenario = None
        self.wait_action = None
        self.connect_action = None
        self.apply_action = None
        self.app = SimpleNamespace(aboutToQuit=Signal(), quitting=False)
        self.app.setQuitOnLastWindowClosed = lambda value: None

        def quit_app():
            if not self.app.quitting:
                self.app.quitting = True
                self.app.aboutToQuit.emit()
        self.app.quit = quit_app

        def execute():
            if self.scenario:
                self.scenario()
            else:
                self.drain()
            return 0
        self.app.exec_ = execute

        class Timer:
            def __init__(self):
                self.timeout = Signal()
                self.active = False
                self.starts = 0
                harness.timers.append(self)

            def setSingleShot(self, value):
                pass

            def setInterval(self, value):
                pass

            def start(self):
                self.active = True
                self.starts += 1

            def stop(self):
                self.active = False

            def isActive(self):
                return self.active

            def fire(self):
                self.active = False
                self.timeout.emit()

            @staticmethod
            def singleShot(delay, callback):
                harness.queue.append(callback)

        class Socket:
            def __init__(self):
                self.readyRead = Signal()
                self.disconnected = Signal()
                self.errorOccurred = Signal()
                self.data = bytearray(initial or b'')
                self.messages = []
                harness.socket = self

            def connectToServer(self, endpoint):
                self.endpoint = endpoint

            def waitForConnected(self, timeout):
                if harness.wait_action:
                    harness.wait_action()
                return True

            def readAll(self):
                data, self.data = bytes(self.data), bytearray()
                return data

            def write(self, data):
                self.messages.append(json.loads(data))

            def flush(self):
                pass

            def send(self, message):
                self.data.extend((json.dumps(message) + '\n').encode())
                self.readyRead.emit()

        class Native:
            def __init__(self, owner_pid=0):
                self.ready = Signal()
                self.error = Signal()
                self.explorer_exited = Signal()
                self.bridge = None
                self.owner_pid = owner_pid
                self.applied = []
                self.stops = 0
                self.connections = 0
                harness.natives.append(self)

            def connect_desktop(self):
                self.connections += 1
                if harness.connect_action:
                    harness.connect_action(self)
                else:
                    self.bridge = 100
                    self.ready.emit()

            def set_paths(self, paths):
                self.applied.append(list(paths))
                if harness.apply_action:
                    harness.apply_action(self)

            def stop(self):
                self.stops += 1
                self.bridge = None

        namespace = {
            'QApplication': lambda argv: self.app, 'QLocalSocket': Socket,
            'QTimer': Timer, 'NativeDesktop': Native, 'json': json,
            'sys': SimpleNamespace(argv=['helper']),
        }
        tree = ast.parse((ROOT / 'shortcut_app/native_desktop_host.py').read_text(encoding='utf-8-sig'))
        function = next(node for node in tree.body
                        if isinstance(node, ast.FunctionDef) and node.name == 'run_native_desktop')
        exec(compile(ast.Module(body=[function], type_ignores=[]), 'native_desktop_host.py', 'exec'), namespace)
        self.run = namespace['run_native_desktop']

    def next_event(self):
        self.queue.pop(0)()

    def drain(self):
        for _ in range(100):
            if not self.queue or self.app.quitting:
                return
            self.next_event()
        raise AssertionError('Unexpected unbounded callback loop')


class NativeHelperLifecycleTests(unittest.TestCase):
    def test_initial_paths_buffered_before_event_loop_are_applied(self):
        harness = HelperHarness(b'{"paths": ["first"]}\n')
        self.assertEqual(harness.run('test-endpoint', owner_pid=1234), 0)
        native = harness.natives[0]
        self.assertEqual(native.owner_pid, 1234)
        self.assertEqual(native.applied, [['first']])
        self.assertEqual(harness.socket.messages, [{'ready': True}])
        self.assertEqual(native.stops, 1)

    def test_native_ready_waits_for_complete_initial_paths(self):
        harness = HelperHarness(b'{"paths": ["fir')

        def scenario():
            harness.drain()
            self.assertEqual(harness.natives[0].applied, [])
            self.assertEqual(harness.socket.messages, [])
            harness.socket.data.extend(b'st"]}\n')
            harness.socket.readyRead.emit()
            self.assertEqual(harness.natives[0].applied, [['first']])
            self.assertEqual(harness.socket.messages, [{'ready': True}])
        harness.scenario = scenario
        harness.run('test')

    def test_disconnect_during_connection_never_constructs_native_or_enters_loop(self):
        harness = HelperHarness()
        harness.wait_action = lambda: harness.socket.disconnected.emit()
        harness.scenario = lambda: self.fail('Event loop must not start after disconnection')
        self.assertEqual(harness.run('test'), 1)
        self.assertEqual(harness.natives, [])

    def test_partial_update_does_not_reapply_previous_paths(self):
        harness = HelperHarness(b'{"paths": ["first"]}\n')

        def scenario():
            harness.drain()
            harness.socket.data.extend(b'{"paths": ["second"')
            harness.socket.readyRead.emit()
            self.assertEqual(harness.natives[0].applied, [['first']])
            harness.socket.data.extend(b']}\n{"paths": ["latest"]}\n')
            harness.socket.readyRead.emit()
            self.assertEqual(harness.natives[0].applied, [['first'], ['latest']])
        harness.scenario = scenario
        harness.run('test')

    def test_disconnect_after_collection_restores_once_and_stops_retry_timers(self):
        harness = HelperHarness(b'{"paths": ["first"]}\n')

        def scenario():
            harness.drain()
            harness.socket.disconnected.emit()
            harness.socket.errorOccurred.emit(1)
        harness.scenario = scenario
        harness.run('test')
        self.assertEqual(harness.natives[0].stops, 1)
        self.assertTrue(harness.app.quitting)
        self.assertFalse(any(timer.active for timer in harness.timers))

    def test_malformed_message_stops_collection_and_reports_failure(self):
        for bad_message in ({'paths': [None]}, {'paths': 'wrong'}, {'paths': ['bad\0path']}):
            with self.subTest(message=bad_message):
                harness = HelperHarness(b'{"paths": ["first"]}\n')

                def scenario():
                    harness.drain()
                    harness.socket.send(bad_message)
                harness.scenario = scenario
                harness.run('test')
                self.assertEqual(harness.natives[0].stops, 1)
                self.assertIn('error', harness.socket.messages[-1])

    def test_timeout_retry_uses_latest_paths_and_delays_ready_until_success(self):
        harness = HelperHarness(b'{"paths": ["first"]}\n')

        def apply(native):
            if len(native.applied) == 1:
                error = OSError('Explorer temporarily busy')
                error.winerror = 1460
                raise error
        harness.apply_action = apply

        def scenario():
            harness.drain()
            retry = harness.timers[0]
            self.assertTrue(retry.active)
            self.assertEqual(harness.socket.messages, [])
            harness.socket.send({'paths': ['latest']})
            self.assertEqual(harness.natives[0].applied, [['first']])
            retry.fire()
            self.assertEqual(harness.natives[0].applied, [['first'], ['latest']])
            self.assertEqual(harness.socket.messages, [{'ready': True}])
        harness.scenario = scenario
        harness.run('test')

    def test_explorer_restart_gets_fresh_connection_retry_budget(self):
        harness = HelperHarness(b'{"paths": ["first"]}\n')

        def connect(native):
            raise OSError('Explorer is starting')
        harness.connect_action = connect

        def scenario():
            harness.drain()
            reconnect = harness.timers[1]
            for _ in range(18):
                reconnect.fire()
            self.assertEqual(harness.natives[0].connections, 19)
            harness.natives[0].explorer_exited.emit()
            reconnect.fire()
            self.assertFalse(harness.app.quitting)
            self.assertEqual(harness.socket.messages, [])
            harness.connect_action = None
            reconnect.fire()
            harness.drain()
            self.assertEqual(harness.natives[0].applied, [['first']])
            self.assertEqual(harness.socket.messages, [{'ready': True}])
        harness.scenario = scenario
        harness.run('test')

    def test_unexpected_apply_exception_is_reported_and_cleanup_runs(self):
        harness = HelperHarness(b'{"paths": ["first"]}\n')

        def apply(native):
            raise RuntimeError('unexpected native apply error')
        harness.apply_action = apply
        harness.run('test')
        self.assertEqual(harness.socket.messages, [{'error': 'unexpected native apply error'}])
        self.assertEqual(harness.natives[0].stops, 1)

    def test_event_loop_exception_still_stops_native(self):
        harness = HelperHarness(b'{"paths": ["first"]}\n')

        def scenario():
            harness.drain()
            raise RuntimeError('unexpected event loop error')
        harness.scenario = scenario
        self.assertEqual(harness.run('test'), 1)
        self.assertEqual(harness.natives[0].stops, 1)
        self.assertEqual(harness.socket.messages[-1], {'error': 'unexpected event loop error'})


if __name__ == '__main__':
    unittest.main()
