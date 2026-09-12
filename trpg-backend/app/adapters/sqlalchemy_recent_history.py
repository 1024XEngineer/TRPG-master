"""SQLAlchemy projection of transport history into player-safe model context."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import cast

import structlog
from collaboration_framework.contracts import ActionRequest, PlayerInput, PlayerView, VisibleFact
from collaboration_framework.engine import EngineExecutionResult
from collaboration_framework.host.schemas import (
    HistoryVisibility,
    RecentHistoryBudget,
    RecentSafeResult,
    RecentTurn,
    RecentTurnContext,
    VisibleHistoryText,
)
from collaboration_framework.host.schemas.history import RecentNpcReply
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.event_text import payload_ids
from app.models.engine import ActionExecution
from app.models.event import Event, EventAudience

_CANDIDATE_LIMIT = 24
_UTTERANCE_LIMIT = 800
_NARRATION_LIMIT = 1200
_INTENT_LIMIT = 400
_RESULT_TEXT_LIMIT = 1200
logger = structlog.get_logger()


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 1:
        return "…"
    return text[: limit - 1] + "…"


def _turn_chars(turn: RecentTurn) -> int:
    return sum(
        len(text)
        for text in (
            turn.player_utterance.text,
            turn.accepted_intent_summary or "",
            turn.published_narration.text if turn.published_narration else "",
            *(reply.text.text for reply in turn.npc_replies),
            *(
                fact.text
                for fact in (
                    turn.player_safe_result.visible_facts if turn.player_safe_result else ()
                )
            ),
        )
    )


def _bounded_facts(facts: Iterable[VisibleFact]) -> tuple[VisibleFact, ...]:
    remaining = _RESULT_TEXT_LIMIT
    bounded: list[VisibleFact] = []
    for fact in facts:
        if remaining <= 0:
            break
        text = _truncate(fact.text, remaining)
        bounded.append(fact.model_copy(update={"text": text}))
        remaining -= len(text)
    return tuple(bounded)


def _select_turns(
    turns_newest_first: list[RecentTurn],
    *,
    scene_id: str,
    budget: RecentHistoryBudget,
) -> tuple[RecentTurn, ...]:
    if not turns_newest_first:
        return ()

    adjacent = turns_newest_first[0]
    selected: list[RecentTurn] = [adjacent]
    same_scene = [
        turn
        for turn in turns_newest_first[1:]
        if turn.scene_id is not None and turn.scene_id == scene_id
    ]
    other = [turn for turn in turns_newest_first[1:] if turn not in same_scene]
    for turn in (*same_scene, *other):
        if len(selected) >= budget.max_turns:
            break
        selected.append(turn)

    while sum(_turn_chars(turn) for turn in selected) > budget.max_chars:
        removable = max(
            (turn for turn in selected if turn is not adjacent),
            key=turns_newest_first.index,
            default=None,
        )
        if removable is None:
            break
        selected.remove(removable)

    # The adjacent turn must remain. If it alone exceeds the global budget, retain
    # its utterance and narration while first dropping lower-priority semantic/result
    # text and then shrinking presentation tails deterministically.
    total = sum(_turn_chars(turn) for turn in selected)
    if total > budget.max_chars:
        adjacent = adjacent.model_copy(
            update={
                "accepted_intent_summary": None,
                "player_safe_result": (
                    adjacent.player_safe_result.model_copy(update={"visible_facts": ()})
                    if adjacent.player_safe_result is not None
                    else None
                ),
            }
        )
        selected[0] = adjacent
        total = sum(_turn_chars(turn) for turn in selected)
    if total > budget.max_chars:
        overflow = total - budget.max_chars
        narration = adjacent.published_narration
        if narration is not None and len(narration.text) > 1:
            new_length = max(1, len(narration.text) - overflow)
            adjacent = adjacent.model_copy(
                update={
                    "published_narration": narration.model_copy(
                        update={"text": _truncate(narration.text, new_length)}
                    )
                }
            )
            selected[0] = adjacent
        total = sum(_turn_chars(turn) for turn in selected)
        if total > budget.max_chars and adjacent.npc_replies:
            replies = list(adjacent.npc_replies)
            while len(replies) > 1 and total > budget.max_chars:
                total -= len(replies.pop().text.text)
            if total > budget.max_chars:
                reply = replies[0]
                length = max(1, len(reply.text.text) - (total - budget.max_chars))
                replies[0] = reply.model_copy(
                    update={
                        "text": reply.text.model_copy(
                            update={"text": _truncate(reply.text.text, length)}
                        )
                    }
                )
            adjacent = adjacent.model_copy(update={"npc_replies": tuple(replies)})
            selected[0] = adjacent
            total = sum(_turn_chars(turn) for turn in selected)
        if total > budget.max_chars and len(adjacent.player_utterance.text) > 1:
            new_length = max(
                1,
                len(adjacent.player_utterance.text) - (total - budget.max_chars),
            )
            adjacent = adjacent.model_copy(
                update={
                    "player_utterance": adjacent.player_utterance.model_copy(
                        update={
                            "text": _truncate(
                                adjacent.player_utterance.text,
                                new_length,
                            )
                        }
                    )
                }
            )
            selected[0] = adjacent

    if sum(_turn_chars(turn) for turn in selected) > budget.max_chars:
        selected[0] = selected[0].model_copy(update={"published_narration": None})
    return tuple(reversed(selected))


def _viewer_condition(player_id: str):
    return or_(
        Event.visibility == "public",
        and_(Event.visibility == "player_scoped", Event.player_id == player_id),
        and_(
            Event.visibility == "scene_scoped",
            exists(
                select(EventAudience.event_id).where(
                    EventAudience.event_id == Event.id, EventAudience.player_id == player_id
                )
            ),
        ),
    )


def _action_correlation(event: Event) -> str | None:
    if event.event_type == "dialogue.player":
        explicit = event.payload.get("clientActionId") or event.payload.get("client_action_id")
        if isinstance(explicit, str) and explicit:
            return explicit
        return event.correlation_id.removesuffix(":player") if event.correlation_id else None
    return event.correlation_id


def _reply_correlation(event: Event) -> str | None:
    explicit = event.payload.get("sourceActionId") or event.payload.get("source_action_id")
    if isinstance(explicit, str) and explicit:
        return explicit
    for separator in (":followup-npc:", ":npc:"):
        if event.correlation_id and separator in event.correlation_id:
            return event.correlation_id.rsplit(separator, 1)[0]
    return None


class SqlAlchemyRecentHistorySource:
    """Read only the existing transport and execution tables."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def latest_published_narration(
        self,
        *,
        room_id: str,
        exclude_correlation_id: str,
    ) -> str | None:
        """Return the latest public narration.push already visible in this room.

        Includes opening narration, which is not an action.broadcast and therefore
        does not appear in RecentTurnContext. Do not filter by scene: a travel
        turn often recopies the previous room's weather after scene_id has already
        changed.
        """

        async with self._session_factory() as session:
            event = await session.scalar(
                select(Event)
                .where(
                    Event.room_id == room_id,
                    Event.event_type == "narration.push",
                    Event.visibility == "public",
                    or_(
                        Event.correlation_id.is_(None),
                        Event.correlation_id != exclude_correlation_id,
                    ),
                )
                .order_by(Event.created_at.desc(), Event.id.desc())
                .limit(1)
            )
        if event is None or not isinstance(event.payload, dict):
            return None
        text = event.payload.get("text")
        if not isinstance(text, str) or not text.strip():
            return None
        return text.strip()[:2000]

    async def read(
        self,
        *,
        player_input: PlayerInput,
        player_view: PlayerView,
        exclude_correlation_id: str,
        budget: RecentHistoryBudget,
    ) -> RecentTurnContext:
        async with self._session_factory() as session:
            cutoff = await session.scalar(
                select(Event).where(
                    Event.room_id == player_input.room_id,
                    Event.event_type.in_(("action.broadcast", "dialogue.player")),
                    Event.correlation_id.in_(
                        (exclude_correlation_id, f"{exclude_correlation_id}:player")
                    ),
                )
            )
            conditions = [
                Event.room_id == player_input.room_id,
                Event.event_type.in_(("action.broadcast", "dialogue.player")),
                Event.correlation_id.not_in(
                    (exclude_correlation_id, f"{exclude_correlation_id}:player")
                ),
                _viewer_condition(player_input.player_id),
            ]
            if cutoff is not None:
                conditions.append(
                    or_(
                        Event.created_at < cutoff.created_at,
                        and_(
                            Event.created_at == cutoff.created_at,
                            Event.id < cutoff.id,
                        ),
                    )
                )
            action_events = list(
                (
                    await session.scalars(
                        select(Event)
                        .where(*conditions)
                        .order_by(Event.created_at.desc(), Event.id.desc())
                        .limit(_CANDIDATE_LIMIT)
                    )
                ).all()
            )
            correlations = [
                correlation
                for event in action_events
                if (correlation := _action_correlation(event)) is not None
            ]
            related_conditions = [
                Event.room_id == player_input.room_id,
                Event.correlation_id.in_(
                    (
                        *correlations,
                        *(
                            f"{correlation}:{suffix}:{index}"
                            for correlation in correlations
                            for suffix in ("npc", "followup-npc")
                            for index in range(3)
                        ),
                    )
                ),
                Event.event_type.in_(["narration.push", "check.result", "dialogue.npc"]),
                _viewer_condition(player_input.player_id),
            ]
            execution_conditions = [
                ActionExecution.room_id == player_input.room_id,
                ActionExecution.request_id.in_(correlations),
            ]
            if cutoff is not None:
                related_conditions.append(
                    or_(
                        Event.created_at < cutoff.created_at,
                        and_(
                            Event.created_at == cutoff.created_at,
                            Event.id < cutoff.id,
                        ),
                    )
                )
                execution_conditions.append(ActionExecution.created_at < cutoff.created_at)
            related_events = (
                list(
                    (
                        await session.scalars(
                            select(Event)
                            .where(*related_conditions)
                            .order_by(Event.created_at, Event.id)
                        )
                    ).all()
                )
                if correlations
                else []
            )
            executions = (
                list(
                    (
                        await session.scalars(select(ActionExecution).where(*execution_conditions))
                    ).all()
                )
                if correlations
                else []
            )

        event_by_key = {(event.correlation_id, event.event_type): event for event in related_events}
        execution_by_correlation = {execution.request_id: execution for execution in executions}
        safe_participant_ids = {
            player_view.actor_id,
            *(item.id for item in player_view.scene.visible_entities),
            *(item.id for item in player_view.scene.visible_actors),
        }
        projected: list[RecentTurn] = []
        truncated_field_count = 0
        for action_event in action_events:
            correlation_id = _action_correlation(action_event)
            if correlation_id is None or action_event.player_id is None:
                continue
            own_turn = action_event.player_id == player_input.player_id
            execution = execution_by_correlation.get(correlation_id)
            request: ActionRequest | None = None
            engine_result: EngineExecutionResult | None = None
            if execution is not None and own_turn:
                request = ActionRequest.model_validate(execution.request_json)
                engine_result = EngineExecutionResult.model_validate(execution.result_json)
            legacy_actor_id = (
                execution.request_json.get("actor_id")
                if execution is not None and isinstance(execution.request_json.get("actor_id"), str)
                else None
            )
            legacy_source_revision = (
                execution.request_json.get("source_view_revision")
                if execution is not None
                and isinstance(
                    execution.request_json.get("source_view_revision"),
                    str,
                )
                else None
            )
            source_actor_id = action_event.actor_id or legacy_actor_id
            if source_actor_id is None:
                continue
            utterance = action_event.payload.get("utterance")
            if not isinstance(utterance, str) or not utterance.strip():
                continue

            narration_event = event_by_key.get((correlation_id, "narration.push"))
            narration: VisibleHistoryText | None = None
            if narration_event is not None and (
                narration_event.visibility == "public"
                or (
                    own_turn
                    and narration_event.visibility == "player_scoped"
                    and narration_event.player_id == player_input.player_id
                )
            ):
                narration_text = narration_event.payload.get("text")
                if isinstance(narration_text, str) and narration_text.strip():
                    truncated_field_count += int(len(narration_text) > _NARRATION_LIMIT)
                    narration = VisibleHistoryText(
                        text=_truncate(narration_text, _NARRATION_LIMIT),
                        visibility=narration_event.visibility,
                    )

            reply_events = [
                event
                for event in related_events
                if event.event_type == "dialogue.npc"
                and _reply_correlation(event) == correlation_id
                and event.actor_id
                and isinstance(event.payload.get("text"), str)
                and event.payload["text"].strip()
            ]
            replies = tuple(
                RecentNpcReply(
                    speaker_id=cast(str, event.actor_id),
                    speaker_name=event.payload.get("speakerName")
                    or event.payload.get("speaker_name"),
                    text=VisibleHistoryText(
                        text=_truncate(event.payload["text"].strip(), _NARRATION_LIMIT),
                        visibility=cast(HistoryVisibility, event.visibility),
                    ),
                    listener_ids=payload_ids(event.payload, "listener_ids", "listenerIds"),
                )
                for event in reply_events
            )
            accepted_summary = None
            safe_result = None
            participants: list[str] = []
            if source_actor_id in safe_participant_ids or own_turn:
                participants.append(source_actor_id)
            if own_turn and request is not None and engine_result is not None:
                truncated_field_count += int(len(request.intent.summary) > _INTENT_LIMIT)
                accepted_summary = _truncate(request.intent.summary, _INTENT_LIMIT)
                action_result = engine_result.action_result
                safe_result = RecentSafeResult(
                    resolution=action_result.resolution,
                    outcome=action_result.outcome,
                    check_result=action_result.check_result,
                    visible_facts=_bounded_facts(action_result.visible_facts),
                )
                target = request.intent.target
                target_id = getattr(target, "id", None)
                if target_id in safe_participant_ids and target_id not in participants:
                    participants.append(target_id)

            participants.extend(
                item
                for item in payload_ids(action_event.payload, "participant_ids", "participantIds")
                if item not in participants
            )
            evidence = [
                f"transport_event:{action_event.id}",
                *(f"transport_event:{event.id}" for event in reply_events),
            ]
            if execution is not None and own_turn:
                evidence.append(f"action_execution:{correlation_id}")
            if narration_event is not None and narration is not None:
                evidence.append(f"transport_event:{narration_event.id}")
            check_event = event_by_key.get((correlation_id, "check.result"))
            if (
                check_event is not None
                and own_turn
                and check_event.player_id == player_input.player_id
            ):
                evidence.append(f"transport_event:{check_event.id}")

            projected.append(
                RecentTurn(
                    correlation_id=correlation_id,
                    source_player_id=action_event.player_id,
                    source_actor_id=source_actor_id,
                    scene_id=action_event.scene_id,
                    source_view_revision=(action_event.view_revision or legacy_source_revision),
                    committed_view_revision=(
                        narration_event.view_revision
                        if narration_event is not None
                        else (
                            engine_result.action_result.view_revision
                            if engine_result is not None
                            else None
                        )
                    ),
                    participants=tuple(participants),
                    player_utterance=VisibleHistoryText(
                        text=_truncate(utterance, _UTTERANCE_LIMIT),
                        visibility=cast(
                            HistoryVisibility,
                            action_event.visibility,
                        ),
                    ),
                    accepted_intent_summary=accepted_summary,
                    player_safe_result=safe_result,
                    published_narration=narration,
                    npc_replies=replies,
                    evidence_refs=tuple(evidence),
                )
            )
            truncated_field_count += int(len(utterance) > _UTTERANCE_LIMIT)

        selected_turns = _select_turns(
            projected,
            scene_id=player_view.scene_id,
            budget=budget,
        )
        projected_by_correlation = {turn.correlation_id: turn for turn in projected}
        globally_truncated_count = sum(
            _turn_chars(turn) < _turn_chars(projected_by_correlation[turn.correlation_id])
            for turn in selected_turns
        )
        context = RecentTurnContext(
            room_id=player_input.room_id,
            viewer_player_id=player_input.player_id,
            as_of_revision=player_view.revision,
            turns=selected_turns,
        )
        logger.info(
            "recent_history_projection",
            room_ref=hashlib.sha256(player_input.room_id.encode("utf-8")).hexdigest()[:12],
            correlation_id=exclude_correlation_id,
            candidate_turn_count=len(action_events),
            projected_turn_count=len(projected),
            selected_turn_count=len(selected_turns),
            character_count=sum(_turn_chars(turn) for turn in selected_turns),
            truncated_count=(
                truncated_field_count
                + max(0, len(projected) - len(selected_turns))
                + globally_truncated_count
            ),
        )
        return context.validate_for(
            player_input=player_input,
            player_view=player_view,
        )
