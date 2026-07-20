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

    def test_current_documentation_has_three_authoritative_design_files(self) -> None:
        docs = ROOT / "docs"
        current = sorted(path.name for path in docs.glob("*.md"))
        self.assertEqual(
            current,
            ["agent编排技术选型.md", "architecture.md", "数据模型设计.md"],
        )

        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("docs/architecture.md", readme)
        self.assertIn("docs/数据模型设计.md", readme)
        self.assertIn("docs/agent编排技术选型.md", readme)

        archive_index = (docs / "archive" / "README.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("不是当前实现依据", archive_index)
        self.assertIn("../数据模型设计.md", archive_index)

    def test_data_model_document_covers_current_model_fields(self) -> None:
        from collaboration_framework.contracts import (
            ActionRequest,
            ActionResult,
            AllowOperationSpec,
            CheckpointOutcomeSpec,
            CheckpointOutcomesSpec,
            CheckpointSpec,
            ConditionSpec,
            EntitySpec,
            Intent,
            ModifyOperationSpec,
            ModuleContent,
            PlayerInput,
            PlayerView,
            ProjectionSnapshot,
            RuleSpec,
            SceneSpec,
            WinConditionSpec,
        )
        from collaboration_framework.engine.models import (
            ActorState,
            EngineExecutionResult,
            GameState,
            StateChange,
            StateModifiedEvent,
            StateModifiedPayload,
        )
        from collaboration_framework.host.schemas import (
            IntentContext,
            NarrationContext,
            NarrationOutput,
            PlayerTurnPayload,
            TurnOutput,
            TurnState,
            WebSocketOutput,
        )

        models = (
            PlayerInput,
            ProjectionSnapshot,
            PlayerView,
            Intent,
            ActionRequest,
            ActionResult,
            IntentContext,
            NarrationContext,
            NarrationOutput,
            PlayerTurnPayload,
            WebSocketOutput,
            TurnOutput,
            TurnState,
            ActorState,
            GameState,
            StateChange,
            StateModifiedPayload,
            StateModifiedEvent,
            EngineExecutionResult,
            ConditionSpec,
            AllowOperationSpec,
            ModifyOperationSpec,
            RuleSpec,
            SceneSpec,
            EntitySpec,
            CheckpointOutcomeSpec,
            CheckpointOutcomesSpec,
            CheckpointSpec,
            WinConditionSpec,
            ModuleContent,
        )
        document = (ROOT / "docs" / "数据模型设计.md").read_text(
            encoding="utf-8"
        )
        for model in models:
            with self.subTest(model=model.__name__):
                self.assertIn(model.__name__, document)
                for field_name in model.model_fields:
                    self.assertIn(field_name, document)


if __name__ == "__main__":
    unittest.main()
