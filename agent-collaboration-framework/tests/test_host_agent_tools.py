from __future__ import annotations

from dataclasses import FrozenInstanceError
from io import StringIO
import json
import logging
import unittest

from collaboration_framework.contracts import (
    CheckpointOption,
    ContractModel,
    PlayerInput,
    PlayerView,
    VisibleEntity,
)
from collaboration_framework.host.application import ToolDefinition, ToolRegistry
from collaboration_framework.host.schemas import (
    GetVisibleEntityArgs,
    GetVisibleEntityResult,
    HostAgentContext,
    SearchVisibleEntitiesArgs,
    SearchVisibleEntitiesResult,
    ToolErrorResult,
)
from collaboration_framework.host.tools import build_player_view_tool_registry


SECRET = "SECRET_SENTINEL_DO_NOT_LEAK"


def make_context() -> HostAgentContext:
    return HostAgentContext(
        player_input=PlayerInput(
            room_id="room_001",
            player_id="player_001",
            actor_id="actor_001",
            client_action_id="action_001",
            utterance="检查书架",
        ),
        player_view=PlayerView(
            room_id="room_001",
            player_id="player_001",
            actor_id="actor_001",
            scene_id="library",
            phase="playing",
            revision="7",
            visible_entities=(
                VisibleEntity(
                    id="entity_b",
                    kind="object",
                    name="Ancient Shelf",
                    aliases=("Bookcase",),
                    content="Old oak furniture.",
                ),
                VisibleEntity(
                    id="entity_a",
                    kind="location",
                    name="Shelf Door",
                    content="A narrow exit.",
                ),
                VisibleEntity(
                    id="entity_c",
                    kind="object",
                    name="Locked Cabinet",
                    aliases=("Book Shelf",),
                    content="Its doors are locked.",
                ),
                VisibleEntity(
                    id="entity_d",
                    kind="npc",
                    name="Curator",
                    content="Dust from a shelf marks their coat.",
                ),
                VisibleEntity(
                    id="entity_e",
                    kind="location",
                    name="ＲＥＤ   Door",
                    content="A painted doorway.",
                ),
                VisibleEntity(
                    id="entity_f",
                    kind="object",
                    name="Reading Desk",
                    content="A plain writing desk.",
                ),
            ),
            checkpoint_options=(
                CheckpointOption(
                    id="checkpoint_z",
                    target_id="entity_b",
                    action_hint="inspect",
                    skills=("spot_hidden",),
                ),
                CheckpointOption(
                    id="checkpoint_other",
                    target_id="entity_c",
                    action_hint="open",
                    skills=("lockpick",),
                ),
                CheckpointOption(
                    id="checkpoint_a",
                    target_id="entity_b",
                    action_hint="search",
                    skills=("investigation",),
                ),
            ),
        ),
    )


def error_code(result: ContractModel) -> str:
    if not isinstance(result, ToolErrorResult):
        raise AssertionError(f"expected ToolErrorResult, got {type(result)!r}")
    return result.error.code


class ToolRegistryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.registry = build_player_view_tool_registry()
        self.bound = self.registry.bind(make_context())

    def test_definitions_are_immutable_sorted_and_read_only(self) -> None:
        self.assertEqual(
            [definition.name for definition in self.registry.definitions],
            ["get_visible_entity", "search_visible_entities"],
        )
        for definition in self.registry.definitions:
            with self.subTest(definition=definition.name):
                self.assertEqual(definition.access, "read_only")
                self.assertTrue(definition.description)
                self.assertTrue(definition.public_progress_label)
        with self.assertRaises(FrozenInstanceError):
            self.registry.definitions[0].name = "changed"  # type: ignore[misc]

    def test_bind_requires_validated_host_agent_context(self) -> None:
        with self.assertRaisesRegex(TypeError, "HostAgentContext"):
            self.registry.bind(object())  # type: ignore[arg-type]

    def test_duplicate_registration_fails(self) -> None:
        definition = self.registry.definitions[0]
        with self.assertRaisesRegex(ValueError, "duplicate tool registration"):
            ToolRegistry((definition, definition))

    async def test_unknown_tool_does_not_execute_registered_handler(self) -> None:
        calls = 0

        async def counted_handler(
            _context: HostAgentContext,
            _arguments: ContractModel,
        ) -> SearchVisibleEntitiesResult:
            nonlocal calls
            calls += 1
            return SearchVisibleEntitiesResult()

        definition = ToolDefinition(
            name="known_tool",
            description="A known read-only tool.",
            args_model=SearchVisibleEntitiesArgs,
            result_model=SearchVisibleEntitiesResult,
            public_progress_label="正在执行已知工具",
            handler=counted_handler,
        )
        result = await ToolRegistry((definition,)).bind(make_context()).ainvoke(
            "unknown_tool",
            {"query": "shelf"},
        )

        self.assertEqual(error_code(result), "TOOL_NOT_FOUND")
        self.assertEqual(calls, 0)

        non_string_result = await ToolRegistry((definition,)).bind(
            make_context()
        ).ainvoke(
            ["known_tool"],  # type: ignore[arg-type]
            {"query": "shelf"},
        )
        self.assertEqual(error_code(non_string_result), "TOOL_NOT_FOUND")
        self.assertEqual(calls, 0)

    async def test_invalid_arguments_are_rejected_before_handler(self) -> None:
        invalid_payloads = (
            {},
            {"query": ""},
            {"query": "   "},
            {"query": "shelf", "kind": "secret"},
            {"query": "shelf", "limit": 0},
            {"query": "shelf", "limit": 6},
            {"query": "shelf", "unexpected": True},
            {"query": "shelf", "room_id": "other_room"},
            {"query": "shelf", "player_id": "other_player"},
            {"query": "shelf", "actor_id": "other_actor"},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                result = await self.bound.ainvoke(
                    "search_visible_entities",
                    payload,
                )
                self.assertEqual(error_code(result), "INVALID_TOOL_ARGUMENTS")

    async def test_result_is_validated_against_declared_model(self) -> None:
        async def malformed_handler(
            _context: HostAgentContext,
            _arguments: ContractModel,
        ) -> object:
            return {
                "matches": [
                    {"id": "", "kind": "object", "name": "Invalid"}
                ]
            }

        definition = ToolDefinition(
            name="malformed_tool",
            description="Returns an invalid result for contract testing.",
            args_model=SearchVisibleEntitiesArgs,
            result_model=SearchVisibleEntitiesResult,
            public_progress_label="正在验证工具结果",
            handler=malformed_handler,
        )
        result = await ToolRegistry((definition,)).bind(make_context()).ainvoke(
            "malformed_tool",
            {"query": "shelf"},
        )

        self.assertEqual(error_code(result), "INVALID_TOOL_RESULT")

    async def test_internal_exception_is_redacted(self) -> None:
        async def failing_handler(
            _context: HostAgentContext,
            _arguments: ContractModel,
        ) -> object:
            raise RuntimeError(f"database detail: {SECRET}")

        definition = ToolDefinition(
            name="failing_tool",
            description="Fails for redaction testing.",
            args_model=SearchVisibleEntitiesArgs,
            result_model=SearchVisibleEntitiesResult,
            public_progress_label="正在验证失败脱敏",
            handler=failing_handler,
        )
        result = await ToolRegistry((definition,)).bind(make_context()).ainvoke(
            "failing_tool",
            {"query": "shelf"},
        )

        self.assertEqual(error_code(result), "TOOL_INTERNAL_ERROR")
        self.assertNotIn(SECRET, result.model_dump_json())
        self.assertNotIn("database", result.model_dump_json())

    async def test_base_exception_is_not_swallowed(self) -> None:
        class StopRun(BaseException):
            pass

        async def stopping_handler(
            _context: HostAgentContext,
            _arguments: ContractModel,
        ) -> object:
            raise StopRun()

        definition = ToolDefinition(
            name="stopping_tool",
            description="Stops the run for contract testing.",
            args_model=SearchVisibleEntitiesArgs,
            result_model=SearchVisibleEntitiesResult,
            public_progress_label="正在停止测试运行",
            handler=stopping_handler,
        )
        with self.assertRaises(StopRun):
            await ToolRegistry((definition,)).bind(make_context()).ainvoke(
                "stopping_tool",
                {"query": "shelf"},
            )

    def test_adapter_schemas_are_json_safe_and_scope_free(self) -> None:
        forbidden = {
            "room_id",
            "player_id",
            "actor_id",
            "secret",
            "sdk",
            "reasoning",
        }
        for definition in self.registry.definitions:
            with self.subTest(definition=definition.name):
                arguments_schema = definition.arguments_json_schema()
                result_schema = definition.result_json_schema()
                self.assertFalse(arguments_schema["additionalProperties"])
                self.assertFalse(result_schema["additionalProperties"])

                rendered = json.dumps(
                    {
                        "arguments": arguments_schema,
                        "result": result_schema,
                    },
                    ensure_ascii=False,
                ).lower()
                for token in forbidden:
                    self.assertNotIn(token, rendered)
                self.assertNotIn(SECRET.lower(), rendered)


class VisibleEntityToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.context = make_context()
        self.bound = build_player_view_tool_registry().bind(self.context)
        self.hidden_entity = VisibleEntity(
            id="hidden_entity",
            kind="object",
            name=SECRET,
            content=f"Hidden content: {SECRET}",
        )

    async def search(self, **arguments: object) -> SearchVisibleEntitiesResult:
        result = await self.bound.ainvoke(
            "search_visible_entities",
            arguments,
        )
        self.assertIsInstance(result, SearchVisibleEntitiesResult)
        return result

    async def test_searches_name_alias_and_content_with_stable_priority(self) -> None:
        result = await self.search(query="shelf")
        self.assertEqual(
            [match.id for match in result.matches],
            ["entity_a", "entity_b", "entity_c", "entity_d"],
        )

    async def test_search_normalizes_nfkc_case_and_whitespace(self) -> None:
        result = await self.search(query="red door")
        self.assertEqual([match.id for match in result.matches], ["entity_e"])

        full_width_result = await self.search(query="ＳＨＥＬＦ")
        self.assertEqual(
            [match.id for match in full_width_result.matches],
            ["entity_a", "entity_b", "entity_c", "entity_d"],
        )

    async def test_search_applies_kind_filter_and_limit(self) -> None:
        filtered = await self.search(query="shelf", kind="object")
        self.assertEqual(
            [match.id for match in filtered.matches],
            ["entity_b", "entity_c"],
        )

        limited = await self.search(query="shelf", limit=2)
        self.assertEqual(
            [match.id for match in limited.matches],
            ["entity_a", "entity_b"],
        )

    async def test_search_returns_each_entity_once_at_its_best_rank(self) -> None:
        result = await self.search(query="shelf")
        ids = [match.id for match in result.matches]
        self.assertEqual(ids.count("entity_c"), 1)
        self.assertLess(ids.index("entity_c"), ids.index("entity_d"))

    async def test_search_without_matches_is_successful_and_empty(self) -> None:
        result = await self.search(query="telescope")
        self.assertEqual(result.matches, ())

    async def test_search_never_reads_unbound_hidden_entities(self) -> None:
        result = await self.search(query=SECRET)
        self.assertEqual(result.matches, ())
        self.assertNotIn(SECRET, result.model_dump_json())
        self.assertEqual(self.hidden_entity.name, SECRET)

    async def test_get_returns_safe_detail_and_only_related_checkpoints(self) -> None:
        result = await self.bound.ainvoke(
            "get_visible_entity",
            {"entity_id": "entity_b"},
        )

        self.assertIsInstance(result, GetVisibleEntityResult)
        self.assertEqual(result.id, "entity_b")
        self.assertEqual(result.aliases, ("Bookcase",))
        self.assertEqual(
            [option.id for option in result.checkpoint_options],
            ["checkpoint_a", "checkpoint_z"],
        )
        self.assertNotIn("checkpoint_other", result.model_dump_json())

    async def test_get_rejects_scope_fields_and_missing_id(self) -> None:
        invalid_payloads = (
            {},
            {"entity_id": ""},
            {"entity_id": "entity_b", "room_id": "other_room"},
            {"entity_id": "entity_b", "player_id": "other_player"},
            {"entity_id": "entity_b", "actor_id": "other_actor"},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                result = await self.bound.ainvoke(
                    "get_visible_entity",
                    payload,
                )
                self.assertEqual(error_code(result), "INVALID_TOOL_ARGUMENTS")

    async def test_get_uses_one_error_for_hidden_foreign_and_missing_ids(self) -> None:
        payloads: list[dict[str, str]] = [
            {"entity_id": "hidden_entity"},
            {"entity_id": "other_player_entity"},
            {"entity_id": "does_not_exist"},
        ]
        serialized_errors: list[str] = []
        for payload in payloads:
            result = await self.bound.ainvoke("get_visible_entity", payload)
            self.assertEqual(error_code(result), "ENTITY_NOT_VISIBLE")
            serialized_errors.append(result.model_dump_json())

        self.assertEqual(len(set(serialized_errors)), 1)
        self.assertEqual(
            json.loads(serialized_errors[0]),
            {
                "error": {
                    "code": "ENTITY_NOT_VISIBLE",
                    "message": (
                        "The requested entity is not available in the "
                        "current player view."
                    ),
                }
            },
        )
        self.assertNotIn(SECRET, serialized_errors[0])

    async def test_tool_calls_do_not_log_arguments_results_or_secrets(self) -> None:
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        try:
            search_result = await self.bound.ainvoke(
                "search_visible_entities",
                {"query": SECRET},
            )
            get_result = await self.bound.ainvoke(
                "get_visible_entity",
                {"entity_id": "hidden_entity"},
            )
        finally:
            root_logger.removeHandler(handler)

        combined = (
            search_result.model_dump_json()
            + get_result.model_dump_json()
            + stream.getvalue()
        )
        self.assertNotIn(SECRET, combined)


class ToolSchemaModelTests(unittest.TestCase):
    def test_declared_models_forbid_unknown_fields(self) -> None:
        models = (
            SearchVisibleEntitiesArgs,
            SearchVisibleEntitiesResult,
            GetVisibleEntityArgs,
            GetVisibleEntityResult,
        )
        for model in models:
            with self.subTest(model=model.__name__):
                self.assertEqual(model.model_config["extra"], "forbid")


if __name__ == "__main__":
    unittest.main()
