"""检查当前工程的命名、启动入口和自启动标识。"""
import ast
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


class BrandingTests(unittest.TestCase):
    def test_entrypoint_guardian_command_is_processed_before_loading_qt(self):
        code = (
            "import sys; sys.argv=['shortcut.py','--desktop-guardian']; "
            "from shortcut_app.bootstrap import run; "
            "assert run()==2; assert 'PyQt5' not in sys.modules"
        )
        subprocess.run([sys.executable, '-B', '-c', code], cwd=ROOT, check=True, timeout=10)

    def test_entire_project_has_no_previous_name_in_paths_or_file_bytes(self):
        token = bytes.fromhex('646f636b')
        patterns = (token, token.decode().encode('utf-16-le'), token.decode().encode('utf-16-be'))
        self.assertNotIn(token.decode(), ROOT.name.lower())
        self.assertFalse((ROOT / '.git').exists())
        self.assertFalse((ROOT / '.venv').exists())
        for path in ROOT.rglob('*'):
            self.assertNotIn(token.decode(), path.name.lower(), str(path.relative_to(ROOT)))
            if path.is_file():
                data = path.read_bytes().lower()
                for pattern in patterns:
                    self.assertNotIn(pattern, data, str(path.relative_to(ROOT)))

    def test_autostart_uses_only_current_application_name(self):
        tree = ast.parse((ROOT / 'shortcut_app/application.py').read_text(encoding='utf-8'))
        node = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == 'set_autostart')
        registry = SimpleNamespace(OpenKey=Mock(return_value='key'), SetValueEx=Mock(), DeleteValue=Mock(),
                                   CloseKey=Mock(), HKEY_CURRENT_USER=1, KEY_SET_VALUE=2, KEY_QUERY_VALUE=4, REG_SZ=1)
        scope = {'APP_NAME': 'shortcut', 'RUN_KEY': 'Run',
                 'autostart_command': lambda: 'shortcut.exe', 'log': Mock()}
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'application.py', 'exec'), scope)
        with patch.dict('sys.modules', winreg=registry):
            self.assertTrue(scope['set_autostart'](True))
            registry.SetValueEx.assert_called_once_with('key', 'shortcut', 0, 1, 'shortcut.exe')
            registry.DeleteValue.assert_not_called()
            self.assertTrue(scope['set_autostart'](False))
            registry.DeleteValue.assert_called_once_with('key', 'shortcut')


if __name__ == '__main__':
    unittest.main()
