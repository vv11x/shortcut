import ast
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PackagingEntrypointTests(unittest.TestCase):
    def test_pyinstaller_runs_package_main_module(self):
        spec_path = PROJECT_ROOT / "shortcut.spec"
        module = ast.parse(spec_path.read_text(encoding="utf-8"), filename=str(spec_path))
        analysis = next(
            statement.value
            for statement in module.body
            if isinstance(statement, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "analysis" for target in statement.targets)
        )
        script_argument = ast.unparse(analysis.args[0])
        self.assertIn("__main__.py", script_argument)

    def test_pyinstaller_excludes_host_icu_binaries(self):
        spec_path = PROJECT_ROOT / "shortcut.spec"
        module = ast.parse(spec_path.read_text(encoding="utf-8"), filename=str(spec_path))
        excluded = next(
            ast.literal_eval(statement.value)
            for statement in module.body
            if isinstance(statement, ast.Assign)
            and any(
                isinstance(target, ast.Name)
                and target.id == "incompatible_environment_binaries"
                for target in statement.targets
            )
        )
        self.assertEqual(excluded, {"icuuc.dll", "icudt78.dll"})

    def test_installer_removes_legacy_host_icu_binaries(self):
        installer_path = PROJECT_ROOT / "installer" / "shortcut.iss"
        installer_script = installer_path.read_text(encoding="utf-8")
        self.assertIn('Type: files; Name: "{app}\\_internal\\icuuc.dll"', installer_script)
        self.assertIn('Type: files; Name: "{app}\\_internal\\icudt78.dll"', installer_script)


if __name__ == "__main__":
    unittest.main()
