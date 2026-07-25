"""Storage-independent deterministic rule kernel."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Literal, TypeAlias

from collaboration_framework.contracts import (
    ActionOutcome,
    ActionRequest,
    ActionResolution,
    ActionResult,
    AddOperationSpec,
    AllowOperationSpec,
    ApplyConditionSpec,
    CheckpointSpec,
    ConditionSpec,
    ContractError,
    DefaultCheck,
    EntitySpec,
    ForbidOperationSpec,
    ForceOperationSpec,
    MatchedTarget,
    ModifyOperationSpec,
    ModuleCheck,
    ModuleContent,
    OperationSpec,
    RuleCheckResult,
    RuleSpec,
    SetOperationSpec,
    TransitionSpec,
    TriggerEndingSpec,
    TriggerRuleSpec,
    VisibleFact,
)

from .dice import (
    CheckOutcomeName,
    DiceRoller,
    DiceSource,
    coc7_success_level,
    outcome_name,
    passes_difficulty,
)
from .expression import ExpressionEvaluator, expression_context
from .models import (
    EngineExecutionResult,
    GameState,
    StateChange,
    StateModifiedEvent,
    StateModifiedPayload,
)

CheckOutcomeResolver: TypeAlias = Callable[
    [ActionRequest, CheckpointSpec],
    CheckOutcomeName,
]
HookResult: TypeAlias = Literal["none", "append", "override", "forbid"]

_ATTACK_VERBS = frozenset({"attack", "fight", "shoot", "strike"})
_TIME_VERBS = frozenset({"wait", "rest", "wait_until_night", "time_elapsed"})
_FORCE_ACTION = re.compile(r"^coc7\.(?P<name>[a-z_]+)\((?P<arguments>.*)\)$")


class RuleKernel:
    """Pure evaluator over one immutable module and one authoritative snapshot."""

    def __init__(
        self,
        check_outcome_resolver: CheckOutcomeResolver | None = None,
        *,
        dice_source: DiceSource | None = None,
        allow_legacy_missing_skill: bool = True,
        max_rule_steps: int = 64,
    ) -> None:
        self._check_outcome_resolver = check_outcome_resolver
        self._dice_source = dice_source
        self._allow_legacy_missing_skill = allow_legacy_missing_skill
        self._max_rule_steps = max_rule_steps

    def execute(
        self,
        *,
        request: ActionRequest,
        module_content: ModuleContent,
        game_state: GameState,
    ) -> tuple[EngineExecutionResult, GameState]:
        execution = _Execution(
            request=request,
            module_content=module_content,
            game_state=game_state,
            check_outcome_resolver=self._check_outcome_resolver,
            dice_roller=DiceRoller(self._dice_source),
            allow_legacy_missing_skill=self._allow_legacy_missing_skill,
            max_rule_steps=self._max_rule_steps,
        )
        return execution.run()

    @staticmethod
    def condition_matches(
        condition: ConditionSpec,
        state: GameState | dict[str, Any],
        *,
        request: ActionRequest | None = None,
        target_id: str | None = None,
    ) -> bool:
        payload = (
            state.model_dump(mode="python", by_alias=True)
            if isinstance(state, GameState)
            else state
        )
        if condition.expr is not None:
            return ExpressionEvaluator().matches(
                condition.expr,
                expression_context(payload, request=request, target_id=target_id),
            )
        try:
            actual = _read_path(payload, _runtime_path(condition.path, request))
        except ContractError:
            # Compatibility for old partial offline snapshots: a missing
            # path-condition is inactive, while invalid expressions still fail.
            return False
        return actual == condition.equals


class _Execution:
    def __init__(
        self,
        *,
        request: ActionRequest,
        module_content: ModuleContent,
        game_state: GameState,
        check_outcome_resolver: CheckOutcomeResolver | None,
        dice_roller: DiceRoller,
        allow_legacy_missing_skill: bool,
        max_rule_steps: int,
    ) -> None:
        self.request = request
        self.module = module_content
        self.state = game_state.model_dump(mode="python", by_alias=True)
        self.check_outcome_resolver = check_outcome_resolver
        self.dice = dice_roller
        self.allow_legacy_missing_skill = allow_legacy_missing_skill
        self.max_rule_steps = max_rule_steps
        self.events: list[StateModifiedEvent] = []
        self.facts: list[str] = []
        self.visible: list[str] = []
        self.constraints: list[str] = []
        self.check_result: RuleCheckResult | None = None
        self.fired_rules: set[tuple[str, str]] = set()
        self.rule_steps = 0
        self.target_id: str | None = None

    def run(self) -> tuple[EngineExecutionResult, GameState]:
        self._validate_execution_context()
        intent = self.request.intent
        if intent.kind == "unknown" or not isinstance(intent.target, MatchedTarget):
            return self._finalize(
                resolution="unrecognized",
                outcome="not_applicable",
                visible=("没有找到与该说法对应的当前场景目标。",),
                constraints=("不得编造目标或状态变化。",),
            )
        if self.state.get("phase") != "playing":
            return self._finalize(
                resolution="blocked",
                outcome="not_applicable",
                visible=("游戏已经结束，不能再提交新的动作。",),
                constraints=("不得叙述新的规则结果。",),
            )

        self.target_id = intent.target.id
        current_scene = self._scene(str(self.state["scene_id"]))
        available_exit = next(
            (
                item
                for item in current_scene.available_exits
                if item.id == self.target_id
            ),
            None,
        )
        if available_exit is not None and isinstance(intent.check, DefaultCheck):
            destination_scene_id = None
            if intent.verb in {"travel", "move", "go"}:
                if (
                    current_scene.exits
                    and available_exit.destination_scene_id not in current_scene.exits
                ):
                    raise ContractError("Player-visible exit is outside Scene.exits")
                destination_scene_id = available_exit.destination_scene_id
            return self._complete_default_check(
                entity=None,
                destination_scene_id=destination_scene_id,
            )
        if available_exit is not None and intent.verb in {"travel", "move", "go"}:
            if (
                current_scene.exits
                and available_exit.destination_scene_id not in current_scene.exits
            ):
                raise ContractError("Player-visible exit is outside Scene.exits")
            self._transition(
                available_exit.destination_scene_id,
                cause=f"action:{self.request.request_id}",
            )
            return self._complete_turn(resolution="direct", outcome="success")

        target_scene = self._scene_or_none(self.target_id)
        if target_scene is not None and isinstance(intent.check, DefaultCheck):
            destination_scene_id = None
            if (
                target_scene.id != current_scene.id
                and current_scene.exits
                and target_scene.id not in current_scene.exits
            ):
                return self._finalize(
                    resolution="blocked",
                    outcome="not_applicable",
                    visible=("当前场景没有通向该地点的出口。",),
                    constraints=("不得声称玩家已经影响或到达不可接触的场景。",),
                )
            if (
                intent.verb in {"travel", "move", "go"}
                and target_scene.id != current_scene.id
            ):
                destination_scene_id = target_scene.id
            return self._complete_default_check(
                entity=None,
                destination_scene_id=destination_scene_id,
            )
        if target_scene is not None and intent.verb in {"travel", "move", "go"}:
            if current_scene.exits and target_scene.id not in current_scene.exits:
                return self._finalize(
                    resolution="blocked",
                    outcome="not_applicable",
                    visible=("当前场景没有通向该地点的出口。",),
                    constraints=("不得声称玩家已经移动到不可达场景。",),
                )
            self._transition(target_scene.id, cause=f"action:{self.request.request_id}")
            return self._complete_turn(resolution="direct", outcome="success")

        if self.target_id not in current_scene.entity_ids:
            return self._finalize(
                resolution="blocked",
                outcome="not_applicable",
                visible=("这个目标不在当前场景中。",),
                constraints=("不得声称动作已经执行。",),
            )
        entity = self._entity(self.target_id)

        interaction_rules = self._matching_rules("on_interact", entity)
        interaction_plan, selected_rules = self._select_rules(
            "on_interact",
            interaction_rules,
        )
        allows_action = any(
            isinstance(operation, AllowOperationSpec)
            and operation.action == intent.verb
            for rule in selected_rules
            for operation in rule.then
        )
        if interaction_plan == "forbid":
            return self._finalize(
                resolution="blocked",
                outcome="not_applicable",
                visible=(entity.blocked_text or "这个行动被规则阻止了。",),
                constraints=("不得声称被拒绝的状态变化已经发生。",),
            )
        if (
            intent.verb in entity.refuse_ops
            and not allows_action
            and interaction_plan != "override"
        ):
            return self._finalize(
                resolution="blocked",
                outcome="not_applicable",
                visible=(entity.blocked_text or "这个行动被规则阻止了。",),
                constraints=("不得声称被拒绝的状态变化已经发生。",),
            )

        if isinstance(intent.check, DefaultCheck) and intent.verb not in _ATTACK_VERBS:
            # Ordinary checks are descriptive rule resolutions.  They respect
            # entity-level forbids, but do not execute module interaction or
            # checkpoint operations that could advance the plot.
            return self._complete_default_check(entity=entity)

        self._apply_rules("on_interact", selected_rules)
        if interaction_plan == "override":
            return self._complete_turn(resolution="direct", outcome="success")

        if intent.verb in _ATTACK_VERBS:
            attack_plan = self._apply_hook("on_attack_declare", entity)
            if attack_plan == "forbid":
                return self._finalize(
                    resolution="blocked",
                    outcome="not_applicable",
                    visible=("该攻击被规则禁止。",),
                    constraints=("不得叙述攻击命中或造成伤害。",),
                )
            if attack_plan == "override":
                attack_outcome: ActionOutcome = "success"
            else:
                self._resolve_attack(entity)
                attack_outcome = (
                    "success"
                    if self.check_result and self.check_result.passed
                    else "failure"
                )
            return self._complete_turn(
                resolution="direct",
                outcome=attack_outcome,
            )

        if isinstance(intent.check, ModuleCheck):
            outcome = self._resolve_checkpoint(entity)
            return self._complete_turn(
                resolution="checkpoint",
                outcome="failure" if outcome in {"failure", "fumble"} else "success",
                fact_source=(f"checkpoint:{intent.check.checkpoint_id}:{outcome}"),
            )

        self.facts.append(
            f"{self.request.actor_id} 对 {self.target_id} 执行 {intent.verb}"
        )
        self.visible.append(self._direct_visible_text(entity, intent.verb))
        if intent.verb in _TIME_VERBS:
            self._advance_time(intent.verb)
        return self._complete_turn(
            resolution="direct",
            outcome=(
                "success"
                if allows_action or intent.verb in _TIME_VERBS
                else "not_applicable"
            ),
        )

    def _complete_turn(
        self,
        *,
        resolution: ActionResolution,
        outcome: ActionOutcome,
        fact_source: str | None = None,
    ) -> tuple[EngineExecutionResult, GameState]:
        self._drain_state_change_hooks()
        self._apply_hook("on_turn_end")
        self._drain_state_change_hooks()
        self._apply_win_conditions()
        return self._finalize(
            resolution=resolution,
            outcome=outcome,
            fact_source=fact_source,
        )

    def _complete_default_check(
        self,
        *,
        entity: EntitySpec | None,
        destination_scene_id: str | None = None,
    ) -> tuple[EngineExecutionResult, GameState]:
        outcome = self._resolve_default_check()
        passed = outcome not in {"failure", "fumble"}
        self.facts.append(
            f"{self.request.actor_id} 对 {self.target_id} 执行 "
            f"{self.request.intent.verb}（普通检定{'通过' if passed else '未通过'}）"
        )
        if passed and entity is not None:
            self.visible.append(
                self._direct_visible_text(entity, self.request.intent.verb)
            )
        elif passed:
            self.visible.append("你在这次尝试中充分发挥了相应技巧。")
        else:
            self.visible.append("你在这次尝试中没能充分发挥相应技巧。")
        self.constraints.append(
            "这是普通检定；不得把结果扩展为未执行的模组检查点、"
            "未公开线索或额外状态变化。"
        )
        if passed:
            self.constraints.append(
                "检定已通过；只能使用 ActionResult.visible_facts 与动作后的 "
                "PlayerView 描述即时效果。"
            )
        else:
            self.constraints.append(
                "检定未通过；不得声称发现新的隐藏信息或取得依赖该检定的额外效果。"
            )
        if destination_scene_id is not None:
            self._transition(
                destination_scene_id,
                cause=f"action:{self.request.request_id}",
            )
        return self._complete_turn(
            resolution="direct",
            outcome="success" if passed else "failure",
        )

    def _validate_execution_context(self) -> None:
        if self.state.get("room_id") != self.request.room_id:
            raise ContractError("ActionRequest room_id does not match GameState")
        actor = self.state.get("actors", {}).get(self.request.actor_id)
        if not actor or actor.get("player_id") != self.request.player_id:
            raise ContractError("player_id/actor_id is not bound to the room")

    def _resolve_checkpoint(self, entity: EntitySpec) -> CheckOutcomeName:
        check = self.request.intent.check
        if not isinstance(check, ModuleCheck):
            raise AssertionError("checkpoint resolution requires ModuleCheck")
        checkpoint = self._validated_checkpoint(
            checkpoint_id=check.checkpoint_id,
            scene_id=str(self.state["scene_id"]),
            target_id=entity.id,
            proposed_skills=check.proposed_skills,
        )
        self._apply_hook("on_check_declare", entity)
        if self.check_outcome_resolver is not None:
            resolved = self.check_outcome_resolver(self.request, checkpoint)
        elif not checkpoint.skills:
            resolved = "success"
        else:
            resolved = self._roll_check(
                checkpoint_id=checkpoint.id,
                candidate_skills=check.proposed_skills or checkpoint.skills,
                allowed_skills=checkpoint.skills,
                difficulty=checkpoint.difficulty or "regular",
            )
        self._apply_hook("on_check_roll", entity)
        checkpoint_outcome = getattr(checkpoint.outcomes, resolved)
        if checkpoint_outcome is None:
            checkpoint_outcome = (
                checkpoint.outcomes.failure
                if resolved == "fumble"
                else checkpoint.outcomes.success
            )
        for operation in checkpoint_outcome.ops:
            self._apply_operation(
                operation,
                cause=f"checkpoint:{checkpoint.id}",
            )
        self._record_facts(
            checkpoint_outcome.facts, cause=f"checkpoint:{checkpoint.id}"
        )
        self.visible.extend(
            information.text
            for information in checkpoint_outcome.player_visible_information
            if information.visibility.audience not in {"keeper", "ho"}
        )
        self.constraints.extend(checkpoint_outcome.narration_constraints)
        self._apply_hook("on_check_resolve", entity)
        return resolved

    def _resolve_default_check(self) -> CheckOutcomeName:
        check = self.request.intent.check
        if not isinstance(check, DefaultCheck):
            raise AssertionError("default resolution requires DefaultCheck")
        if not check.proposed_skills:
            raise ContractError("Default check requires at least one proposed skill")
        if any(
            self._actor_check_value(skill_id) is None
            for skill_id in check.proposed_skills
        ):
            raise ContractError("Default check skills must belong to the current Actor")
        return self._roll_check(
            checkpoint_id=None,
            candidate_skills=check.proposed_skills,
            allowed_skills=check.proposed_skills,
            difficulty="regular",
        )

    def _roll_check(
        self,
        *,
        checkpoint_id: str | None,
        candidate_skills: tuple[str, ...],
        allowed_skills: tuple[str, ...],
        difficulty: Literal["regular", "hard", "extreme"],
    ) -> CheckOutcomeName:
        if not set(candidate_skills).issubset(allowed_skills):
            raise ContractError(
                "Proposed skills are outside the allowed checkpoint skills"
            )
        candidates: list[tuple[int, str]] = []
        for skill_id in candidate_skills:
            value = self._actor_check_value(skill_id)
            if value is not None:
                candidates.append((value, skill_id))
        if not candidates:
            if self.allow_legacy_missing_skill:
                return "success"
            raise ContractError("Actor has no value for the proposed check skills")
        target_value, skill_id = max(candidates)
        roll_value = (
            self.request.roll_value
            if self.request.roll_value is not None
            else self.dice.percentile()
        )
        level = coc7_success_level(target_value, roll_value)
        passed = passes_difficulty(level, difficulty)
        self.check_result = RuleCheckResult(
            checkpoint_id=checkpoint_id,
            skill_id=skill_id,
            target_value=target_value,
            roll_value=roll_value,
            difficulty=difficulty,
            success_level=level,
            passed=passed,
        )
        return outcome_name(level, passed=passed)

    def _actor_check_value(self, skill_id: str) -> int | None:
        actor = self.state["actors"][self.request.actor_id]
        actor_state = actor.get("state", {})
        skills = actor_state.get("skills", {})
        attributes = actor_state.get("attributes", {})
        value: Any
        if skill_id == "luck":
            value = actor.get("resources", {}).get("luck")
            if value is None:
                value = attributes.get("LUCK")
        elif skill_id in attributes:
            value = attributes.get(skill_id)
        else:
            value = skills.get(skill_id)
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    def _resolve_attack(self, entity: EntitySpec) -> None:
        stat_block = entity.stat_block
        if stat_block is None or stat_block.HP is None:
            raise ContractError("Attack target has no runtime stat block")
        check = self.request.intent.check
        if isinstance(check, DefaultCheck) and check.proposed_skills:
            candidate_skills = check.proposed_skills
            if any(
                self._actor_check_value(skill_id) is None
                for skill_id in candidate_skills
            ):
                raise ContractError(
                    "Attack check skills must belong to the current Actor"
                )
        else:
            candidate_skills = ("fighting-brawl",)
        resolved = self._roll_check(
            checkpoint_id=None,
            candidate_skills=candidate_skills,
            allowed_skills=candidate_skills,
            difficulty="regular",
        )
        if resolved in {"failure", "fumble"}:
            self.visible.append("攻击没有命中目标。")
            return
        hp_path = f"entities.{entity.id}.hp"
        if self.state["entities"][entity.id].get("hp") is None:
            self._write(hp_path, stat_block.HP, cause=f"combat:{entity.id}:hydrate")
        current_hp = _read_path(self.state, hp_path)
        damage = self.dice.roll("1d3")
        new_hp = max(0, int(current_hp) - damage)
        self._write(hp_path, new_hp, cause=f"combat:{self.request.request_id}:damage")
        self.visible.append(f"攻击命中，造成 {damage} 点伤害。")
        self.facts.append(f"{entity.id} 受到 {damage} 点伤害")
        if new_hp == 0:
            alive_path = f"entities.{entity.id}.alive"
            if self.state["entities"][entity.id].get("alive") is not None:
                self._write(
                    alive_path,
                    False,
                    cause=f"combat:{self.request.request_id}:death",
                )
            self._apply_hook("on_death", entity)

    def _advance_time(self, verb: str) -> None:
        elapsed = int(self.state["clock"]["elapsed_minutes"])
        self._write(
            "clock.elapsed_minutes",
            elapsed + 60,
            cause=f"time:{self.request.request_id}",
        )
        self._write(
            "clock.turn",
            int(self.state["clock"]["turn"]) + 1,
            cause=f"time:{self.request.request_id}",
        )
        if verb == "wait_until_night" or elapsed + 60 >= 720:
            self._write(
                "clock.time_of_day",
                "night",
                cause=f"time:{self.request.request_id}",
            )
        self._apply_hook("on_time_elapsed")

    def _matching_rules(
        self,
        hook: str,
        entity: EntitySpec | None = None,
    ) -> list[RuleSpec]:
        rules = [*self.module.module_rules]
        if entity is not None:
            rules.extend(entity.rules)
        elif hook in {"on_state_change", "on_death"}:
            rules.extend(
                rule for candidate in self.module.entities for rule in candidate.rules
            )
        matching = [
            rule
            for rule in rules
            if rule.hook == hook
            and (hook, rule.id) not in self.fired_rules
            and self._condition_matches(rule.when)
            and (
                hook != "on_interact"
                or not any(
                    isinstance(operation, AllowOperationSpec) for operation in rule.then
                )
                or any(
                    isinstance(operation, AllowOperationSpec)
                    and operation.action == self.request.intent.verb
                    for operation in rule.then
                )
            )
        ]
        return sorted(matching, key=lambda item: (-item.priority, item.id))

    @staticmethod
    def _select_rules(
        hook: str,
        matching: list[RuleSpec],
    ) -> tuple[HookResult, list[RuleSpec]]:
        if any(rule.mode == "forbid" for rule in matching):
            return "forbid", []
        overrides = [rule for rule in matching if rule.mode == "override"]
        if overrides:
            return "override", overrides[:1]
        appends = [rule for rule in matching if rule.mode == "append"]
        return ("append", appends) if appends else ("none", [])

    def _apply_hook(
        self,
        hook: str,
        entity: EntitySpec | None = None,
    ) -> HookResult:
        result, selected = self._select_rules(
            hook,
            self._matching_rules(hook, entity),
        )
        self._apply_rules(hook, selected)
        return result

    def _apply_rules(self, hook: str, rules: list[RuleSpec]) -> None:
        for rule in rules:
            self._step_rule(hook, rule)
            for operation in rule.then:
                self._apply_operation(operation, cause=f"rule:{rule.id}")
            self._record_facts(rule.facts, cause=f"rule:{rule.id}")
            self.visible.extend(
                information.text
                for information in rule.player_visible_information
                if information.visibility.audience not in {"keeper", "ho"}
            )

    def _step_rule(self, hook: str, rule: RuleSpec) -> None:
        self.rule_steps += 1
        if self.rule_steps > self.max_rule_steps:
            raise ContractError("Rule execution budget exceeded")
        self.fired_rules.add((hook, rule.id))

    def _drain_state_change_hooks(self) -> None:
        while True:
            matching = self._matching_rules("on_state_change")
            if not matching:
                return
            before = len(self.events)
            _, selected = self._select_rules("on_state_change", matching)
            self._apply_rules("on_state_change", selected)
            if len(self.events) == before:
                return

    def _condition_matches(self, condition: ConditionSpec) -> bool:
        return RuleKernel.condition_matches(
            condition,
            self.state,
            request=self.request,
            target_id=self.target_id,
        )

    def _apply_operation(self, operation: OperationSpec, *, cause: str) -> None:
        if isinstance(operation, ModifyOperationSpec):
            self._write(
                _runtime_path(operation.path, self.request), operation.set, cause
            )
        elif isinstance(operation, SetOperationSpec):
            self._write(
                _runtime_path(operation.path, self.request), operation.value, cause
            )
        elif isinstance(operation, AddOperationSpec):
            path = _runtime_path(operation.path, self.request)
            before = _read_path(self.state, path)
            if (
                not isinstance(before, (int, float))
                or isinstance(before, bool)
                or not isinstance(operation.value, (int, float))
                or isinstance(operation.value, bool)
            ):
                raise ContractError("Add operation requires numeric values")
            self._write(path, before + operation.value, cause)
        elif isinstance(operation, TransitionSpec):
            self._transition(operation.scene_id, cause=cause)
        elif isinstance(operation, ApplyConditionSpec):
            self._apply_condition(operation.condition, cause=cause)
        elif isinstance(operation, TriggerEndingSpec):
            self._trigger_ending(operation.ending_id, cause=cause)
        elif isinstance(operation, TriggerRuleSpec):
            self._trigger_rule(operation.rule_id)
        elif isinstance(operation, ForceOperationSpec):
            self._force(operation.action, cause=cause)
        elif isinstance(operation, (AllowOperationSpec, ForbidOperationSpec)):
            return
        else:
            raise ContractError(f"Unsupported runtime operation: {operation.op}")

    def _transition(self, scene_id: str, *, cause: str) -> None:
        self._scene(scene_id)
        if scene_id == self.state["scene_id"]:
            return
        self._apply_hook("on_scene_exit")
        self._write("scene_id", scene_id, cause)
        self._apply_hook("on_scene_enter")

    def _apply_condition(self, condition: str, *, cause: str) -> None:
        path = f"actors.{self.request.actor_id}.conditions"
        conditions = tuple(_read_path(self.state, path))
        if condition not in conditions:
            self._write(path, (*conditions, condition), cause)

    def _trigger_rule(self, rule_id: str) -> None:
        rules = [
            *self.module.module_rules,
            *(rule for entity in self.module.entities for rule in entity.rules),
        ]
        rule = next((candidate for candidate in rules if candidate.id == rule_id), None)
        if rule is None:
            raise ContractError(f"Triggered rule does not exist: {rule_id}")
        if not self._condition_matches(rule.when):
            return
        self._apply_rules(f"trigger:{rule.id}", [rule])

    def _force(self, action: str, *, cause: str) -> None:
        if action == "ghouls_overwhelm_and_abduct_actor":
            self._apply_condition("unconscious", cause=cause)
            return
        match = _FORCE_ACTION.fullmatch(action)
        if match is None:
            raise ContractError(f"Unsupported force action: {action}")
        name = match.group("name")
        arguments = [
            item.strip()
            for item in match.group("arguments").split(",")
            if item.strip() and "=" not in item
        ]
        if name == "san_check" and len(arguments) >= 2:
            current = self._materialize_resource("san", cause=cause)
            roll = self.dice.percentile()
            loss_expression = arguments[0] if roll <= current else arguments[1]
            loss = max(0, self.dice.roll(loss_expression))
            self._change_resource("san", max(0, current - loss), cause=cause)
            self.facts.append(f"{self.request.actor_id} 失去 {loss} 点 SAN")
            self.visible.append(f"理智检定造成 {loss} 点理智损失。")
            if loss >= 5:
                self._apply_condition("temporary_insanity", cause=cause)
            return
        if name == "san_loss" and len(arguments) == 1:
            current = self._materialize_resource("san", cause=cause)
            loss = max(0, self.dice.roll(arguments[0]))
            self._change_resource("san", max(0, current - loss), cause=cause)
            self.facts.append(f"{self.request.actor_id} 失去 {loss} 点 SAN")
            return
        if name == "san_gain" and len(arguments) == 1:
            current = self._materialize_resource("san", cause=cause)
            gain = max(0, self.dice.roll(arguments[0]))
            mythos = self._materialize_resource("mythos", cause=cause)
            self._change_resource(
                "san",
                min(99 - min(99, mythos), current + gain),
                cause=cause,
            )
            self.facts.append(f"{self.request.actor_id} 恢复 {gain} 点 SAN")
            return
        if name == "gain_mythos" and len(arguments) == 1:
            current = self._materialize_resource("mythos", cause=cause)
            gain = max(0, self.dice.roll(arguments[0]))
            new_mythos = current + gain
            self._change_resource("mythos", new_mythos, cause=cause)
            current_san = _read_path(
                self.state,
                f"actors.{self.request.actor_id}.resources.san",
            )
            maximum_san = 99 - min(99, new_mythos)
            if isinstance(current_san, int) and current_san > maximum_san:
                self._change_resource(
                    "san",
                    maximum_san,
                    cause=f"{cause}:san_cap",
                )
            self.facts.append(f"{self.request.actor_id} 获得 {gain}% 克苏鲁神话")
            return
        raise ContractError(f"Invalid force action arguments: {action}")

    def _materialize_resource(self, resource: str, *, cause: str) -> int:
        path = f"actors.{self.request.actor_id}.resources.{resource}"
        value = _read_path(self.state, path)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        actor_state = self.state["actors"][self.request.actor_id]["state"]
        derived = actor_state.get("derived_stats", {})
        attributes = actor_state.get("attributes", {})
        fallback = {
            "hp": derived.get("HP", actor_state.get("hp")),
            "san": derived.get("SAN", actor_state.get("san")),
            "mp": derived.get("MP", actor_state.get("mp")),
            "luck": attributes.get("LUCK", actor_state.get("luck")),
            "mythos": 0,
        }.get(resource)
        if not isinstance(fallback, int) or isinstance(fallback, bool):
            raise ContractError(f"Actor resource is unavailable: {resource}")
        self._write(path, fallback, f"{cause}:hydrate")
        return fallback

    def _change_resource(self, resource: str, value: int, *, cause: str) -> None:
        self._write(
            f"actors.{self.request.actor_id}.resources.{resource}",
            value,
            cause,
        )

    def _record_facts(self, facts: tuple[str, ...], *, cause: str) -> None:
        for fact in facts:
            if fact not in self.facts:
                self.facts.append(fact)
        information = {item.id: item for item in self.module.information_items}
        party_discovered = tuple(self.state.get("discovered_facts", ()))
        actor_discovered_by_id = dict(self.state.get("actor_discovered_facts", {}))
        actor_discovered = tuple(actor_discovered_by_id.get(self.request.actor_id, ()))
        party_additions: list[str] = []
        actor_additions: list[str] = []
        for fact in facts:
            item = information.get(fact)
            if item is None:
                continue
            actor_scoped = (
                item.visibility.audience == "actor"
                or not item.visibility.discovery_shares_to_party
            )
            if actor_scoped:
                if fact not in actor_discovered and fact not in actor_additions:
                    actor_additions.append(fact)
            elif fact not in party_discovered and fact not in party_additions:
                party_additions.append(fact)
        if party_additions:
            self._write(
                "discovered_facts",
                (*party_discovered, *party_additions),
                f"{cause}:discover",
            )
        if actor_additions:
            actor_discovered_by_id[self.request.actor_id] = (
                *actor_discovered,
                *actor_additions,
            )
            self._write(
                "actor_discovered_facts",
                actor_discovered_by_id,
                f"{cause}:discover-private",
            )

    def _apply_win_conditions(self) -> None:
        if self.state.get("phase") == "ended":
            return
        for condition in self.module.win_conditions:
            if not self._condition_matches(condition.when):
                continue
            self.facts.append(condition.fact or f"触发结局 {condition.id}")
            self.visible.append(
                condition.player_visible_information or "故事进入结局。"
            )
            if condition.is_ending:
                self._trigger_ending(
                    condition.id,
                    cause=f"win_condition:{condition.id}",
                )
                return

    def _trigger_ending(self, ending_id: str, *, cause: str) -> None:
        if not any(item.id == ending_id for item in self.module.win_conditions):
            raise ContractError(f"Ending does not exist: {ending_id}")
        self._write("ending_id", ending_id, cause)
        self._write("phase", "ended", cause)

    def _write(self, path: str, after: Any, cause: str) -> None:
        parts = path.split(".")
        if not parts or parts[0] not in {
            "actors",
            "entities",
            "clock",
            "scene_id",
            "ending_id",
            "phase",
            "discovered_facts",
            "actor_discovered_facts",
        }:
            raise ContractError(f"State path is outside the runtime whitelist: {path}")
        parent: Any = self.state
        for part in parts[:-1]:
            if not isinstance(parent, dict) or part not in parent:
                raise ContractError(f"State path does not exist: {path}")
            parent = parent[part]
        leaf = parts[-1]
        if not isinstance(parent, dict):
            raise ContractError(f"State path is not writable: {path}")
        before = parent.get(leaf)
        if before == after:
            return
        parent[leaf] = after
        sequence = int(self.state.get("event_sequence", 0)) + 1
        self.state["event_sequence"] = sequence
        self.events.append(
            StateModifiedEvent(
                event_id=f"evt_{sequence:04d}",
                sequence=sequence,
                room_id=self.request.room_id,
                actor_id=self.request.actor_id,
                client_action_id=self.request.request_id,
                cause=cause,
                payload=StateModifiedPayload.model_validate(
                    {
                        "path": path,
                        "from": _event_value(before),
                        "to": _event_value(after),
                    }
                ),
            )
        )

    def _validated_checkpoint(
        self,
        *,
        checkpoint_id: str,
        scene_id: str,
        target_id: str,
        proposed_skills: tuple[str, ...],
    ) -> CheckpointSpec:
        for checkpoint in self.module.checkpoints:
            if checkpoint.id != checkpoint_id:
                continue
            if checkpoint.scene_id != scene_id or checkpoint.target_id != target_id:
                raise ContractError(
                    "Checkpoint does not match current scene and target"
                )
            if not set(proposed_skills).issubset(checkpoint.skills):
                raise ContractError(
                    "Proposed skills are outside the checkpoint catalog"
                )
            return checkpoint
        raise ContractError(f"Checkpoint does not exist: {checkpoint_id}")

    def _scene(self, scene_id: str):
        scene = self._scene_or_none(scene_id)
        if scene is None:
            raise ContractError(f"Scene does not exist: {scene_id}")
        return scene

    def _scene_or_none(self, scene_id: str):
        return next((item for item in self.module.scenes if item.id == scene_id), None)

    def _entity(self, entity_id: str) -> EntitySpec:
        entity = next(
            (item for item in self.module.entities if item.id == entity_id),
            None,
        )
        if entity is None:
            raise ContractError(f"Intent target does not exist: {entity_id}")
        return entity

    @staticmethod
    def _direct_visible_text(entity: EntitySpec, verb: str) -> str:
        return entity.direct_responses.get(
            verb,
            entity.content or "行动完成，但没有新的可见变化。",
        )

    def _finalize(
        self,
        *,
        resolution: ActionResolution,
        outcome: ActionOutcome,
        visible: tuple[str, ...] | None = None,
        constraints: tuple[str, ...] | None = None,
        fact_source: str | None = None,
    ) -> tuple[EngineExecutionResult, GameState]:
        if visible is not None:
            self.visible.extend(visible)
        if constraints is not None:
            self.constraints.extend(constraints)
        validated_state = GameState.model_validate(self.state)
        source = fact_source or f"action:{self.request.request_id}:{resolution}"
        visible_facts = tuple(
            VisibleFact(id=f"{source}:result:{index}", text=text)
            for index, text in enumerate(self.visible, start=1)
        )
        action_result = ActionResult(
            request_id=self.request.request_id,
            action_id=f"action:{self.request.request_id}",
            resolution=resolution,
            outcome=outcome,
            check_result=self.check_result,
            visible_facts=visible_facts,
            narration_constraints=tuple(self.constraints),
            view_revision=str(validated_state.event_sequence),
            event_refs=tuple(event.event_id for event in self.events),
        )
        execution = EngineExecutionResult(
            action_result=action_result,
            confirmed_facts=tuple(self.facts),
            state_changes=tuple(
                StateChange.model_validate(
                    {
                        "path": event.payload.path,
                        "from": event.payload.from_value,
                        "to": event.payload.to,
                        "cause": event.cause,
                    }
                )
                for event in self.events
            ),
            events=tuple(self.events),
            state_version=validated_state.event_sequence,
        )
        return execution, validated_state


def _runtime_path(path: str, request: ActionRequest | None = None) -> str:
    parts = path.split(".")
    if len(parts) >= 4 and parts[0] == "entity" and parts[2] == "state":
        return ".".join(("entities", parts[1], *parts[3:]))
    if len(parts) >= 3 and parts[0] == "entity":
        return ".".join(("entities", *parts[1:]))
    if parts and parts[0] == "actor" and request is not None:
        if len(parts) >= 2 and parts[1] in {"resources", "conditions", "state"}:
            return ".".join(("actors", request.actor_id, *parts[1:]))
        return ".".join(("actors", request.actor_id, "state", *parts[1:]))
    return path


def _read_path(state: dict[str, Any], path: str) -> Any:
    cursor: Any = state
    for part in path.split("."):
        if not isinstance(cursor, dict) or part not in cursor:
            raise ContractError(f"State path does not exist: {path}")
        cursor = cursor[part]
    return cursor


def _event_value(value: Any) -> Any:
    """Normalize immutable runtime containers to JSON-compatible Event values."""

    if isinstance(value, tuple):
        return [_event_value(item) for item in value]
    if isinstance(value, list):
        return [_event_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _event_value(item) for key, item in value.items()}
    return value
