from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "collaboration_framework"


def imports_for(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


class ArchitectureTests(unittest.TestCase):
    def test_modular_monolith_directories_exist(self) -> None:
        for name in ("contracts", "ports", "host", "engine", "module", "bootstrap"):
            self.assertTrue((PACKAGE / name).is_dir(), name)

    def test_obsolete_flat_modules_are_removed(self) -> None:
        for name in ("contracts.py", "ports.py", "workflow.py", "routing.py"):
            self.assertFalse((PACKAGE / name).exists(), name)

    def test_contracts_do_not_import_components(self) -> None:
        for path in (PACKAGE / "contracts").rglob("*.py"):
            for imported in imports_for(path):
                self.assertFalse(
                    imported.startswith(
                        (
                            "collaboration_framework.host",
                            "collaboration_framework.engine",
                            "collaboration_framework.module",
                            "collaboration_framework.bootstrap",
                        )
                    ),
                    f"{path.name}: {imported}",
                )

    def test_host_does_not_import_engine_or_module(self) -> None:
        for path in (PACKAGE / "host").rglob("*.py"):
            for imported in imports_for(path):
                self.assertFalse(
                    imported.startswith(
                        (
                            "collaboration_framework.engine",
                            "collaboration_framework.module",
                        )
                    ),
                    f"{path.relative_to(PACKAGE)}: {imported}",
                )

    def test_engine_does_not_import_host(self) -> None:
        for path in (PACKAGE / "engine").rglob("*.py"):
            for imported in imports_for(path):
                self.assertFalse(
                    imported.startswith("collaboration_framework.host"),
                    f"{path.relative_to(PACKAGE)}: {imported}",
                )

    def test_core_has_no_model_or_langgraph_dependency(self) -> None:
        forbidden = ("pydantic_ai", "openai", "langgraph")
        for path in PACKAGE.rglob("*.py"):
            text = path.read_text(encoding="utf-8").lower()
            for token in forbidden:
                self.assertNotIn(token, text, f"{token} in {path.relative_to(ROOT)}")
        project = (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
        for token in forbidden:
            self.assertNotIn(token, project)


if __name__ == "__main__":
    unittest.main()
