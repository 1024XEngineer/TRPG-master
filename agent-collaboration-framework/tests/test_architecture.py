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


def runtime_imports_for(path: Path) -> set[str]:
    """`imports_for`, minus anything only imported for type annotations.

    A name imported inside `if TYPE_CHECKING:` never executes, so it creates
    no runtime dependency edge — the distinction that lets a leaf package
    annotate against a component's models without depending on it.
    """

    tree = ast.parse(path.read_text(encoding="utf-8"))
    type_checking_nodes: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        is_type_checking = (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
            isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
        )
        if is_type_checking:
            for child in ast.walk(node):
                type_checking_nodes.add(id(child))

    imports: set[str] = set()
    for node in ast.walk(tree):
        if id(node) in type_checking_nodes:
            continue
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


class ArchitectureTests(unittest.TestCase):
    def test_modular_monolith_directories_exist(self) -> None:
        for name in (
            "contracts",
            "ports",
            "host",
            "engine",
            "module",
            "bootstrap",
            "registry",
        ):
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
                            "collaboration_framework.registry",
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

    def test_obsolete_v2_host_surface_is_removed(self) -> None:
        obsolete = (
            "application/host_agent_intent_resolver.py",
            "application/intent_parser.py",
            "application/intent_aligner.py",
            "application/narrator.py",
            "application/tool_registry.py",
            "ports/host_agent.py",
            "ports/intent_model.py",
            "ports/narration_model.py",
            "ports/turn.py",
            "schemas/agent.py",
            "schemas/tools.py",
            "schemas/turn.py",
            "adapters/one_shot.py",
        )
        for relative in obsolete:
            self.assertFalse((PACKAGE / "host" / relative).exists(), relative)
        for relative in ("adapters/openai_agents", "tools"):
            self.assertFalse(any((PACKAGE / "host" / relative).glob("*.py")), relative)

    def test_active_host_contracts_have_stable_imports(self) -> None:
        from collaboration_framework.contracts import ActionPlanPolicy, Intent
        from collaboration_framework.host.application.errors import (
            TurnExecutionError,
        )
        from collaboration_framework.host.prompts.action_plan import (
            PROMPT_VERSION,
            TURN_PLANNER_PROMPT_VERSION,
            current_step_adjudication_instructions,
            host_turn_decision_instructions,
            turn_planning_instructions,
        )
        from collaboration_framework.host.schemas import HostAgentContext

        self.assertEqual(
            TurnExecutionError.__module__,
            "collaboration_framework.host.application.errors",
        )
        self.assertTrue(HostAgentContext.model_fields)
        self.assertTrue(Intent.model_fields)
        self.assertEqual(PROMPT_VERSION, "trpg-host-intent-v6")
        self.assertEqual(TURN_PLANNER_PROMPT_VERSION, "trpg-turn-planner-v2")
        planning = turn_planning_instructions(ActionPlanPolicy())
        self.assertIn("公开地点、人物、物件名称或别名", planning)
        self.assertIn("泛化成“眼前的人”", planning)
        self.assertTrue(host_turn_decision_instructions(ActionPlanPolicy()))
        self.assertTrue(current_step_adjudication_instructions())

    def test_engine_does_not_import_host(self) -> None:
        for path in (PACKAGE / "engine").rglob("*.py"):
            for imported in imports_for(path):
                self.assertFalse(
                    imported.startswith("collaboration_framework.host"),
                    f"{path.relative_to(PACKAGE)}: {imported}",
                )

    def test_registry_stays_a_leaf(self) -> None:
        """The #347 registry tables are engine-shipped lookup data, not
        orchestration.

        Both `engine` (execution time) and `module` (publish-time validation)
        read these tables, and §6 of docs/architecture.md forbids
        `module -> engine`. So the tables cannot live under `engine/`: they sit
        alongside `contracts/` as a leaf, and must not import any component
        package at runtime. An evaluator needing an engine state model imports
        it under `TYPE_CHECKING` for annotations only, which is why this check
        ignores type-checking blocks.
        """

        for path in (PACKAGE / "registry").rglob("*.py"):
            for imported in runtime_imports_for(path):
                self.assertFalse(
                    imported.startswith(
                        (
                            "collaboration_framework.host",
                            "collaboration_framework.engine",
                            "collaboration_framework.module",
                            "collaboration_framework.bootstrap",
                        )
                    ),
                    f"{path.relative_to(PACKAGE)}: {imported}",
                )

    def test_parser_draft_stays_inside_module_boundary(self) -> None:
        for directory in ("contracts", "engine", "host", "ports"):
            for path in (PACKAGE / directory).rglob("*.py"):
                self.assertNotIn(
                    "ModuleDraft",
                    path.read_text(encoding="utf-8"),
                    str(path.relative_to(PACKAGE)),
                )

        public_module_api = (PACKAGE / "module" / "__init__.py").read_text(encoding="utf-8")
        self.assertNotIn("ModuleDraft", public_module_api)

    def test_removed_provider_sdks_have_no_framework_imports_or_dependencies(
        self,
    ) -> None:
        provider_prefixes = ("agents", "openai")
        for path in PACKAGE.rglob("*.py"):
            provider_imports = {
                imported for imported in imports_for(path) if imported.startswith(provider_prefixes)
            }
            self.assertFalse(
                provider_imports,
                f"{path.relative_to(ROOT)}: {sorted(provider_imports)}",
            )

        project = (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
        self.assertNotIn('"openai', project)
        self.assertNotIn('"openai-agents', project)

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

    def test_current_documentation_keeps_only_authoritative_decisions(self) -> None:
        docs = ROOT / "docs"
        current = sorted(path.name for path in docs.glob("*.md"))
        self.assertEqual(current, ["architecture.md", "数据模型设计.md"])

        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("docs/architecture.md", readme)
        self.assertIn("docs/数据模型设计.md", readme)
        self.assertFalse((docs / "archive").exists())

        architecture_decisions = sorted(path.name for path in (docs / "architecture").glob("*.md"))
        self.assertEqual(
            architecture_decisions,
            [
                "adr-module-parser-architecture.md",
                "issue-208-action-plan.md",
                "issue-271-validation.md",
                "issue-415-time-model.md",
            ],
        )

        module_decisions = sorted(path.name for path in (docs / "module-parser").glob("*.md"))
        self.assertEqual(
            module_decisions,
            [
                "MODULECONTENT-README.md",
                "module-content-field-decisions.md",
            ],
        )

    def test_data_model_document_covers_current_model_fields(self) -> None:
        from collaboration_framework.contracts import (
            ActionRequest,
            ActionResult,
            Intent,
            ModuleContentV3,
            ModulePresentation,
            PlayerInput,
            PlayerView,
            ProjectionSnapshot,
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
            HostAgentContext,
            NarrationOutput,
        )

        models = (
            PlayerInput,
            ProjectionSnapshot,
            PlayerView,
            Intent,
            ActionRequest,
            ActionResult,
            NarrationOutput,
            HostAgentContext,
            ActorState,
            GameState,
            StateChange,
            StateModifiedPayload,
            StateModifiedEvent,
            EngineExecutionResult,
            EngineRuntimeSnapshot,
            CompletedAction,
            ModulePresentation,
            ModuleContentV3,
        )
        document = (ROOT / "docs" / "数据模型设计.md").read_text(encoding="utf-8")
        for model in models:
            with self.subTest(model=model.__name__):
                self.assertIn(model.__name__, document)
                for field_name in model.model_fields:
                    self.assertIn(field_name, document)


class WriteBoundaryTests(unittest.TestCase):
    """v3 的权威写入口必须有一个 A 可以依赖的 Protocol。

    v2 时期这个位置上是 ActionExecutor；它随 Checkpoint 运行时一起删掉之后，
    ports/ 里一度只剩读侧，看起来像"规则引擎不再执行状态修改"。写通道其实一直在
    （AdjudicationEngineService.submit → commit_adjudication），缺的只是端口声明。
    """

    def test_adjudication_engine_satisfies_the_write_port(self) -> None:
        from collaboration_framework.engine import AdjudicationEngineService
        from collaboration_framework.ports import AdjudicationExecutor

        for method in AdjudicationExecutor.__protocol_attrs__:
            self.assertTrue(
                hasattr(AdjudicationEngineService, method),
                f"具体实现缺少写入口方法: {method}",
            )


if __name__ == "__main__":
    unittest.main()
