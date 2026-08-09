"""Authoritative room inventory import and custody transitions (#212 §9)."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

from collaboration_framework.contracts import (
    ChangeItemCustodyRequest,
    ChangeItemCustodyResult,
    ConfirmInventoryImportDraftRequest,
    ConfirmInventoryImportResult,
    CreateInventoryImportDraftRequest,
    InventoryImportDraft,
    InventoryImportEntry,
    InventoryView,
    ItemAcquisition,
    ItemComponent,
    ItemDefinition,
    ItemDisplay,
    ItemInstance,
    ItemKnowledge,
    ModuleContentV3,
)
from collaboration_framework.engine import GameState
from collaboration_framework.engine.projection_v3 import project_inventory_items
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.engine import (
    GameEvent,
    GameSession,
    InventoryCommandExecution,
    InventoryImportDraftRecord,
    ModuleVersion,
)
from app.models.room import Player


class InventoryError(RuntimeError):
    pass


class InventoryNotFoundError(InventoryError):
    pass


class InventoryConflictError(InventoryError):
    pass


class InventoryRevisionConflictError(InventoryConflictError):
    pass


class ItemAlreadyTakenError(InventoryConflictError):
    pass


class ItemVersionConflictError(InventoryConflictError):
    pass


def _actor_for_player(state: GameState, player: Player) -> str:
    actor_id = next(
        (actor_id for actor_id, actor in state.actors.items() if actor.player_id == player.id),
        None,
    )
    if actor_id is None:
        raise InventoryConflictError("当前玩家没有局内角色")
    return actor_id


async def _runtime(
    db: AsyncSession, room_id: str
) -> tuple[GameSession, GameState, ModuleContentV3]:
    session = await db.get(GameSession, room_id)
    if session is None:
        raise InventoryNotFoundError("房间运行时不存在")
    # AsyncSession may be reused by service-level callers with expire_on_commit=False.
    # Refresh so custody/version races are decided from the committed authority.
    await db.refresh(session)
    state = GameState.model_validate(deepcopy(session.state_json))
    version = await db.get(ModuleVersion, (session.module_id, session.module_version))
    if version is None or version.content_schema_version != 3:
        raise InventoryConflictError("背包运行时只支持 ModuleContent v3 房间")
    return session, state, ModuleContentV3.model_validate(deepcopy(version.content_json))


def _normalized_definition(claim) -> ItemDefinition:
    return ItemDefinition(
        definition_id=f"import:{claim.claim_id}",
        display=ItemDisplay(name=claim.raw_name.strip()),
        item_component=ItemComponent(quantity=max(claim.declared_quantity, 1)),
    )


def _review_claims(
    request: CreateInventoryImportDraftRequest,
    module: ModuleContentV3,
) -> tuple[InventoryImportEntry, ...]:
    reserved = {
        text.strip().casefold()
        for entity in module.entities
        for text in (entity.id, entity.name, entity.player_visible_name)
        if text.strip()
    }
    entries: list[InventoryImportEntry] = []
    seen_claims: set[str] = set()
    for claim in request.claims:
        if claim.claim_id in seen_claims:
            raise InventoryConflictError(f"重复的 claim_id: {claim.claim_id}")
        seen_claims.add(claim.claim_id)
        if claim.declared_quantity < 1:
            entries.append(
                InventoryImportEntry(
                    claim_id=claim.claim_id,
                    decision="rejected",
                    reason_code="invalid_quantity",
                    narrative_policy="not_brought",
                )
            )
        elif claim.raw_name.strip().casefold() in reserved:
            entries.append(
                InventoryImportEntry(
                    claim_id=claim.claim_id,
                    decision="rejected",
                    reason_code="reserved_canon_identity",
                    narrative_policy="not_brought",
                )
            )
        elif claim.declared_properties:
            # Free-form properties are never promoted into executable capability.
            entries.append(
                InventoryImportEntry(
                    claim_id=claim.claim_id,
                    decision="normalized",
                    reason_code="restricted_by_setting",
                    normalized_definition=_normalized_definition(claim),
                    narrative_policy="adjusted",
                )
            )
        else:
            entries.append(
                InventoryImportEntry(
                    claim_id=claim.claim_id,
                    decision="accepted",
                    normalized_definition=_normalized_definition(claim),
                    narrative_policy="brought",
                )
            )
    return tuple(entries)


async def create_import_draft(
    db: AsyncSession,
    *,
    room_id: str,
    player: Player,
    request: CreateInventoryImportDraftRequest,
) -> InventoryImportDraft:
    existing = await db.scalar(
        select(InventoryImportDraftRecord).where(
            InventoryImportDraftRecord.room_id == room_id,
            InventoryImportDraftRecord.request_id == request.request_id,
        )
    )
    if existing is not None:
        draft = InventoryImportDraft.model_validate(deepcopy(existing.draft_json))
        if existing.player_id != player.id or existing.request_json != request.to_json_dict():
            raise InventoryConflictError("request_id 已被不同的导入请求使用")
        return draft

    session, state, module = await _runtime(db, room_id)
    if request.source_revision != str(session.state_version):
        raise InventoryRevisionConflictError("背包导入草稿基于过期的房间 revision")
    actor_id = _actor_for_player(state, player)
    draft = InventoryImportDraft(
        draft_id=uuid4().hex,
        request_id=request.request_id,
        room_id=room_id,
        player_id=player.id,
        actor_id=actor_id,
        source_revision=request.source_revision,
        character_revision=request.character_revision,
        entries=_review_claims(request, module),
    )
    db.add(
        InventoryImportDraftRecord(
            room_id=room_id,
            draft_id=draft.draft_id,
            request_id=request.request_id,
            player_id=player.id,
            actor_id=actor_id,
            version=1,
            confirmed=False,
            request_json=request.to_json_dict(),
            draft_json=draft.to_json_dict(),
        )
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise InventoryConflictError("导入草稿请求发生竞争，请重试") from exc
    return draft


async def confirm_import_draft(
    db: AsyncSession,
    *,
    room_id: str,
    draft_id: str,
    player: Player,
    request: ConfirmInventoryImportDraftRequest,
) -> ConfirmInventoryImportResult:
    record = await db.get(InventoryImportDraftRecord, (room_id, draft_id))
    if record is None or record.player_id != player.id:
        raise InventoryNotFoundError("背包导入草稿不存在")
    command_json = {
        "draft_id": draft_id,
        "player_id": player.id,
        "command": request.to_json_dict(),
    }
    replay = await db.get(InventoryCommandExecution, (room_id, request.request_id))
    if replay is not None:
        if replay.kind != "confirm_import" or replay.request_json != command_json:
            raise InventoryConflictError("request_id 已被不同的背包命令使用")
        return ConfirmInventoryImportResult.model_validate(deepcopy(replay.result_json))
    draft = InventoryImportDraft.model_validate(deepcopy(record.draft_json))
    if record.confirmed or draft.confirmed:
        raise InventoryConflictError("背包导入草稿已经确认")
    if request.draft_version != record.version:
        raise ItemVersionConflictError("背包导入草稿 version 已变化")

    session, state, _ = await _runtime(db, room_id)
    if request.source_revision != str(session.state_version) or draft.source_revision != str(
        session.state_version
    ):
        raise InventoryRevisionConflictError("确认导入时房间 revision 已变化")
    if _actor_for_player(state, player) != draft.actor_id:
        raise InventoryConflictError("导入草稿角色作用域不匹配")

    entries = [entry for entry in draft.entries if entry.normalized_definition is not None]
    final_revision = session.state_version + len(entries)
    created_ids: list[str] = []
    events: list[GameEvent] = []
    for offset, entry in enumerate(entries, start=1):
        definition = entry.normalized_definition
        assert definition is not None
        item_id = f"item_{uuid4().hex}"
        event_id = f"item-created-{uuid4().hex}"
        revision = session.state_version + offset
        item = ItemInstance(
            id=item_id,
            room_id=room_id,
            origin="runtime",
            definition_id=definition.definition_id,
            display=definition.display,
            item_component=definition.item_component,
            custody={
                "kind": "actor_inventory",
                "ref_id": draft.actor_id,
                "form": "carried",
            },
            acquisition=ItemAcquisition(
                source_type="character_import",
                source_id=draft.character_revision,
                player_safe_label="角色卡带入",
                event_id=event_id,
                revision=str(revision),
            ),
            version=1,
            created_event_id=event_id,
            last_event_id=event_id,
            updated_revision=str(final_revision),
        )
        state.item_instances[item_id] = item
        state.actor_item_knowledge.setdefault(draft.actor_id, {})[item_id] = ItemKnowledge(
            item_id=item_id, scope="actor", identity="known"
        )
        created_ids.append(item_id)
        events.append(
            GameEvent(
                room_id=room_id,
                sequence=revision,
                event_id=event_id,
                client_action_id=request.request_id,
                type="item.created",
                actor_id=draft.actor_id,
                visibility="private",
                cause="inventory_import_confirmed",
                payload={"item_id": item_id, "claim_id": entry.claim_id},
            )
        )
    state = state.model_copy(update={"event_sequence": final_revision})
    result = ConfirmInventoryImportResult(
        request_id=request.request_id,
        draft_id=draft_id,
        created_item_ids=tuple(created_ids),
        revision=str(final_revision),
    )
    changed = await db.execute(
        update(GameSession)
        .where(
            GameSession.room_id == room_id,
            GameSession.state_version == session.state_version,
        )
        .values(
            state_json=state.to_json_dict(),
            state_version=final_revision,
            updated_at=datetime.now(UTC),
        )
        .execution_options(synchronize_session=False)
    )
    if getattr(changed, "rowcount", None) != 1:
        await db.rollback()
        raise InventoryRevisionConflictError("确认导入时房间发生并发更新")
    db.add_all(events)
    confirmed = draft.model_copy(update={"confirmed": True, "version": draft.version + 1})
    record.version = confirmed.version
    record.confirmed = True
    record.draft_json = confirmed.to_json_dict()
    db.add(
        InventoryCommandExecution(
            room_id=room_id,
            request_id=request.request_id,
            kind="confirm_import",
            request_json=command_json,
            result_json=result.to_json_dict(),
            committed_state_version=final_revision,
        )
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise InventoryConflictError("导入确认发生竞争，请重试") from exc
    return result


async def change_custody(
    db: AsyncSession,
    *,
    room_id: str,
    item_id: str,
    player: Player,
    request: ChangeItemCustodyRequest,
) -> ChangeItemCustodyResult:
    session, state, _ = await _runtime(db, room_id)
    actor_id = _actor_for_player(state, player)
    if request.actor_id != actor_id:
        raise InventoryConflictError("不能以其他角色身份移动物品")
    command_json = {
        "item_id": item_id,
        "player_id": player.id,
        "command": request.to_json_dict(),
    }
    replay = await db.get(InventoryCommandExecution, (room_id, request.request_id))
    if replay is not None:
        if replay.kind != "change_custody" or replay.request_json != command_json:
            raise InventoryConflictError("request_id 已被不同的背包命令使用")
        return ChangeItemCustodyResult.model_validate(deepcopy(replay.result_json))
    item = state.item_instances.get(item_id)
    if item is None or item.state.status != "active":
        raise InventoryNotFoundError("物品不存在")
    if item.version != request.expected_version:
        if request.reason == "pickup" and not (
            item.custody.kind == "location" and item.custody.ref_id == state.scene_id
        ):
            raise ItemAlreadyTakenError("物品已被其他角色拿走")
        raise ItemVersionConflictError("物品 version 已变化")
    if request.reason == "pickup":
        if not (item.custody.kind == "location" and item.custody.ref_id == state.scene_id):
            raise ItemAlreadyTakenError("物品已被其他角色拿走")
        if not item.item_component.portable:
            raise InventoryConflictError("该物品不可携带")
        if request.to_custody.kind != "actor_inventory" or request.to_custody.ref_id != actor_id:
            raise InventoryConflictError("拾取物品只能进入自己的背包")
    else:
        if item.custody.kind != "actor_inventory" or item.custody.ref_id != actor_id:
            raise InventoryConflictError("只有物品持有者可以移动它")
        if request.reason in {"drop", "throw", "place"} and (
            request.to_custody.kind != "location" or request.to_custody.ref_id != state.scene_id
        ):
            raise InventoryConflictError("放下物品的地点必须是当前位置")
        if request.reason == "transfer" and (
            request.to_custody.kind != "actor_inventory"
            or request.to_custody.ref_id not in state.actors
        ):
            raise InventoryConflictError("转交目标角色不存在")
    if request.source_revision != str(session.state_version):
        raise InventoryRevisionConflictError("物品命令基于过期的房间 revision")

    new_revision = session.state_version + 1
    event_id = f"item-custody-{uuid4().hex}"
    updated_item = item.model_copy(
        update={
            "custody": request.to_custody,
            "version": item.version + 1,
            "last_event_id": event_id,
            "updated_revision": str(new_revision),
        }
    )
    state.item_instances[item_id] = updated_item
    state = state.model_copy(update={"event_sequence": new_revision})
    result = ChangeItemCustodyResult(
        request_id=request.request_id,
        item=updated_item,
        revision=str(new_revision),
        event_id=event_id,
    )
    changed = await db.execute(
        update(GameSession)
        .where(
            GameSession.room_id == room_id,
            GameSession.state_version == session.state_version,
        )
        .values(
            state_json=state.to_json_dict(),
            state_version=new_revision,
            updated_at=datetime.now(UTC),
        )
        .execution_options(synchronize_session=False)
    )
    if getattr(changed, "rowcount", None) != 1:
        await db.rollback()
        raise InventoryRevisionConflictError("物品命令发生并发更新")
    db.add(
        GameEvent(
            room_id=room_id,
            sequence=new_revision,
            event_id=event_id,
            client_action_id=request.request_id,
            type="item.custody_changed",
            actor_id=actor_id,
            visibility="public",
            cause=request.reason,
            payload={
                "item_id": item_id,
                "from": item.custody.to_json_dict(),
                "to": request.to_custody.to_json_dict(),
                "item_version": updated_item.version,
            },
        )
    )
    db.add(
        InventoryCommandExecution(
            room_id=room_id,
            request_id=request.request_id,
            kind="change_custody",
            request_json=command_json,
            result_json=result.to_json_dict(),
            committed_state_version=new_revision,
        )
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise InventoryConflictError("物品命令发生竞争，请刷新后重试") from exc
    return result


async def inventory_view(
    db: AsyncSession,
    *,
    room_id: str,
    player: Player,
) -> InventoryView:
    _, state, _ = await _runtime(db, room_id)
    actor_id = _actor_for_player(state, player)
    inventory, loose = project_inventory_items(state, actor_id=actor_id, location_id=state.scene_id)
    return InventoryView(inventory=inventory, loose_items=loose)
