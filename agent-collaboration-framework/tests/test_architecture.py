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

    def test_host_agent_port_is_host_private_and_sdk_independent(self) -> None:
        from collaboration_framework.host.ports import HostAgentPort

        self.assertFalse((PACKAGE / "ports" / "host_agent.py").exists())
        self.assertTrue((PACKAGE / "host" / "ports" / "host_agent.py").is_file())
        self.assertEqual(
            {
                name
                for name in HostAgentPort.__dict__
                if not name.startswith("_")
            },
            {"astream"},
        )

        stable_host_agent_files = (
            PACKAGE / "host" / "schemas" / "agent.py",
            PACKAGE / "host" / "ports" / "host_agent.py",
        )
        forbidden_prefixes = (
            "agents",
            "openai",
            "collaboration_framework.engine",
            "collaboration_framework.module",
            "collaboration_framework.ports",
        )
        for path in stable_host_agent_files:
            for imported in imports_for(path):
                self.assertFalse(
                    imported.startswith(forbidden_prefixes),
                    f"{path.relative_to(PACKAGE)}: {imported}",
                )

    def test_host_agent_tools_are_read_only_and_authority_independent(self) -> None:
        from collaboration_framework.host.tools import (
            build_player_view_tool_registry,
        )

        tool_paths = (
            PACKAGE / "host" / "application" / "tool_registry.py",
            PACKAGE / "host" / "schemas" / "tools.py",
            PACKAGE / "host" / "tools" / "visible_entities.py",
        )
        forbidden_prefixes = (
            "agents",
            "openai",
            "collaboration_framework.engine",
            "collaboration_framework.module",
            "collaboration_framework.ports",
        )
        for path in tool_paths:
            self.assertTrue(path.is_file(), path)
            for imported in imports_for(path):
                self.assertFalse(
                    imported.startswith(forbidden_prefixes),
                    f"{path.relative_to(PACKAGE)}: {imported}",
                )

        definitions = build_player_view_tool_registry().definitions
        self.assertEqual(
            {definition.name for definition in definitions},
            {"search_visible_entities", "get_visible_entity"},
        )
        self.assertTrue(
            all(definition.access == "read_only" for definition in definitions)
        )

    def test_engine_does_not_import_host(self) -> None:
        for path in (PACKAGE / "engine").rglob("*.py"):
            for imported in imports_for(path):
                self.assertFalse(
                    imported.startswith("collaboration_framework.host"),
                    f"{path.relative_to(PACKAGE)}: {imported}",
                )

    def test_provider_sdks_are_isolated_to_adapter_and_bootstrap(self) -> None:
        adapter_root = (
            PACKAGE / "host" / "adapters" / "openai_agents"
        )
        bootstrap_file = PACKAGE / "bootstrap" / "host_agent.py"
        provider_prefixes = ("agents", "openai")

        for path in PACKAGE.rglob("*.py"):
            provider_imports = {
                imported
                for imported in imports_for(path)
                if imported.startswith(provider_prefixes)
            }
            if not provider_imports:
                continue
            self.assertTrue(
                path.is_relative_to(adapter_root) or path == bootstrap_file,
                (
                    f"provider SDK import outside private adapter/bootstrap: "
                    f"{path.relative_to(ROOT)}: {sorted(provider_imports)}"
                ),
            )

        project = (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
        self.assertIn('"openai==2.44.0"', project)
        self.assertIn('"openai-agents==0.8.4"', project)

    def test_pydantic_ai_and_langgraph_remain_globally_forbidden(self) -> None:
        forbidden = ("pydantic_ai", "langgraph")
        for path in PACKAGE.rglob("*.py"):
            for imported in imports_for(path):
                self.assertFalse(
                    imported.startswith(forbidden),
                    f"{path.relative_to(PACKAGE)}: {imported}",
                )
        project = (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
        for token in forbidden:
            self.assertNotIn(token, project)

    def test_current_documentation_has_two_authoritative_design_files(self) -> None:
        docs = ROOT / "docs"
        current = sorted(path.name for path in docs.glob("*.md"))
        self.assertEqual(current, ["architecture.md", "数据模型设计.md"])

        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("docs/architecture.md", readme)
        self.assertIn("docs/数据模型设计.md", readme)

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
            CompletedAction,
            EngineExecutionResult,
            EngineRuntimeSnapshot,
            GameState,
            StateChange,
            StateModifiedEvent,
            StateModifiedPayload,
        )
        from collaboration_framework.host.schemas import (
            GetVisibleEntityArgs,
            GetVisibleEntityResult,
            HostAgentCompleted,
            HostAgentContext,
            HostAgentFailed,
            HostAgentToolCompleted,
            HostAgentToolStarted,
            HostAgentUsage,
            IntentContext,
            NarrationContext,
            NarrationOutput,
            PlayerTurnPayload,
            SearchVisibleEntitiesArgs,
            SearchVisibleEntitiesResult,
            ToolError,
            ToolErrorResult,
            TurnOutput,
            TurnState,
            VisibleEntitySummary,
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
            HostAgentContext,
            HostAgentUsage,
            HostAgentToolStarted,
            HostAgentToolCompleted,
            HostAgentCompleted,
            HostAgentFailed,
            SearchVisibleEntitiesArgs,
            VisibleEntitySummary,
            SearchVisibleEntitiesResult,
            GetVisibleEntityArgs,
            GetVisibleEntityResult,
            ToolError,
            ToolErrorResult,
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
            EngineRuntimeSnapshot,
            CompletedAction,
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
