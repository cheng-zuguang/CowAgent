import sys
import unittest
from pathlib import Path


if sys.version_info >= (3, 11):
    import tomllib
else:
    tomllib = None


class TestPackageMetadata(unittest.TestCase):
    def test_web_runtime_dependency_is_declared_for_editable_install(self):
        pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
        if tomllib is None:
            text = pyproject.read_text(encoding="utf-8")
            self.assertIn('"web.py"', text)
            return

        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        dependencies = data["project"]["dependencies"]

        self.assertIn("web.py", dependencies)


if __name__ == "__main__":
    unittest.main()
