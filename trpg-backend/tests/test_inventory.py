"""Issue #212 §9 inventory draft, projection, idempotency and custody CAS."""

from collaboration_framework.contracts import (
    ChangeItemCustodyRequest,
    ConfirmInventoryImportDraftRequest,
    CreateInventoryImportDraftRequest,
    ItemClaim,
    ItemComponent,
    ItemCustody,
    ItemDisplay,
    ItemInstance,
    ItemKnowledge,
)
from collaboration_framework.engine import GameState
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.engine import GameEvent, GameSession
from app.service import inventory as inventory_service
from tests.test_engine_runtime import _start_room


async def test_inventory_http_draft_and_confirm_routes(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    room, players, _ = await _start_room(db_session, room_number=90, prepare_checkpoint=False)
    session = await db_session.get(GameSession, room.id)
    assert session is not None
    headers = {"X-Reconnect-Token": players[0].reconnect_token}
    draft_response = await client.post(
        f"/api/v1/rooms/{room.id}/inventory-import-drafts",
        headers=headers,
        json={
            "request_id": "http-draft",
            "source_revision": str(session.state_version),
            "character_revision": "sheet-1",
            "claims": [{"claim_id": "rope", "raw_name": "绳索"}],
        },
    )
    assert draft_response.status_code == 200, draft_response.text
    draft = draft_response.json()["data"]

    confirm_response = await client.post(
        f"/api/v1/rooms/{room.id}/inventory-import-drafts/{draft['draft_id']}/confirm",
        headers=headers,
        json={
            "request_id": "http-confirm",
            "source_revision": draft["source_revision"],
            "draft_version": draft["version"],
        },
    )
    assert confirm_response.status_code == 200, confirm_response.text
    view_response = await client.get(f"/api/v1/rooms/{room.id}/inventory", headers=headers)
    assert view_response.status_code == 200, view_response.text
    # 开局就带着角色卡上的装备（手电筒），确认导入的绳索追加在后面。
    assert "绳索" in [item["name"] for item in view_response.json()["data"]["inventory"]]


async def test_import_draft_is_reviewed_then_confirmed_idempotently(
    db_session: AsyncSession,
) -> None:
    room, players, _ = await _start_room(db_session, room_number=91, prepare_checkpoint=False)
    session = await db_session.get(GameSession, room.id)
    assert session is not None
    request = CreateInventoryImportDraftRequest(
        request_id="draft-request",
        source_revision=str(session.state_version),
        character_revision="character-v7",
        claims=(
            ItemClaim(claim_id="lamp", raw_name="手电筒"),
            ItemClaim(
                claim_id="weapon",
                raw_name="古董手枪",
                declared_properties=("自动命中",),
            ),
            ItemClaim(claim_id="none", raw_name="空盒", declared_quantity=0),
        ),
    )

    draft = await inventory_service.create_import_draft(
        db_session, room_id=room.id, player=players[0], request=request
    )

    assert [entry.decision for entry in draft.entries] == [
        "accepted",
        "normalized",
        "rejected",
    ]
    assert draft.entries[1].normalized_definition is not None
    assert draft.entries[1].normalized_definition.item_component.capabilities == ()
    confirm = ConfirmInventoryImportDraftRequest(
        request_id="confirm-request",
        source_revision=draft.source_revision,
        draft_version=draft.version,
    )
    result = await inventory_service.confirm_import_draft(
        db_session,
        room_id=room.id,
        draft_id=draft.draft_id,
        player=players[0],
        request=confirm,
    )
    replay = await inventory_service.confirm_import_draft(
        db_session,
        room_id=room.id,
        draft_id=draft.draft_id,
        player=players[0],
        request=confirm,
    )
    view = await inventory_service.inventory_view(db_session, room_id=room.id, player=players[0])

    assert replay == result
    assert len(result.created_item_ids) == 2
    assert {item.name for item in view.inventory} == {"手电筒", "古董手枪"}
    events = list(
        await db_session.scalars(
            select(GameEvent).where(
                GameEvent.room_id == room.id,
                GameEvent.type == "item.created",
            )
        )
    )
    assert len(events) == 2


async def test_second_pickup_loses_with_item_already_taken(
    db_session: AsyncSession,
) -> None:
    room, players, _ = await _start_room(
        db_session,
        room_number=92,
        player_count=2,
        prepare_checkpoint=False,
    )
    session = await db_session.get(GameSession, room.id)
    assert session is not None
    state = GameState.model_validate(session.state_json)
    actor_ids = {actor.player_id: actor_id for actor_id, actor in state.actors.items()}
    item = ItemInstance(
        id="loose_lamp",
        room_id=room.id,
        origin="runtime",
        definition_id="lamp",
        display=ItemDisplay(name="地上的提灯"),
        item_component=ItemComponent(),
        custody=ItemCustody(kind="location", ref_id=state.scene_id, form="loose"),
        version=1,
        created_event_id="seed-item",
        last_event_id="seed-item",
        updated_revision=str(session.state_version),
    )
    state.item_instances[item.id] = item
    state.party_item_knowledge[item.id] = ItemKnowledge(item_id=item.id, identity="known")
    session.state_json = state.to_json_dict()
    await db_session.commit()

    original_revision = str(session.state_version)
    winner_actor = actor_ids[players[0].id]
    loser_actor = actor_ids[players[1].id]
    await inventory_service.change_custody(
        db_session,
        room_id=room.id,
        item_id=item.id,
        player=players[0],
        request=ChangeItemCustodyRequest(
            request_id="pickup-winner",
            source_revision=original_revision,
            actor_id=winner_actor,
            expected_version=1,
            reason="pickup",
            to_custody=ItemCustody(kind="actor_inventory", ref_id=winner_actor, form="carried"),
        ),
    )

    try:
        await inventory_service.change_custody(
            db_session,
            room_id=room.id,
            item_id=item.id,
            player=players[1],
            request=ChangeItemCustodyRequest(
                request_id="pickup-loser",
                source_revision=original_revision,
                actor_id=loser_actor,
                expected_version=1,
                reason="pickup",
                to_custody=ItemCustody(kind="actor_inventory", ref_id=loser_actor, form="carried"),
            ),
        )
    except inventory_service.ItemAlreadyTakenError:
        pass
    else:
        raise AssertionError("second pickup must report item_already_taken")

    winner_view = await inventory_service.inventory_view(
        db_session, room_id=room.id, player=players[0]
    )
    loser_view = await inventory_service.inventory_view(
        db_session, room_id=room.id, player=players[1]
    )
    # 角色卡装备现在开局就在背包里，所以这里断言「抢到的那件归赢家、输家没有」，
    # 而不是断言整个背包只有这一件。
    assert item.id in {entry.id for entry in winner_view.inventory}
    assert item.id not in {entry.id for entry in loser_view.inventory}
