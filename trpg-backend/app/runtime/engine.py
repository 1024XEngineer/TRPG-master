"""确定性、服务端权威的规则执行边界。"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import CheckResult, Event
from app.models.replay import (
    GameStateSnapshot,
    ProcessedCommand,
    RoomSession,
    RoomSummary,
)
from app.models.room import Room
from app.module_runtime import RuntimeModule
from app.runtime.checkpoints import checkpoint_bypass_reason, checkpoint_label
from app.runtime.contracts import (
    ActionRequest,
    ActionResult,
    Intent,
    PendingCheck,
    RuntimeEvent,
)
from app.runtime.dice import DiceRoller, SystemDiceRoller
from app.runtime.state import ActorState, GameState
from app.runtime.store import SQLAlchemyGameStateStore


class RuntimeConflictError(RuntimeError):
    pass


class StaleRevisionError(RuntimeConflictError):
    pass


class IdempotencyConflictError(RuntimeConflictError):
    pass


class ActionExecutor:
    """所有玩家命令唯一允许产生权威副作用的入口。"""

    def __init__(
        self,
        *,
        store: SQLAlchemyGameStateStore | None = None,
        dice: DiceRoller | None = None,
    ) -> None:
        self.store = store or SQLAlchemyGameStateStore()
        self.dice = dice or SystemDiceRoller()

    async def execute(self, db: AsyncSession, request: ActionRequest) -> ActionResult:
        request_hash = self._hash(request.model_dump(mode="json"))
        replayed = await self._replay_processed(
            db, request.room_session_id, request.request_id, request_hash
        )
        if replayed is not None:
            return replayed

        session = await db.get(RoomSession, request.room_session_id)
        if session is None or session.room_id != request.room_id or session.status != "active":
            raise RuntimeConflictError("游戏会话不存在或已经结束")
        snapshot = await self.store.snapshot(db, session.id)
        state = GameState.model_validate(snapshot.state)
        state.revision = snapshot.revision
        if request.source_revision != state.revision:
            raise StaleRevisionError(
                f"状态版本已变化：客户端 {request.source_revision}，服务端 {state.revision}"
            )
        if request.actor_id not in state.actors:
            raise RuntimeConflictError("调查员不属于当前游戏会话")
        if state.pending_checks:
            raise RuntimeConflictError("当前有尚未完成的检定")

        runtime_module = await self.store.module_for_session(db, session)
        events: list[RuntimeEvent] = []
        narration_facts: list[str] = []
        pending = self._execute_intent(
            state,
            runtime_module,
            request.intent,
            request.utterance,
            events,
            narration_facts,
        )
        state_changed = bool(events or pending)
        # 玩家发言与规则事件进入同一笔幂等事务，确保重连后能够按顺序恢复，
        # 同一个 requestId 重试时也不会重复写入 EventLog。
        events.insert(
            0,
            RuntimeEvent(
                event_type="player.message",
                payload={
                    "text": request.utterance,
                    "requestId": request.request_id,
                },
                visibility="room",
            ),
        )
        state.last_intent = request.intent.model_dump(mode="json")
        state.variables["last_utterance"] = request.utterance
        state.revision += 1
        result = ActionResult(
            request_id=request.request_id,
            resolution="pending_check" if pending else "resolved",
            outcome="awaiting_roll" if pending else "action_resolved",
            state_revision=state.revision,
            state_changed=state_changed,
            pending_check=pending,
            events=events,
            narration_facts=narration_facts,
        )
        await self._persist(
            db,
            snapshot=snapshot,
            state=state,
            player_id=request.player_id,
            request_id=request.request_id,
            request_hash=request_hash,
            result=result,
        )
        return result

    async def resolve_pending(
        self,
        db: AsyncSession,
        *,
        room_id: str,
        room_session_id: str,
        player_id: str,
        request_id: str,
        check_request_id: str,
        source_revision: int,
    ) -> ActionResult:
        command = {
            "kind": "resolve_pending",
            "roomId": room_id,
            "roomSessionId": room_session_id,
            "playerId": player_id,
            "requestId": request_id,
            "checkRequestId": check_request_id,
            "sourceRevision": source_revision,
        }
        request_hash = self._hash(command)
        replayed = await self._replay_processed(db, room_session_id, request_id, request_hash)
        if replayed is not None:
            return replayed

        session = await db.get(RoomSession, room_session_id)
        if session is None or session.room_id != room_id or session.status != "active":
            raise RuntimeConflictError("游戏会话不存在或已经结束")
        snapshot = await self.store.snapshot(db, session.id)
        state = GameState.model_validate(snapshot.state)
        state.revision = snapshot.revision
        if source_revision != state.revision:
            raise StaleRevisionError(
                f"状态版本已变化：客户端 {source_revision}，服务端 {state.revision}"
            )
        pending = next(
            (item for item in state.pending_checks if item.check_request_id == check_request_id),
            None,
        )
        if pending is None:
            raise RuntimeConflictError("检定请求不存在或已经结算")

        runtime_module = await self.store.module_for_session(db, session)
        actor = state.actors[pending.actor_id]
        events: list[RuntimeEvent] = []
        narration_facts: list[str] = []
        if pending.kind == "skill":
            outcome = self._resolve_skill_check(
                state, runtime_module, actor, pending, events, narration_facts
            )
        else:
            outcome = self._resolve_san_check(state, runtime_module, actor, pending, events)
        state.pending_checks = [
            item for item in state.pending_checks if item.check_request_id != check_request_id
        ]
        self._evaluate_endings(state, runtime_module, events)
        state.revision += 1
        next_pending = state.pending_checks[0] if state.pending_checks else None
        result = ActionResult(
            request_id=request_id,
            resolution="pending_check" if next_pending else "resolved",
            outcome=outcome,
            state_revision=state.revision,
            state_changed=True,
            pending_check=next_pending,
            events=events,
            narration_facts=narration_facts,
        )
        await self._persist(
            db,
            snapshot=snapshot,
            state=state,
            player_id=player_id,
            request_id=request_id,
            request_hash=request_hash,
            result=result,
        )
        if state.active_ending_id:
            await self._finish_game(db, session, state, runtime_module)
        return result

    def _execute_intent(
        self,
        state: GameState,
        runtime_module: RuntimeModule,
        intent: Intent,
        utterance: str,
        events: list[RuntimeEvent],
        narration_facts: list[str],
    ) -> PendingCheck | None:
        actor = state.actors[next(iter(state.actors))]
        context = {
            "intent": intent.model_dump(mode="json"),
            "utterance": utterance,
        }

        if intent.kind == "checkpoint":
            return self._request_checkpoint(
                state,
                runtime_module,
                actor,
                intent,
                events,
                narration_facts,
            )

        if intent.kind == "choice":
            choice = intent.choice_id or intent.summary
            state.variables["player.choice"] = choice
            if choice.startswith("scene."):
                self._transition_if_available(
                    state,
                    runtime_module,
                    choice,
                    events,
                    narration_facts,
                    context=context,
                )
            elif choice in {"call_name", "call_douglas_name"}:
                self._fire_trigger(
                    state, runtime_module, "trigger.call_douglas_name", context, events
                )
            elif choice in {"talk", "polite_conversation"}:
                self._fire_trigger(
                    state, runtime_module, "trigger.talk_with_douglas", context, events
                )
        elif intent.kind == "dialogue":
            if state.current_scene_id == "scene.douglas_conversation":
                self._fire_trigger(
                    state, runtime_module, "trigger.talk_with_douglas", context, events
                )
            elif state.current_scene_id == "scene.confrontation":
                self._fire_trigger(
                    state, runtime_module, "trigger.call_douglas_name", context, events
                )
        elif intent.target_id and intent.target_id.startswith("scene."):
            self._transition_if_available(
                state,
                runtime_module,
                intent.target_id,
                events,
                narration_facts,
                context=context,
            )

        if intent.kind in {"free", "unknown"} and not events:
            events.append(
                RuntimeEvent(
                    event_type="action.observed",
                    payload={"summary": intent.summary},
                )
            )
        self._evaluate_endings(state, runtime_module, events, context=context)
        return state.pending_checks[0] if state.pending_checks else None

    def _request_checkpoint(
        self,
        state: GameState,
        runtime_module: RuntimeModule,
        actor: ActorState,
        intent: Intent,
        events: list[RuntimeEvent],
        narration_facts: list[str],
    ) -> PendingCheck | None:
        if intent.checkpoint_id is None:
            raise RuntimeConflictError("Checkpoint 意图缺少 checkpoint_id")
        checkpoint = runtime_module.get("checkpoints", intent.checkpoint_id)
        if checkpoint is None or checkpoint.get("scene_id") != state.current_scene_id:
            raise RuntimeConflictError("Checkpoint 不属于当前场景")
        if not self._conditions_met(checkpoint.get("prerequisites", []), state, runtime_module, {}):
            raise RuntimeConflictError("Checkpoint 前置条件尚未满足")
        skills = list(checkpoint["skills"])
        bypass_reason = checkpoint_bypass_reason(actor, checkpoint)
        if bypass_reason is not None:
            state.last_check = {
                "kind": "skill",
                "checkpoint_id": intent.checkpoint_id,
                "skill_id": None,
                "grade": "bypassed",
                "succeeded": True,
                "bypass_reason": bypass_reason,
            }
            self._apply_effects(
                state,
                runtime_module,
                checkpoint.get("on_success", []),
                {
                    "check": state.last_check,
                    "intent": intent.model_dump(mode="json"),
                    "utterance": intent.approach or intent.summary,
                },
                events,
                narration_facts,
            )
            if intent.checkpoint_id not in state.completed_checkpoint_ids:
                state.completed_checkpoint_ids.append(intent.checkpoint_id)
            self._advance_time(state, checkpoint.get("time_cost"))
            events.append(
                RuntimeEvent(
                    event_type="check.bypassed",
                    payload={
                        "checkpointId": intent.checkpoint_id,
                        "label": checkpoint_label(checkpoint),
                        "reason": bypass_reason,
                    },
                    visibility="player",
                )
            )
            return None
        skill_id = intent.skill_id or skills[0]
        if skill_id not in skills:
            raise RuntimeConflictError("所选技能不在 Checkpoint 候选中")
        target = self._skill_value(actor, skill_id)
        pending = PendingCheck(
            check_request_id=str(uuid.uuid4()),
            kind="skill",
            actor_id=actor.actor_id,
            checkpoint_id=intent.checkpoint_id,
            skill_id=skill_id,
            target_value=target,
            difficulty=checkpoint.get("difficulty", "regular"),
            reason=intent.summary,
        )
        state.pending_checks.append(pending)
        events.append(
            RuntimeEvent(
                event_type="check.requested",
                payload=pending.model_dump(mode="json"),
                visibility="player",
            )
        )
        return pending

    def _resolve_skill_check(
        self,
        state: GameState,
        runtime_module: RuntimeModule,
        actor: ActorState,
        pending: PendingCheck,
        events: list[RuntimeEvent],
        narration_facts: list[str],
    ) -> str:
        checkpoint = runtime_module.get("checkpoints", pending.checkpoint_id or "")
        if checkpoint is None:
            raise RuntimeConflictError("Checkpoint 已不存在")
        roll = self.dice.d100()
        grade = self._check_grade(roll, pending.target_value)
        succeeded = self._meets_difficulty(grade, pending.difficulty, pending.target_value)
        state.last_check = {
            "kind": "skill",
            "checkpoint_id": pending.checkpoint_id,
            "skill_id": pending.skill_id,
            "roll": roll,
            "target": pending.target_value,
            "grade": grade,
            "succeeded": succeeded,
        }
        context = {
            "check": state.last_check,
            "intent": state.last_intent or {},
            "utterance": state.variables.get("last_utterance", ""),
        }
        if grade == "fumble":
            effects = checkpoint.get("on_fumble", []) or checkpoint.get("on_failure", [])
        elif succeeded:
            effects = checkpoint.get("on_success", [])
        else:
            effects = checkpoint.get("on_failure", [])
        self._apply_effects(
            state,
            runtime_module,
            effects,
            context,
            events,
            narration_facts,
        )
        if (
            succeeded or not checkpoint.get("repeat")
        ) and pending.checkpoint_id not in state.completed_checkpoint_ids:
            state.completed_checkpoint_ids.append(pending.checkpoint_id or "")
        self._advance_time(state, checkpoint.get("time_cost"))
        events.append(
            RuntimeEvent(
                event_type="check.resolved",
                payload={
                    "checkRequestId": pending.check_request_id,
                    "checkpointId": pending.checkpoint_id,
                    "skillId": pending.skill_id,
                    "rollValue": roll,
                    "targetValue": pending.target_value,
                    "grade": grade,
                    "succeeded": succeeded,
                },
                visibility="player",
            )
        )
        return grade

    def _resolve_san_check(
        self,
        state: GameState,
        runtime_module: RuntimeModule,
        actor: ActorState,
        pending: PendingCheck,
        events: list[RuntimeEvent],
    ) -> str:
        sanity_event = runtime_module.get("sanity_events", pending.sanity_event_id or "")
        if sanity_event is None:
            raise RuntimeConflictError("SAN 事件已不存在")
        roll = self.dice.d100()
        succeeded = roll <= actor.current_san
        expression = sanity_event["loss"]["success" if succeeded else "failure"]
        loss = self.dice.expression(str(expression))
        for cap in sanity_event.get("caps", []):
            scope = str(cap["scope"])
            used = int(state.variables.get(f"san.cap.{scope}", 0))
            maximum = int(cap["maximum"])
            loss = min(loss, max(0, maximum - used))
            state.variables[f"san.cap.{scope}"] = used + loss
        actor.current_san = max(0, actor.current_san - loss)
        if loss >= 5:
            state.variables["temporary_insanity"] = True
            if pending.sanity_event_id == "san.see_ghoul_crowd":
                state.variables["temporary_insanity_during_ghoul_crowd"] = True
        state.last_check = {
            "kind": "san",
            "sanity_event_id": pending.sanity_event_id,
            "roll": roll,
            "target": pending.target_value,
            "succeeded": succeeded,
            "loss": loss,
        }
        events.append(
            RuntimeEvent(
                event_type="san.resolved",
                payload={
                    "checkRequestId": pending.check_request_id,
                    "sanityEventId": pending.sanity_event_id,
                    "rollValue": roll,
                    "targetValue": pending.target_value,
                    "succeeded": succeeded,
                    "sanLoss": loss,
                    "currentSan": actor.current_san,
                },
                visibility="player",
            )
        )
        return "san_success" if succeeded else "san_failure"

    def _apply_effects(
        self,
        state: GameState,
        runtime_module: RuntimeModule,
        effects: list[dict[str, Any]],
        context: dict[str, Any],
        events: list[RuntimeEvent],
        narration_facts: list[str],
    ) -> None:
        actor = state.actors[next(iter(state.actors))]
        for effect in effects:
            effect_type = effect["type"]
            if effect_type == "grant_clue":
                clue_id = str(effect["clue_id"])
                if clue_id not in state.granted_clue_ids:
                    state.granted_clue_ids.append(clue_id)
                    clue = runtime_module.get("clues", clue_id) or {}
                    events.append(
                        RuntimeEvent(
                            event_type="clue.granted",
                            payload={
                                "clueId": clue_id,
                                "name": clue.get("summary", clue_id),
                                "description": clue.get("summary"),
                            },
                            visibility="player",
                        )
                    )
                    self._apply_effects(
                        state,
                        runtime_module,
                        clue.get("effects", []),
                        context,
                        events,
                        narration_facts,
                    )
            elif effect_type == "set_state":
                self._set_path(state, str(effect["path"]), effect.get("value"))
            elif effect_type == "transition":
                self._transition(
                    state,
                    runtime_module,
                    str(effect["scene_id"]),
                    events,
                    narration_facts,
                    context=context,
                )
            elif effect_type == "fire_trigger":
                self._fire_trigger(
                    state, runtime_module, str(effect["trigger_id"]), context, events
                )
            elif effect_type == "request_san_check":
                sanity_id = str(effect["sanity_event_id"])
                if not any(item.sanity_event_id == sanity_id for item in state.pending_checks):
                    sanity_event = runtime_module.get("sanity_events", sanity_id)
                    if sanity_event is None:
                        raise RuntimeConflictError(f"未知 SAN 事件：{sanity_id}")
                    pending = PendingCheck(
                        check_request_id=str(uuid.uuid4()),
                        kind="san",
                        actor_id=actor.actor_id,
                        sanity_event_id=sanity_id,
                        target_value=actor.current_san,
                        reason=str(sanity_event.get("trigger", sanity_id)),
                    )
                    state.pending_checks.append(pending)
                    events.append(
                        RuntimeEvent(
                            event_type="san.requested",
                            payload=pending.model_dump(mode="json"),
                            visibility="player",
                        )
                    )
            elif effect_type == "trigger_ending":
                self._activate_ending(state, runtime_module, str(effect["ending_id"]), events)
            elif effect_type == "move_entity":
                entity_id = str(effect["entity_id"])
                state.entity_states.setdefault(entity_id, {})["scene_id"] = effect["scene_id"]
                events.append(
                    RuntimeEvent(
                        event_type="entity.moved",
                        payload={
                            "entityId": entity_id,
                            "sceneId": effect["scene_id"],
                        },
                        visibility="keeper",
                    )
                )
            elif effect_type == "recover_san":
                amount = self.dice.expression(str(effect["expression"]))
                actor.current_san = min(actor.max_san, actor.current_san + amount)
                events.append(
                    RuntimeEvent(
                        event_type="san.recovered",
                        payload={"amount": amount, "currentSan": actor.current_san},
                        visibility="player",
                    )
                )
            elif effect_type == "award_skill":
                skill_id = str(effect["skill_id"])
                amount = int(effect["amount"])
                actor.skills[skill_id] = actor.skills.get(skill_id, 0) + amount
                actor.max_san = max(0, 99 - actor.skills.get("cthulhu_mythos", 0))
                actor.current_san = min(actor.current_san, actor.max_san)
            elif effect_type == "roll_cost":
                amount = self.dice.expression(str(effect["expression"]))
                currency = str(effect.get("currency", "USD"))
                actor.currency[currency] = max(0, actor.currency.get(currency, 0) - amount)
                state.variables["last_cost"] = {
                    "amount": amount,
                    "currency": currency,
                }
            elif effect_type == "conditional_state_change":
                when = effect.get("when", {})
                if self._get_path(state, str(when.get("path", ""))) == when.get("equals"):
                    self._apply_effects(
                        state,
                        runtime_module,
                        effect.get("then", []),
                        context,
                        events,
                        narration_facts,
                    )
            elif effect_type == "conditional_hazard":
                declaration = str(effect.get("unless_player_declared", ""))
                utterance = str(context.get("utterance", "")).lower()
                if declaration and declaration.replace("_", " ") not in utterance:
                    state.variables[f"hazard.{effect.get('effect')}"] = True
                    if effect.get("effect") == "unconscious_until_night":
                        state.clock["time_of_day"] = "night"
            else:
                raise RuntimeConflictError(f"未实现的 Effect：{effect_type}")

    def _fire_trigger(
        self,
        state: GameState,
        runtime_module: RuntimeModule,
        trigger_id: str,
        context: dict[str, Any],
        events: list[RuntimeEvent],
    ) -> None:
        trigger = runtime_module.get("triggers", trigger_id)
        if trigger is None:
            raise RuntimeConflictError(f"未知 Trigger：{trigger_id}")
        if runtime_module.package.runtime_defaults.trigger_once:
            if trigger_id in state.fired_trigger_ids:
                return
            state.fired_trigger_ids.append(trigger_id)
        events.append(
            RuntimeEvent(
                event_type="trigger.fired",
                payload={"triggerId": trigger_id},
                visibility="keeper",
            )
        )
        self._apply_effects(
            state,
            runtime_module,
            trigger.get("effects", []),
            context,
            events,
            [],
        )

    def _conditions_met(
        self,
        conditions: list[dict[str, Any]],
        state: GameState,
        runtime_module: RuntimeModule,
        context: dict[str, Any],
    ) -> bool:
        for condition in conditions:
            kind = condition["type"]
            if kind == "state_eq":
                matched = self._get_path(state, str(condition["path"])) == condition.get("value")
            elif kind == "clue_not_owned":
                matched = condition["clue_id"] not in state.granted_clue_ids
            elif kind == "check_fumble":
                matched = bool(
                    state.last_check
                    and state.last_check.get("grade") == "fumble"
                    and state.last_check.get("checkpoint_id") == condition.get("checkpoint_id")
                )
            elif kind == "player_choice":
                matched = state.variables.get("player.choice") == condition.get("value")
            elif kind == "player_attacks":
                intent = context.get("intent", state.last_intent or {})
                matched = (
                    intent.get("kind") == "choice"
                    and intent.get("choice_id") in {"attack", "attack_ghouls"}
                    and condition.get("target") == "group.ghouls"
                )
            elif kind == "temporary_insanity_during_ghoul_crowd":
                matched = bool(state.variables.get("temporary_insanity_during_ghoul_crowd", False))
            else:
                raise RuntimeConflictError(f"未实现的 Condition：{kind}")
            if not matched:
                return False
        return True

    def _evaluate_endings(
        self,
        state: GameState,
        runtime_module: RuntimeModule,
        events: list[RuntimeEvent],
        *,
        context: dict[str, Any] | None = None,
    ) -> None:
        if state.active_ending_id:
            return
        endings = sorted(
            runtime_module.package.content.endings,
            key=lambda ending: int(ending.get("priority", 0)),
            reverse=True,
        )
        for ending in endings:
            if self._conditions_met(
                ending.get("conditions", []),
                state,
                runtime_module,
                context or {},
            ):
                self._activate_ending(state, runtime_module, str(ending["id"]), events)
                return

    def _activate_ending(
        self,
        state: GameState,
        runtime_module: RuntimeModule,
        ending_id: str,
        events: list[RuntimeEvent],
    ) -> None:
        ending = runtime_module.get("endings", ending_id)
        if ending is None:
            raise RuntimeConflictError(f"未知 Ending：{ending_id}")
        state.active_ending_id = ending_id
        events.append(
            RuntimeEvent(
                event_type="game.ended",
                payload={
                    "endingId": ending_id,
                    "outcome": ending.get("outcome"),
                    "summary": ending.get("summary"),
                },
            )
        )

    def _transition_if_available(
        self,
        state: GameState,
        runtime_module: RuntimeModule,
        scene_id: str,
        events: list[RuntimeEvent],
        narration_facts: list[str],
        *,
        context: dict[str, Any] | None = None,
    ) -> None:
        current = runtime_module.get("scenes", state.current_scene_id) or {}
        if scene_id not in current.get("next_scene_ids", []):
            raise RuntimeConflictError("目标场景不能从当前位置到达")
        self._transition(
            state,
            runtime_module,
            scene_id,
            events,
            narration_facts,
            context=context,
        )

    def _transition(
        self,
        state: GameState,
        runtime_module: RuntimeModule,
        scene_id: str,
        events: list[RuntimeEvent],
        narration_facts: list[str],
        *,
        context: dict[str, Any] | None = None,
    ) -> None:
        scene = runtime_module.get("scenes", scene_id)
        if scene is None:
            raise RuntimeConflictError(f"未知场景：{scene_id}")
        state.current_scene_id = scene_id
        if scene_id not in state.discovered_scene_ids:
            state.discovered_scene_ids.append(scene_id)
        active_encounter = next(
            (
                encounter
                for encounter in runtime_module.package.content.encounters
                if scene_id in encounter.get("scene_ids", [])
            ),
            None,
        )
        next_encounter_id = str(active_encounter["id"]) if active_encounter is not None else None
        if state.active_encounter_id != next_encounter_id:
            state.active_encounter_id = next_encounter_id
            events.append(
                RuntimeEvent(
                    event_type=(
                        "encounter.started" if next_encounter_id is not None else "encounter.ended"
                    ),
                    payload={"encounterId": next_encounter_id},
                    visibility="room",
                )
            )
        events.append(
            RuntimeEvent(
                event_type="scene.changed",
                payload={
                    "sceneId": scene_id,
                    "name": scene["name"],
                    "playerDescription": scene["player_description"],
                },
            )
        )
        scene_key = scene_id.removeprefix("scene.")
        for trigger_id in scene.get("trigger_ids", []):
            trigger = runtime_module.get("triggers", trigger_id)
            trigger_event = str((trigger or {}).get("event", ""))
            if trigger_event.startswith(f"player_enters_{scene_key}"):
                self._fire_trigger(
                    state,
                    runtime_module,
                    str(trigger_id),
                    context or {},
                    events,
                )

    def _advance_time(self, state: GameState, time_cost: str | None) -> None:
        if not time_cost:
            return
        amount_text, _, unit = time_cost.partition(" ")
        amount = int(amount_text) if amount_text.isdigit() else 1
        if unit in {"day", "days"}:
            state.clock["day"] = int(state.clock.get("day", 0)) + amount
            state.clock["time_of_day"] = "day"
        elif unit in {"night", "nights"}:
            state.clock["day"] = int(state.clock.get("day", 0)) + max(0, amount - 1)
            state.clock["time_of_day"] = "night"

    @staticmethod
    def _skill_value(actor: ActorState, skill_id: str) -> int:
        if skill_id == "luck":
            return int(actor.attributes.get("LUCK", 0))
        attribute = skill_id.upper()
        if attribute in actor.attributes:
            return int(actor.attributes[attribute])
        return int(actor.skills.get(skill_id, 0))

    @staticmethod
    def _check_grade(roll: int, target: int) -> str:
        if roll == 1:
            return "critical"
        if (target < 50 and roll >= 96) or roll == 100:
            return "fumble"
        if roll <= max(1, target // 5):
            return "extreme"
        if roll <= max(1, target // 2):
            return "hard"
        if roll <= target:
            return "regular"
        return "failure"

    @staticmethod
    def _meets_difficulty(grade: str, difficulty: str, target: int) -> bool:
        del target
        ranks = {
            "fumble": 0,
            "failure": 0,
            "regular": 1,
            "hard": 2,
            "extreme": 3,
            "critical": 4,
        }
        required = {"regular": 1, "hard": 2, "extreme": 3}.get(difficulty, 1)
        return ranks[grade] >= required

    @staticmethod
    def _state_bucket(state: GameState, path: str) -> tuple[dict[str, Any], str] | None:
        candidates: list[tuple[str, dict[str, dict[str, Any]]]] = [
            ("location.", state.location_states),
            ("npc.", state.entity_states),
            ("group.", state.entity_states),
            ("object.", state.resource_states),
            ("item.", state.resource_states),
        ]
        for prefix, bucket in candidates:
            if not path.startswith(prefix):
                continue
            segments = path.split(".")
            for end in range(len(segments) - 1, 0, -1):
                item_id = ".".join(segments[:end])
                if item_id in bucket:
                    key = ".".join(segments[end:])
                    return bucket[item_id], key
        return None

    def _get_path(self, state: GameState, path: str) -> Any:
        bucket = self._state_bucket(state, path)
        if bucket is not None:
            value: Any = bucket[0]
            for segment in bucket[1].split("."):
                if not isinstance(value, dict):
                    return None
                value = value.get(segment)
            return value
        return state.variables.get(path)

    def _set_path(self, state: GameState, path: str, value: Any) -> None:
        bucket = self._state_bucket(state, path)
        if bucket is None:
            state.variables[path] = value
            return
        target, nested_path = bucket
        segments = nested_path.split(".")
        for segment in segments[:-1]:
            target = target.setdefault(segment, {})
        target[segments[-1]] = value

    async def _persist(
        self,
        db: AsyncSession,
        *,
        snapshot: GameStateSnapshot,
        state: GameState,
        player_id: str,
        request_id: str,
        request_hash: str,
        result: ActionResult,
    ) -> None:
        snapshot.revision = state.revision
        for runtime_event in result.events:
            state.event_sequence += 1
            db.add(
                Event(
                    room_id=state.room_id,
                    room_session_id=state.room_session_id,
                    player_id=player_id,
                    sequence=state.event_sequence,
                    request_id=request_id,
                    event_type=runtime_event.event_type,
                    payload=runtime_event.payload,
                    visibility=runtime_event.visibility,
                    state_revision=state.revision,
                )
            )
            if runtime_event.event_type in {"check.resolved", "san.resolved"}:
                payload = runtime_event.payload
                db.add(
                    CheckResult(
                        room_id=state.room_id,
                        player_id=player_id,
                        character_id=next(iter(state.actors)),
                        check_type=(
                            "san" if runtime_event.event_type == "san.resolved" else "skill"
                        ),
                        skill_or_stat=payload.get("skillId", "SAN"),
                        checkpoint_id=payload.get("checkpointId"),
                        sanity_event_id=payload.get("sanityEventId"),
                        request_id=request_id,
                        roll_value=payload.get("rollValue"),
                        target_value=payload.get("targetValue"),
                        result=payload.get("grade")
                        or ("success" if payload.get("succeeded") else "failure"),
                    )
                )
        snapshot.state = state.model_dump(mode="json")
        db.add(
            ProcessedCommand(
                room_session_id=state.room_session_id,
                request_id=request_id,
                request_hash=request_hash,
                result=result.model_dump(mode="json"),
                state_revision=state.revision,
            )
        )
        await db.commit()

    async def _replay_processed(
        self,
        db: AsyncSession,
        room_session_id: str,
        request_id: str,
        request_hash: str,
    ) -> ActionResult | None:
        processed = await db.scalar(
            select(ProcessedCommand).where(
                ProcessedCommand.room_session_id == room_session_id,
                ProcessedCommand.request_id == request_id,
            )
        )
        if processed is None:
            return None
        if processed.request_hash != request_hash:
            raise IdempotencyConflictError("同一 requestId 对应了不同命令")
        result = ActionResult.model_validate(processed.result)
        return result.model_copy(update={"resolution": "replayed"})

    async def _finish_game(
        self,
        db: AsyncSession,
        session: RoomSession,
        state: GameState,
        runtime_module: RuntimeModule,
    ) -> None:
        now = datetime.now(UTC)
        session.status = "completed"
        session.ended_at = now
        room = await db.get(Room, state.room_id)
        if room is not None:
            room.phase = "Completed"
            room.ended_at = now
        ending = runtime_module.get("endings", state.active_ending_id or "") or {}
        summary = await db.scalar(select(RoomSummary).where(RoomSummary.room_id == state.room_id))
        actor = state.actors[next(iter(state.actors))]
        structured = {
            "endingId": state.active_ending_id,
            "outcome": ending.get("outcome"),
            "clueIds": state.granted_clue_ids,
            "completedCheckpointIds": state.completed_checkpoint_ids,
            "finalSan": actor.current_san,
            "eventSequence": state.event_sequence,
        }
        if summary is None:
            summary = RoomSummary(room_id=state.room_id)
            db.add(summary)
        summary.ending_id = state.active_ending_id
        summary.outcome = ending.get("outcome")
        summary.summary_text = ending.get("summary")
        summary.highlights = [
            f"发现 {len(state.granted_clue_ids)} 条线索",
            f"完成 {len(state.completed_checkpoint_ids)} 次关键调查",
            f"最终理智值 {actor.current_san}",
        ]
        summary.structured_data = structured
        await db.commit()

    @staticmethod
    def _hash(payload: dict[str, Any]) -> str:
        canonical = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        return hashlib.sha256(canonical).hexdigest()
