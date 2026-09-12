"""Narration retrieves memories for NPCs visible after authoritative travel."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from collaboration_framework.contracts import ModuleContentV3
from collaboration_framework.engine import (
    ActorState,
    AdjudicationEngineService,
    InMemoryEngineStore,
    RuleEngineService,
)
from collaboration_framework.engine.initialization import create_initial_game_state
from collaboration_framework.host.schemas import ActionPlanStepContext, ConversationSummary
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.action_plan_turn import build_action_plan_turn_application
from app.core.config import Settings
from app.models.event import Event
from app.models.memory import ConversationSummaryRecord
from app.models.room import Player
from tests.test_accompanying_host import FIXTURE, travel
from tests.test_memory_system import _create_memory_room


@pytest.mark.parametrize("accompanying", [True, False])
async def test_narration_reads_cross_scene_memories_for_post_travel_npcs(
    db_session: AsyncSession, memory_store, accompanying: bool
):
    room, player, actor_id = await _create_memory_room(db_session, 516)
    content = ModuleContentV3.model_validate_json(FIXTURE.read_text())
    state = create_initial_game_state(
        content,
        room_id=room.id,
        actors={
            actor_id: ActorState(
                player_id=player.id,
                name="调查员",
                source_character_id="character",
                source_character_version=1,
                state={"skills": {}, "attributes": {"STR": 50}},
            )
        },
    ).model_copy(update={"scene_id": "resort_reception"}, deep=True)
    state.entities["emily"]["accompanying"] = accompanying
    store = InMemoryEngineStore()
    store.register_room(module_content=content, initial_state=state)
    rules = RuleEngineService(store)
    object_id = next(
        entity.id
        for entity in content.entities
        if entity.located_in == "lane_manor" and entity.kind == "object"
    )
    invitation = "跟我一起走，去见詹姆斯父母。"
    agreement = "好，我跟你走，去找莱恩先生和太太。"
    destination_npc_memory = "莱恩夫人曾请你到庄园告知调查结果。"
    unrelated_memory = "詹姆斯独自留在接待大厅。"
    object_memory = "曾在度假村讨论过这份传单。"
    start = datetime(2026, 9, 8, tzinfo=UTC)
    for index, (speaker, event_type, payload) in enumerate(
        [
            (actor_id, "dialogue.player", {"utterance": invitation, "listenerIds": ["emily"]}),
            ("emily", "dialogue.npc", {"text": agreement}),
            ("mrs_lane", "dialogue.npc", {"text": destination_npc_memory}),
            ("james", "dialogue.npc", {"text": unrelated_memory}),
            (object_id, "narration.push", {"text": object_memory}),
        ]
    ):
        db_session.add(
            Event(
                room_id=room.id,
                player_id=player.id,
                actor_id=speaker,
                event_type=event_type,
                visibility="public",
                scene_id="resort_reception",
                payload=payload,
                created_at=start + timedelta(seconds=index),
            )
        )
    other_player = Player(id=str(uuid.uuid4()), room_id=room.id, nickname="其他玩家")
    keeper_only_memory = "其他玩家私下说过的审计口令。"
    db_session.add_all(
        [
            other_player,
            Event(
                room_id=room.id,
                player_id=other_player.id,
                actor_id="mrs_lane",
                event_type="dialogue.npc",
                visibility="player_scoped",
                scene_id="resort_reception",
                view_revision="0",
                payload={"text": keeper_only_memory},
                created_at=start,
            ),
            ConversationSummaryRecord(
                room_id=room.id,
                player_id=player.id,
                summary_json=ConversationSummary(
                    room_id=room.id,
                    player_id=player.id,
                    summary="已经谈过一同前往庄园。",
                    source_revision="0",
                ).model_dump(mode="json"),
            ),
        ]
    )
    await db_session.commit()

    class Client:
        def __init__(self):
            self.calls = []
            self.narration_input = None
            self.step_input = None
            self.plan_input = None

        async def generate(self, *, schema_name, schema, instructions, input_payload):
            self.calls.append(schema_name)
            if schema_name == "trpg_turn_plan":
                self.plan_input = input_payload
                return {
                    "kind": "action_plan",
                    "goal": "前往莱恩庄园",
                    "steps": [{"kind": "travel", "semantic_goal": "前往莱恩庄园"}],
                }
            if schema_name == "trpg_action_plan_step_adjudication":
                self.step_input = input_payload
                return travel(
                    ActionPlanStepContext.model_validate(input_payload), "lane_manor"
                ).to_json_dict()
            assert schema_name == "trpg_action_plan_narration"
            self.narration_input = input_payload
            return {
                "kind": "narration",
                "text": "你抵达莱恩庄园，在会客厅站定。",
                "claimed_evidence_refs": [],
                "suggested_actions": [],
            }

    client = Client()
    application = build_action_plan_turn_application(
        store=store,
        engine=rules,
        adjudication_engine=AdjudicationEngineService(store),
        settings=Settings(host_model_provider="deepseek", deepseek_api_key="offline-test"),
        client=client,
        planner_client=client,
        memory_source=memory_store,
    )
    result = await application.start(
        room_id=room.id,
        player_id=player.id,
        client_action_id="travel-with-memory",
        utterance="去莱恩庄园",
    )
    assert result.status in {"awaiting_narration", "completed"}
    assert store.inspect_state(room.id).scene_id == "lane_manor"
    assert client.narration_input is not None
    view = client.narration_input["player_view"]
    assert view["scene"]["id"] == "lane_manor"
    visible = {npc["id"] for npc in view["scene"]["visible_entities"] if npc["kind"] == "npc"}
    assert ("emily" in visible) == accompanying
    assert "mrs_lane" in visible
    memories = [entry["content"] for entry in client.narration_input["memories"]]
    assert (agreement in memories) == accompanying
    assert any(invitation in text for text in memories) == accompanying
    assert destination_npc_memory in memories
    assert unrelated_memory not in memories
    assert object_memory not in memories
    assert client.calls == [
        "trpg_turn_plan",
        "trpg_action_plan_step_adjudication",
        "trpg_action_plan_narration",
    ]

    assert client.step_input is not None and client.plan_input is not None
    assert client.step_input["memories"]
    assert client.step_input["conversation_summary"]["summary"] == "已经谈过一同前往庄园。"
    assert any(entry["content"] == keeper_only_memory for entry in client.step_input["memories"])
    for payload in (client.plan_input, client.narration_input):
        assert all(entry["content"] != keeper_only_memory for entry in payload["memories"])
